"""
Real MCX futures feed + hourly bar accumulator for CRUDEOIL and NATURALGAS.

Ported from fetch_mcx_futures()/record_mcx_sample() in the STOCK SCREENER
APP's fetch_and_build.py (D:\\STOCK SCREENER APP), not reinvented: same
curl_cffi Chrome-impersonation approach (needed because MCX sits behind
Akamai bot-protection that blocks plain `requests` at the TLS layer, not
just the HTTP layer -- confirmed by hand during this app's build), same
"visit the page once to get past Akamai, then hit the JSON endpoint"
sequence, same front-month-by-volume contract selection.

MCX publishes no historical intraday candles at all -- only a live
snapshot (today's OHLC + previous close, no earlier history). Building
hourly bars means sampling that snapshot on a cadence and folding it into
the current hour's bar ourselves. mcx_bars.json is seeded from the
STOCK SCREENER APP's own accumulated history (63 bars each for CRUDEOIL
and NATURALGAS as of 2026-09-11) so the S/R model has enough bars to run
from day one instead of needing ~3 fresh trading days to reaccumulate --
the two files are independent copies from that point forward and will
drift apart, which is fine, they're sampling the same public data.
"""
import datetime
import json
import os
import time

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

MCX_MARKET_WATCH_URL = "https://www.mcxindia.com/market-data/market-watch/GetMarketWatch?culture=en"
MCX_SYMBOLS = ("CRUDEOIL", "NATURALGAS")

_MCX_CACHE = {"at": 0.0, "rows": []}
_MCX_TTL_SEC = 55.0  # matches the live-price poll cadence; MCX's snapshot is ~1.7MB, not cheap to refetch

MCX_BARS_FILE = os.path.join(BASE_DIR, "mcx_bars.json")
MCX_MAX_BARS = 1500


def is_commodity_session_open(now_ist: datetime.datetime | None = None) -> bool:
    """MCX: Mon-Fri, 09:00-23:30 IST. Doesn't account for MCX-specific
    holidays (a short list, mostly overlapping NSE's) -- worst case this
    samples a couple of extra times on a holiday, which record_mcx_sample
    already handles safely (a flat/unchanged snapshot just produces a
    flat bar, not corrupt data)."""
    now_ist = now_ist or datetime.datetime.now(IST)
    if now_ist.weekday() >= 5:
        return False
    t = now_ist.time()
    return datetime.time(9, 0) <= t <= datetime.time(23, 30)


def fetch_mcx_futures(symbol: str) -> dict:
    """Front-month (by volume) MCX futures snapshot for `symbol`
    ("CRUDEOIL" or "NATURALGAS"). Returns {} when the feed is unavailable
    -- callers must degrade, never invent a price."""
    global _MCX_CACHE
    now = time.time()
    if not _MCX_CACHE["rows"] or (now - _MCX_CACHE["at"]) > _MCX_TTL_SEC:
        try:
            from curl_cffi import requests as cr
            sess = cr.Session(impersonate="chrome")
            sess.get("https://www.mcxindia.com/market-data/market-watch", timeout=20)
            resp = sess.get(MCX_MARKET_WATCH_URL, timeout=25, headers={
                "Referer": "https://www.mcxindia.com/market-data/market-watch",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            })
            payload = json.loads(resp.text)
            _MCX_CACHE = {"at": now, "rows": (payload.get("data") or {}).get("Data") or []}
        except Exception as e:
            print(f"  [warn] MCX market watch unavailable: {e}")
            if not _MCX_CACHE["rows"]:
                return {}

    futures = [r for r in _MCX_CACHE["rows"]
               if r.get("Symbol") == symbol and r.get("InstrumentName") == "FUTCOM"]
    if not futures:
        return {}
    front = max(futures, key=lambda r: r.get("Volume") or 0)
    return {
        "mcx_symbol": symbol,
        "mcx_expiry": front.get("ExpiryDate"),
        "mcx_unit": front.get("Unit"),
        "mcx_ltp": front.get("LTP"),
        "mcx_change": front.get("AbsoluteChange"),
        "mcx_pct": front.get("PercentChange"),
        "mcx_volume": front.get("Volume"),
        "mcx_oi": front.get("OpenInterest"),
    }


def load_mcx_bars() -> dict:
    try:
        with open(MCX_BARS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_mcx_bars(state: dict) -> None:
    tmp = MCX_BARS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, separators=(",", ":"))
    os.replace(tmp, MCX_BARS_FILE)


def record_mcx_sample(state: dict, now_ist: datetime.datetime | None = None) -> dict:
    """Fold one market-watch snapshot into the current hourly bar. Volume
    arrives cumulative for the session; a bar's volume is the increase
    since the previous sample, reset to 0 on a new session or a decrease
    (session rollover) rather than trusted negative."""
    now_ist = now_ist or datetime.datetime.now(IST)
    bucket = now_ist.replace(minute=0, second=0, microsecond=0).isoformat()
    today = now_ist.date().isoformat()

    for symbol in MCX_SYMBOLS:
        quote = fetch_mcx_futures(symbol)
        ltp = quote.get("mcx_ltp")
        if not ltp:
            continue

        entry = state.setdefault(symbol, {"bars": [], "cum_volume": None, "date": today})
        cum = quote.get("mcx_volume") or 0
        if entry.get("date") != today or entry.get("cum_volume") is None or cum < entry["cum_volume"]:
            delta = 0.0
        else:
            delta = float(cum - entry["cum_volume"])
        entry["cum_volume"] = cum
        entry["date"] = today

        # Open interest is a running level (contracts outstanding), not a
        # per-bar flow like volume -- so the bar stores the latest OI reading
        # (its close-of-bar snapshot). OI *change* across bars is what carries
        # the signal (rising price + rising OI = conviction; rising price +
        # falling OI = short covering), and that is derived downstream.
        oi = quote.get("mcx_oi")

        bars = entry["bars"]
        if bars and bars[-1]["t"] == bucket:
            bar = bars[-1]
            bar["h"] = max(bar["h"], ltp)
            bar["l"] = min(bar["l"], ltp)
            bar["c"] = ltp
            bar["v"] += delta
            if oi is not None:
                bar["oi"] = oi
        else:
            bars.append({"t": bucket, "o": ltp, "h": ltp, "l": ltp, "c": ltp, "v": delta,
                         **({"oi": oi} if oi is not None else {})})
            if len(bars) > MCX_MAX_BARS:
                del bars[:-MCX_MAX_BARS]
    return state


def recent_oi_change(symbol: str, state: dict | None = None, lookback: int = 6) -> dict:
    """Open-interest direction over the last `lookback` bars that carry OI.

    Returns {"oi": latest, "oi_prev": earlier, "oi_pct": change %, "rising":
    bool|None}. rising is None when there aren't two OI readings to compare --
    OI only started being stored recently, so early bars have none and the
    caller must treat "unknown" as "no confirmation", not as "falling".
    """
    state = state if state is not None else load_mcx_bars()
    bars = (state.get(symbol) or {}).get("bars") or []
    ois = [(b["t"], b["oi"]) for b in bars if b.get("oi")]
    if len(ois) < 2:
        return {"oi": ois[-1][1] if ois else None, "oi_prev": None, "oi_pct": None, "rising": None}
    window = ois[-max(2, lookback):]
    latest = float(window[-1][1])
    prev = float(window[0][1])
    pct = ((latest - prev) / prev * 100.0) if prev else None
    return {"oi": latest, "oi_prev": prev,
            "oi_pct": round(pct, 2) if pct is not None else None,
            "rising": (latest > prev) if prev else None}


def bars_dataframe(symbol: str, state: dict | None = None) -> pd.DataFrame | None:
    state = state if state is not None else load_mcx_bars()
    bars = (state.get(symbol) or {}).get("bars") or []
    if not bars:
        return None
    return pd.DataFrame(
        [{"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"], "Volume": b["v"]} for b in bars],
        index=pd.to_datetime([b["t"] for b in bars]),
    )


if __name__ == "__main__":
    for sym in MCX_SYMBOLS:
        q = fetch_mcx_futures(sym)
        df = bars_dataframe(sym)
        print(f"{sym}: {q} | bars recorded: {0 if df is None else len(df)}")
