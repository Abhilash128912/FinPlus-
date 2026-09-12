"""
NSE index futures feed via the INDmoney (INDstocks) trading API -- the
BankNifty/Nifty leg of the pair-trading signal.

Uses the front-month FUTURES contract for each index, not the raw spot
index: the index itself carries no genuine traded volume, and sr_volume's
delta-volume pivot gates need real volume to mean anything (mirrors how
fetch_mcx_futures() in fetch_and_build.py already picks a real traded
contract for crude/natgas rather than reasoning about spot). Front-month is
looked up dynamically from the FNO instrument list rather than hardcoded --
NIFTY-Sep2026-FUT is only the front month until expiry, then it rolls.

Auth: a bearer token from https://www.indstocks.com/app/api-trading/access-tokens,
read from the INDMONEY_ACCESS_TOKEN env var -- never hardcoded, never logged.
It expires every 24h by INDmoney's own design; this module does not attempt
silent refresh, a stale/missing token just makes calls fail, which callers
should treat as a feed outage like any other and degrade accordingly.
"""
import csv
import datetime
import io
import os
import time

import pandas as pd
import requests

BASE_URL = "https://api.indstocks.com"
INDEX_UNDERLYINGS = ("NIFTY", "BANKNIFTY")

# Front-month contract per index only changes on expiry day, so this is
# cached far longer than a price -- refetching the ~13MB instrument list
# every poll would be pure waste.
_FRONT_MONTH_CACHE: dict = {"at": 0.0, "contracts": {}}
_FRONT_MONTH_TTL_SEC = 6 * 3600


def _token() -> str | None:
    return os.environ.get("INDMONEY_ACCESS_TOKEN")


def _headers() -> dict:
    tok = _token()
    if not tok:
        raise RuntimeError("INDMONEY_ACCESS_TOKEN is not set")
    return {"Authorization": tok, "Accept": "application/json"}


def _refresh_front_month_cache() -> None:
    resp = requests.get(f"{BASE_URL}/market/instruments", params={"source": "fno"},
                         headers=_headers(), timeout=30)
    resp.raise_for_status()

    by_underlying: dict[str, list[dict]] = {u: [] for u in INDEX_UNDERLYINGS}
    for row in csv.DictReader(io.StringIO(resp.text)):
        if row.get("INSTRUMENT_NAME") != "FUTIDX":
            continue
        symbol = row.get("TRADING_SYMBOL", "")
        for underlying in INDEX_UNDERLYINGS:
            # Prefix match with the trailing "-": "NIFTY-Sep2026-FUT" must not
            # also catch "NIFTYNXT50-..." or leave "BANKNIFTY-..." unmatched
            # under the "NIFTY" key.
            if symbol.startswith(underlying + "-"):
                by_underlying[underlying].append(row)

    contracts = {}
    for underlying, rows in by_underlying.items():
        if not rows:
            continue

        def expiry_dt(row):
            try:
                return datetime.datetime.strptime(row["EXPIRY_DATE"], "%m/%d/%Y %H:%M")
            except (KeyError, ValueError):
                return datetime.datetime.max

        nearest = min(rows, key=expiry_dt)
        contracts[underlying] = {
            "security_id": nearest["SECURITY_ID"],
            "scrip_code": f"NFO_{nearest['SECURITY_ID']}",
            "trading_symbol": nearest["TRADING_SYMBOL"],
            "expiry": nearest.get("EXPIRY_DATE"),
            "lot_units": nearest.get("LOT_UNITS"),
        }

    _FRONT_MONTH_CACHE["contracts"] = contracts
    _FRONT_MONTH_CACHE["at"] = time.time()


def get_front_month_contract(underlying: str) -> dict | None:
    """underlying: 'NIFTY' or 'BANKNIFTY'. Returns None if the feed is down
    or the underlying has no current futures listing (shouldn't happen for
    these two, but a delisting/renaming should degrade, not crash)."""
    if time.time() - _FRONT_MONTH_CACHE["at"] > _FRONT_MONTH_TTL_SEC:
        _refresh_front_month_cache()
    return _FRONT_MONTH_CACHE["contracts"].get(underlying)


def get_ltp(scrip_code: str) -> float | None:
    return get_ltp_many([scrip_code]).get(scrip_code)


def get_ltp_many(scrip_codes: list[str]) -> dict[str, float | None]:
    """Batched LTP for multiple scrip-codes in one call -- for fast polling
    (e.g. every 3s for NIFTY+BANKNIFTY together) this is what keeps a tight
    poll loop to one request instead of one per symbol."""
    resp = requests.get(f"{BASE_URL}/market/quotes/ltp", params={"scrip-codes": ",".join(scrip_codes)},
                         headers=_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    return {code: data.get(code, {}).get("live_price") for code in scrip_codes}


def _parse_depth_node(node: dict) -> dict:
    def num(s):
        try:
            return float(str(s).replace(",", ""))
        except (TypeError, ValueError):
            return None

    agg = node.get("aggregate") or {}
    levels = []
    for lvl in node.get("depth") or []:
        levels.append({
            "buy_qty": num(lvl.get("buy", {}).get("quantity")),
            "buy_price": num(lvl.get("buy", {}).get("price")),
            "sell_price": num(lvl.get("sell", {}).get("price")),
            "sell_qty": num(lvl.get("sell", {}).get("quantity")),
        })
    best = levels[0] if levels else {}
    spread = (best.get("sell_price") - best.get("buy_price")
              if best.get("sell_price") is not None and best.get("buy_price") is not None else None)
    return {
        "total_buy": num(agg.get("total_buy")), "total_sell": num(agg.get("total_sell")),
        "buy_pct": agg.get("buy_percentage"), "sell_pct": agg.get("sell_percentage"),
        "best_bid": best.get("buy_price"), "best_ask": best.get("sell_price"), "spread": spread,
        "levels": levels,
    }


def get_market_depth(scrip_code: str) -> dict | None:
    return get_market_depth_many([scrip_code]).get(scrip_code)


def get_market_depth_many(scrip_codes: list[str]) -> dict[str, dict | None]:
    """5-level bid/ask depth + aggregate buy/sell split, batched into one
    call. Confirmed working for NFO index futures; MCX's free feed has no
    order-book data at all (BuyPrice/SellPrice/BuyQuantity/SellQuantity
    come back zero on every row -- it's a summary snapshot, not a real
    feed), so this has no MCX equivalent. INDmoney returns numbers as
    comma-formatted strings ("23,473") -- normalized to floats here."""
    resp = requests.get(f"{BASE_URL}/market/quotes/mkt", params={"scrip-codes": ",".join(scrip_codes)},
                         headers=_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    out = {}
    for code in scrip_codes:
        node = ((data.get(code) or {}).get("market_depth") or {}).get(code)
        out[code] = _parse_depth_node(node) if node else None
    return out


def get_quotes_full_many(scrip_codes: list[str]) -> dict[str, dict | None]:
    """Everything the fast-poll loop needs in ONE call: live price, day
    change (amount and %), day open/high/low, previous close, circuit
    limits, and the same 5-level depth get_market_depth_many returns --
    replaces what used to be two separate calls (ltp + mkt) each tick."""
    resp = requests.get(f"{BASE_URL}/market/quotes/full", params={"scrip-codes": ",".join(scrip_codes)},
                         headers=_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    out = {}
    for code in scrip_codes:
        node = data.get(code)
        if not node:
            out[code] = None
            continue
        depth_node = ((node.get("market_depth") or {}).get(code))
        out[code] = {
            "ltp": node.get("live_price"),
            "day_change": node.get("day_change"),
            "day_change_pct": node.get("day_change_percentage"),
            "day_open": node.get("day_open"), "day_high": node.get("day_high"), "day_low": node.get("day_low"),
            "prev_close": node.get("prev_close"),
            "upper_circuit": node.get("upper_circuit"), "lower_circuit": node.get("lower_circuit"),
            "volume": node.get("volume"),
            "depth": _parse_depth_node(depth_node) if depth_node else None,
        }
    return out


def get_daily_candles(scrip_code: str, days: int = 370) -> pd.DataFrame:
    """1D OHLCV, up to `days` back (INDmoney caps 1day interval at ~1 year per call)."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    resp = requests.get(f"{BASE_URL}/market/historical/1day",
                         params={"scrip-codes": scrip_code, "start_time": start_ms, "end_time": end_ms},
                         headers=_headers(), timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    candles = (payload.get("data") or {}).get(scrip_code, {}).get("candles") or []
    if not candles:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    df = df.set_index("time").rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    return df[["Open", "High", "Low", "Close", "Volume"]]


def get_hourly_candles(scrip_code: str, days: int = 14) -> pd.DataFrame:
    """1H OHLCV, up to `days` back (INDmoney caps 60minute at 15 days per call)."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    resp = requests.get(f"{BASE_URL}/market/historical/60minute",
                         params={"scrip-codes": scrip_code, "start_time": start_ms, "end_time": end_ms},
                         headers=_headers(), timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    candles = (payload.get("data") or {}).get(scrip_code, {}).get("candles") or []
    if not candles:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    df = pd.DataFrame(candles)
    df["time"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    df = df.set_index("time").rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    return df[["Open", "High", "Low", "Close", "Volume"]]


# ─── Option Chain & Expiries Support ──────────────────────────────────────────

_OPTION_EXPIRIES_CACHE: dict = {"at": 0.0, "data": {}}
_OPTION_EXPIRIES_TTL_SEC = 6 * 3600  # 6 hours cache
_INDEX_OPTION_UNDERLYINGS = ("NIFTY", "BANKNIFTY")


def _refresh_option_expiries_cache() -> None:
    """Pulls real expiry dates per underlying from the FNO instruments feed --
    the previous version of this cache was a hand-seeded dict of fixed 2026
    dates that was never refreshed from anywhere, so it silently went stale
    the moment those specific contracts expired."""
    resp = requests.get(f"{BASE_URL}/market/instruments", params={"source": "fno"},
                         headers=_headers(), timeout=30)
    resp.raise_for_status()

    by_underlying: dict[str, set[str]] = {}

    def _add(underlying: str, expiry_raw: str) -> None:
        try:
            dt = datetime.datetime.strptime(expiry_raw, "%m/%d/%Y %H:%M")
        except (ValueError, TypeError):
            return
        by_underlying.setdefault(underlying, set()).add(dt.strftime("%Y-%m-%d"))

    for row in csv.DictReader(io.StringIO(resp.text)):
        instrument = row.get("INSTRUMENT_NAME")
        symbol = row.get("TRADING_SYMBOL", "")
        expiry_raw = row.get("EXPIRY_DATE", "")
        if instrument == "OPTIDX":
            for underlying in _INDEX_OPTION_UNDERLYINGS:
                # Prefix match with the trailing "-": "NIFTY-..." must not also
                # catch "NIFTYNXT50-...".
                if symbol.startswith(underlying + "-"):
                    _add(underlying, expiry_raw)
        elif instrument == "OPTSTK":
            eq_symbol = symbol.split("-")[0]
            if eq_symbol:
                _add(eq_symbol, expiry_raw)

    _OPTION_EXPIRIES_CACHE["data"] = {u: sorted(dates) for u, dates in by_underlying.items()}
    _OPTION_EXPIRIES_CACHE["at"] = time.time()
_OPTION_CHAIN_CACHE: dict = {}  # key: (underlying, expiry) -> {"at": timestamp, "data": ...}
_OPTION_CHAIN_TTL_SEC = 5.0  # 5-second in-memory throttle to protect broker API limits

_NSE_EQUITY_IDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nse_equity_security_ids.json")
_NSE_EQUITY_IDS_MAP = None


def _get_equity_security_id(symbol: str) -> str | None:
    global _NSE_EQUITY_IDS_MAP
    if symbol == "RELIANCE":
        return "2885"
    if _NSE_EQUITY_IDS_MAP is None:
        try:
            if os.path.exists(_NSE_EQUITY_IDS_FILE):
                import json
                with open(_NSE_EQUITY_IDS_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    _NSE_EQUITY_IDS_MAP = raw.get("map", raw)
            else:
                _NSE_EQUITY_IDS_MAP = {}
        except Exception:
            _NSE_EQUITY_IDS_MAP = {}
    return _NSE_EQUITY_IDS_MAP.get(symbol.upper().strip())


def _last_weekday_of_month(year: int, month: int, weekday: int) -> "datetime.date":
    """weekday: Monday=0 ... Sunday=6. Returns the last such weekday in the given month."""
    if month == 12:
        next_month = datetime.date(year + 1, 1, 1)
    else:
        next_month = datetime.date(year, month + 1, 1)
    d = next_month - datetime.timedelta(days=1)
    while d.weekday() != weekday:
        d -= datetime.timedelta(days=1)
    return d


def get_option_expiries(underlying: str) -> list[str]:
    """Returns sorted ISO date strings (e.g. ['2026-09-15', '2026-09-22', ...]) for available expiries."""
    sym = underlying.upper().strip()

    if time.time() - _OPTION_EXPIRIES_CACHE["at"] > _OPTION_EXPIRIES_TTL_SEC:
        try:
            _refresh_option_expiries_cache()
        except Exception as e:
            print(f"[indmoney_feed] error refreshing option expiries: {e}")

    cached = _OPTION_EXPIRIES_CACHE.get("data", {}).get(sym)
    if cached:
        return cached

    # Live discovery hasn't produced data for this symbol yet (feed unreachable,
    # or a symbol with no listed options) -- compute a schedule instead of
    # falling back to a fixed date list that would eventually go stale.
    today = datetime.date.today()

    if sym in _INDEX_OPTION_UNDERLYINGS:
        fallbacks = []
        for w in range(1, 6):
            d = today + datetime.timedelta(days=w * 7)
            fallbacks.append(d.strftime("%Y-%m-%d"))
        return fallbacks

    # All NSE equity stocks trade on monthly contracts (last Thursday of the month).
    expiries = []
    year, month = today.year, today.month
    for _ in range(3):
        d = _last_weekday_of_month(year, month, 3)  # Thursday
        if d < today:
            month += 1
            if month > 12:
                month, year = 1, year + 1
            d = _last_weekday_of_month(year, month, 3)
        expiries.append(d.strftime("%Y-%m-%d"))
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return expiries


def get_option_chain(underlying: str, expiry: str | None = None) -> dict | None:
    """
    Fetches live option chain from INDmoney API with Greeks, IV, OI, Volume, and PCR.
    Supports NIFTY, BANKNIFTY, RELIANCE, and other NSE Equities.
    """
    sym = underlying.upper().strip()
    cache_key = (sym, expiry)
    now = time.time()

    cached = _OPTION_CHAIN_CACHE.get(cache_key)
    if cached and (now - cached["at"] < _OPTION_CHAIN_TTL_SEC):
        return cached["data"]

    # Resolve exchange, segment, underlying-scrip
    if sym == "NIFTY":
        exchange, segment, underlying_scrip = "NSE", "INDEX", "40000001"
    elif sym == "BANKNIFTY":
        exchange, segment, underlying_scrip = "NSE", "INDEX", "40000003"
    elif sym == "RELIANCE":
        exchange, segment, underlying_scrip = "NSE", "EQUITY", "2885"
    else:
        scrip = _get_equity_security_id(sym)
        if not scrip:
            return None
        exchange, segment, underlying_scrip = "NSE", "EQUITY", scrip

    # Resolve expiry if omitted
    expiries = get_option_expiries(sym)
    target_expiry = expiry if expiry else (expiries[0] if expiries else None)
    if not target_expiry:
        # Fallback default to current month end if expiries table is empty
        today = datetime.date.today()
        target_expiry = (today + datetime.timedelta(days=(3 - today.weekday() + 7) % 7)).strftime("%Y-%m-%d")

    try:
        resp = requests.get(
            f"{BASE_URL}/market/option-chain",
            params={
                "exchange": exchange,
                "segment": segment,
                "underlying-scrip": underlying_scrip,
                "expiry": target_expiry,
            },
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        raw_data = payload.get("data") or {}
        strikes_map = raw_data.get("strikes") or {}
        underlying_ltp = raw_data.get("underlying_ltp")

        if not strikes_map:
            return None

        # Sort strike keys numerically
        sorted_strike_nums = sorted([float(k) for k in strikes_map.keys()])
        atm_strike = (min(sorted_strike_nums, key=lambda k: abs(k - underlying_ltp))
                      if underlying_ltp else sorted_strike_nums[len(sorted_strike_nums) // 2])

        total_ce_oi, total_pe_oi = 0, 0
        total_ce_vol, total_pe_vol = 0, 0
        formatted_strikes = []

        for s_num in sorted_strike_nums:
            s_key = str(int(s_num)) if s_num.is_integer() else str(s_num)
            s_data = strikes_map.get(s_key) or {}
            ce = s_data.get("ce") or {}
            pe = s_data.get("pe") or {}

            ce_oi = int(ce.get("oi") or 0)
            pe_oi = int(pe.get("oi") or 0)
            ce_vol = int(ce.get("volume") or 0)
            pe_vol = int(pe.get("volume") or 0)

            total_ce_oi += ce_oi
            total_pe_oi += pe_oi
            total_ce_vol += ce_vol
            total_pe_vol += pe_vol

            formatted_strikes.append({
                "strike": s_num,
                "is_atm": (s_num == atm_strike),
                "ce": {
                    "security_id": ce.get("security_id"),
                    "trading_symbol": ce.get("trading_symbol"),
                    "ltp": ce.get("last_price"),
                    "prev_close": ce.get("previous_close_price"),
                    "oi": ce_oi,
                    "oi_change": ce_oi - int(ce.get("previous_oi") or ce_oi),
                    "volume": ce_vol,
                    "bid": ce.get("top_bid_price"),
                    "ask": ce.get("top_ask_price"),
                    "iv": ce.get("iv"),
                    "delta": (ce.get("greeks") or {}).get("delta"),
                    "theta": (ce.get("greeks") or {}).get("theta"),
                    "gamma": (ce.get("greeks") or {}).get("gamma"),
                    "vega": (ce.get("greeks") or {}).get("vega"),
                },
                "pe": {
                    "security_id": pe.get("security_id"),
                    "trading_symbol": pe.get("trading_symbol"),
                    "ltp": pe.get("last_price"),
                    "prev_close": pe.get("previous_close_price"),
                    "oi": pe_oi,
                    "oi_change": pe_oi - int(pe.get("previous_oi") or pe_oi),
                    "volume": pe_vol,
                    "bid": pe.get("top_bid_price"),
                    "ask": pe.get("top_ask_price"),
                    "iv": pe.get("iv"),
                    "delta": (pe.get("greeks") or {}).get("delta"),
                    "theta": (pe.get("greeks") or {}).get("theta"),
                    "gamma": (pe.get("greeks") or {}).get("gamma"),
                    "vega": (pe.get("greeks") or {}).get("vega"),
                }
            })

        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 1.0
        pcr_sentiment = "BULLISH" if pcr > 1.20 else "BEARISH" if pcr < 0.80 else "NEUTRAL"

        # Find ATM nodes for summary
        atm_node = next((s for s in formatted_strikes if s["is_atm"]), formatted_strikes[len(formatted_strikes)//2])
        atm_ce_ltp = atm_node["ce"].get("ltp") or 0.0
        atm_pe_ltp = atm_node["pe"].get("ltp") or 0.0
        straddle_prem = round(atm_ce_ltp + atm_pe_ltp, 2)

        out = {
            "underlying": sym,
            "underlying_ltp": underlying_ltp,
            "expiry": target_expiry,
            "available_expiries": expiries,
            "atm_strike": atm_strike,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "total_ce_volume": total_ce_vol,
            "total_pe_volume": total_pe_vol,
            "pcr": pcr,
            "pcr_sentiment": pcr_sentiment,
            "atm_ce": atm_node["ce"],
            "atm_pe": atm_node["pe"],
            "straddle_premium": straddle_prem,
            "upper_breakeven": round(atm_strike + straddle_prem, 2),
            "lower_breakeven": round(atm_strike - straddle_prem, 2),
            "strikes": formatted_strikes,
            "updated_at": now,
        }

        _OPTION_CHAIN_CACHE[cache_key] = {"at": now, "data": out}
        return out
    except Exception as e:
        print(f"[indmoney_feed] error fetching option chain for {sym}: {e}")
        return None


if __name__ == "__main__":
    for underlying in INDEX_UNDERLYINGS:
        contract = get_front_month_contract(underlying)
        if not contract:
            print(f"{underlying}: no front-month contract found")
            continue
        ltp = get_ltp(contract["scrip_code"])
        candles = get_hourly_candles(contract["scrip_code"])
        print(f"{underlying}: {contract['trading_symbol']} (expiry {contract['expiry']}) "
              f"ltp={ltp} bars={len(candles)}")
