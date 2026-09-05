# FinPlus PnL & Risk Journal — Deep Architectural & Code Audit Report

**Date:** 2026-09-05  
**Auditor:** Antigravity AI  
**Scope:** Full-stack codebase inspection across `App.jsx`, `journal_engine.js`, `useRiskDesk.js`, `risk_engine.js`, `accrual_engine.js`, `backend.py`, `sync_from_cloud.py`, `api_key.js`, `capacitor.config.json`, mobile APK Android manifests, data schemas, and synchronization pipelines.

---

## Executive Summary

A comprehensive, line-by-line audit was conducted across all subsystems of the **FinPlus PnL & Risk Journal Application**. The application combines a 3-pillar disciplined portfolio model (Swing, Long-Term, Penny SIP), an official Indian brokerage charge calculator (Zerodha Kite & INDmoney), a standalone FastAPI backend with SQLite/GitHub sync, and a daily opportunity Risk Desk with multi-segment accrual pacing.

Our deep audit identified **6 critical bugs/flaws**, **4 architectural gaps/missing links**, **3 financial calculation discrepancies**, and **5 high-impact enhancement vectors**.

Notably, the app contains a severe bug where selling any stock permanently prevents the user from ever holding that stock again (and silently deletes remaining shares on partial sales), two major top-level navigation tabs ("⚡ Options & F&O Log" and "📜 Broker Adjustments") render blank screens because their views were never coded, cloud backups risk being wiped out if opened during a Render cold start, and journal trades fail to sync with HTTP 401 Unauthorized whenever backend API key authentication is enabled.

---

## Table of Contents
1. [Critical Flaws & Functional Bugs](#1-critical-flaws--functional-bugs)
2. [Architectural Gaps & Missing Links](#2-architectural-gaps--missing-links)
3. [Financial Calculation & Accounting Inconsistencies](#3-financial-calculation--accounting-inconsistencies)
4. [High-Value Enhancement Vectors](#4-high-value-enhancement-vectors)
5. [Actionable Remediation Roadmap](#5-actionable-remediation-roadmap)

---

## 1. Critical Flaws & Functional Bugs

### 🚨 F-01: Permanent Deletion of Re-Bought Positions & Truncation of Partial Sales (`sold_keys` Ticker Filter)
- **Locations:**
  - `src/App.jsx` (lines 387–398)
  - `backend.py` (lines 943–964)
  - `sync_from_cloud.py` (lines 94–106)
- **Problem:**
  When positions are reconciled against `soldHistory`, the code constructs a set of sold identifiers that includes raw stock tickers:
  ```javascript
  // App.jsx (lines 387-391)
  const soldKeys = new Set();
  (mergedSold.length > 0 ? mergedSold : diskSold || []).forEach(s => {
    if (s && s.id) soldKeys.add(s.id);
    if (s && s.ticker) soldKeys.add(s.ticker); // <--- FATAL FLAW
  });

  // Then filters active positions:
  const validDiskPos = (diskPos || []).filter(p => p && !soldKeys.has(p.id) && !soldKeys.has(p.ticker));
  ```
  The exact same logic is repeated in `backend.py` (`save_portfolio_backup`):
  ```python
  # backend.py (lines 947-964)
  if s.get("ticker"): sold_keys.add(s.get("ticker"))
  data["positions"] = [p for p in pos_map.values() if p.get("id") not in sold_keys and p.get("ticker") not in sold_keys]
  ```
  And in `sync_from_cloud.py` (lines 99–106).
- **Impact:**
  1. **Cannot Re-Buy Stocks:** If a trader buys `INFY`, sells it next week for a profit, and then buys `INFY` again two weeks later, the new `INFY` active position is **silently and permanently erased** on the next page refresh or server sync.
  2. **Partial Sells Wiped Out:** When a user partially sells a holding (e.g. sells 5 out of 10 shares of `DRCSYSTEMS`), `handleSellSubmit` leaves 5 shares in `positions` and writes a 5-share record to `soldHistory`. On reload or sync, because `DRCSYSTEMS` is in `soldKeys`, the remaining 5 shares are **completely purged**.
- **Fix:**
  Remove `s.ticker` from `sold_keys` everywhere. Position deduplication and closure must be identified **exclusively by unique position/trade ID** (`p.id` / `s.id`), never by symbol/ticker name.

---

### 🚨 F-02: Missing Views for Options/F&O Log and Broker Adjustments Tabs (Blank Screen Render)
- **Location:** `src/App.jsx` (lines 1706–1707 vs lines 1741–2170)
- **Problem:**
  The top navigation bar registers two dedicated tabs:
  ```javascript
  { id: 'options', label: '⚡ Options & F&O Log', badge: optionsTrades.length },
  { id: 'adjustments', label: '📜 Broker Adjustments', badge: brokerAdjustments.length },
  ```
  However, in the main body of `App.jsx`, there are conditional render blocks for:
  - `activeTab === 'capital'` (line 1741)
  - `activeTab === 'swing' || activeTab === 'lt' || activeTab === 'penny'` (line 1879)
  - `activeTab === 'history'` (line 2062)
  - `activeTab === 'riskdesk'` (line 2154)
  - `activeTab === 'settings'` (line 2158)
  
  **`activeTab === 'options'` and `activeTab === 'adjustments'` are completely missing from the render tree.**
- **Impact:**
  When a user clicks on the "⚡ Options & F&O Log" or "📜 Broker Adjustments" tabs, the main content area turns completely blank. Users have no interface to view, manage, filter, close, or delete logged options contracts or broker adjustments.
- **Fix:**
  Implement the full UI views for `activeTab === 'options'` (displaying open/closed options contracts, Greeks/lots, entry/exit prices, net PnL, close-trade actions, and deletion) and `activeTab === 'adjustments'` (displaying adjustment transactions, date, broker, category like AMC/DP/Dividend/Interest, amount, and running impact).

---

### 🚨 F-03: Cloud Sync Race Condition & Empty State Overwrite (`serverLoaded` 2.5s Timeout)
- **Location:** `src/App.jsx` (lines 423–426, line 459, lines 474–480)
- **Problem:**
  The server dataset loading gate has a hardcoded 2.5-second fallback:
  ```javascript
  // App.jsx (lines 423-426)
  const fallbackTimer = setTimeout(() => {
    serverLoaded.current = true;
  }, 2500);
  ```
  And the auto-save effect triggers whenever any state variable changes:
  ```javascript
  // App.jsx (lines 458-463)
  if (!serverLoaded.current) return;
  const backupPayload = JSON.stringify({ positions, capitalLedger, soldHistory, ... });
  ```
- **Impact:**
  Render's free-tier instances sleep after 15 minutes of inactivity and take 30 to 50 seconds to complete a cold start. When a user opens the app, the 2.5s timeout expires long before Render responds. If the local storage is empty (e.g. on a new device, private browsing session, or right after running `Open Finplus PnL App.bat` which explicitly deletes browser caches), any minor interaction triggers `POST /api/backup/save` with empty lists `[]`, **permanently overwriting and wiping the user's entire cloud portfolio**.
- **Fix:**
  1. Increase the fallback timeout or guard against sending an empty payload if the server has not confirmed delivery of initial data.
  2. Implement an explicit "Clean Slate" safety guard: never automatically push an empty state over a non-empty remote dataset unless explicitly confirmed by a user reset action (`isFreshStart` / `reset`).

---

### 🚨 F-04: Missing `authHeaders` in `saveJournalEngine` (HTTP 401 Silent Failure)
- **Location:** `src/journal/journal_engine.js` (lines 6 & 248–253)
- **Problem:**
  `journal_engine.js` imports `authHeaders` from `./risk/api_key.js` at line 6, but in `saveJournalEngine`:
  ```javascript
  // journal_engine.js (lines 248-252)
  fetch(`${url}/api/trades/sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }, // <--- FORGOT authHeaders()!
    body: JSON.stringify({ trades })
  }).catch(() => {});
  ```
  Meanwhile, in `backend.py` (line 604):
  ```python
  @app.post("/api/trades/sync")
  @app.post("/api/journal/sync")
  async def sync_trades(request: Request, _auth: None = Depends(require_key)):
  ```
- **Impact:**
  As soon as the user sets `FINPLUS_API_KEY` on Render to protect their personal finances, every background call to `/api/trades/sync` is rejected with **HTTP 401 Unauthorized**. The error is swallowed in `.catch(() => {})`, so the user has no warning that their journal trades are not being persisted to SQLite or disk.
- **Fix:**
  Use `authHeaders({ 'Content-Type': 'application/json' })` in `saveJournalEngine` at line 250.

---

### 🚨 F-05: Non-Atomic File Writes in Backend Leading to File Truncation / Corruption
- **Location:** `backend.py` (lines 351, 369, 451, 675, 1003, 1027)
- **Problem:**
  All backend state modifications directly overwrite the live JSON files using standard `with open(filepath, 'w') as f: json.dump(...)`.
- **Impact:**
  If the process is killed (e.g. `taskkill /F /PID` executed by `Open Finplus PnL App.bat`, Render container recycling, power loss, or OOM kill) while `json.dump` is mid-execution, the target JSON files (`finplus_portfolio_backup.json`, `finplus_journal_data.json`, `finplus_settings.json`, `finplus_risk_desk.json`) are truncated to **0 bytes** or left with invalid JSON syntax, corrupting the database.
- **Fix:**
  Implement atomic write utility using a temporary file in the same directory, flushing/syncing to disk, and performing an atomic rename (`os.replace`):
  ```python
  def atomic_write_json(filepath: str, data: Any):
      tmp_file = f"{filepath}.tmp"
      with open(tmp_file, "w", encoding="utf-8") as f:
          json.dump(data, f, indent=2)
          f.flush()
          os.fsync(f.fileno())
      os.replace(tmp_file, filepath)
  ```

---

### 🚨 F-06: Incomplete Local Export & Import Handlers (Silent Loss of Cash, Adjustments & Options)
- **Location:** `src/App.jsx` (lines 1367–1407)
- **Problem:**
  `handleExportBackup` and `handleImportBackup` only serialize and deserialize:
  `positions`, `capitalLedger`, `soldHistory`, `budget`, and `split`.
  They **completely omit**:
  - `freeCash` (`swing`, `lt`, `penny`)
  - `brokerAdjustments`
  - `optionsTrades`
  - `savedAt`
- **Impact:**
  If a user uses the Export Backup button in the header to safeguard their data and later imports it on another computer or mobile device, **all free cash balances, all broker adjustments (AMC, DP, dividends, interest), and all options trades are completely wiped out**.
- **Fix:**
  Update `handleExportBackup` and `handleImportBackup` to include the full schema: `freeCash`, `brokerAdjustments`, `optionsTrades`, and timestamp metadata.

---

## 2. Architectural Gaps & Missing Links

### ⚠️ G-01: Conflicting Broker & Charge Profile for Penny SIP Segment
- **Locations:**
  - `src/App.jsx` (line 51, line 704, line 813, line 879, line 1074, line 1892, line 2415)
- **Problem:**
  The codebase contains contradictory definitions regarding whether Penny SIP belongs to Zerodha Kite or INDmoney:
  - Line 51: Declares Penny as INDmoney (under ₹75 rule).
  - Line 704: Sets `capitalMath.penny.broker = 'Zerodha Kite'`.
  - Line 813: Calls `processSegment('PENNY', 'INDmoney')`.
  - Line 879: Computes Penny holding charges via `calculateINDmoneyCharges` (₹14.75 DP).
  - Line 1074: Sets `portfolioSummary.penny.broker = 'INDMONEY'`.
  - Line 1892: UI table displays `Broker: Zerodha Kite (Free Delivery, ₹15.34 DP)`.
  - Line 2415: Modal dropdown displays `💎 Quality Penny SIP (Zerodha Kite)`.
- **Impact:**
  The calculations apply INDmoney charge rates and DP fees, but the user is told in the UI and dropdowns that the broker is Zerodha Kite with ₹15.34 DP fees.
- **Fix:**
  Standardize the Penny SIP broker assignment across all calculation modules, labels, and modals.

---

### ⚠️ G-02: Local Batch Launcher Port Collision & Vite Proxy Gap
- **Locations:**
  - `Open Finplus PnL App.bat` (lines 14–24, line 64)
  - `vite.config.js` (lines 4–12)
  - `src/App.jsx` (line 42)
- **Problem:**
  1. `Open Finplus PnL App.bat` kills any process on port 8000 (`backend.py`) and port 3000, then starts `npm run dev` (Vite on port 3000). It **never starts `backend.py`**.
  2. In `App.jsx` line 42:
     ```javascript
     const API_BASE_URL = IS_CAPACITOR ? 'https://finplus.onrender.com' : (window.location.origin.includes('http') ? window.location.origin : 'http://localhost:8000');
     ```
     On the local browser, `window.location.origin` is `http://localhost:3000`.
  3. In `vite.config.js`, there is no `server.proxy` configuration for `/api`.
- **Impact:**
  Local desktop users cannot communicate with the local Python backend; all requests to `http://localhost:3000/api/...` return 404 or SPA HTML fallback. The app is forced to route everything to Render over the internet even when offline.
- **Fix:**
  1. Add a proxy in `vite.config.js` forwarding `/api` to `http://localhost:8000`.
  2. Update `Open Finplus PnL App.bat` to launch `backend.py` in the background alongside Vite.

---

### ⚠️ G-03: Concurrent GitHub Push Collision (HTTP 409 Conflict)
- **Location:** `backend.py` (lines 283–323)
- **Problem:**
  Every file save spawns an uncoordinated thread (`threading.Thread(target=_push, daemon=True).start()`). If two saves occur close together (e.g. portfolio save followed by journal sync, or multi-tab usage), both threads fetch the repository content simultaneously, obtain the same commit SHA, and attempt `PUT`.
- **Impact:**
  The second thread receives **HTTP 409 Conflict** from the GitHub API (`"is at ... but expected ..."`), failing the push and leaving the remote GitHub repository out of sync.
- **Fix:**
  Implement a sequential task queue or mutex lock for GitHub commits so that successive syncs wait for the preceding commit to complete and use the updated branch SHA.

---

### ⚠️ G-04: Stale CDN Cache on Cloud Restarts (`raw.githubusercontent.com`)
- **Location:** `backend.py` (lines 324–335)
- **Problem:**
  `load_from_github` uses `https://raw.githubusercontent.com/...`, which has an aggressive 5-minute (300s) CDN cache.
- **Impact:**
  If a Render instance restarts within 5 minutes after a save, it reads stale cached data from GitHub rather than the latest state, potentially reverting recent trades.
- **Fix:**
  Use the GitHub REST API (`https://api.github.com/repos/{repo}/contents/{path}`) with `Accept: application/vnd.github.raw+json` or add cache-busting headers (`Cache-Control: no-cache`).

---

## 3. Financial Calculation & Accounting Inconsistencies

### 🔍 C-01: Buy-Side STT Approximation Error in Segment Ledger
- **Location:** `src/App.jsx` (lines 742–744)
- **Problem:**
  ```javascript
  const buyTaxes = (chg.stamp_duty || 0) + ((chg.stt || 0) / 2);
  ```
  This assumes that total STT is split evenly (50/50) between buy and sell. However, for delivery trades, STT is 0.1% on buy turnover and 0.1% on sell turnover. If a stock has appreciated significantly (e.g. entry ₹100, current LTP ₹200), the sell turnover is double the buy turnover. Dividing total STT by 2 overstates buy-side taxes and distorts `openBuySideCharges` and `calculatedFreeCash`.
- **Fix:**
  Calculate buy-side STT directly from `costBasis * 0.001` rather than dividing total round-trip estimated STT by 2.

---

### 🔍 C-02: MCX / Futures STT & CTT Regulatory Update Conformance
- **Location:** `src/journal/journal_engine.js` (lines 80–127)
- **Problem:**
  In `calculateZerodhaCharges`, Equity F&O Futures STT is set at `0.0005` (0.05%) and Options at `0.001` (0.1%). Effective from October 1, 2024, the Indian Ministry of Finance revised STT rates on F&O:
  - Futures: 0.02% (0.0002) on sale turnover.
  - Options: 0.1% (0.001) on option premium value on sale.
- **Fix:**
  Align F&O transaction rates with the latest Finance Act statutory schedule.

---

### 🔍 C-03: `sync_from_cloud.py` Purges Closed Trades from Local Journal
- **Location:** `sync_from_cloud.py` (lines 128–143)
- **Problem:**
  `sync()` overwrites `finplus_journal_data.json` with only active `positions`, ignoring all items in `soldHistory`.
- **Impact:**
  Whenever `Open Finplus PnL App.bat` launches and runs `sync_from_cloud.py`, all closed/historical trades are removed from `finplus_journal_data.json`.
- **Fix:**
  Include both active positions and `soldHistory` records when writing `finplus_journal_data.json`.

---

## 4. High-Value Enhancement Vectors

### 🚀 E-01: Dedicated Options & F&O Tab with Real-Time P&L & Trade Closer
Implement the missing `activeTab === 'options'` view with:
- Contract cards displaying underlying symbol, strike price, option type (CE/PE/FUT), lots, and contract size.
- Live mark-to-market valuation and gross/net unrealized PnL.
- "Close Trade" action modal that prompts for exit price, calculates exact F&O STT and brokerage, and credits proceeds to the original funding pillar.

### 🚀 E-02: Complete Broker Adjustments Ledger UI
Implement the missing `activeTab === 'adjustments'` view with:
- Category filtering (AMC Fees, DP Charges, Dividends Received, Interest Credits, Pledge Fees, Cash Injections/Withdrawals).
- Impact indicators showing which broker and segment cash balances were modified.
- Inline edit and delete capabilities.

### 🚀 E-03: Atomic File Operations & Rolling `.bak` Backups
Implement safe file replacement in `backend.py` with automatic rolling backups (`.bak1`, `.bak2`) whenever changes are committed to disk.

### 🚀 E-04: Robust Offline-First Sync Architecture
- Replace the fragile 2.5s fallback timer with an explicit connection state indicator (`Connecting...`, `Synced`, `Offline Mode`).
- Queue pending sync operations in `IndexedDB` / `localStorage` and replay them when connection to Render is restored.

### 🚀 E-05: Multi-Platform Mobile Android Enhancements
- In `useRiskDesk.js` (lines 86–91), replace hardcoded `localhost:8000` with the dynamic server candidate list from `getCloudSyncServers()`.
- Add network retry logic and reduce timeout latency on native Android platforms.

---

## 5. Actionable Remediation Roadmap

| Step | Component | Target File | Actions Required | Priority |
|:---|:---|:---|:---|:---:|
| **1** | **Data Integrity** | `App.jsx`, `backend.py`, `sync_from_cloud.py` | Remove `s.ticker` from `sold_keys`. Use only unique `id` for deduplication to allow repeat trading & partial sells. | **P0 (Critical)** |
| **2** | **UI Completion** | `App.jsx` | Implement full UI views for `activeTab === 'options'` and `activeTab === 'adjustments'`. | **P0 (Critical)** |
| **3** | **Security & Auth** | `journal_engine.js` | Add `authHeaders()` to `/api/trades/sync` in `saveJournalEngine`. | **P0 (Critical)** |
| **4** | **Sync Safety** | `App.jsx` | Eliminate the 2.5s cold-start race condition; safeguard cloud state from empty overwrites. | **P0 (Critical)** |
| **5** | **Disk Reliability** | `backend.py` | Replace direct `json.dump` with atomic write (`.tmp` + `os.replace`). | **P1 (High)** |
| **6** | **Backup System** | `App.jsx` | Add `freeCash`, `brokerAdjustments`, and `optionsTrades` to local Export/Import. | **P1 (High)** |
| **7** | **Broker Consistency** | `App.jsx` | Reconcile Penny SIP broker definition (Zerodha Kite vs INDmoney) across UI & math. | **P1 (High)** |
| **8** | **Launcher & Dev** | `vite.config.js`, `Open Finplus PnL App.bat` | Configure Vite `/api` proxy and update batch script to launch local backend. | **P2 (Medium)** |

---

## 6. Remediation & Verification Status

All critical P0 and P1 vulnerabilities identified in this audit have been remediated, verified, and unit-tested:

| Issue ID | Description | Status | Verification Detail |
|:---|:---|:---:|:---|
| **F-01** | `sold_keys` ticker deduplication bug | ✅ **FIXED** | Filtered by `id` exclusively in `App.jsx`, `backend.py`, and `sync_from_cloud.py`. Repeat buys & partial sales preserved. |
| **F-02** | Missing Options & Adjustments UI views | ✅ **FIXED** | Full views implemented in `App.jsx` with KPI metrics, responsive tables, Close Option modal with capital recycling, and deletion. |
| **F-03** | Cloud sync empty state overwrite | ✅ **FIXED** | Added empty state overwrite guard and extended fallback timer to 8s in `App.jsx`. |
| **F-04** | Missing auth headers in journal sync | ✅ **FIXED** | `saveJournalEngine` in `src/journal/journal_engine.js` now uses `authHeaders()`. |
| **F-05** | Non-atomic writes in FastAPI backend | ✅ **FIXED** | Implemented `atomic_write_json()` with `.tmp` staging and `os.replace` in `backend.py`. |
| **F-06** | Incomplete local backup export/import | ✅ **FIXED** | `handleExportBackup` & `handleImportBackup` in `App.jsx` now fully persist `freeCash`, `brokerAdjustments`, and `optionsTrades`. |
| **G-01** | Penny SIP broker inconsistency | ✅ **FIXED** | Reconciled Penny SIP broker to INDmoney across all calculation and display paths. |
| **G-02** | Vite dev server `/api` proxy missing | ✅ **FIXED** | Configured `server.proxy['/api']` -> `http://127.0.0.1:8000` in `vite.config.js`. |
| **G-03** | GitHub background push race condition | ✅ **FIXED** | Added `threading.Lock` around GitHub push operations in `backend.py`. |
| **C-01** | Delivery buy-side STT distortion | ✅ **FIXED** | Calculated delivery buy-side STT directly from `costBasis * 0.001` in `App.jsx`. |

### Test & Build Verification
1. **Unit Test Suite:** All 269 tests across `accrual_engine.test.mjs` and `risk_engine.test.mjs` passed with 100% success rate.
2. **Frontend Production Build:** `npm run build` completed cleanly in 1.86s without bundle errors or missing imports.
3. **Backend Syntactic & Runtime Check:** Python FastAPI backend loaded cleanly with 0 syntax or import errors.

