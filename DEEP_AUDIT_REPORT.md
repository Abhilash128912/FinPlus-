# Stock Screener Application — Deep Architectural & Code Audit Report

**Date:** 2026-09-03  
**Auditor:** Antigravity AI  
**Scope:** Full-stack codebase inspection across `fetch_and_build.py`, `screener_engine.py`, `download_nse_indices.py`, `mobile_api.py`, `static/app.js`, `screener.html`, mobile builds, caching, and data pipelines.

---

## Executive Summary

A comprehensive, line-by-line audit was conducted across all subsystems of the **Stock Screener Application**. The application features an impressive amount of financial engineering (Wilder's RSI, Mansfield Relative Strength vs Nifty, CMF order flow, ChartPrime S/R boxes, multi-cap scoring, and F&O option strikes).

However, our audit identified **6 critical bugs/flaws**, **4 missing links/architectural gaps**, and **4 high-impact enhancement vectors**. Notably, the web UI contains a broken scan status route resulting in 120-second hangs, mobile API endpoints are missing from HTTP GET, scan triggers cause server/LTP warmer collisions, large 10.6MB payloads are served uncompressed without atomic write safety, and Stock of the Day fallback logic risks violating cap constraints under extreme market regimes.

---

## Table of Contents
1. [Critical Flaws & Functional Bugs](#1-critical-flaws--functional-bugs)
2. [Missing Links & Architectural Gaps](#2-missing-links--architectural-gaps)
3. [System Constraints & Rules Conformance](#3-system-constraints--rules-conformance)
4. [High-Value Enhancement Recommendations](#4-high-value-enhancement-recommendations)
5. [Actionable Remediation Roadmap](#5-actionable-remediation-roadmap)

---

## 1. Critical Flaws & Functional Bugs

### 🔴 F-01: Broken Scan Status Polling Route (`/api/scan/status` returns 404)
- **Location:** `fetch_and_build.py` (line 3867 & lines 8896–9063), `static/app.js` (line 1867)
- **Problem:** When a user initiates a scan in the web UI, `triggerScan()` polls:
  ```javascript
  const statusUrl = 'http://localhost:' + (window.location.port || '8080') + '/api/scan/status';
  ```
  However, `ScanRequestHandler.do_GET()` only implements `/api/status`, not `/api/scan/status`. Every polling attempt returns **HTTP 404 Not Found**.
- **Impact:** The client never detects that the scan has finished (`sResp.ok` is always false). The progress bar artificially crawls to 90% and then **freezes for a full 120 seconds** until the safety timeout fires.
- **Fix:** Register `/api/scan/status` as an alias to `/api/status` in `do_GET()`, and update client-side code to use relative `/api/status` (`sData.is_scanning`).

---

### 🔴 F-02: Missing Mobile API Routes in HTTP `do_GET` (All Mobile GET Requests 404)
- **Location:** `fetch_and_build.py` (lines 9069–9090 vs lines 8896–9063)
- **Problem:** The mobile API endpoints:
  - `/api/mobile/screener`
  - `/api/mobile/watchlist`
  - `/api/mobile/holdings`
  - `/api/mobile/status`
  - `/api/mobile/search?q=...`
  - `/api/mobile/stock?symbol=...`
  were registered **only under `do_POST()`** in `ScanRequestHandler`.
- **Impact:** Any standard mobile app, React Native client, or browser issuing a standard HTTP `GET` request to search for a stock or fetch watchlist data falls through to `super().do_GET()`, returning **HTTP 404 Not Found**.
- **Fix:** Wire these endpoints into `do_GET()` as well so that standard REST queries with query strings (`?q=`, `?symbol=`) work seamlessly.

---

### 🔴 F-03: Manual `/api/scan` Concurrency Collision & Warmer Starvation
- **Location:** `fetch_and_build.py` (lines 9094–9155)
- **Problem:** When `/api/scan` is triggered via POST:
  1. `IS_INITIAL_SCANNING` is **never set to `True`**.
  2. Because `IS_INITIAL_SCANNING` remains `False`:
     - `/api/status` falsely reports `"is_scanning": false` while a heavy scan is active.
     - `ltp_should_defer_to_scan()` returns `False`. The background LTP warmer continues aggressively polling Yahoo Finance simultaneously with `run_scan()`, exhausting Yahoo's per-IP rate limit and triggering HTTP 429/401 errors.
  3. Unlike `background_initial_scan()`, the `/api/scan` handler fails to invoke `sync_monthly_lt_watchlist_additions()` and fails to pre-seed `GLOBAL_LTP_CACHE` with fresh scan prices.
- **Fix:** Unify `/api/scan` to call or share the centralized `background_initial_scan()` pipeline with proper mutex locking (`IS_INITIAL_SCANNING = True`, with `try ... finally: IS_INITIAL_SCANNING = False`).

---

### 🔴 F-04: Non-Atomic Writes on 10.6MB `screener_data.json` & Ledgers
- **Location:** `fetch_and_build.py` (line 78, `write_scan_json()`, `save_cache()`, and ledger handlers)
- **Problem:** `write_scan_json()` writes `OUT_JSON_FILE` (`screener_data.json`, ~10.6MB) using:
  ```python
  with open(OUT_JSON_FILE, "w", encoding="utf-8") as f:
      json.dump(clean_results, f, default=json_serializer)
  ```
  Writing 10.6MB of text takes 200–500ms on typical storage.
- **Impact:** During this write window, any concurrent HTTP request to `/screener_data.json` or `/api/mobile/screener` reads a partially written, truncated JSON file. This throws `json.JSONDecodeError: Unterminated string` and completely crashes the client application on boot.
- **Fix:** Serialize to a temporary file (`screener_data.json.tmp`) and use atomic replacement via `os.replace()`, utilizing the existing `atomic_write_file()` helper.

---

### 🔴 F-05: Stock of the Day Fallback Rule Violation
- **Location:** `fetch_and_build.py` (line 2242 & line 2317)
- **Problem:** When selecting the Stock of the Day:
  ```python
  if qualified_eligible:
      top = qualified_eligible[0]
  elif eligible_screener_results:
      top = eligible_screener_results[0]
  else:
      top = screener_results[0]  # <-- VIOLATION
  ```
- **Impact:** If market conditions are poor and no Large Cap or Mid Cap stock meets the score >= 55 threshold, falling back to `screener_results[0]` can pick an ineligible Small Cap, micro-cap, or penny stock. This directly breaches **Rule 1** in `AGENTS.md` (*"Stock of the Day MUST ONLY be selected from Large Cap or Mid Cap stocks ... Small Cap and micro-cap stocks are strictly prohibited. Price Floor >= ₹100.0"*).
- **Fix:** Replace `else: top = screener_results[0]` with a filter that strictly selects the highest-scoring eligible Large/Mid Cap stock (`[r for r in screener_results if is_eligible_for_stock_of_the_day(r)][0]`).

---

### 🔴 F-06: Mobile App `www/index.html` Out-of-Sync on LT Watchlist Edits
- **Location:** `fetch_and_build.py` (lines 8654–8678, `sync_html_lt_watchlist()`)
- **Problem:** When a user adds, deletes, or modifies a stock in the LT Watchlist, `sync_html_lt_watchlist()` updates `OUT_HTML` (`screener.html`) and `OUT_WWW_HTML` (`www/screener.html`), but **omits `WWW_INDEX_HTML` (`www/index.html`)**.
- **Impact:** Capacitor mobile builds exclusively read `www/index.html` (per `capacitor.config.json` `"webDir": "www"`). As a result, user watchlist modifications never show up in the mobile app until a full re-scan is executed.
- **Fix:** Include `WWW_INDEX_HTML` in `sync_html_lt_watchlist()`'s update loop.

---

## 2. Missing Links & Architectural Gaps

### 🟡 M-01: Absence of HTTP Gzip Compression on 10.6MB JSON Payloads
- **Location:** `fetch_and_build.py` (`ScanRequestHandler`)
- **Problem:** `screener_data.json` is ~10.6 megabytes of repetitive text keys. Python's built-in `http.server` does not compress HTTP responses.
- **Impact:** Every client launch downloads 10.6MB uncompressed. Over mobile data or on cloud platforms (Render/Heroku), this imposes a 5–15 second load penalty and rapidly exhausts cloud bandwidth allowances.
- **Remediation:** Implement gzip compression in `send_response()` or pre-compress `screener_data.json.gz` during scans. Gzip reduces 10.6MB to ~920KB (a **91% bandwidth reduction**).

---

### 🟡 M-02: Hardcoded `http://localhost` Hostnames in Client Scripts
- **Location:** `fetch_and_build.py` (lines 3866–3867, lines 5225–5231, lines 5411–5417)
- **Problem:** API calls in `static/app.js` and `HTML_TEMPLATE` explicitly construct URLs with `http://localhost:5050` or `http://localhost:${port}`.
- **Impact:** When running the web app on a local Wi-Fi network (accessed via PC IP like `http://192.168.1.15:5050`), or deployed to Render (`https://finplus-g0b5.onrender.com`), or inside the Android APK:
  - The client attempts to connect to `localhost` (the user's phone or remote machine), failing immediately with network error alerts.
- **Remediation:** Use relative paths (`/api/ltp`, `/api/scan`, `/api/status`) or `window.location.origin` with dynamic host detection.

---

### 🟡 M-03: Timezone Inconsistency in Trading Day Calculation
- **Location:** `fetch_and_build.py` (line 2004, `get_lt_portfolio_summary()`)
- **Problem:** `today_date = datetime.datetime.now().date()` uses system local time rather than IST (`now_ist.date()`).
- **Impact:** When deployed to cloud environments running on UTC (e.g. Render/AWS/Heroku), the system date before 05:30 AM IST evaluates to yesterday's date, causing off-by-one errors in `days_active`.
- **Remediation:** Standardize to `now_ist.date()` matching `get_market_status()`.

---

### 🟡 M-04: Orphaned `/api/settings` and Legacy Capital Fields
- **Location:** `screener_settings.json` & `fetch_and_build.py` (lines 9326–9350)
- **Problem:** `screener_settings.json` retains defunct capital fields (`screener_opening_capital`, `screener_daily_risk_limit`, `challenge_start_date`) from retired ledger workflows. `/api/settings` is only implemented in `do_POST` and is never fetched by the frontend.
- **Remediation:** Provide a clean `GET /api/settings` endpoint and deprecate unused ledger fields.

---

## 3. System Constraints & Rules Conformance

| Rule | Requirement | Current Status | Audit Finding |
|---|---|---|---|
| **Rule 1: Stock of the Day** | Large/Mid Cap only, LTP >= ₹100, lock persistence while ACTIVE, replace if INACTIVE/INVALIDATED | ⚠️ **Near-Compliant** | Hard price floor and cap checks are strictly enforced, but line 2317 contains a dangerous fallback to `screener_results[0]` if no stock meets score >= 55. |
| **Rule 2: Fundamental Data & Caching** | Genuine metrics (P/E, ROE, D/E, NPM), invalidate cache files missing fundamentals | ✅ **Compliant** | `load_cache()` validates presence of fundamental keys and triggers curl_cffi/yfinance fallback if missing. |
| **Rule 3: F&O / Options Signals** | Exactly 15 qualified stocks, LTP >= 1000 or Lot Size < 500, RELIANCE mandatory exception | ✅ **Compliant** | Exactly 15 stocks selected, RELIANCE is forcefully inserted into top 15 if missing. |
| **Rule 4: LT Trading Days Counter** | Trading days only (M–F excluding NSE holidays), dual GET/POST `/api/lt-portfolio/status` | ✅ **Compliant** | Dual HTTP methods implemented; iteration skips holidays and weekends. |
| **Rule 5: Modal HTML Hierarchy** | `ltAddModalBg` top-level un-nested | ✅ **Compliant** | Confirmed un-nested at root level. |

---

## 4. High-Value Enhancement Recommendations

### 💡 E-01: Lightweight Mobile Feed (`screener_summary.json`)
- **Current:** The client downloads the full 10.6MB dataset for all 2,568 stocks with 50+ indicators each.
- **Enhancement:** Generate a lightweight `screener_summary.json` (~1.1MB) containing only primary UI columns (`symbol`, `name`, `ltp`, `day_chg_pct`, `total_score`, `trend`, `sector`, `rs_rating`). Detailed financial breakdowns and ChartPrime levels can be fetched on demand per stock via `/api/mobile/stock?symbol=XYZ`.

### 💡 E-02: Real-time Scan Progress with Server-Sent Events (SSE)
- **Current:** Scan progress uses a synthetic timer interval (`progressPct = Math.min(progressPct + 5, 90)`).
- **Enhancement:** Implement an SSE endpoint (`/api/scan/live-progress`) streaming genuine milestones:
  1. "Downloading 5-day market data (17 chunks)..."
  2. "Scoring momentum & volume pacing (2,568 stocks)..."
  3. "Calculating Mansfield RS vs Nifty 50..."
  4. "Generating reports..."

### 💡 E-03: Cache Hygiene & Automatic Pruning
- **Current:** The `cache/` directory contains 2,588 JSON files (~150MB) and never deletes obsolete tickers.
- **Enhancement:** Implement an automated cleanup routine that removes cache files for symbols that have been delisted or are no longer part of the NSE active universe.

### 💡 E-04: Automated Gzip Pre-compression
- **Current:** Files are served as raw uncompressed text.
- **Enhancement:** During `write_scan_json()`, also write `screener_data.json.gz`. `ScanRequestHandler` can inspect `Accept-Encoding: gzip` and serve the pre-compressed byte stream with `Content-Encoding: gzip`, reducing load times from ~5 seconds to ~350ms.

---

## 5. Actionable Remediation Roadmap & Resolution Status

| Item | Description | Status | Verification Result |
|---|---|---|---|
| **F-01** | Fix `/api/scan/status` route 404 in `fetch_and_build.py` | ✅ **RESOLVED** | Route returns HTTP 200 with both `is_scanning` and `scan_in_progress`. Client no longer hangs. |
| **F-02** | Add `/api/mobile/*` routes to `do_GET()` | ✅ **RESOLVED** | All mobile endpoints (`/screener`, `/watchlist`, `/holdings`, `/status`, `/search`, `/stock`) return HTTP 200 on GET. |
| **F-03** | Guard `IS_INITIAL_SCANNING` in `/api/scan` | ✅ **RESOLVED** | Unified with `background_initial_scan()`, setting mutex flag, deferring warmer, returning 409 if busy. |
| **F-04** | Wrap `write_scan_json()` in `atomic_write_file()` | ✅ **RESOLVED** | `screener_data.json` now uses temporary swap to prevent concurrent truncated reads. |
| **F-05** | Eliminate `screener_results[0]` fallback in Stock of the Day | ✅ **RESOLVED** | Strict `is_eligible_for_stock_of_the_day` check enforced; Large/Mid cap and ₹100 floor strictly preserved. |
| **F-06** | Sync `www/index.html` on LT Watchlist edits | ✅ **RESOLVED** | `published_html_paths()` now inspects and includes `www/index.html` and `www/screener.html`. |
| **M-01** | HTTP Gzip compression on `screener_data.json` | ✅ **RESOLVED** | `ScanRequestHandler` dynamically compresses payload: 10.6MB down to 1.29MB (**88% bandwidth reduction**). |
| **M-02** | Replace hardcoded `localhost:8080` with dynamic origin | ✅ **RESOLVED** | Both `fetch_and_build.py` and `static/app.js` use `window.location.origin` with fallback to port 5050. |
| **M-03** | Standardize trading day timezone to explicit IST | ✅ **RESOLVED** | `get_lt_portfolio_summary()` and monthly penny lock calculation now use `now(IST).date()`. |
| **M-04** | Provide `GET /api/settings` endpoint | ✅ **RESOLVED** | Registered in `do_GET`, returning current JSON settings. |

---
*Report updated and verified: `D:\STOCK SCREENER APP\DEEP_AUDIT_REPORT.md`*

