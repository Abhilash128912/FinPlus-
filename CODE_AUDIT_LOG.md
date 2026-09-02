# Stock Screener App — Code Audit & Fix Log
Last Updated: 2026-08-30

Scope: Correctness bugs (logic errors, wrong calculations, silent failures). P&L/capital ledger code is OUT OF SCOPE — stale, to be removed entirely (FinPlus PnL app handles that instead).

---

## 1. backend.py — AUDITED & FIXED

### BUG 1 — Dead route: `/` never serves the frontend
- **Issue:** Two handlers registered for `GET /`: `health_check()` (registered first at line 461 — won) and `serve_root()` (line 667 — unreachable dead code).
- **Status:** FIXED
- **Fix Details:** Removed duplicate `@app.get("/")` decorator from `health_check()`. Keep `@app.get("/health")` for health checks and `@app.get("/")` for `serve_root()`.

---

## 2. screener_engine.py — AUDITED & FIXED (3081 lines)

### BUG 2 — `has_strength_data` uses `any()` not a completeness check
- **Issue:** A stock with only 1 of 5 fundamental metrics available got full confidence weighting (40-50%) in `score_stock`, while partial data was indistinguishable from genuinely weak data.
- **Status:** FIXED
- **Fix Details:** Updated `score_stock` to require at least 2 valid fundamental metrics (`valid_s >= 2` and `valid_v >= 2`) before granting fundamental category weighting.

### BUG 3 — F&O strike labels off-by-one (`compute_fno_signal`)
- **Issue:** `ce_base` / `pe_base` were calculated but discarded, shifting strike recommendations one interval further OTM than labeled.
- **Status:** FIXED
- **Fix Details:** Updated strike assignments to `ce_strike_1 = ce_base`, `ce_strike_2 = ce_base + strike_iv` (and mirrored for PE).

### BUG 4 — Stale NSE expiry day assumption (`get_nse_monthly_expiry`)
- **Issue:** Monthly contract expiry calculated last Thursday (`weekday - 3`) instead of Tuesday (`weekday - 1`) per the updated NSE circular.
- **Status:** FIXED
- **Fix Details:** Updated `get_nse_monthly_expiry()` helper logic to calculate Tuesday expiries (`weekday - 1`). Companion UI text in `fetch_and_build.py` (line 5240) also updated.

---

## 3. fetch_and_build.py — IN PROGRESS (8272 lines; P&L/ledger sections skipped per user)

### BUG 5 — Timezone mismatch in cache staleness logic
- **Issue:** `save_cache()` saved naive timestamps (`now().isoformat()`), which on UTC cloud host environments were interpreted as IST in `is_price_stale()`, creating a 5.5 hour staleness error.
- **Status:** FIXED
- **Fix Details:** Standardized `save_cache()`, `load_cache()`, and `is_price_stale()` to use explicit IST timezone awareness (`datetime.timezone(datetime.timedelta(hours=5, minutes=30))`).

### MAJOR STRUCTURAL FINDING — Three competing frontends
- `Procfile` (`web: python fetch_and_build.py`) is what's actually deployed. `fetch_and_build.py` contains its own embedded HTTP server (`ScanRequestHandler` class) AND embedded HTML template (`HTML_TEMPLATE`), written to `index.html`.
- `backend.py` (FastAPI) is a separate, parallel backend that only serves whatever static `index.html` exists.
- `src/App.jsx` (React, 6900 lines) cannot currently be built due to missing dependencies in `package.json`.
- **Note:** Changes made in `src/App.jsx` are not reflected in the live app; live UI comes from `fetch_and_build.py`.

### SKIPPED (per user — stale P&L/ledger code, to be removed entirely)
- `execute_lt_buy_order` / `execute_lt_sell_order`
- `load_lt_capital_ledger` / `save_lt_capital_ledger` / `get_lt_portfolio_summary`
- `calc_indmoney_charges` (screener_engine.py)

---

## 4. Verification Results

Automated test script `scratch/test_audit_fixes.py` verified all 5 fixes:

```text
[PASS] Expiry test: 29 Sep 2026 is Tuesday (30 days to expiry)
[PASS] F&O strike test: CE1=2550, CE2=2600.0, PE1=2500, PE2=2450.0
[PASS] Cache staleness test: cached_at=2026-08-30T12:48:18.962258+05:30, is_stale=False
[PASS] Scoring completeness test: partial info score breakdown = 20.0
[PASS] Backend route test: / maps to serve_root

ALL 5 AUDIT FIX TESTS PASSED SUCCESSFULLY!
```
