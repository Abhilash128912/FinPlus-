"""
fresh_rs.py -- universe-wide Relative Strength rating (1-99) from FRESH INDstocks daily candles.

Same definition as screener_engine.compute_relative_strength_ratings():
    raw = 0.4 * (stock 1M return - NIFTY 1M return) + 0.6 * (stock 3M return - NIFTY 3M return)
ranked as a percentile across the whole stock universe. The desktop scan computes this once per
scan, so its stored RS can be days old; this recomputes it from today's candles. Only the final
ratings are kept in memory (not the candles), refreshed at most every RS_TTL_SEC.
"""
import time

import requests

import equity_scan

RS_TTL_SEC = 6 * 3600          # refresh interval
RS_MAX_AGE_SEC = 12 * 3600     # older than this is treated as unavailable
_RS: dict = {"at": 0.0, "rating": {}, "coverage": 0, "universe": 0}


def _closes_ret(close, back: int):
    return (float(close.iloc[-1]) / float(close.iloc[-back - 1]) - 1.0) * 100.0


def refresh_universe_rs(force: bool = False) -> dict:
    """Recompute every stock's RS rating. ~2,500 stocks = ~500 INDstocks requests (5 stocks each),
    paced under the rate limit with back-off on HTTP 429."""
    if not force and _RS["rating"] and time.time() - _RS["at"] < RS_TTL_SEC:
        return _RS
    import indmoney_feed
    symbols = sorted({r["symbol"] for r in equity_scan.load_screener_data() if r.get("symbol")})
    sec_map = equity_scan.get_security_id_map()
    nifty = indmoney_feed.get_daily_candles("NSE_40000001", days=200)["Close"].dropna()
    if len(nifty) < 70:
        print("[fresh_rs] NIFTY candles unavailable; RS not refreshed")
        return _RS
    n1, n3 = _closes_ret(nifty, 21), _closes_ret(nifty, 63)

    todo = [s for s in symbols if s in sec_map]
    raw: dict = {}

    def _collect(names: list) -> list:
        """Fetch candles for `names` (5 per request, paced, 429 back-off), add their raw RS to
        `raw`, and return the names whose request FAILED (throttled/errored) so they can be retried.
        A stock with fewer than 64 bars is simply too new for a 3-month return -- not a failure."""
        failed = []
        for i in range(0, len(names), 5):
            batch = names[i:i + 5]
            code_to_sym = {f"NSE_{sec_map[s]}": s for s in batch}
            dfs = None
            for attempt in range(5):
                try:
                    dfs = equity_scan.fetch_daily_candles_batch(list(code_to_sym), days=140)
                    break
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 429:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    break
                except Exception:
                    break
            if dfs is None:
                failed.extend(batch)
                time.sleep(0.3)
                continue
            for code, sym in code_to_sym.items():
                df = dfs.get(code)
                if df is None or df.empty:
                    continue
                c = df["Close"].dropna()
                if len(c) < 64:
                    continue
                raw[sym] = 0.4 * (_closes_ret(c, 21) - n1) + 0.6 * (_closes_ret(c, 63) - n3)
            time.sleep(0.25)
        return failed

    failed = _collect(todo)
    for _ in range(2):                      # retry the throttled batches, slower each time
        if not failed:
            break
        time.sleep(6)
        failed = _collect(failed)

    if len(raw) < 0.6 * len(todo):
        print(f"[fresh_rs] only {len(raw)}/{len(todo)} stocks priced; keeping previous RS")
        return _RS
    ordered = sorted(raw, key=lambda s: (raw[s], s))
    n = len(ordered)
    rating = {s: max(1, min(99, int(round((k / n) * 99)))) for k, s in enumerate(ordered, 1)}
    _RS.update({"at": time.time(), "rating": rating, "coverage": len(raw), "universe": len(todo)})
    print(f"[fresh_rs] RS refreshed for {len(raw)}/{len(todo)} stocks")
    return _RS


def rs_rating(symbol: str):
    """Fresh RS rating for a symbol, or None if the universe RS is not (recently) available."""
    if time.time() - _RS["at"] > RS_MAX_AGE_SEC:
        return None
    return _RS["rating"].get(symbol)
