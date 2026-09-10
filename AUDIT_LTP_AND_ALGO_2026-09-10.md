# Screener Audit — Live LTP Pipeline + Filtering Algorithm
**Date:** 10 Sep 2026 · **Scope:** `fetch_and_build.py` (server + embedded HTML/JS), `screener_engine.py`
**Not covered:** backtesting (per your instruction), `mobile_view.py`, F&O engine, LT/penny pipelines.

## What I could and could not verify
- **Static trace:** complete, both files, end to end.
- **Empirical:** ran `screener_engine` against your own `cache/*.json` on your machine to reproduce the scoring bugs (results in §B1).
- **Live network:** could not test. The sandbox has no route to Yahoo, and the shell on your laptop is folder-scoped so it cannot reach `127.0.0.1:5050`. Verification commands for you to run are in §D.

---

## A. LIVE LTP PIPELINE

### How it actually works
```
browser (10s timer, visible rows only)
   -> POST /api/ltp {symbols:[...]}          (fetch_and_build.py:9646)
   -> handler is CACHE-ONLY, never fetches   (:9727 comment)
   -> reads GLOBAL_LTP_CACHE, else falls back to last-scan price (flagged stale)
background_ltp_warmer thread (:353)
   -> every 5s, takes <=120 most-recently-requested symbols
   -> batch_fetch_live_prices()  ->  yf.download(period="5d")   (:1353)
```
The architecture is sound. The problems are in the fetcher choice, the staleness maths, and the market-hours gating.

### A1 — [HIGH] The warmer uses daily bars, not the live quote endpoint
`batch_fetch_live_prices()` (`:1372`) calls `yf.download(tickers=chunk, period="5d")` and takes `Close` of the last **daily** bar as LTP. On NSE that bar is Yahoo's delayed consolidated daily candle — typically 15–20 min behind, and it does not tick every few seconds.

You already have the correct fetcher: `fetch_live_price_only()` (`:1285`) hits `/v8/finance/chart/{t}?interval=1m&range=1d` and reads `meta.regularMarketPrice` — the near-real-time quote, ~0.3s per call, with a curl_cffi fallback. It is currently used **only** inside the scan and for USDINR. The live feed never touches it.

**Fix:** give the warmer a quote-only path. `yf.download` is needed during a scan (you want OHLCV + recent bars); the warmer only needs a price.
```python
# in background_ltp_warmer(), replace  prices = batch_fetch_live_prices(symbols)
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
    prices = {t: {"price": p} for t, p in
              zip(symbols, ex.map(fetch_live_price_only, symbols)) if p}
```
Note `fetch_live_price_only` already writes `GLOBAL_LTP_CACHE` itself and has its own 10s/120s TTL, so drop that internal TTL or pass a bypass flag when the warmer calls it.

### A2 — [HIGH] The freshness window is smaller than the refresh cycle
`LTP_FRESH_WINDOW_SEC = 180` (`:279`) is the TTL the handler uses to decide "fresh". Your own comment on `:245` says `yf.download` costs **30–190s per call**. When a cycle lands above 180s, every price is classed expired — and the handler then throws the 190-second-old *live* price away and serves the **scan-time** price instead (`:9740–9748`, the `uncached` branch only consults `fallback_map`).

So the feed degrades from "3 minutes late" to "up to an hour late" precisely when it's slowest. Two fixes, both worth doing:
1. Fixing A1 makes a cycle ~2–5s, so 180s stops binding.
2. Never discard a live price for an older one — prefer cache, flag it, fall back only if there is no cached value at all:
```python
for norm_t in normalized_tickers:
    e = GLOBAL_LTP_CACHE.get(norm_t)
    if e and (now - e[1] < ttl):
        raw_prices[norm_t] = e[0]
    elif e:                       # expired but still newer than the scan
        raw_prices[norm_t] = e[0]
        stale_set.add(norm_t)
    else:
        uncached.append(norm_t)
```

### A3 — [MEDIUM] The warmer runs 24x7
`background_ltp_warmer()` has no market-hours check. It polls Yahoo every 5s on Saturdays, at 3am, on holidays — the exact behaviour that gets an IP rate-limited, and rate-limiting is what makes the feed look broken during the session. Gate the cycle:
```python
if not is_equity_market_open():
    time.sleep(60); continue
```
(Keep a slow post-close pass — one cycle every 5 min until ~16:00 IST — so the closing price settles in.)

### A4 — [MEDIUM] The browser's market-status clock ignores holidays
`calculateCurrentMarketStatus()` (`:4009`) checks weekends only — there is **no holiday list client-side** — and on every 30s tick it overwrites the server's honest answer:
```js
MARKET_INFO.is_equity_open = currentMkt.is_equity_open;   // :4097
```
So on 14 Sep (Ganesh Chaturthi — this coming Monday) the header will read *"Live Market · Active"* and the page will present Friday's closes as live prices. Inline `NSE_HOLIDAYS_2026` into the template alongside `SWING_GATES` and check it in that function.

### A5 — [MEDIUM] The holiday table is 2026-only and has one real miss
`NSE_HOLIDAYS_2026` (`:609`) vs the official NSE 2026 calendar:
- **Missing:** `2026-01-15` Municipal Corporation Election (Maharashtra) — a genuine NSE equity holiday.
- **Harmless extras:** 15 Feb (Sun), 21 Mar (Sat), 15 Aug (Sat) already fall on weekends.
- **Wrong classification:** `2026-11-08` Diwali Laxmi Pujan is a **Muhurat trading session**, not a closure. Marking it a holiday makes `is_equity_market_open()` return False that evening, so LTP drops to the 120s closed-market cadence during a live session.
- **From 01 Jan 2027 the dict is empty**, so every 2027 weekday is treated as a trading day. Move this to a small JSON file you refresh yearly, and log a warning when `max(holiday year) < current year`.

### A6 — [MEDIUM] Live price flips WAIT to BUY_NOW on a price touch alone
`refreshLiveLTP()` (`:6046`):
```js
if (sc.ltp >= sc.gtt_breakout_level && (sc.status === 'WAIT' || sc.swing_action === 'WAIT FOR BREAKOUT')) {
    sc.status = 'BUY_NOW'; sc.swing_action = 'BUY NOW';
}
```
This is the reversal-from-resistance trap. An intraday *touch* of the level, on no volume, with two hours left in the session, is promoted to BUY NOW — and it never reverts if price falls back below. The scan's own breakout rule requires close > level **and** volume >= 1.3x avg **and** body >= 50% of range; the live path requires none of that. Either (a) make it revert when `ltp < level`, or (b) introduce an intermediate `LEVEL TOUCHED — AWAIT CLOSE` state and only promote to BUY NOW after 15:15 IST. (b) is what your strategy actually says.

### A7 — [LOW] Per-symbol fallback prices are never checked for staleness
In the bulk path, `stalePrices` is populated from the server's `stale` map. The per-symbol retry (`fetchLiveLTPForSymbol`, `:6001`) adds to `fetchedPrices` with no staleness check, so scan-time fallbacks arriving via that path inflate `freshCount` and can hold the badge green while the feed is dead.

### A8 — [LOW] Hourly scheduler uses naive local time and ignores holidays
`automated_hourly_market_scheduler()` (`:10673`) calls `datetime.datetime.now()` with no tzinfo — the one thing the module header at `:47` forbids — and gates on `weekday() < 5` only. Harmless on the laptop today, wrong on any UTC host, and it runs full hourly scans on holidays. Use `datetime.datetime.now(IST)` and `is_non_trading_day()`.

---

## B. FILTERING / SCORING ALGORITHM

### B1 — [CRITICAL] Fibonacci, AVWAP and RSI-divergence scores are silently dropped from the final result
`compute_swing_setup()` returns `fib_status`, `fib_badge`, `avwap_status`, `has_rsi_div` … but **not** `fib_pts`, `avwap_pts`, `rsi_div_pts` (`screener_engine.py:1170–1199`).

It is then called a second time — twice, in fact — with `history=None`:
- `apply_1h_sr_overlay()` → `compute_swing_setup(scored)` (`fetch_and_build.py:8834`)
- `compute_relative_strength_ratings()` → `compute_swing_setup(s)` (`screener_engine.py:1848`)

On those passes the function reads the points back off the row:
```python
"fib_pts": float(scored.get("fib_pts") or 0.0)      # :1090  -> always 0.0
"avwap_pts": float(scored.get("avwap_pts") or 0.0)  # :1096  -> always 0.0
"rsi_div_pts": float(scored.get("rsi_div_pts") or 0.0)  # :1102 -> always 0.0
```
They were never written, so they come back **zero every time**. The RS pass runs last, so **the scores that reach `screener_data.json`, the HTML and the APK are the ones with all three engines zeroed out.** Up to 25 setup points (≈41 points of `setup_score` after the /60 normalisation) and 15 entry points vanish.

Reproduced on your own cache, pass 1 vs pass 2:

| Symbol | setup 1→2 | entry 1→2 | action 1 → action 2 |
|---|---|---|---|
| BEL | 60.0 → **40.0** | 100 → 96 | WATCH / WAIT → **REJECT** |
| FEDERALBNK | 53.3 → **41.7** | 76 → 61 | WATCH / WAIT → **REJECT** |
| TNPL | 68.3 → 61.7 | 89 → 74 | WATCH / WAIT (score −9.5) |
| RVNL | 0.0 → 35.0 | 56 → 61 | (−25 fib penalty lost) |
| ITC / NBCC | 0.0 → 11.7 | 56 → 61 | (−25 fib penalty lost) |

**Fix — one line.** Add the three keys to the return dict of `compute_swing_setup`:
```python
"fib_pts": fib_info.get("fib_pts", 0.0),
"avwap_pts": avwap_info.get("avwap_pts", 0.0),
"rsi_div_pts": rsi_div_info.get("rsi_div_pts", 0.0),
```
Everything downstream then reads real values. Re-run the scan after this — your BUY NOW / WATCH / REJECT distribution will move noticeably.

### B2 — [HIGH] The "Fibonacci retracement" has no swing ordering, so it is really "distance below the 50-bar high"
`compute_fibonacci_levels()` (`:920`) takes `swing_high = max(High[-50:])` and `swing_low = min(Low[-50:])` with **no requirement that the low precedes the high**. A retracement is only defined for a completed up-leg.

Consequences:
- A stock that topped, crashed, then bounced 65% off the bottom scores `FIB_382_ZONE` **+15 "prime swing entry"** — it is a downtrend bounce.
- Any healthy uptrend that had one sharp 50-bar range and sits >61.8% down it gets `FIB_618_EXCEEDED`, a **hard `REJECT — FIB 61.8% BROKEN` label that overrides every other signal** (`:1330`). That branch alone rejected ITC, NBCC, POWERGRID and RVNL in my run.

**Fix:** find the swing high first, then take the low **before** it:
```python
h_idx = int(recent_highs.values.argmax())
if h_idx == 0:                      # high is the oldest bar -> no up-leg to retrace
    return {**none_result}
swing_high = float(recent_highs.iloc[h_idx])
swing_low  = float(recent_lows.iloc[:h_idx].min())
```
and additionally require `ltp` to be above the 200-DMA before applying the 61.8% hard reject, so a long-term uptrend isn't killed by one violent 10-week range.

### B3 — [HIGH] The retest window is truncated to ~7 bars by the scan loop bound
`detect_sr_breaks_and_retests()` documents a 20-bar (1H) / 10-bar (daily) retest window, but the search loop is:
```python
for b in range(1, min(freshness_bars + 5, n)):   # :1683
```
1H: `freshness_bars=4` → b max 8 → `breakout_bars_ago` max **7**, against a `retest_window` of 20.
Daily: `freshness_bars=1` → b max 5 → `breakout_bars_ago` max **4**, against a window of 10.

So the RETEST_BUY trigger can only ever see breakouts 2–7 bars back. Roughly two-thirds of your retest setups are invisible. **Fix:** `for b in range(1, min(retest_window + 2, n)):`

### B4 — [MEDIUM] "Fresh breakout" allows entry up to 6% above resistance
Trigger A accepts `-0.5 <= dist_from_res_pct <= 6.0` (`:1718`). That is exactly the "already 3–4% up by the time it fires" problem you've been chasing. Tighten the *entry-eligible* band to `<= 2.0%` and keep 2–6% as a separate `BREAKOUT — EXTENDED` label rather than a buy. Also note `prev_close <= res_level * 1.01` lets a bar count as a breakout when the previous close was already 1% **above** resistance.

### B5 — [MEDIUM] Resistance cluster selection can pick a level that isn't overhead
`best_cluster = max(clusters, key=lambda c: (len(c["prices"]), np.mean(c["prices"])))` (`:1667`) picks the most-tested cluster anywhere in the lookback, with no reference to current price. A heavily-tested cluster 12% below LTP wins over the genuine near-term ceiling. **Fix:** restrict candidates to clusters within roughly `-3%` to `+15%` of LTP before ranking, and prefer the nearest overhead cluster with >=2 tests.

### B6 — [MEDIUM] Early-session volume pacing can inflate `volume_spike` up to 66x
`score_momentum()` (`:355`) extrapolates partial-day volume:
```python
progress = min(1.0, max(0.015, mins_elapsed / 375.0))
vol_pace = vol / progress
```
The 0.015 floor means a scan at 09:16 divides five minutes of volume by 0.015 — a **66x** projection. `volume_spike` feeds the setup score (+8), the S/R confluence score (+15) and the intraday gate (`>=1.1`), so an opening-bell burst manufactures a full-day volume blowout across three engines. Compounding it: `vol` comes from the cached `info` dict, whose as-of time may not match "now" at all.

**Fix:** don't pace before ~09:45 (`mins_elapsed < 30` → use the raw ratio against a same-time-of-day baseline, or skip the volume component and mark it unavailable), and store the volume's own timestamp in the cache so the pacing denominator matches it.

### B7 — [MEDIUM] MA200 / MA50 / EMA20 are computed on short history without renaming
- `ma200 = Close.tail(200).mean()` runs at `len(history) >= 100` (`:255`) — with 120 bars you get a 120-DMA presented and used as the 200-DMA.
- `ma50` likewise at `len >= 40`.
- `ema20 = Close.ewm(span=min(20, len(history)))` (`:378`) — a 15-bar series yields a 15-EMA labelled EMA20.

These feed `dist_ma50_pct`, `dist_ema20_pct`, the trend classification and the entry score, so recently-listed names get systematically flattering trend readings. **Fix:** require the real period (`>= 200` / `>= 50` / `>= 20`) and emit `None` otherwise — your "show — when unavailable" convention already handles it downstream.

### B8 — [MEDIUM] `setup_score` saturates
`setup_score = min(100, setup_pts / 60 * 100)` (`:1215`), but the maximum attainable `setup_pts` is ~115 once fib/RSI-div are restored. Everything above 60 raw points collapses to 100, so your strongest setups are indistinguishable from merely good ones — and `setup_score >= 70` (the BUY NOW gate) is reached at just 42 raw points. Normalise by the real maximum, or use a percentile rank across the scan like you already do for RS.

### B9 — [MEDIUM] Market-cap filter in the UI disagrees with the badge on the row
JS `applyFilters()` (`fetch_and_build.py:7538`): large `>= 2,00,000 Cr`, mid `50,000–2,00,000 Cr`.
Python `run_scan()` (`:1774`): Large `>= 5,00,000 Cr`, Mid `1,50,000–5,00,000 Cr`.
Filter for "Large Cap" and you get rows badged "Mid Cap". Export `CAP_THRESHOLDS` from Python into the template the way `SWING_GATES` already is.

### B10 — [LOW] Two smaller filter defects
- `applyFilters()` line 1: `if (!search && qual === 'qualified' && ...)` — typing anything in the search box **silently disables the qualified/watch filter**.
- The sort inside `applyFilters()` does raw numeric subtraction (`(a[c]??-999) - (b[c]??-999)`), unlike `sortTable()` which handles strings. Sorting by symbol/sector there yields `NaN`.

### B11 — [LOW] `ret_1m` / `ret_3m` are not always 1M / 3M
`idx_1m = min(len(c_series) - 1, 21)` (`screener_engine.py:622`) — a stock with 12 bars of history gets a 12-day return fed into the RS percentile as if it were a 1-month return, competing against 21-day returns. Return `None` below the minimum bar count and exclude those rows from the RS ranking.

---

## C. ENHANCEMENTS (ranked by value per hour of work)

1. **ATR-normalise every stop and target.** `swing_sl` is a flat 3.5% with 2%/7% clamps (`:1264`) and intraday is a flat 1% (`:2861`), identical for a 0.8%-ATR largecap and a 4%-ATR smallcap. Use `SL = entry − 1.5 × ATR(14)`, targets at 1.5R/2.5R. This single change usually does more for hit-rate than any new signal.
2. **Position sizing from the risk budget.** You already store `screener_daily_risk_limit: 250` and per-bucket MSL in `screener_settings.json`, but no pick carries a quantity. Show `qty = floor(risk_per_trade / (entry − SL))` on every card — it turns a signal into an order.
3. **Persist a signal ledger.** Append every state transition (`WATCH → BUY NOW`, `BUY NOW → REJECT`) with timestamp, price and the reason string to a JSONL file. Costs ~20 lines, and it is what lets you reconcile the screener against your paper-trading app without a backtest harness.
4. **Confirm breakouts on the close, not the touch** (see A6). Add a `15:15 IST` re-evaluation pass that re-runs `detect_sr_breaks_and_retests` on the day's completed candle and freezes the day's verdict.
5. **Liquidity gate on the swing list too.** `INTRADAY_GATES` enforces `>= Rs 5 Cr` traded value; `SWING_GATES` only checks price and cap. A Rs 50-crore-cap MTF name with Rs 40 lakh of daily turnover currently passes. Add `min_traded_value` (Rs 2 Cr) to `SWING_GATES`.
6. **Sector breadth as a regime filter.** You compute per-stock RS but not sector RS. `% of a sector's stocks above their 50-DMA` is cheap from data you already have and is a strong veto — buying the best-looking name in the weakest sector is the common way a good screener loses money.
7. **Delivery percentage.** NSE publishes daily `sec_bhavdata_full.csv` free. Delivery % separates real accumulation from intraday churn better than any volume-spike ratio, and you flagged it as valuable in the pre-breakout work.
8. **Show data age on every card.** With A1–A3 fixed, print `LTP as of HH:MM:SS` and `scan as of HH:MM` on each row. Every decision you make from this app depends on which of the two numbers you're looking at.
9. **Split the 10,752-line `fetch_and_build.py`.** The ~5,700-line `HTML_TEMPLATE` string is where the client bugs in A4/A6/B9/B10 hide. `static/app.js` already exists — moving the template out is mechanical and matches your own <300-line convention.
10. **A `--selftest` flag** that scores 20 cached tickers and asserts invariants (pass-1 and pass-2 scores match, no `None` MAs on long history, `sr_score` in range). It would have caught B1 the day it was introduced.

---

## D. VERIFY IT YOURSELF

```powershell
# 1. Is the feed genuinely live? Run twice, 30s apart, during market hours.
curl "http://127.0.0.1:5050/api/ltp?symbols=RELIANCE,BEL,TCS"
#    -> "stale" must be false for all three, and prices must differ between runs.

# 2. Compare the warmer's price against the real quote:
curl "https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?interval=1m&range=1d"
#    -> meta.regularMarketPrice vs what /api/ltp returned. Gap = A1.

# 3. Prove B1 in one line:
python -c "import json;d=json.load(open('screener_data.json'));print([ (r['symbol'],r.get('fib_pts'),r.get('avwap_pts')) for r in d[:5] ])"
#    -> all None. They should be numbers.
```

## Fix order
**Today:** B1 (one line, changes every score on the page) → A5 + A4 (14 Sep is a holiday) → B3.
**This week:** A1 + A2 + A3 (the live feed) → A6 → B2.
**Then:** B4–B11, then §C.
