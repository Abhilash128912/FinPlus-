"""
Combines the two feeds (mcx_feed for CRUDEOIL/NATURALGAS, indmoney_feed for
NIFTY/BANKNIFTY futures) with sr_volume's signal model into one CE/PE call
per instrument. This makes no entry/exit/sizing decision -- direction only,
which strike/premium to actually buy is read off the user's own broker
terminal. See sr_volume.py's own docstring for why BUY/SELL fires on a
level *bounce*, not a breakout.

The commodity path (crude, natural gas) is materially richer than the index
path, because those two instruments have edges an equity-style level model
alone can't see. On top of the base sr_volume signal, compute_commodity_signal
layers:

  A. NYMEX proxy enrichment  -- deep CL=F/NG=F intraday history (INR-scaled)
     feeds the level model when the self-sampled MCX series is still thin,
     and provides a second-timeframe confluence check. (nymex_intraday)
  B. Event awareness         -- EIA / API inventory releases open a blackout
     window that suppresses and flags signals fired into the number.
     (event_calendar)
  C. Daily-trend alignment   -- a BUY that fights a daily downtrend is a
     counter-trend knife-catch; alignment adjusts confidence. (trend_engine)
  D. Per-instrument gates    -- gas gets wider stops / heavier volume gates
     than crude. (commodity_config)
  F. Open-interest read      -- rising price on rising OI is conviction;
     on falling OI it's short covering. (mcx_feed.recent_oi_change)
  G. Position sizing         -- lots that keep the loss-at-stop inside a
     rupee risk budget. (commodity_config.position_size)
  H. Move decomposition      -- how much of today's MCX move is the commodity
     vs the rupee.
  J. Session weighting       -- thin early-session hours are down-weighted
     vs the liquid US-overlap evening.

Every layer degrades independently: if the proxy feed, FX, trend, or OI is
unavailable the signal still computes on the MCX bars alone, just without
that particular confirmation. Nothing here invents data.
"""
import datetime

import commodity_config
import event_calendar
import mcx_feed
import nymex_intraday
import sr_volume

try:
    import indmoney_feed
    _INDMONEY_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - import-time env issue, not a runtime one
    indmoney_feed = None
    _INDMONEY_IMPORT_ERROR = str(e)

try:
    import signal_journal
except Exception:  # journal is best-effort; a signal must never fail to compute because logging broke
    signal_journal = None

try:
    import trend_engine
except Exception:
    trend_engine = None


def option_call_for_srv_signal(srv_signal: str) -> str | None:
    """BUY the underlying's direction -> buy a CE; SELL -> buy a PE. None
    for "NONE"/"NO_DATA": no signal means no call, not a coin flip."""
    return {"BUY": "CE", "SELL": "PE"}.get(srv_signal)


# Matches SR_PROFILES["intraday"] in the STOCK SCREENER APP's fetch_and_build.py
# exactly -- same-day trades should be judged against same-day reference points.
# Without use_prev_day_levels, the model can only ever fire off a pivot that's
# survived 20 bars (~3+ trading days) of confirmation, which is why a same-day
# move -- however real -- won't register until it's several days old. This adds
# the faster previous-day-high/low break path the original intraday tab relies
# on; it still won't catch a bounce that happened *today* and never broke
# yesterday's range, because that's not what a level break is.
INTRADAY_SR_GATES = {"max_stop_pct": 2.5, "min_reward_risk": 1.5, "max_target_pct": 3.0,
                     "use_prev_day_levels": True}


COMMODITY_ITEMS = [
    {"id": "crude", "name": "Crude Oil (MCX)", "mcx_symbol": "CRUDEOIL", "icon": "\U0001F6E2️"},
    {"id": "natgas", "name": "Natural Gas (MCX)", "mcx_symbol": "NATURALGAS", "icon": "⚡"},
]

INDEX_ITEMS = [
    {"id": "nifty", "name": "NIFTY 50", "underlying": "NIFTY", "icon": "\U0001F4C8"},
    {"id": "banknifty", "name": "BANK NIFTY", "underlying": "BANKNIFTY", "icon": "\U0001F3E6"},
]

EQUITY_ITEMS = [
    {"id": "reliance", "name": "Reliance Industries", "symbol": "RELIANCE", "scrip_code": "NSE_2885", "icon": "👑"},
]

# Daily-trend cache: trend_engine.get_commodity_trend() hits yfinance, and the
# daily trend does not move intraday, so caching it per symbol for a while keeps
# the 60s signal refresh from refetching two years of daily bars every pass.
_TREND_CACHE: dict[str, dict] = {}
_TREND_TTL_SEC = 20 * 60

_BULLISH_TRENDS = {"Strong Uptrend", "Uptrend", "Accumulation"}
_BEARISH_TRENDS = {"Downtrend", "Distribution"}


def _no_data(name: str, icon: str, reason: str) -> dict:
    return {
        "name": name, "icon": icon, "ltp": None,
        "srv_available": False, "srv_signal": "NO_DATA",
        "srv_reason": reason, "option_call": None,
    }


def _cached_daily_trend(mcx_symbol: str) -> dict | None:
    if trend_engine is None:
        return None
    import time
    now = time.time()
    hit = _TREND_CACHE.get(mcx_symbol)
    if hit and (now - hit["at"]) < _TREND_TTL_SEC:
        return hit["trend"]
    try:
        t = trend_engine.get_commodity_trend(mcx_symbol)
    except Exception:
        t = None
    _TREND_CACHE[mcx_symbol] = {"at": now, "trend": t}
    return t


def _session_factor(now_ist: datetime.datetime) -> tuple[float, str]:
    """Confidence multiplier for the time of day within the MCX session.

    MCX energy is thin and choppy in the morning and comes alive when the US
    session overlaps in the evening (NYMEX pit open, EIA prints, the bulk of
    the day's volume). A level defended on evening volume means more than one
    poked in a quiet 10am hour, so early hours are down-weighted -- not
    voided, just believed less.
    """
    t = now_ist.time()
    if datetime.time(17, 30) <= t <= datetime.time(23, 0):
        return 1.0, "US-overlap (liquid)"
    if datetime.time(23, 0) < t <= datetime.time(23, 30):
        return 0.85, "near close"
    if datetime.time(14, 0) <= t < datetime.time(17, 30):
        return 0.9, "midday"
    return 0.75, "early session (thin)"


def _decompose_move(quote: dict, symbol: str) -> dict:
    """Split today's MCX % move into commodity-driven vs rupee-driven.

    MCX price ≈ NYMEX price × USD/INR. If MCX is up 1.2% but WTI is up only
    0.3%, most of the "move" is a weaker rupee, not a stronger barrel -- a
    distinction that matters before reading a chart level as commodity
    conviction. The commodity leg is the proxy's own daily % change (scale-
    invariant, so USD % = INR % before FX drift); the FX leg is the residual.
    Returns {} when the proxy day-change isn't available.
    """
    mcx_pct = quote.get("mcx_pct")
    if mcx_pct is None:
        return {}
    commodity_pct = nymex_intraday.day_change_pct(symbol)
    if commodity_pct is None:
        return {}
    return {
        "srv_move_total_pct": round(float(mcx_pct), 2),
        "srv_move_commodity_pct": round(commodity_pct, 2),
        "srv_move_fx_pct": round(float(mcx_pct) - commodity_pct, 2),
    }


def _apply_commodity_layers(sig: dict, item: dict, quote: dict, usdinr_rate: float,
                            proxy_info: dict, now_utc: datetime.datetime) -> dict:
    """Fold events / trend / OI / session / sizing onto a base sr_volume sig.

    Adjusts srv_strength (kept alongside the untouched srv_base_strength) and
    attaches the extra fields the card renders. Only meaningful for a fired
    BUY/SELL; for NONE it still attaches event context and OI so the card can
    show "quiet, EIA in 3h" rather than nothing.
    """
    symbol = item["mcx_symbol"]
    direction = sig.get("srv_signal")
    fired = direction in ("BUY", "SELL")
    now_ist = now_utc.astimezone(event_calendar.IST)

    base_strength = float(sig.get("srv_strength") or 0.0)
    sig["srv_base_strength"] = round(base_strength, 1)
    factors = []          # human-readable confidence notes
    mult = 1.0

    # --- B. Event calendar: next event + blackout ------------------------
    nxt = event_calendar.next_event(symbol, now_utc)
    if nxt:
        sig["srv_next_event"] = nxt["name"]
        sig["srv_next_event_in_h"] = round(nxt["minutes_until"] / 60.0, 1)
        sig["srv_next_event_when"] = nxt["when_ist_str"]
        sig["srv_next_event_impact"] = nxt["impact"]
    bo = event_calendar.blackout(symbol, now_utc)
    sig["srv_event_blackout"] = bo["active"]
    if bo["active"] and fired:
        # A signal into an inventory print is not a signal. Keep the analysis
        # visible but pull the option call and warn -- the user should wait
        # for the number, not take a position into it.
        sig["srv_blackout_phase"] = bo["phase"]
        phase_txt = ("ahead of" if bo["phase"] == "pre" else "just after")
        sig["srv_reason"] = (f"⚠ {phase_txt} {bo['event']['name']} — signal held; "
                             f"{sig.get('srv_reason', '')}")
        sig["option_call"] = None
        mult *= 0.25
        factors.append(f"event blackout ({bo['phase']}) ×0.25")

    # --- J. Session/time-of-day weighting --------------------------------
    sf, sf_label = _session_factor(now_ist)
    sig["srv_session"] = sf_label
    if fired:
        mult *= sf
        if sf < 1.0:
            factors.append(f"{sf_label} ×{sf:.2f}")

    # --- C. Daily-trend alignment ----------------------------------------
    trend = _cached_daily_trend(symbol)
    if trend and trend.get("available"):
        tstate = trend.get("trend")
        sig["srv_daily_trend"] = tstate
        if fired:
            bullish, bearish = tstate in _BULLISH_TRENDS, tstate in _BEARISH_TRENDS
            if (direction == "BUY" and bullish) or (direction == "SELL" and bearish):
                sig["srv_trend_aligned"] = True
                mult *= 1.15
                factors.append(f"aligned with daily {tstate} ×1.15")
            elif (direction == "BUY" and bearish) or (direction == "SELL" and bullish):
                sig["srv_trend_aligned"] = False
                mult *= 0.7
                factors.append(f"counter-trend vs daily {tstate} ×0.70")
            else:
                sig["srv_trend_aligned"] = None  # neutral daily trend

    # --- F. Open interest -------------------------------------------------
    oi = mcx_feed.recent_oi_change(symbol)
    if oi.get("oi") is not None:
        sig["srv_oi"] = oi["oi"]
        sig["srv_oi_pct"] = oi.get("oi_pct")
    if fired and oi.get("rising") is not None:
        rising = oi["rising"]
        # Price moving in the signal's direction WITH rising OI = new money
        # backing the move (conviction). Rising price on falling OI = short
        # covering / long liquidation = a move that tends to fade.
        if rising:
            mult *= 1.1
            sig["srv_oi_read"] = "rising OI (new positions backing the move)"
            factors.append("OI rising ×1.10")
        else:
            mult *= 0.9
            sig["srv_oi_read"] = "falling OI (covering — move may fade)"
            factors.append("OI falling ×0.90")

    # --- I. Multi-timeframe confluence -----------------------------------
    if fired:
        level = sig.get("srv_support") if direction == "BUY" else sig.get("srv_resistance")
        conf = nymex_intraday.confluence(symbol, usdinr_rate, quote.get("mcx_ltp"), level)
        if conf.get("confirmed"):
            sig["srv_confluence"] = conf["daily_level"]
            mult *= 1.1
            factors.append("daily-timeframe confluence ×1.10")

    # --- H. Move decomposition -------------------------------------------
    sig.update(_decompose_move(quote, symbol))

    # --- G. Position sizing ----------------------------------------------
    if fired:
        ps = commodity_config.position_size(symbol, sig.get("srv_entry"), sig.get("srv_stop"))
        if ps:
            sig["srv_position"] = ps

    # Final adjusted confidence, clamped, with the reasoning trail.
    if fired:
        sig["srv_strength"] = round(max(0.0, min(100.0, base_strength * mult)), 1)
        sig["srv_confidence_factors"] = factors
    return sig


def compute_commodity_signal(item: dict) -> dict:
    try:
        symbol = item["mcx_symbol"]
        quote = mcx_feed.fetch_mcx_futures(symbol)
        if not quote:
            return _no_data(item["name"], item["icon"], "MCX feed unavailable")

        # D. Per-instrument gate profile over the shared intraday base.
        gates = dict(INTRADAY_SR_GATES)
        gates.update(commodity_config.gates_for(symbol))

        mcx_ltp = quote.get("mcx_ltp")
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        # Primary series: the real, tradeable MCX self-sampled bars.
        mcx_df = mcx_feed.bars_dataframe(symbol)
        mcx_bars_have = 0 if mcx_df is None else len(mcx_df)
        mcx_sig = sr_volume.compute_signal(mcx_df, gates) if mcx_df is not None else dict(sr_volume.NO_SIGNAL)

        # A. NYMEX proxy series (deep intraday history, INR-scaled + basis-aligned).
        usdinr_rate = nymex_intraday.get_usdinr_rate()
        proxy_info = nymex_intraday.enriched_bars(symbol, usdinr_rate, mcx_ltp)
        proxy_df = proxy_info.get("df")
        proxy_sig = sr_volume.compute_signal(proxy_df, gates) if proxy_df is not None else dict(sr_volume.NO_SIGNAL)

        # Choose the base signal:
        #  - MCX fired -> trust the real series.
        #  - MCX has too few bars to fire but the proxy did -> use the proxy as
        #    a labelled fallback so a warming-up card isn't uselessly blank.
        #  - otherwise -> MCX's NONE (with proxy agreement noted if any).
        enough_mcx = mcx_bars_have >= gates.get("min_bars", sr_volume.GATES["min_bars"])
        used_proxy = False
        if mcx_sig.get("srv_signal") in ("BUY", "SELL"):
            base = dict(mcx_sig)
            base["srv_source"] = "MCX bars"
        elif not enough_mcx and proxy_sig.get("srv_signal") in ("BUY", "SELL"):
            base = dict(proxy_sig)
            base["srv_source"] = "NYMEX proxy (MCX warming up)"
            used_proxy = True
        else:
            base = dict(mcx_sig)
            base["srv_source"] = "MCX bars"

        # Confluence between the two independent series when both fired.
        if (mcx_sig.get("srv_signal") in ("BUY", "SELL")
                and proxy_sig.get("srv_signal") == mcx_sig.get("srv_signal")):
            base["srv_series_agree"] = True

        sig = {
            "name": item["name"], "icon": item["icon"],
            "ltp": mcx_ltp, "pct_chg": quote.get("mcx_pct"),
            "expiry": quote.get("mcx_expiry"), "volume": quote.get("mcx_volume"),
            "bars_recorded": mcx_bars_have if not used_proxy else (0 if proxy_df is None else len(proxy_df)),
            "bars_needed": gates.get("min_bars", sr_volume.GATES["min_bars"]),
            "option_call": option_call_for_srv_signal(base.get("srv_signal", "NONE")),
            **base,
        }

        sig = _apply_commodity_layers(sig, item, quote, usdinr_rate, proxy_info, now_utc)

        # Re-derive the option call after layers (blackout may have pulled it).
        if sig.get("srv_event_blackout") and sig.get("srv_signal") in ("BUY", "SELL"):
            pass  # option_call already set to None inside the layer
        else:
            sig["option_call"] = option_call_for_srv_signal(sig.get("srv_signal", "NONE"))

        # E. Journal: log a genuinely-new fired signal, unless it's held for an
        # event -- an event-time coin flip shouldn't pollute the hit-rate.
        if signal_journal is not None and not sig.get("srv_event_blackout"):
            try:
                signal_journal.log_signal(symbol, sig, now_utc)
            except Exception:
                pass

        return sig
    except Exception as e:
        return _no_data(item["name"], item["icon"], f"error: {e}")


def compute_index_signal(item: dict) -> dict:
    if indmoney_feed is None:
        return _no_data(item["name"], item["icon"], f"indmoney_feed import failed: {_INDMONEY_IMPORT_ERROR}")
    try:
        contract = indmoney_feed.get_front_month_contract(item["underlying"])
        if not contract:
            return _no_data(item["name"], item["icon"], "no front-month contract found")

        ltp = indmoney_feed.get_ltp(contract["scrip_code"])
        candles = indmoney_feed.get_hourly_candles(contract["scrip_code"])
        sig = sr_volume.compute_signal(candles, INTRADAY_SR_GATES)

        return {
            "name": item["name"], "icon": item["icon"],
            "trading_symbol": contract["trading_symbol"], "expiry": contract["expiry"],
            "lot_units": contract.get("lot_units"), "ltp": ltp,
            "bars_recorded": len(candles), "bars_needed": sr_volume.GATES["min_bars"],
            "option_call": option_call_for_srv_signal(sig.get("srv_signal", "NONE")),
            **sig,
        }
    except Exception as e:
        return _no_data(item["name"], item["icon"], f"error: {e}")


def compute_equity_signal(item: dict) -> dict:
    if indmoney_feed is None:
        return _no_data(item["name"], item["icon"], f"indmoney_feed import failed: {_INDMONEY_IMPORT_ERROR}")
    try:
        scrip = item["scrip_code"]
        ltp = indmoney_feed.get_ltp(scrip)
        candles = indmoney_feed.get_hourly_candles(scrip)
        sig = sr_volume.compute_signal(candles, INTRADAY_SR_GATES)

        return {
            "name": item["name"], "icon": item["icon"],
            "symbol": item["symbol"], "trading_symbol": item["symbol"],
            "ltp": ltp,
            "bars_recorded": len(candles), "bars_needed": sr_volume.GATES["min_bars"],
            "option_call": option_call_for_srv_signal(sig.get("srv_signal", "NONE")),
            **sig,
        }
    except Exception as e:
        return _no_data(item["name"], item["icon"], f"error: {e}")


def compute_all_signals() -> dict:
    return {
        item["id"]: compute_commodity_signal(item) for item in COMMODITY_ITEMS
    } | {
        item["id"]: compute_index_signal(item) for item in INDEX_ITEMS
    } | {
        item["id"]: compute_equity_signal(item) for item in EQUITY_ITEMS
    }


if __name__ == "__main__":
    for key, sig in compute_all_signals().items():
        print(f"{key}: ltp={sig.get('ltp')} srv_signal={sig.get('srv_signal')} "
              f"strength={sig.get('srv_strength')} src={sig.get('srv_source')} "
              f"option_call={sig.get('option_call')} next_event={sig.get('srv_next_event')} "
              f"reason={sig.get('srv_reason')}")
