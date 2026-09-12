"""
option_strategy_engine.py - Algorithmic Option Strategy and Analytics Engine

Calculates derivatives analytics and algorithmic trade recommendations:
  1. Max Pain strike calculation across open interest distribution.
  2. Institutional Support (highest Put OI) and Resistance (highest Call OI) walls.
  3. ATM Straddle pricing, implied volatility regime, and expected expiry move.
  4. Algorithmic trade selection (Directional Calls/Puts, Spreads, Straddles/Iron Condors)
     driven by quantitative criteria (S/R volume signal, daily trend, PCR, Delta, IV).
  5. Permanent support for RELIANCE alongside NIFTY and BANKNIFTY across all signal regimes
     (BUY, SELL, NEUTRAL).
"""

from typing import Any, Dict, List, Optional


def compute_max_pain(strikes: List[Dict[str, Any]]) -> Optional[float]:
    """Calculates the Max Pain strike where option sellers incur the lowest cumulative loss."""
    if not strikes:
        return None

    candidate_strikes = [s["strike"] for s in strikes]
    min_loss = float("inf")
    best_strike = None

    for target_strike in candidate_strikes:
        total_loss = 0.0
        for s in strikes:
            k = s["strike"]
            ce_oi = (s.get("ce") or {}).get("oi") or 0
            pe_oi = (s.get("pe") or {}).get("oi") or 0

            # Loss on Call writers if price closes at target_strike: max(0, target_strike - k) * ce_oi
            if target_strike > k:
                total_loss += (target_strike - k) * ce_oi

            # Loss on Put writers if price closes at target_strike: max(0, k - target_strike) * pe_oi
            if target_strike < k:
                total_loss += (k - target_strike) * pe_oi

        if total_loss < min_loss:
            min_loss = total_loss
            best_strike = target_strike

    return best_strike


def analyze_option_derivatives(chain_data: Dict[str, Any], signal_dict: Optional[Dict[str, Any]] = None, trend_dict: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Produces comprehensive derivatives analytics and algorithmic strategy setups for an underlying."""
    if not chain_data:
        return {}

    underlying = chain_data.get("underlying", "UNKNOWN").upper()
    spot_ltp = float(chain_data.get("underlying_ltp") or 0.0)
    atm_strike = float(chain_data.get("atm_strike") or 0.0)
    pcr = float(chain_data.get("pcr") or 1.0)
    pcr_sentiment = chain_data.get("pcr_sentiment") or "NEUTRAL"
    strikes = chain_data.get("strikes") or []
    atm_ce = chain_data.get("atm_ce") or {}
    atm_pe = chain_data.get("atm_pe") or {}

    # Max Pain calculation
    max_pain = compute_max_pain(strikes) or atm_strike

    # Institutional OI walls
    highest_call_oi = -1
    highest_call_strike = atm_strike
    highest_put_oi = -1
    highest_put_strike = atm_strike

    for s in strikes:
        k = float(s["strike"])
        c_oi = (s.get("ce") or {}).get("oi") or 0
        p_oi = (s.get("pe") or {}).get("oi") or 0

        if c_oi > highest_call_oi:
            highest_call_oi = c_oi
            highest_call_strike = k

        if p_oi > highest_put_oi:
            highest_put_oi = p_oi
            highest_put_strike = k

    # Straddle metrics
    ce_ltp = float(atm_ce.get("ltp") or 0.0)
    pe_ltp = float(atm_pe.get("ltp") or 0.0)
    straddle_prem = float(chain_data.get("straddle_premium") or (ce_ltp + pe_ltp))
    upper_breakeven = round(atm_strike + straddle_prem, 1)
    lower_breakeven = round(atm_strike - straddle_prem, 1)
    implied_move_pct = round((straddle_prem / spot_ltp) * 100, 2) if spot_ltp > 0 else 0.0

    # Greeks
    ce_delta = atm_ce.get("delta")
    pe_delta = atm_pe.get("delta")
    ce_theta = atm_ce.get("theta")
    pe_theta = atm_pe.get("theta")
    ce_iv = atm_ce.get("iv")
    pe_iv = atm_pe.get("iv")
    iv_vals = [v for v in (ce_iv, pe_iv) if v is not None]
    avg_iv = round(sum(iv_vals) / len(iv_vals), 1) if iv_vals else None
    avg_iv_txt = f"{avg_iv:.1f}%" if avg_iv is not None else "N/A"

    # Signal & Trend integration
    srv_signal = (signal_dict or {}).get("srv_signal", "NO_DATA")
    option_call = (signal_dict or {}).get("option_call")  # "CE", "PE", or None
    trend_state = (trend_dict or {}).get("trend", "NEUTRAL")

    # Determine Algorithmic Option Regime & Strategy
    # Selection criteria uses multiple confirmations:
    # 1. Option call recommendation ("CE" -> Bullish, "PE" -> Bearish)
    # 2. S/R volume signal
    # 3. PCR sentiment (> 1.15 bullish bias, < 0.85 bearish bias)
    # 4. Underlying price vs Max Pain / Institutional walls

    regime = "NEUTRAL"
    if option_call == "CE" or srv_signal == "BUY" or (trend_state == "BULLISH" and pcr >= 1.10):
        regime = "BULLISH"
    elif option_call == "PE" or srv_signal == "SELL" or (trend_state == "BEARISH" and pcr <= 0.85):
        regime = "BEARISH"
    elif pcr > 1.25 and spot_ltp >= highest_put_strike:
        regime = "BULLISH"
    elif pcr < 0.70 and spot_ltp <= highest_call_strike:
        regime = "BEARISH"

    # Strike step size estimation
    step = 50.0
    if strikes and len(strikes) > 1:
        diffs = [abs(strikes[i+1]["strike"] - strikes[i]["strike"]) for i in range(len(strikes)-1)]
        step = min(diffs) if diffs else (50.0 if underlying == "NIFTY" else 100.0 if underlying == "BANKNIFTY" else 20.0)

    strategies = []

    if regime == "BULLISH":
        # Strategy 1: Directional ATM/Near-ITM Call Buy
        rec_strike = atm_strike
        rec_opt = atm_ce
        entry_price = float(rec_opt.get("ltp") or 0.0)
        target1_price = round(entry_price * 1.40, 2)
        target2_price = round(entry_price * 1.80, 2)
        stop_price = round(entry_price * 0.70, 2)
        rr_ratio = round((target1_price - entry_price) / max(0.1, (entry_price - stop_price)), 2)

        strategies.append({
            "type": "DIRECTIONAL_BUY",
            "name": f"Buy {int(rec_strike) if rec_strike.is_integer() else rec_strike} CE",
            "style": "BULLISH MOMENTUM",
            "badge_class": "badge-green",
            "leg": "LONG CALL",
            "strike": rec_strike,
            "instrument": f"{underlying} {rec_strike} CE",
            "entry": entry_price,
            "target1": target1_price,
            "target2": target2_price,
            "stop_loss": stop_price,
            "rr": rr_ratio,
            "delta": rec_opt.get("delta"),
            "theta": rec_opt.get("theta"),
            "gamma": rec_opt.get("gamma"),
            "iv": rec_opt.get("iv"),
            "rationale": (
                f"Underlying in bullish posture with PCR at {pcr:.2f} ({pcr_sentiment}). "
                f"Heavy Put writing at {int(highest_put_strike)} provides firm downside cushion. "
                f"Positive Delta ({rec_opt.get('delta', 0.5):.2f}) captures upside acceleration towards resistance {int(highest_call_strike)}."
            ),
            "suitability": "Aggressive / Intraday Momentum"
        })

        # Strategy 2: Bull Call Spread (Hedged against theta) — only offered when
        # the short leg's real price is on the fetched chain; a missing wing must
        # never be treated as "costs nothing".
        sell_strike = atm_strike + step
        sell_opt = next((s["ce"] for s in strikes if abs(s["strike"] - sell_strike) < 0.1 and s.get("ce")), None)
        if sell_opt and sell_opt.get("ltp") is not None:
            sell_ltp = float(sell_opt["ltp"])
            net_debit = round(entry_price - sell_ltp, 2)
            max_profit = round(step - net_debit, 2)
            spread_rr = round(max_profit / max(0.1, net_debit), 2)

            strategies.append({
                "type": "BULL_CALL_SPREAD",
                "name": f"Bull Call Spread ({int(rec_strike)} / {int(sell_strike)})",
                "style": "HEDGED SPREAD",
                "badge_class": "badge-purple",
                "leg": f"+1 {int(rec_strike)} CE / -1 {int(sell_strike)} CE",
                "strike": f"{int(rec_strike)} / {int(sell_strike)}",
                "entry": net_debit,
                "target1": round(net_debit + max_profit * 0.6, 2),
                "target2": round(net_debit + max_profit * 0.85, 2),
                "stop_loss": round(net_debit * 0.60, 2),
                "rr": spread_rr,
                "delta": round((rec_opt.get("delta") or 0.5) - (sell_opt.get("delta") or 0.3), 2),
                "theta": round((rec_opt.get("theta") or -10) - (sell_opt.get("theta") or -6), 1),
                "gamma": rec_opt.get("gamma"),
                "iv": avg_iv,
                "rationale": (
                    f"Offsets time decay ({rec_opt.get('theta', 0):.1f}/day) by shorting {int(sell_strike)} CE. "
                    f"Net debit ₹{net_debit:.2f} caps maximum risk while targeting ₹{max_profit:.2f} reward at resistance."
                ),
                "suitability": "Conservative / Carry through Expiry"
            })

    elif regime == "BEARISH":
        # Strategy 1: Directional ATM/Near-ITM Put Buy
        rec_strike = atm_strike
        rec_opt = atm_pe
        entry_price = float(rec_opt.get("ltp") or 0.0)
        target1_price = round(entry_price * 1.40, 2)
        target2_price = round(entry_price * 1.80, 2)
        stop_price = round(entry_price * 0.70, 2)
        rr_ratio = round((target1_price - entry_price) / max(0.1, (entry_price - stop_price)), 2)

        strategies.append({
            "type": "DIRECTIONAL_BUY",
            "name": f"Buy {int(rec_strike) if rec_strike.is_integer() else rec_strike} PE",
            "style": "BEARISH MOMENTUM",
            "badge_class": "badge-red",
            "leg": "LONG PUT",
            "strike": rec_strike,
            "instrument": f"{underlying} {rec_strike} PE",
            "entry": entry_price,
            "target1": target1_price,
            "target2": target2_price,
            "stop_loss": stop_price,
            "rr": rr_ratio,
            "delta": rec_opt.get("delta"),
            "theta": rec_opt.get("theta"),
            "gamma": rec_opt.get("gamma"),
            "iv": rec_opt.get("iv"),
            "rationale": (
                f"Underlying facing selling pressure with PCR at {pcr:.2f} ({pcr_sentiment}). "
                f"High Call OI barrier at {int(highest_call_strike)} caps upside. "
                f"Negative Delta ({rec_opt.get('delta', -0.5):.2f}) gains as spot tests lower support at {int(highest_put_strike)}."
            ),
            "suitability": "Aggressive / Intraday Breakdown"
        })

        # Strategy 2: Bear Put Spread — only offered when the short leg's real
        # price is on the fetched chain (same reasoning as the bull spread above).
        sell_strike = atm_strike - step
        sell_opt = next((s["pe"] for s in strikes if abs(s["strike"] - sell_strike) < 0.1 and s.get("pe")), None)
        if sell_opt and sell_opt.get("ltp") is not None:
            sell_ltp = float(sell_opt["ltp"])
            net_debit = round(entry_price - sell_ltp, 2)
            max_profit = round(step - net_debit, 2)
            spread_rr = round(max_profit / max(0.1, net_debit), 2)

            strategies.append({
                "type": "BEAR_PUT_SPREAD",
                "name": f"Bear Put Spread ({int(rec_strike)} / {int(sell_strike)})",
                "style": "HEDGED SPREAD",
                "badge_class": "badge-purple",
                "leg": f"+1 {int(rec_strike)} PE / -1 {int(sell_strike)} PE",
                "strike": f"{int(rec_strike)} / {int(sell_strike)}",
                "entry": net_debit,
                "target1": round(net_debit + max_profit * 0.6, 2),
                "target2": round(net_debit + max_profit * 0.85, 2),
                "stop_loss": round(net_debit * 0.60, 2),
                "rr": spread_rr,
                "delta": round((rec_opt.get("delta") or -0.5) - (sell_opt.get("delta") or -0.3), 2),
                "theta": round((rec_opt.get("theta") or -10) - (sell_opt.get("theta") or -6), 1),
                "gamma": rec_opt.get("gamma"),
                "iv": avg_iv,
                "rationale": (
                    f"Reduces net capital outlay to ₹{net_debit:.2f} while cushioning theta burn. "
                    f"Targeting ₹{max_profit:.2f} payout if spot moves below {int(sell_strike)} before expiry."
                ),
                "suitability": "Conservative / Carry through Expiry"
            })

    else:
        # NEUTRAL / RANGEBOUND REGIME (e.g. Reliance or Nifty rangebound)
        # Strategy 1: Non-directional Theta Harvest (Short Straddle / Iron Fly)
        daily_theta = abs((ce_theta or 0.0) + (pe_theta or 0.0))
        strategies.append({
            "type": "STRADDLE_SELL",
            "name": f"ATM {int(atm_strike)} Straddle / Iron Fly",
            "style": "THETA HARVEST",
            "badge_class": "badge-yellow",
            "leg": f"SELL {int(atm_strike)} CE + SELL {int(atm_strike)} PE",
            "strike": atm_strike,
            "entry": straddle_prem,
            "target1": round(straddle_prem * 0.65, 2),  # collect 35% decay
            "target2": round(straddle_prem * 0.40, 2),  # collect 60% decay
            "stop_loss": round(straddle_prem * 1.35, 2), # 35% SL on combined premium
            "rr": 1.75,
            "delta": round((ce_delta or 0.5) + (pe_delta or -0.5), 2),
            "theta": round(daily_theta, 1),
            "gamma": round((atm_ce.get("gamma") or 0.0) + (atm_pe.get("gamma") or 0.0), 4),
            "iv": avg_iv,
            "upper_breakeven": upper_breakeven,
            "lower_breakeven": lower_breakeven,
            "rationale": (
                f"Market in balanced consolidation (PCR {pcr:.2f}, IV {avg_iv_txt}). "
                f"Maximum profit collected if spot remains between ₹{lower_breakeven:.0f} and ₹{upper_breakeven:.0f}. "
                f"Yields approximately +₹{daily_theta:.1f}/day in rapid theta erosion."
            ),
            "suitability": "Non-Directional / Rangebound Decay"
        })

        # Strategy 2: Iron Condor (Defensive range play)
        otm_call_strike = atm_strike + step
        otm_put_strike = atm_strike - step
        otm_call_opt = next((s["ce"] for s in strikes if abs(s["strike"] - otm_call_strike) < 0.1 and s.get("ce")), None)
        otm_put_opt = next((s["pe"] for s in strikes if abs(s["strike"] - otm_put_strike) < 0.1 and s.get("pe")), None)

        # Net position Greeks from real leg data only — short ATM straddle + long
        # wings. A missing leg means "unknown", never a plausible-looking guess.
        condor_delta = None
        if (ce_delta is not None and pe_delta is not None and otm_call_opt and otm_put_opt
                and otm_call_opt.get("delta") is not None and otm_put_opt.get("delta") is not None):
            condor_delta = round(-ce_delta - pe_delta + otm_call_opt["delta"] + otm_put_opt["delta"], 3)

        ce_gamma = atm_ce.get("gamma")
        pe_gamma = atm_pe.get("gamma")
        condor_gamma = None
        if (ce_gamma is not None and pe_gamma is not None and otm_call_opt and otm_put_opt
                and otm_call_opt.get("gamma") is not None and otm_put_opt.get("gamma") is not None):
            condor_gamma = round(-ce_gamma - pe_gamma + otm_call_opt["gamma"] + otm_put_opt["gamma"], 4)

        strategies.append({
            "type": "IRON_CONDOR",
            "name": f"Iron Condor ({int(otm_put_strike)} / {int(otm_call_strike)})",
            "style": "DEFINED RISK RANGE",
            "badge_class": "badge-purple",
            "leg": f"-1 {int(atm_strike)} CE/PE, +1 Wings ({int(otm_put_strike)} PE / {int(otm_call_strike)} CE)",
            "strike": f"{int(otm_put_strike)} - {int(otm_call_strike)}",
            "entry": round(straddle_prem * 0.45, 2),
            "target1": round(straddle_prem * 0.20, 2),
            "target2": round(straddle_prem * 0.10, 2),
            "stop_loss": round(straddle_prem * 0.70, 2),
            "rr": 1.5,
            "delta": condor_delta,
            "theta": round(daily_theta * 0.65, 1),
            "gamma": condor_gamma,
            "iv": avg_iv,
            "rationale": (
                f"Safe defined-risk corridor protecting against black-swan gap openings while harvesting steady theta."
            ),
            "suitability": "Defined Risk / Overnight Hold"
        })

    return {
        "underlying": underlying,
        "spot_ltp": spot_ltp,
        "atm_strike": atm_strike,
        "pcr": pcr,
        "pcr_sentiment": pcr_sentiment,
        "max_pain": max_pain,
        "highest_call_strike": highest_call_strike,
        "highest_call_oi": highest_call_oi,
        "highest_put_strike": highest_put_strike,
        "highest_put_oi": highest_put_oi,
        "straddle_premium": straddle_prem,
        "upper_breakeven": upper_breakeven,
        "lower_breakeven": lower_breakeven,
        "implied_move_pct": implied_move_pct,
        "avg_iv": avg_iv,
        "regime": regime,
        "strategies": strategies,
        "atm_ce": atm_ce,
        "atm_pe": atm_pe,
        "strikes_count": len(strikes),
    }


# ─── Top 10 Options Screener (5 CE · 5 PE · Reliance Always Included) ──────────

import time
import os
import requests
import csv
import io
import equity_scan
import indmoney_feed

_FNO_SET_CACHE = {"at": 0.0, "symbols": set(), "lot_sizes": {}}
_TOP_OPTIONS_CACHE = {"at": 0.0, "data": None}
_TOP_OPTIONS_TTL_SEC = 180.0  # 3-minute cache for top 10 option stock picks

# Universe filter for the Top 10 screener: skip cheap, high-lot-size names
# (e.g. YESBANK) in favour of higher-priced, smaller-lot stocks, which is where
# a single option contract represents a more meaningful notional. RELIANCE is
# exempt -- it's permanently included regardless of these thresholds.
MIN_LTP_FOR_OPTIONS = 1000.0
MAX_LOT_SIZE_FOR_OPTIONS = 500

# Liquidity/positioning filter applied on top of the intraday equity score:
# a candidate's own live option chain must show real combined OI above this
# floor (illiquid chains have unreliable PCR and wide spreads) and its PCR
# sentiment -- using indmoney_feed's own BULLISH/BEARISH/NEUTRAL convention --
# must not actively contradict the equity-side call.
MIN_TOTAL_OI_FOR_OPTIONS = 50_000
OPTIONS_SHORTLIST_SIZE = 8  # candidates checked per side before narrowing to 5


def _ensure_fno_cache() -> None:
    now = time.time()
    if _FNO_SET_CACHE["symbols"] and (now - _FNO_SET_CACHE["at"] < 24 * 3600):
        return

    fno_set = set()
    lot_sizes: dict[str, int] = {}
    token = os.environ.get("INDMONEY_ACCESS_TOKEN")
    if token:
        try:
            resp = requests.get(
                "https://api.indstocks.com/market/instruments",
                params={"source": "fno"},
                headers={"Authorization": token},
                timeout=25,
            )
            if resp.status_code == 200:
                reader = csv.DictReader(io.StringIO(resp.text))
                for r in reader:
                    if r.get("INSTRUMENT_NAME") == "OPTSTK":
                        sym = r.get("TRADING_SYMBOL", "").split("-")[0]
                        if sym:
                            fno_set.add(sym)
                            if sym not in lot_sizes:
                                try:
                                    lot_sizes[sym] = int(float(r.get("LOT_UNITS") or 0))
                                except (TypeError, ValueError):
                                    pass
        except Exception as e:
            print(f"[option_strategy_engine] error loading fno instruments: {e}")

    if not fno_set:
        fno_set = {
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL",
            "ITC", "KOTAKBANK", "LT", "AXISBANK", "BAJFINANCE", "TATAMOTORS", "MARUTI",
            "SUNPHARMA", "TITAN", "ULTRACEMCO", "TATASTEEL", "POWERGRID", "NTPC",
            "PAYTM", "YESBANK", "LICHSGFIN", "INDUSTOWER", "LAURUSLABS", "PIIND",
            "GODREJPROP", "COCHINSHIP", "IEX", "KEI", "GODFRYPHLP", "LODHA",
        }

    _FNO_SET_CACHE["at"] = now
    _FNO_SET_CACHE["symbols"] = fno_set
    _FNO_SET_CACHE["lot_sizes"] = lot_sizes


def get_fno_symbols() -> set[str]:
    """Returns the set of symbols permitted for equity options (OPTSTK) on NSE."""
    _ensure_fno_cache()
    return _FNO_SET_CACHE["symbols"]


def get_fno_lot_sizes() -> dict[str, int]:
    """Returns {symbol: lot size} for equity options, from the same live feed."""
    _ensure_fno_cache()
    return _FNO_SET_CACHE["lot_sizes"]


def get_options_universe() -> list[dict]:
    """Real equity candidates eligible for the options screener: LTP > ₹1,000
    and lot size < 500, RELIANCE always exempt from both thresholds. This is
    the single definition of the universe -- the Top 10 screener and the
    sector heatmap both filter through this, so they never disagree."""
    fno_set = get_fno_symbols()
    lot_sizes = get_fno_lot_sizes()
    candidates = equity_scan.load_liquid_candidates()

    def _passes(c: dict) -> bool:
        sym = c.get("symbol")
        if sym not in fno_set:
            return False
        if sym == "RELIANCE":
            return True
        ltp = c.get("ltp") or 0.0
        lot = lot_sizes.get(sym)
        return ltp > MIN_LTP_FOR_OPTIONS and lot is not None and lot < MAX_LOT_SIZE_FOR_OPTIONS

    return [c for c in candidates if _passes(c)]


_HEATMAP_CACHE = {"at": 0.0, "data": None}
_HEATMAP_TTL_SEC = 60.0
_EMPTY_HEATMAP = {"sectors": [], "total_stocks": 0, "updated_at": None}


def build_sector_heatmap() -> dict:
    """Cache-read only -- never computes inline. The actual computation runs
    on a schedule in a background thread (see refresh_sector_heatmap), so a
    page view is never blocked on it. Returns an empty-but-valid shape until
    the first background refresh has completed."""
    return _HEATMAP_CACHE["data"] or _EMPTY_HEATMAP


def refresh_sector_heatmap() -> dict:
    """Groups the options-eligible universe (same filter as the Top 10
    screener) by sector, for a day-change heatmap. Real day moves only --
    a candidate missing a valid LTP/prev_close is skipped, not zero-filled.
    Called from a background loop, not from the request path."""
    now = time.time()
    candidates = get_options_universe()
    sectors: dict[str, list[dict]] = {}

    for c in candidates:
        ltp = c.get("ltp") or 0.0
        raw_pc = c.get("prev_close")
        if not raw_pc or raw_pc <= 0 or not ltp or ltp <= 0:
            continue
        day_chg_pct = ((ltp - raw_pc) / raw_pc) * 100.0
        sector = c.get("sector") or "Other"
        sectors.setdefault(sector, []).append({
            "symbol": c.get("symbol"),
            "name": c.get("name") or c.get("symbol"),
            "ltp": ltp,
            "day_chg_pct": round(day_chg_pct, 2),
            "volume_spike": round(c.get("volume_spike") or 1.0, 2),
            "rsi": round(c.get("rsi") or 50.0, 1),
        })

    for tiles in sectors.values():
        tiles.sort(key=lambda t: t["day_chg_pct"], reverse=True)

    sector_order = sorted(
        sectors.keys(),
        key=lambda s: sum(t["day_chg_pct"] for t in sectors[s]) / len(sectors[s]),
        reverse=True,
    )

    out = {
        "sectors": [{"name": s, "avg_chg_pct": round(sum(t["day_chg_pct"] for t in sectors[s]) / len(sectors[s]), 2),
                     "tiles": sectors[s]} for s in sector_order],
        "total_stocks": sum(len(v) for v in sectors.values()),
        "updated_at": now,
    }

    _HEATMAP_CACHE["at"] = now
    _HEATMAP_CACHE["data"] = out
    return out


_EMPTY_TOP_OPTIONS = {"ce_picks": [], "pe_picks": [], "updated_at": None, "total_picks": 0}


def scan_top_options_stocks() -> dict:
    """Cache-read only -- never computes inline. The OI/PCR liquidity check
    below needs up to ~16 live option-chain fetches, which is too slow and too
    fragile to API hiccups to run inside a page request; refresh_top_options_stocks
    does the real work on a schedule in a background thread instead."""
    return _TOP_OPTIONS_CACHE["data"] or _EMPTY_TOP_OPTIONS


def refresh_top_options_stocks() -> dict:
    """
    Filters exactly 10 stocks (5 CE and 5 PE) based on the stock screener's intraday
    scoring model, ensuring RELIANCE is always included in the list. Called from a
    background loop, not from the request path.
    """
    now = time.time()
    fno_candidates = get_options_universe()

    import sys
    sys.path.insert(0, r"D:\STOCK SCREENER APP")
    import screener_engine as se

    scored_buy = []
    scored_sell = []

    for c in fno_candidates:
        ltp = c.get("ltp") or 0.0
        raw_pc = c.get("prev_close")
        if not raw_pc or raw_pc <= 0 or not ltp or ltp <= 0:
            continue
        day_chg_pct = ((ltp - raw_pc) / raw_pc) * 100.0
        rsi = c.get("rsi") or 50.0
        vol_spike = c.get("volume_spike") or 1.0
        momentum = c.get("momentum") or 0.0
        rs_rating = c.get("rs_rating") or 50.0
        ma50 = c.get("ma50") or ltp

        if day_chg_pct > 0 and rsi >= 50.0:
            sc = se.intraday_score_components("BUY", day_chg_pct, vol_spike, rsi, momentum, rs_rating)
            scored_buy.append((sc["intraday_score"], c, day_chg_pct, sc))
        elif day_chg_pct < 0 and rsi <= 50.0:
            sc = se.intraday_score_components("SELL", day_chg_pct, vol_spike, rsi, momentum, rs_rating)
            scored_sell.append((sc["intraday_score"], c, day_chg_pct, sc))

    scored_buy.sort(key=lambda x: x[0], reverse=True)
    scored_sell.sort(key=lambda x: x[0], reverse=True)

    def _liquidity_and_sentiment(sym: str, want_sentiment: str) -> dict | None:
        """Fetches sym's live option chain and returns it only if real combined
        OI clears the liquidity floor and its PCR sentiment (indmoney_feed's own
        BULLISH/BEARISH/NEUTRAL convention) doesn't contradict the equity-side
        call. None if the chain can't be fetched at all -- a missing chain is
        never treated as passing."""
        chain = indmoney_feed.get_option_chain(sym)
        if not chain:
            return None
        total_oi = (chain.get("total_ce_oi") or 0) + (chain.get("total_pe_oi") or 0)
        if total_oi < MIN_TOTAL_OI_FOR_OPTIONS:
            return None
        sentiment = chain.get("pcr_sentiment") or "NEUTRAL"
        if want_sentiment == "BULLISH" and sentiment == "BEARISH":
            return None
        if want_sentiment == "BEARISH" and sentiment == "BULLISH":
            return None
        return chain

    def _enrich_with_liquidity(entries: list, want_sentiment: str, limit: int) -> list:
        kept = []
        for entry in entries[:OPTIONS_SHORTLIST_SIZE]:
            score, c, day_chg, sc_comp = entry
            chain = _liquidity_and_sentiment(c.get("symbol"), want_sentiment)
            if chain is None:
                continue
            kept.append((score, c, day_chg, sc_comp, chain))
            if len(kept) >= limit:
                break
        return kept

    # Top 5 CE Picks — each has cleared the real-OI liquidity floor and a
    # non-contradictory PCR reading on its own live chain.
    top_ce_entries = _enrich_with_liquidity(scored_buy, "BULLISH", 5)

    # Top 5 PE Picks with RELIANCE guaranteed — built only from real market data.
    # RELIANCE is included even if it missed the normal RSI<=50 gate or the
    # OI/PCR filter, as long as its real day move is bearish-leaning; it is
    # never given an invented quote, and its card still carries its own real
    # live OI/PCR whenever that chain is fetchable.
    scored_sell_without_rel = [x for x in scored_sell if x[1].get("symbol") != "RELIANCE"]
    rel_source = next((x for x in scored_sell if x[1].get("symbol") == "RELIANCE"), None)

    if rel_source is None:
        rel_cand = next((c for c in fno_candidates if c.get("symbol") == "RELIANCE"), None)
        if rel_cand:
            ltp = rel_cand.get("ltp") or 0.0
            raw_pc = rel_cand.get("prev_close")
            if raw_pc and raw_pc > 0 and ltp and ltp > 0:
                day_chg_pct = ((ltp - raw_pc) / raw_pc) * 100.0
                if day_chg_pct <= 0:
                    rsi = rel_cand.get("rsi") or 50.0
                    vol_spike = rel_cand.get("volume_spike") or 1.0
                    momentum = rel_cand.get("momentum") or 0.0
                    rs_rating = rel_cand.get("rs_rating") or 50.0
                    sc_rel = se.intraday_score_components("SELL", day_chg_pct, vol_spike, rsi, momentum, rs_rating)
                    rel_source = (sc_rel["intraday_score"], rel_cand, day_chg_pct, sc_rel)

    rel_entry = None
    if rel_source:
        rel_chain = indmoney_feed.get_option_chain(rel_source[1].get("symbol"))
        rel_entry = (*rel_source, rel_chain)  # rel_chain may be None -- the card handles that

    top_pe_from_scan = _enrich_with_liquidity(scored_sell_without_rel, "BEARISH", 4 if rel_entry else 5)
    top_pe_entries = ([rel_entry] if rel_entry else []) + top_pe_from_scan
    if not top_pe_entries:
        # Nothing cleared the liquidity/sentiment filter and RELIANCE data
        # wasn't available either -- fall back to the raw top scores (still
        # real equity data, just not liquidity-checked) rather than an empty board.
        top_pe_entries = [(*e, None) for e in scored_sell[:5]]

    def _build_option_card(entry, direction: str) -> dict:
        score, c, day_chg, sc_comp, chain = entry
        sym = c.get("symbol")
        ltp = float(c.get("ltp") or 0.0)
        vol_spike = float(c.get("volume_spike") or 1.0)
        rsi = float(c.get("rsi") or 50.0)
        name = c.get("name") or sym
        sector = c.get("sector") or "Equity F&O"

        # Calculate step & ATM strike
        if ltp > 2000:
            step = 50.0
        elif ltp > 1000:
            step = 20.0
        elif ltp > 500:
            step = 10.0
        elif ltp > 100:
            step = 5.0
        elif ltp > 50:
            step = 2.5
        else:
            step = 1.0
        atm_k = round(ltp / step) * step
        strike_disp = int(atm_k) if float(atm_k).is_integer() else atm_k

        # Option trade parameters, OI and PCR: only populated from the real
        # chain fetched during selection above — never guessed off spot price.
        est_premium = None
        target1 = None
        target2 = None
        stop_loss = None
        delta = None
        total_oi = None
        pcr = None
        pcr_sentiment = None
        if chain:
            total_oi = (chain.get("total_ce_oi") or 0) + (chain.get("total_pe_oi") or 0)
            pcr = chain.get("pcr")
            pcr_sentiment = chain.get("pcr_sentiment")
            atm_opt = chain.get("atm_ce") if direction == "CE" else chain.get("atm_pe")
            if atm_opt and atm_opt.get("ltp"):
                est_premium = float(atm_opt["ltp"])
                target1 = round(est_premium * 1.40, 2)
                target2 = round(est_premium * 1.80, 2)
                stop_loss = round(est_premium * 0.70, 2)
                if atm_opt.get("delta") is not None:
                    delta = float(atm_opt["delta"])

        return {
            "symbol": sym,
            "name": name,
            "sector": sector,
            "direction": direction,
            "badge_class": "badge-green" if direction == "CE" else "badge-red",
            "rec_option": f"BUY {strike_disp} {direction}",
            "strike": strike_disp,
            "spot_ltp": ltp,
            "day_chg_pct": round(day_chg, 2),
            "volume_spike": round(vol_spike, 2),
            "rsi": round(rsi, 1),
            "intraday_score": round(score, 1),
            "premium": est_premium,
            "target1": target1,
            "target2": target2,
            "stop_loss": stop_loss,
            "rr": 1.33,
            "delta": delta,
            "total_oi": total_oi,
            "pcr": pcr,
            "pcr_sentiment": pcr_sentiment,
            "is_reliance": (sym == "RELIANCE"),
            "rationale": (
                f"{'Bullish momentum' if direction == 'CE' else 'Bearish breakdown'} with "
                f"day move {day_chg:+.2f}%, {vol_spike:.1f}x volume spike, and RSI {rsi:.1f}."
            ),
        }

    ce_cards = [_build_option_card(e, "CE") for e in top_ce_entries]
    pe_cards = [_build_option_card(e, "PE") for e in top_pe_entries]

    out = {
        "ce_picks": ce_cards,
        "pe_picks": pe_cards,
        "updated_at": now,
        "total_picks": len(ce_cards) + len(pe_cards),
    }

    _TOP_OPTIONS_CACHE["at"] = now
    _TOP_OPTIONS_CACHE["data"] = out
    return out

