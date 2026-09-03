"""
fetch_and_build.py
==================
Main script for the Stock Screener App.

Steps:
  1. Read D:\\Nifty 500 stocks.xlsx (or configured path)
  2. Convert NSE symbols → Yahoo Finance .NS tickers
  3. Filter: skip stocks where LTP >= Rs 5000 (Phase 1 gate)
  4. Fetch full yfinance data (batches of 5, with 24h cache)
  5. Score each stock using screener_engine.py
  6. Score your 6 watchlist stocks and fill in entry metrics
  7. Generate a self-contained index.html with all data baked in
  8. Open index.html in your default browser

Run: python fetch_and_build.py
"""

import json
import os
import sys
import time
import datetime
import random
import socket
import hashlib
import concurrent.futures
import urllib.request
import urllib.parse
import webbrowser
import http.server
import socketserver
import threading
import pandas as pd
import yfinance as yf
import logging

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

from screener_engine import score_stock, check_quality_alerts, compute_signal, check_top_pick_status, compute_trend_classification, compute_fno_signal, compute_nifty_market_regime, compute_relative_strength_ratings, get_lt_watchlist_status, compute_quality_penny_stocks, find_best_swing_candidate, compute_sector_aware_lt_quality, run_lt_universe_discovery_pipeline, compute_intraday_picks, select_monthly_lt_watchlist_additions
from screener_engine import TREND_STATES, UPTREND_STATES, TREND_DOWNTREND, sane_metric
from mobile_api import get_screener_data, get_lt_watchlist, get_holdings, search_stocks, get_stock_detail, get_app_status

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CACHE_DIR  = os.path.join(BASE_DIR, "cache")
WL_SEED    = os.path.join(BASE_DIR, "watchlist_seed.json")
WL_FILE    = os.path.join(BASE_DIR, "watchlist_data.json")
LT_WL_FILE = os.path.join(BASE_DIR, "lt_watchlist.json")
LT_MONTHLY_PICKS_FILE = os.path.join(BASE_DIR, "lt_monthly_picks.json")
PENNY_MONTHLY_PICKS_FILE = os.path.join(BASE_DIR, "penny_monthly_picks.json")
OUT_HTML   = os.path.join(BASE_DIR, "screener.html")
OUT_WWW_HTML = os.path.join(BASE_DIR, "www", "screener.html")
STATIC_DIR = os.path.join(BASE_DIR, "static")
APP_CSS_FILE = os.path.join(STATIC_DIR, "app.css")
APP_JS_FILE = os.path.join(STATIC_DIR, "app.js")
# The Capacitor Android WebView serves everything straight out of www/ as a bundled,
# offline-capable local site (webDir in capacitor.config.json) — it never talks to
# the Python HTTP server. So the split-out CSS/JS/data files also need copies under
# www/ with the same relative layout (www/static/app.css etc), or the packaged app
# would load an HTML shell that references /static/app.js and /screener_data.json
# with nothing there to serve them, and show a blank page.
WWW_STATIC_DIR = os.path.join(BASE_DIR, "www", "static")
WWW_APP_CSS_FILE = os.path.join(WWW_STATIC_DIR, "app.css")
WWW_APP_JS_FILE = os.path.join(WWW_STATIC_DIR, "app.js")
WWW_JSON_FILE = os.path.join(BASE_DIR, "www", "screener_data.json")
# The Capacitor CLI (`npx cap sync`) hard-requires an index.html at the webDir root
# as the app's entry point — it has no config option to point at a differently named
# file — so www/index.html must exist as a copy of www/screener.html even though the
# Python server itself is fine with either name.
WWW_INDEX_HTML = os.path.join(BASE_DIR, "www", "index.html")

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(WWW_STATIC_DIR, exist_ok=True)
IS_INITIAL_SCANNING = False
SCAN_STARTED_AT = 0.0
# Live LTP fetches stand aside while a scan runs so the two do not compete for
# Yahoo's per-IP budget. But a scan that overruns must not blank live prices for
# the rest of the session: past this bound, polling resumes even mid-scan. One
# batched LTP request per poll is cheap enough not to provoke rate limiting --
# it was ~100 individual requests that made deferring necessary in the first place.
MAX_SCAN_LTP_BLACKOUT_SEC = 600.0


def ltp_should_defer_to_scan() -> bool:
    """True while an in-flight scan should suppress live LTP fetches."""
    if not IS_INITIAL_SCANNING:
        return False
    if SCAN_STARTED_AT and (time.time() - SCAN_STARTED_AT) > MAX_SCAN_LTP_BLACKOUT_SEC:
        return False
    return True


LATEST_SCREENER_RESULTS = []
# Bumped every time a scan finishes (background_initial_scan / the /api/scan POST
# handler) so an already-open tab can tell a *later* scan completed, not just the
# one that happened to be running when it first loaded — see checkScanFreshness()
# client-side, which replaces the old one-shot startup-only reload check.
LAST_SCAN_COMPLETED_AT = None
# Epoch seconds of the last completed scan. LAST_SCAN_COMPLETED_AT above is an ISO
# string for the client; this is the machine-readable twin the scheduler needs to
# do interval arithmetic without reparsing it.
LAST_SCAN_FINISHED_AT = 0.0
# Minimum gap between automated scans. The scheduler previously only checked that
# no scan was *currently* running, so five minutes after the startup scan finished
# it immediately launched another full one -- back-to-back scans that each take
# ~6 minutes and suppress live LTP while they run.
MIN_SECONDS_BETWEEN_AUTO_SCANS = 3600.0

# ── LTP refresh: background warmer, cache-only serving ───────────────────────
# The /api/ltp handler used to fetch from Yahoo inline. yf.download costs ~30-190s
# per call almost regardless of symbol count, while the cache TTL and the browser
# poll interval are both 10s -- so every poll missed cache, started its own fetch,
# and the fetches piled up overlapping each other (15+ concurrent batch refreshes
# observed in the server log). Requests never completed within the poll interval,
# so the UI showed no live prices at all.
#
# Now a single background thread owns all network fetching for the set of symbols
# the UI has actually asked about, and the handler only ever reads the cache. That
# makes responses immediate, caps outbound traffic at one in-flight batch, and
# keeps prices as fresh as the network genuinely allows.
LTP_HOT_SYMBOLS: set = set()
LTP_HOT_LOCK = threading.Lock()
LTP_LAST_REFRESH_AT = 0.0
# How stale a cached price may be before it is reported as stale to the client.
# Sized above a typical refresh cycle so a normal cycle is not mislabelled, while
# still flagging genuinely dead data rather than passing it off as live.
LTP_FRESH_WINDOW_SEC = 180.0


def note_hot_symbols(symbols) -> None:
    """Record symbols the UI is polling so the warmer keeps them fresh."""
    with LTP_HOT_LOCK:
        LTP_HOT_SYMBOLS.update(symbols)


def background_ltp_warmer():
    """Continuously refresh cached prices for the symbols the UI is polling.

    Runs one batch at a time. Skips entirely while a scan is in flight so the two
    never compete for Yahoo's per-IP budget, subject to the same overrun bound the
    request path uses.
    """
    global LTP_LAST_REFRESH_AT
    while True:
        try:
            time.sleep(5)
            if ltp_should_defer_to_scan():
                continue
            with LTP_HOT_LOCK:
                symbols = sorted(LTP_HOT_SYMBOLS)
            if not symbols:
                continue
            prices = batch_fetch_live_prices(symbols)
            if prices:
                now = time.time()
                with GLOBAL_LTP_CACHE_LOCK:
                    for t, p in prices.items():
                        if p and p > 0:
                            GLOBAL_LTP_CACHE[t] = (float(p), now)
                LTP_LAST_REFRESH_AT = now
        except Exception as e:
            log(f"  ⚠ LTP warmer cycle failed: {e}")
OUT_JSON_FILE = os.path.join(BASE_DIR, "screener_data.json")
if os.path.exists(OUT_JSON_FILE):
    try:
        with open(OUT_JSON_FILE, encoding="utf-8") as f:
            LATEST_SCREENER_RESULTS = json.load(f)
    except Exception:
        LATEST_SCREENER_RESULTS = []

GLOBAL_LTP_CACHE = {}
GLOBAL_LTP_CACHE_LOCK = threading.Lock()

def atomic_write_file(filepath: str, content: str):
    """Atomically write content to file using temporary file swap to prevent blank/truncated files."""
    try:
        dir_name = os.path.dirname(filepath)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        tmp_path = filepath + f".tmp_{os.getpid()}_{random.randint(1000, 9999)}"
        with open(tmp_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(content)
        os.replace(tmp_path, filepath)
    except Exception as e:
        try:
            with open(filepath, "w", encoding="utf-8", errors="replace") as f:
                f.write(content)
        except Exception as ex:
            log(f"⚠ Warning: atomic write failed for {filepath}: {ex}")

def json_serializer(o):
    if hasattr(o, 'item'):
        return o.item()
    if hasattr(o, 'isoformat'):
        return o.isoformat()
    if isinstance(o, (bool, type(True))):
        return bool(o)
    return str(o)


def sanitize_for_strict_json(obj):
    """Recursively replace non-finite floats (inf/-inf/NaN) with None.

    Python's json module happily emits the bare tokens Infinity/-Infinity/NaN for
    those values (valid JavaScript, NOT valid JSON per spec). That was harmless
    while screener_data.json's content was inlined straight into HTML as executable
    JS source, but now that the browser fetches this file and parses it with
    JSON.parse (strict), any such value (e.g. pe_ttm on a loss-making stock) makes
    the whole parse fail with "Unexpected token" and the page shows zero data.
    """
    if isinstance(obj, float):
        return obj if obj == obj and obj not in (float('inf'), float('-inf')) else None
    if isinstance(obj, dict):
        return {k: sanitize_for_strict_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_strict_json(v) for v in obj]
    return obj

# ─── Load config ──────────────────────────────────────────────────────────────
with open(CONFIG_FILE) as f:
    cfg = json.load(f)

EXCEL_PATH      = cfg["excel_path"]
MAX_PRICE       = cfg["max_price_per_share"]   # 5000
MIN_TOTAL       = cfg["min_total_score"]        # 55
MIN_STRENGTH    = cfg["min_strength_score"]     # 50
CACHE_TTL_HRS   = cfg["cache_ttl_hours"]        # 24
PHASE_BUDGET    = cfg["phase_budget_per_stock"] # 5000
PHASE_LABEL     = cfg["phase_label"]
MAX_STOCKS      = cfg["max_stocks"]             # 20

FORCE_REFRESH = "--refresh" in sys.argv or "--force-refresh" in sys.argv

# Official NSE/BSE Equity Market Holidays for 2026
NSE_HOLIDAYS_2026 = {
    "2026-01-26": "Republic Day",
    "2026-02-15": "Mahashivratri",
    "2026-03-03": "Holi",
    "2026-03-21": "Id-Ul-Fitr (Ramadan Eid)",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-08-15": "Independence Day",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-08": "Diwali Laxmi Pujan (Muhurat Trading)",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Guru Nanak Jayanti",
    "2026-12-25": "Christmas"
}

def is_non_trading_day(date_s: str) -> bool:
    """Helper to check if a date string YYYY-MM-DD falls on a weekend or NSE holiday."""
    try:
        dt = datetime.datetime.strptime(date_s, "%Y-%m-%d")
        if dt.weekday() >= 5:
            return True
    except Exception:
        pass
    if date_s in NSE_HOLIDAYS_2026:
        return True
    return False


def is_equity_market_open() -> bool:
    """Return True when NSE equity session is currently live (09:15–15:30 IST on trading days)."""
    ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_offset)
    if is_non_trading_day(now.strftime("%Y-%m-%d")):
        return False
    t = now.time()
    return datetime.time(9, 15) <= t <= datetime.time(15, 30)


def is_price_stale(cached_at_str: str) -> bool:
    """Return True if cached LTP is stale and needs refreshing.
    
    1. During live market (Mon-Fri 09:15-15:30 IST on trading days): Stale if older than 5 minutes.
    2. When market is closed: Stale if cache was saved BEFORE the latest market close time (15:30 IST).
       This guarantees that mid-day intraday caches (e.g. 14:01) are automatically refreshed to
       the final closing price once market closes.
    """
    ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(ist_offset)
    try:
        cached_dt = datetime.datetime.fromisoformat(cached_at_str)
        if cached_dt.tzinfo is None:
            cached_dt = cached_dt.replace(tzinfo=ist_offset)
    except Exception:
        return True

    today_str = now_ist.strftime("%Y-%m-%d")
    is_today_trading = not is_non_trading_day(today_str)

    # 1. Market is live right now
    if is_today_trading and datetime.time(9, 15) <= now_ist.time() <= datetime.time(15, 30):
        return (now_ist - cached_dt).total_seconds() > 300  # 5 minutes

    # 2. Market is closed: calculate exact datetime of the most recent market close
    if is_today_trading and now_ist.time() >= datetime.time(15, 30):
        last_trading_date = now_ist.date()
    else:
        check_date = now_ist.date() - datetime.timedelta(days=1)
        while is_non_trading_day(check_date.strftime("%Y-%m-%d")):
            check_date -= datetime.timedelta(days=1)
        last_trading_date = check_date

    last_market_close = datetime.datetime.combine(last_trading_date, datetime.time(15, 30), tzinfo=ist_offset)
    return cached_dt < last_market_close


if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ─── Helpers ──────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except Exception:
        try:
            cleaned = str(msg).encode("ascii", errors="ignore").decode("ascii")
            print(f"[{ts}] {cleaned}", flush=True)
        except Exception:
            pass


def open_in_browser(target: str) -> bool:
    """Robust browser launcher for Windows shell + default browser fallback.

    Accepts either a URL or a local file path (auto-converted to a file:// URL).
    This used to have a second, duplicate definition further down the file that
    silently shadowed this one at runtime (Python just uses whichever def ran
    last) — that duplicate only called webbrowser.open(), missing the more
    reliable os.startfile()/shell "start" paths below, so every open_in_browser()
    call in the app was quietly using the weaker implementation. Merged into one.
    """
    import platform, subprocess
    if not str(target).startswith(("http://", "https://", "file://")):
        target = f"file:///{os.path.abspath(target).replace(os.sep, '/')}"
    if platform.system() == "Windows":
        try:
            os.startfile(target)
            return True
        except Exception:
            try:
                subprocess.Popen(f'start "" "{target}"', shell=True)
                return True
            except Exception:
                pass
    try:
        webbrowser.open(target)
        return True
    except Exception:
        pass
    return False


def cache_path(ticker):
    return os.path.join(CACHE_DIR, f"{ticker.replace('.', '_')}.json")


def load_cache(ticker):
    """Load cached ticker data. Preserves valid fundamental metrics."""
    if FORCE_REFRESH:
        return None
    path = cache_path(ticker)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        info = data.get("info", {})
        cached_at = datetime.datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
        ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=ist_offset)
        now_ist = datetime.datetime.now(ist_offset)
        age_hrs = (now_ist - cached_at).total_seconds() / 3600
        # If cache is valid (< 24h old) and has fundamentals, use it
        has_fund = any(info.get(k) is not None for k in ["returnOnEquity", "debtToEquity", "trailingPE", "profitMargins"])
        if age_hrs < CACHE_TTL_HRS and has_fund:
            return data
        return None
    except Exception:
        pass
    return None


def save_cache(ticker, data):
    path = cache_path(ticker)
    # Merge with existing cache if new fetch is missing fundamental metrics
    if os.path.exists(path):
        try:
            with open(path) as f:
                old_data = json.load(f)
            old_info = old_data.get("info", {})
            new_info = data.get("info", {})
            for k in ["returnOnEquity", "debtToEquity", "profitMargins", "revenueGrowth",
                      "trailingPE", "pegRatio", "priceToBook", "dividendYield", "sector",
                      "industry", "marketCap", "ebit", "totalAssets", "totalCurrentLiabilities"]:
                if new_info.get(k) is None and old_info.get(k) is not None:
                    new_info[k] = old_info.get(k)
        except Exception:
            pass

    ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    data["cached_at"] = datetime.datetime.now(ist_offset).isoformat()
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ─── Step 1: Read Excel ───────────────────────────────────────────────────────
def read_stock_list() -> list[str]:
    tickers = _read_stock_list_raw()
    try:
        fno_master_dict = get_fno_master_list()
        for sym, fno_item in fno_master_dict.items():
            t = fno_item["ticker"]
            if t not in tickers:
                tickers.append(t)
    except Exception as e:
        log(f"Error integrating dynamic F&O symbols to scan list: {e}")
    return tickers


def _read_stock_list_raw() -> list[str]:
    auto_json = os.path.join(BASE_DIR, "nifty_stocks_auto.json")
    auto_excel = os.path.join(BASE_DIR, "nifty_stocks_auto.xlsx")

    if os.path.exists(auto_json):
        log(f"Reading Nifty stock list from JSON: {auto_json}")
        with open(auto_json) as f:
            syms = json.load(f)
        tickers = [f"{s}.NS" if not s.endswith(".NS") and not s.endswith(".BO") else s for s in syms]
        
        custom_stocks = cfg.get("custom_stocks", [])
        for cs in custom_stocks:
            cs_clean = cs.strip().upper()
            if not cs_clean.endswith(".NS") and not cs_clean.endswith(".BO"):
                cs_clean += ".NS"
            if cs_clean not in tickers:
                tickers.append(cs_clean)
        
        log(f"  Loaded {len(tickers)} tickers (including {len(custom_stocks)} custom user stocks)")
        return tickers

    target_excel = EXCEL_PATH
    if os.path.exists(auto_excel):
        target_excel = auto_excel

    if not os.path.exists(target_excel):
        log(f"⚠ Stock list excel not found at {target_excel}, using built-in Nifty index universe.")
        default_nifty = [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL", "SBIN", "LICI",
            "ITC", "HINDUNILVR", "LT", "BAJFINANCE", "HCLTECH", "MARUTI", "SUNPHARMA", "ONGC",
            "NTPC", "TATAMOTORS", "AXISBANK", "ADANIENT", "KOTAKBANK", "TITAN", "COALINDIA",
            "POWERGRID", "M&M", "BAJAJFINSV", "ULTRACEMCO", "ASIANPAINT", "TATASTEEL", "IOC",
            "SIEMENS", "DLF", "BEL", "ADANIPORTS", "WIPRO", "NESTLEIND", "ZOMATO", "HAL",
            "JSWSTEEL", "VBL", "GRASIM", "TECHM", "DIVISLAB", "CIPLA", "APOLLOHOSP", "DRREDDY",
            "EICHERMOT", "BPCL", "HEROMOTOCO", "INDUSINDBK", "SBILIFE", "HDFCLIFE", "BRITANNIA",
            "TATAPOWER", "VEDL", "ABB", "GAIL", "ASHOKLEY", "BORANA", "EMMVEE", "FEDERALBNK", "NMDC"
        ]
        custom_stocks = cfg.get("custom_stocks", [])
        all_syms = list(set(default_nifty + [cs.replace(".NS", "") for cs in custom_stocks]))
        return [f"{s}.NS" if not s.endswith(".NS") and not s.endswith(".BO") else s for s in all_syms]

    df = pd.read_excel(target_excel)
    log(f"  Columns found: {list(df.columns)}")

    # Auto-detect symbol column
    sym_col = None
    priority = ["symbol", "ticker", "nse symbol", "nse code", "scrip", "scrip code",
                "stock symbol", "trading symbol", "nse_symbol", "code"]
    cols_lower = {c.lower().strip(): c for c in df.columns}

    for p in priority:
        if p in cols_lower:
            sym_col = cols_lower[p]
            break

    if not sym_col:
        # Fall back: first column that has short uppercase strings
        for col in df.columns:
            sample = df[col].dropna().head(10).astype(str)
            if sample.str.match(r'^[A-Z0-9&-]{2,20}$').mean() > 0.6:
                sym_col = col
                break

    if not sym_col:
        sym_col = df.columns[0]

    log(f"  Using column '{sym_col}' as ticker column")
    raw_symbols = df[sym_col].dropna().astype(str).str.strip().str.upper().tolist()
    
    tickers = []
    for s in raw_symbols:
        # Clean up decimal points from excel numbers (e.g. "500112.0" -> "500112")
        if s.endswith(".0"):
            s = s[:-2]
            
        if not s or s.startswith("SYM") or len(s) < 2:
            continue
            
        if s.endswith(".NS") or s.endswith(".BO"):
            tickers.append(s)
        elif s.isdigit():
            tickers.append(f"{s}.BO")
        else:
            tickers.append(f"{s}.NS")

    custom_stocks = cfg.get("custom_stocks", [])
    for cs in custom_stocks:
        cs_clean = cs.strip().upper()
        if not cs_clean.endswith(".NS") and not cs_clean.endswith(".BO"):
            cs_clean += ".NS"
        if cs_clean not in tickers:
            tickers.append(cs_clean)

    log(f"  Loaded {len(tickers)} tickers (including {len(custom_stocks)} custom user stocks)")
    return tickers


# ─── Step 2: Fetch yfinance data (with cache) ─────────────────────────────────
_CORP_ACTIONS_CACHE = None
_CORP_ACTIONS_LOCK = threading.Lock()

def fetch_nse_corporate_actions() -> dict:
    """Fetch central bulk NSE Corporate Actions feed (cached in-memory & file cache). Zero per-stock network overhead."""
    global _CORP_ACTIONS_CACHE
    with _CORP_ACTIONS_LOCK:
        if _CORP_ACTIONS_CACHE is not None:
            return _CORP_ACTIONS_CACHE
        
        ca_file = os.path.join(CACHE_DIR, "nse_corporate_actions_bulk.json")
        if os.path.exists(ca_file):
            try:
                mtime = os.path.getmtime(ca_file)
                if (time.time() - mtime) < 43200:  # 12 hours cache
                    with open(ca_file, "r", encoding="utf-8") as f:
                        _CORP_ACTIONS_CACHE = json.load(f)
                        return _CORP_ACTIONS_CACHE
            except Exception:
                pass
        
        actions_map = {}
        try:
            from curl_cffi import requests as cffi_requests
            url = "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions"
            }
            session = cffi_requests.Session(impersonate="chrome120")
            session.get("https://www.nseindia.com", headers=headers, timeout=5)
            res = session.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                for item in data:
                    sym = item.get("symbol", "").upper().strip()
                    if not sym:
                        continue
                    subject = item.get("subject", item.get("purpose", ""))
                    ex_date = item.get("exDate", item.get("ex_date", ""))
                    rec_date = item.get("recDate", item.get("record_date", ""))
                    
                    sub_lower = subject.lower()
                    act_type = "OTHER"
                    if "bonus" in sub_lower:
                        act_type = "BONUS"
                    elif "dividend" in sub_lower or "div" in sub_lower:
                        act_type = "DIVIDEND"
                    elif "split" in sub_lower:
                        act_type = "SPLIT"
                    elif "rights" in sub_lower:
                        act_type = "RIGHTS"
                    elif "buyback" in sub_lower:
                        act_type = "BUYBACK"
                    
                    act = {
                        "subject": subject,
                        "ex_date": ex_date,
                        "record_date": rec_date,
                        "type": act_type
                    }
                    if sym not in actions_map:
                        actions_map[sym] = []
                    actions_map[sym].append(act)
                
                try:
                    with open(ca_file, "w", encoding="utf-8") as f:
                        json.dump(actions_map, f, indent=2)
                except Exception:
                    pass
        except Exception as e:
            log(f"Warning: Could not fetch central NSE Corporate Actions feed: {e}")
        
        _CORP_ACTIONS_CACHE = actions_map
        return actions_map


def fetch_news_for_ticker(ticker: str, company_name: str = "") -> list[dict]:
    """Fetch live news via Google News RSS for qualified/watchlist stock."""
    news_list = []
    try:
        import urllib.request
        import xml.etree.ElementTree as ET
        import urllib.parse
        
        clean_sym = ticker.replace(".NS", "").replace(".BO", "").strip()
        query_term = f"{clean_sym} stock news NSE"
        if company_name and len(company_name) > 2 and company_name.upper() != clean_sym:
            query_term = f"{company_name} {clean_sym} stock news"
        encoded_query = urllib.parse.quote(query_term)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
        
        req = urllib.request.Request(
            rss_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=3.5) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        for item in root.findall(".//item")[:5]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pubDate = item.findtext("pubDate", "")
            source = item.findtext("source", "")
            
            clean_title = title
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                clean_title = parts[0].strip()
                if not source and len(parts) > 1:
                    source = parts[1].strip()
                    
            if clean_title and link:
                news_list.append({
                    "title": clean_title,
                    "url": link,
                    "pubDate": pubDate,
                    "provider": source or "Google News",
                    "summary": f"Published: {pubDate}" if pubDate else ""
                })
    except Exception:
        pass
    return news_list



_CRUMB_SESSION = None
_CRUMB_VAL = None
_CRUMB_LOCK = threading.Lock()

def get_yahoo_crumb_session():
    global _CRUMB_SESSION, _CRUMB_VAL
    with _CRUMB_LOCK:
        if _CRUMB_SESSION is not None and _CRUMB_VAL is not None:
            return _CRUMB_SESSION, _CRUMB_VAL
        try:
            from curl_cffi import requests as cffi_requests
            s = cffi_requests.Session(impersonate="chrome120")
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            s.get("https://fc.yahoo.com", headers=headers, timeout=5)
            r = s.get("https://query2.finance.yahoo.com/v1/test/getcrumb", headers=headers, timeout=5)
            if r.status_code == 200 and r.text:
                crumb = r.text.strip()
                _CRUMB_SESSION = s
                _CRUMB_VAL = crumb
                return s, crumb
        except Exception:
            pass
        return None, None


CFFI_LOCK = threading.Lock()

def fetch_via_curl_cffi(ticker: str) -> dict | None:
    # 1. Try ultra-fast, thread-safe urllib first
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1y"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data_json = json.loads(resp.read().decode('utf-8'))
        res_list = data_json.get("chart", {}).get("result")
        if res_list:
            res = res_list[0]
            meta = res.get("meta", {})
            price = meta.get("regularMarketPrice") or meta.get("chartPreviousClose") or 0
            if price > 0:
                timestamps = res.get("timestamp", [])
                quote = res.get("indicators", {}).get("quote", [{}])[0]
                opens = quote.get("open", [])
                highs = quote.get("high", [])
                lows = quote.get("low", [])
                closes = quote.get("close", [])
                volumes = quote.get("volume", [])
                hist_records = []
                if timestamps and closes:
                    for idx, (t, c) in enumerate(zip(timestamps, closes)):
                        if c is not None:
                            o_val = opens[idx] if idx < len(opens) and opens[idx] is not None else c
                            h_val = highs[idx] if idx < len(highs) and highs[idx] is not None else c
                            l_val = lows[idx] if idx < len(lows) and lows[idx] is not None else c
                            v_val = volumes[idx] if idx < len(volumes) and volumes[idx] is not None else 1
                            hist_records.append({"date": str(t), "open": float(o_val), "high": float(h_val), "low": float(l_val), "close": float(c), "volume": float(v_val)})
                
                info = {
                    "regularMarketPrice": price,
                    "currentPrice": price,
                    # Yahoo's chart API meta has NO "previousClose" key at all (that
                    # always silently returned None) — "chartPreviousClose" exists but
                    # is the close at the START of the requested `range` (here 1y), not
                    # yesterday's close, so using it would trade one bug for a worse one
                    # (a ~1-year "day change" instead of a 1-day one). The reliable value
                    # Yahoo actually provides is regularMarketChangePercent (their own
                    # authoritative day-over-day %), so previousClose is derived from that.
                    "previousClose": (
                        round(price / (1 + meta["regularMarketChangePercent"] / 100), 2)
                        if meta.get("regularMarketChangePercent") not in (None, -100) else None
                    ),
                    "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
                    "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
                    "shortName": meta.get("shortName") or ticker.replace(".NS", ""),
                    "longName": meta.get("longName") or ticker.replace(".NS", ""),
                    "currency": meta.get("currency", "INR"),
                    "exchange": meta.get("exchangeName", "NSE")
                }
                return {
                    "ticker": ticker,
                    "info": info,
                    "history_close": hist_records,
                    "news": []
                }
    except Exception:
        pass

    # 2. Guard curl_cffi with CFFI_LOCK to prevent C-extension multithread segfaults
    with CFFI_LOCK:
        try:
            from curl_cffi import requests
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1y"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = requests.get(url, impersonate="chrome120", headers=headers, timeout=6)
            if r.status_code == 200:
                data_json = r.json()
                res_list = data_json.get("chart", {}).get("result")
                if not res_list:
                    return None
                res = res_list[0]
                meta = res.get("meta", {})
                price = meta.get("regularMarketPrice") or meta.get("chartPreviousClose") or 0
                if price == 0:
                    return None
                timestamps = res.get("timestamp", [])
                quote = res.get("indicators", {}).get("quote", [{}])[0]
                opens = quote.get("open", [])
                highs = quote.get("high", [])
                lows = quote.get("low", [])
                closes = quote.get("close", [])
                volumes = quote.get("volume", [])
                hist_records = []
                if timestamps and closes:
                    for idx, (t, c) in enumerate(zip(timestamps, closes)):
                        if c is not None:
                            o_val = opens[idx] if idx < len(opens) and opens[idx] is not None else c
                            h_val = highs[idx] if idx < len(highs) and highs[idx] is not None else c
                            l_val = lows[idx] if idx < len(lows) and lows[idx] is not None else c
                            v_val = volumes[idx] if idx < len(volumes) and volumes[idx] is not None else 1
                            hist_records.append({"date": str(t), "open": float(o_val), "high": float(h_val), "low": float(l_val), "close": float(c), "volume": float(v_val)})
                
                info = {
                    "regularMarketPrice": price,
                    "currentPrice": price,
                    # Yahoo's chart API meta has NO "previousClose" key at all (that
                    # always silently returned None) — "chartPreviousClose" exists but
                    # is the close at the START of the requested `range` (here 1y), not
                    # yesterday's close, so using it would trade one bug for a worse one
                    # (a ~1-year "day change" instead of a 1-day one). The reliable value
                    # Yahoo actually provides is regularMarketChangePercent (their own
                    # authoritative day-over-day %), so previousClose is derived from that.
                    "previousClose": (
                        round(price / (1 + meta["regularMarketChangePercent"] / 100), 2)
                        if meta.get("regularMarketChangePercent") not in (None, -100) else None
                    ),
                    "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
                    "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
                    "shortName": meta.get("shortName") or ticker.replace(".NS", ""),
                    "longName": meta.get("longName") or ticker.replace(".NS", ""),
                    "currency": meta.get("currency", "INR"),
                    "exchange": meta.get("exchangeName", "NSE")
                }

                # Fetch genuine fundamental ratios via Yahoo Finance quoteSummary.
                # get_yahoo_crumb_session() caches and returns ONE shared curl_cffi
                # Session object (its cookies are tied to the crumb, so a fresh
                # session per call won't authenticate) — that object is a libcurl
                # C-extension handle and is NOT safe to call .get() on concurrently
                # from multiple threads, unlike a bare module-level curl_cffi.requests
                # .get() call (which creates its own throwaway session internally and
                # is fine). This ran unlocked across the scan's 16 worker threads,
                # which is almost certainly what was crashing the whole process
                # intermittently with no Python traceback (a native segfault, not a
                # catchable exception) — serialize every use of the shared session
                # under the same lock that guards its creation.
                sess, crumb = get_yahoo_crumb_session()
                if sess and crumb:
                    try:
                        summary_url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
                                       f"?modules=financialData,defaultKeyStatistics,summaryDetail,assetProfile&crumb={crumb}")
                        with _CRUMB_LOCK:
                            r_sum = sess.get(summary_url, headers=headers, timeout=6)
                        if r_sum.status_code == 200:
                            res_sum = (r_sum.json().get("quoteSummary", {}).get("result") or [{}])[0]
                            fd = res_sum.get("financialData", {})
                            ks = res_sum.get("defaultKeyStatistics", {})
                            sd = res_sum.get("summaryDetail", {})
                            ap = res_sum.get("assetProfile", {})

                            def extract_val(d, key):
                                item = d.get(key)
                                if isinstance(item, dict):
                                    return item.get("raw")
                                return item

                            info["returnOnEquity"] = extract_val(fd, "returnOnEquity") or extract_val(ks, "returnOnEquity")
                            info["ebit"] = extract_val(fd, "ebitda") or extract_val(fd, "operatingCashflow") or extract_val(ks, "ebitda")
                            info["totalAssets"] = extract_val(fd, "totalAssets") or extract_val(ks, "totalAssets") or extract_val(sd, "totalAssets")
                            info["totalCurrentLiabilities"] = extract_val(fd, "totalCurrentLiabilities") or extract_val(ks, "totalCurrentLiabilities")
                            info["debtToEquity"] = extract_val(fd, "debtToEquity") or extract_val(ks, "debtToEquity")
                            info["profitMargins"] = extract_val(fd, "profitMargins") or extract_val(ks, "profitMargins")
                            info["revenueGrowth"] = extract_val(fd, "revenueGrowth") or extract_val(ks, "revenueGrowth")
                            info["trailingPE"] = extract_val(sd, "trailingPE") or extract_val(ks, "trailingPE") or extract_val(fd, "trailingPE")
                            info["pegRatio"] = extract_val(ks, "pegRatio") or extract_val(fd, "pegRatio")
                            info["priceToBook"] = extract_val(ks, "priceToBook") or extract_val(sd, "priceToBook") or extract_val(fd, "priceToBook")
                            info["dividendYield"] = extract_val(sd, "dividendYield") or extract_val(ks, "dividendYield")
                            info["sector"] = ap.get("sector") or info.get("sector") or ""
                            info["industry"] = ap.get("industry") or info.get("industry") or ""
                            info["marketCap"] = extract_val(sd, "marketCap") or extract_val(ks, "marketCap") or info.get("marketCap", 0)
                    except Exception:
                        pass

                # Fallback: if essential fundamentals are missing, use yfinance Ticker info
                has_fund = any(info.get(k) is not None for k in ["returnOnEquity", "debtToEquity", "trailingPE", "profitMargins"])
                if not has_fund:
                    try:
                        t_fallback = yf.Ticker(ticker)
                        yf_inf = t_fallback.info
                        if yf_inf and isinstance(yf_inf, dict):
                            for k in ["returnOnEquity", "debtToEquity", "profitMargins", "revenueGrowth",
                                      "trailingPE", "pegRatio", "priceToBook", "dividendYield", "sector",
                                      "industry", "marketCap", "ebit", "totalAssets", "totalCurrentLiabilities"]:
                                if info.get(k) is None and yf_inf.get(k) is not None:
                                    info[k] = yf_inf.get(k)
                    except Exception:
                        pass

                # Fallback 2: If fundamentals are still missing, merge with last known valid cached fundamentals on disk
                has_fund = any(info.get(k) is not None for k in ["returnOnEquity", "debtToEquity", "trailingPE", "profitMargins"])
                if not has_fund:
                    path = cache_path(ticker)
                    if os.path.exists(path):
                        try:
                            with open(path) as f:
                                old_cache = json.load(f).get("info", {})
                            for k in ["returnOnEquity", "debtToEquity", "profitMargins", "revenueGrowth",
                                      "trailingPE", "pegRatio", "priceToBook", "dividendYield", "sector",
                                      "industry", "marketCap", "ebit", "totalAssets", "totalCurrentLiabilities"]:
                                if info.get(k) is None and old_cache.get(k) is not None:
                                    info[k] = old_cache.get(k)
                        except Exception:
                            pass

                data = {
                    "ticker": ticker,
                    "info": info,
                    "history_close": hist_records,
                    "news": []
                }
                save_cache(ticker, data)
                return data
        except Exception:
            pass
    return None


def fetch_live_price_only(ticker: str) -> float | None:
    """Fetch *only* the current market price for a ticker using the Yahoo
    Finance chart API (1-minute interval, intraday).
    TTL: 10s during market hours (live prices change), 120s when closed.
    Returns None on failure.

    Fetcher order:
      1. urllib query1 / query2 (parallel-safe, fast when Yahoo cooperates)
      2. curl_cffi Chrome impersonation (bypasses Yahoo SSL fingerprint block)
         — called WITHOUT CFFI_LOCK because curl_cffi.requests.get() creates
           its own libcurl Session per call and is documented thread-safe.
    """
    now = time.time()
    ttl = 10.0 if is_equity_market_open() else 120.0
    with GLOBAL_LTP_CACHE_LOCK:
        cached_entry = GLOBAL_LTP_CACHE.get(ticker)
        if cached_entry and (now - cached_entry[1] < ttl):
            return cached_entry[0]

    _ltp_errors = []
    for host in ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]:
        try:
            import urllib.request
            import json
            url = f"https://{host}/v8/finance/chart/{ticker}?interval=1m&range=1d"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    meta = (data.get("chart", {}).get("result") or [{}])[0].get("meta", {})
                    price = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
                    if price and float(price) > 0:
                        val = float(price)
                        with GLOBAL_LTP_CACHE_LOCK:
                            GLOBAL_LTP_CACHE[ticker] = (val, time.time())
                        return val
        except Exception as e:
            _ltp_errors.append(f"{host}: {e}")

    # curl_cffi fallback: uses Chrome TLS fingerprint so Yahoo can't block it.
    # No CFFI_LOCK needed here — curl_cffi.requests.get() is a module-level
    # helper that internally does Session().request(), giving each call its own
    # libcurl handle with no shared mutable state between threads.
    try:
        from curl_cffi import requests as cffi_req
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = cffi_req.get(url, impersonate="chrome120", headers=headers, timeout=2.5)
        if r.status_code == 200:
            meta = (r.json().get("chart", {}).get("result") or [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
            if price and float(price) > 0:
                val = float(price)
                with GLOBAL_LTP_CACHE_LOCK:
                    GLOBAL_LTP_CACHE[ticker] = (val, time.time())
                return val
    except Exception as e:
        _ltp_errors.append(f"curl_cffi: {e}")

    # All fetchers failed — log a single consolidated line instead of per-host spam
    if _ltp_errors:
        print(f"[LTP] {ticker} — all fetchers failed: {'; '.join(_ltp_errors)}")
    return None


def batch_fetch_live_prices(tickers: list[str], chunk_size: int = 150) -> dict[str, float]:
    """
    Refreshes live prices for many tickers using yfinance's own download() pipeline,
    which batches many symbols into far fewer underlying HTTP requests than fetching
    each ticker individually. This is what a full-universe scan's price-refresh step
    should use instead of calling fetch_live_price_only() once per ticker — 2500+
    separate per-ticker HTTPS round-trips is what actually produced the ~20+ minute
    scan times, since each one is individually exposed to Yahoo's per-IP rate
    limiting/timeouts, where a couple dozen batched requests are not.

    Yahoo's own batch quote endpoint (/v7/finance/quote) was tried first and
    rejected — it returns 401 Unauthorized even with browser impersonation
    (curl_cffi + chrome UA) because it requires a proper crumb/cookie session,
    which yfinance's download() already manages internally.

    Only touches price — fundamentals/history for tickers that already have a
    cached entry are left untouched; this only fills in a fresher `regularMarketPrice`
    for fetch_ticker_data's stale-price-refresh branch.
    """
    if not tickers:
        return {}

    price_map: dict[str, float] = {}
    chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]
    log(f"  Batch price refresh: {len(tickers)} tickers in {len(chunks)} chunk(s) of up to {chunk_size}...")

    for chunk in chunks:
        try:
            data = yf.download(tickers=chunk, period="1d", group_by="ticker",
                                threads=True, progress=False, timeout=15)
            if data is None or data.empty:
                continue
            is_multi = hasattr(data.columns, "get_level_values")
            for t in chunk:
                try:
                    if is_multi:
                        if t not in data.columns.get_level_values(0):
                            continue
                        closes = data[t]["Close"].dropna()
                    else:
                        # Flat frame — only happens with a single-ticker chunk.
                        closes = data["Close"].dropna()
                    if len(closes) > 0:
                        price_map[t] = float(closes.iloc[-1])
                except Exception:
                    continue
        except Exception as e:
            log(f"  ⚠ Batch price chunk failed ({len(chunk)} tickers): {e}")

    log(f"  Batch price refresh got {len(price_map)}/{len(tickers)} live prices.")
    return price_map


def fetch_ticker_data(ticker: str, live_price_override: float | None = None) -> dict | None:
    cached = load_cache(ticker)
    if cached:
        cached_at_str = cached.get("cached_at", "2000-01-01")
        if is_price_stale(cached_at_str):
            live_price = live_price_override if live_price_override and live_price_override > 0 else fetch_live_price_only(ticker)
            if live_price and live_price > 0:
                cached["info"]["currentPrice"] = live_price
                cached["info"]["regularMarketPrice"] = live_price
                if cached.get("history_close") and len(cached["history_close"]) > 0:
                    cached["history_close"][-1]["close"] = live_price
                cached["last_live_price_update"] = datetime.datetime.now().isoformat()
                save_cache(ticker, cached)
        return cached

    # Primary fetcher: direct browser-impersonated curl_cffi (bypass Yahoo 401 Crumb error & rate limits)
    cffi_res = fetch_via_curl_cffi(ticker)
    if cffi_res is not None:
        return cffi_res

    try:
        t = yf.Ticker(ticker)
        info = t.info

        price = (info.get("currentPrice") or info.get("regularMarketPrice")
                 or info.get("previousClose") or 0)
        if price > 0:
            hist = t.history(period="1y")
            hist_records = []
            if not hist.empty:
                cols_to_keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in hist.columns]
                reset_hist = hist[cols_to_keep].reset_index()
                rename_map = {"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
                hist_records = reset_hist.rename(columns=rename_map).assign(date=lambda x: x["date"].astype(str)).to_dict("records")

            news_list = fetch_news_for_ticker(ticker)

            data = {
                "ticker": ticker,
                "info": {k: v for k, v in info.items()
                         if isinstance(v, (int, float, str, bool, type(None)))},
                "history_close": hist_records,
                "news": news_list,
            }
            save_cache(ticker, data)
            return data

    except Exception:
        pass

    # Fallback to existing disk cache if full fetch fails
    path = cache_path(ticker)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass

    return None


def history_from_records(records: list) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame(records)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col.capitalize()] = pd.to_numeric(df[col], errors="coerce")
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    return df[cols].dropna(subset=["Close"])


# ─── Large & Mid Cap Universe Definitions ─────────────────────────────────────
def load_cap_symbol_sets() -> tuple[set[str], set[str]]:
    large_set = {
        'RELIANCE', 'TCS', 'HDFCBANK', 'BHARTIARTL', 'ICICIBANK', 'INFY', 'ITC', 'SBIN', 'LTIM', 'LODHA',
        'LT', 'HINDUNILVR', 'AXISBANK', 'KOTAKBANK', 'M&M', 'HCLTECH', 'SUNPHARMA', 'NTPC', 'ONGC',
        'TATAMOTORS', 'MARUTI', 'PFC', 'RECLTD', 'POWERGRID', 'COALINDIA', 'TATASTEEL', 'ADANIENT',
        'ADANIPORTS', 'BAJFINANCE', 'BAJAJFINSV', 'ASIANPAINT', 'TITAN', 'ULTRACEMCO', 'ADANIPOWER',
        'SIEMENS', 'HAL', 'BEL', 'DLF', 'IOC', 'VBL', 'TRENT', 'ZOMATO', 'MAZDOCK',
        'CHOLAFIN', 'GRASIM', 'INDUSINDBK', 'HDFCLIFE', 'VEDL', 'JSWSTEEL', 'PIDILITIND', 'HAVELLS',
        'GAIL', 'SBILIFE', 'BPCL', 'ABB', 'AMBUJACEM', 'BANKBARODA', 'PNB', 'DABUR', 'EICHERMOT',
        'SHRIRAMFIN', 'DIVISLAB', 'GODREJCP', 'CIPLA', 'TATAPOWER', 'MUTHOOTFIN', 'ICICIPRULI',
        'BAJAJ-AUTO', 'BRITANNIA', 'VARUNBEV', 'INDIGO', 'BOSCHLTD', 'HEROMOTOCO', 'MAXHEALTH',
        'MANKIND', 'COLPAL', 'TORNTPHARM', 'JIOFIN', 'TATAELXSI', 'PERSISTENT', 'OFSS', 'POLYCAB',
        'SRF', 'MOTHERSON', 'NMDC', 'CGPOWER', 'CUMMINSIND', 'APOLLOHOSP', 'TATACOMM', 'AWL', 'CELLO', 'FSL',
        'SWIGGY', 'HYUNDAI', 'NHPC', 'SJVN', 'JINDALSTEL', 'LUPIN', 'AUROPHARMA', 'SUNDARMFIN'
    }
    mid_set = {
        'FEDERALBNK', 'IDFCFIRSTB', 'GLENMARK', 'ALKEM', 'ASHOKLEY', 'BATAINDIA', 'BHEL', 'COFORGE',
        'CONCOR', 'ESCORTS', 'EXIDEIND', 'GODREJPROP', 'HINDPETRO', 'IDEA', 'IDFC', 'IEX', 'INDIANB',
        'INDUSTOWER', 'IPCALAB', 'JUBLFOOD', 'KALYANKJIL', 'LICHSGFIN', 'MFSL', 'NATIONALUM',
        'OBEROIRLTY', 'OIL', 'PAYTM', 'PETRONET', 'PRESTAGE', 'RADICO', 'SAIL', 'SUZLON', 'TATATRANSM',
        'TATATECH', 'TIINDIA', 'TORNTPOWER', 'UPL', 'VOLTAS', 'YESBANK', 'ZYDUSLIFE', 'ASTRAL', 'ATUL',
        'DEEPAKNTR', 'DIXON', 'KPRMILL', 'METROPOLIS', 'SYNGENE', 'ZENSARTECH', 'KPITTECH', 'HAPPIESTM',
        'CYIENT', 'SONACOMS', 'KEI', 'SUPREMEIND', 'APLAPOLLO', 'CENTURYPLY', 'CROMPTON', 'FINCABLES',
        'RAJESHEXPO', 'RVNL', 'IRFC', 'IRCTC', 'HUDCO', 'NBCC', 'MAHABANK', 'CENTRALBK', 'UCOBANK',
        'IOBA', 'FACT', 'NFL', 'RCF', 'GSFC', 'GESHIP', 'PVRINOX', 'RRKABEL', 'LALPATHLAB', 'GODFRYPHLP',
        'MAPMYINDIA', 'ABSLAMC', 'HEG', 'BLUEDART', 'MINDACORP', 'ICICIGI', 'AUBANK', 'MPHASIS', 'SCI',
        'ZYDUSWELL', 'DEVYANI', 'KIMS', 'POLYMED', 'SAMMAANCAP', 'NUVAMA', 'BOSCHLTD', 'COROMANDEL'
    }
    
    large_file = os.path.join(BASE_DIR, "nifty_largecap.json")
    mid_file = os.path.join(BASE_DIR, "nifty_midcap.json")
    if os.path.exists(large_file):
        try:
            with open(large_file) as f:
                large_set.update([s.strip().upper() for s in json.load(f)])
        except Exception:
            pass
    if os.path.exists(mid_file):
        try:
            with open(mid_file) as f:
                mid_set.update([s.strip().upper() for s in json.load(f)])
        except Exception:
            pass

    return large_set, mid_set

LARGE_CAP_SYMBOLS, MID_CAP_SYMBOLS = load_cap_symbol_sets()

# ─── Load MTF (Margin Trading Facility) Quality Stocks ────────────────────────
def load_mtf_symbols() -> set:
    """Load Zerodha-approved quality equity symbols eligible for MTF / swing radar."""
    mtf_file = os.path.join(BASE_DIR, "mtf_stocks.json")
    mtf_set = set()
    if os.path.exists(mtf_file):
        try:
            with open(mtf_file) as f:
                mtf_set = {s.strip().upper() for s in json.load(f)}
        except Exception:
            pass
    return mtf_set

MTF_SYMBOLS = load_mtf_symbols()
log(f"Loaded {len(MTF_SYMBOLS)} MTF quality equity symbols from mtf_stocks.json")

def is_eligible_for_stock_of_the_day(r: dict) -> bool:
    if not r or not isinstance(r, dict):
        return False
    sym = str(r.get("symbol") or "").strip().upper()
    ltp = float(r.get("ltp") or r.get("current_ltp") or r.get("ltp_at_pick") or 0.0)
    
    # 1. HARD PRICE FLOOR: LTP MUST BE >= Rs 100.0 (Strictly No Penny Stocks)
    if ltp < 100.0:
        return False
        
    # 2. HARD CAPITALIZATION REQUIREMENT: MUST BE LARGE CAP OR MID CAP ONLY (Market Cap >= Rs 15,000 Cr or Nifty 100 / Midcap 150)
    mcap = float(r.get("market_cap") or 0)
    is_large_or_mid = (
        sym in LARGE_CAP_SYMBOLS or
        sym in MID_CAP_SYMBOLS or
        (mcap >= 150_000_000_000 and r.get("cap_category") in ["Large Cap", "Mid Cap"])
    )
    return is_large_or_mid


# ─── Step 3: Main scan loop ───────────────────────────────────────────────────
def run_scan(tickers: list[str]) -> list[dict]:
    total = len(tickers)
    results = []
    skipped_price = 0
    skipped_nodata = 0

    # Load watchlist symbols to identify watchlist stocks during scanning
    watchlist_symbols = set()
    if os.path.exists(WL_FILE):
        try:
            with open(WL_FILE) as f:
                wl = json.load(f)
                watchlist_symbols = {w.get("symbol") for w in wl if isinstance(w, dict) and w.get("symbol")}
        except Exception:
            pass
    if not watchlist_symbols and os.path.exists(WL_SEED):
        try:
            with open(WL_SEED) as f:
                wl = json.load(f)
                watchlist_symbols = {w.get("symbol") for w in wl if isinstance(w, dict) and w.get("symbol")}
        except Exception:
            pass

    # Fetch central NSE Corporate Actions feed ONCE per scan (0.00ms per stock)
    corp_actions_map = fetch_nse_corporate_actions()

    # Symbols exempt from the ₹5000 price cap (F&O stocks traded as options)
    try:
        fno_master_dict = get_fno_master_list()
        fno_symbols = set(fno_master_dict.keys())
    except Exception as e:
        log(f"Error initializing dynamic fno_symbols: {e}")
        fno_symbols = {s.get("symbol") for s in cfg.get("fno_stocks", []) if isinstance(s, dict) and s.get("symbol")}

    # Pre-fetch fresh prices for every ticker whose cache is otherwise valid
    # (fundamentals intact) but whose price has gone stale, in a handful of batched
    # requests rather than one network round-trip per ticker inside the scan loop
    # below — see batch_fetch_live_prices() for why this is the actual fix for scan
    # duration, not raising the worker count.
    stale_price_tickers = []
    for t in tickers:
        c = load_cache(t)
        if c and is_price_stale(c.get("cached_at", "2000-01-01")):
            stale_price_tickers.append(t)
    batch_prices = batch_fetch_live_prices(stale_price_tickers) if stale_price_tickers else {}

    def process_single_ticker(args):
        try:
            i, ticker = args
            clean = ticker.replace(".NS", "").replace(".BO", "")
            data = fetch_ticker_data(ticker, live_price_override=batch_prices.get(ticker))
            if data is None:
                return None, "nodata"
            info = data.get("info", {})
            history = history_from_records(data.get("history_close", []))
            price = (info.get("currentPrice") or info.get("regularMarketPrice")
                     or info.get("previousClose") or 0)
            # Bypass price cap for designated F&O stocks
            if price >= MAX_PRICE and clean not in fno_symbols:
                return None, "price"
            scored = score_stock(info, history)
            scored["symbol"] = clean
            scored["ticker"] = ticker
            if scored.get("total_score", 0) >= 45 or clean in watchlist_symbols or clean in fno_symbols:
                scored = apply_1h_sr_overlay(scored, ticker)
            else:
                scored["sr_1h_available"] = False
            qualified = (
                scored["total_score"] >= MIN_TOTAL and
                scored["strength"] >= MIN_STRENGTH
            )
            scored["qualified"] = qualified
            trend_info = compute_trend_classification(scored)
            scored["trend"] = trend_info["trend"]
            scored["tech_rating"] = trend_info["badge"]
            scored["tech_class"] = trend_info["class"]
            is_wl = clean in watchlist_symbols
            
            # Attach Corporate Actions (in-memory lookup)
            scored["corporate_actions"] = corp_actions_map.get(clean, [])
            
            # Fetch news for qualified or watchlist stocks
            if ("news" not in data or not data["news"]) and (qualified or is_wl):
                comp_name = info.get("shortName") or info.get("longName") or clean
                news_list = fetch_news_for_ticker(ticker, company_name=comp_name)
                data["news"] = news_list
                save_cache(ticker, data)
            scored["news"] = data.get("news") or []
            return scored, "ok"
        except Exception:
            return None, "nodata"

    log(f"\nMultithreaded scanning {total} stocks (16 parallel workers, ultra-fast cache processing)...")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=16) as executor:
        scan_items = list(enumerate(tickers, 1))
        futures = [executor.submit(process_single_ticker, item) for item in scan_items]
        for f in futures:
            try:
                res, status = f.result()
                if status == "nodata":
                    skipped_nodata += 1
                elif status == "price":
                    skipped_price += 1
                elif res:
                    results.append(res)
            except Exception:
                skipped_nodata += 1

    for r in results:
        sym = r.get("symbol", "").upper()
        mcap = r.get("market_cap") or 0
        
        is_large = (sym in LARGE_CAP_SYMBOLS) or (mcap >= 500_000_000_000)
        is_mid = (sym in MID_CAP_SYMBOLS) or (150_000_000_000 <= mcap < 500_000_000_000)
        
        if is_large:
            r["cap_category"] = "Large Cap"
            r["is_large_cap"] = True
            r["is_mid_cap"] = False
            r["is_mid_or_large_cap"] = True
            if mcap == 0: r["market_cap"] = 500_000_000_000
        elif is_mid:
            r["cap_category"] = "Mid Cap"
            r["is_large_cap"] = False
            r["is_mid_cap"] = True
            r["is_mid_or_large_cap"] = True
            if mcap == 0: r["market_cap"] = 250_000_000_000
        else:
            r["cap_category"] = "Small Cap"
            r["is_large_cap"] = False
            r["is_mid_cap"] = False
            r["is_mid_or_large_cap"] = False

        # Tag MTF eligibility (Zerodha quality approved equity)
        r["is_mtf"] = (sym in MTF_SYMBOLS)

    # Multi-level deterministic tie-breaker sort
    results.sort(key=lambda x: (x.get("total_score", 0), x.get("swing_score", 0), x.get("symbol", "")), reverse=True)
    log(f"\nScan complete: {len(results)} priced < ₹{MAX_PRICE}, "
        f"{sum(1 for r in results if r['qualified'])} qualified, "
        f"{skipped_price} excluded by price, {skipped_nodata} no-data\n")
    return results


def get_fno_master_list() -> dict:
    """
    Downloads/caches the Zerodha instruments list and extracts F&O stocks with lot sizes and strike intervals.
    Returns: dict: { symbol: { "lot_size": int, "strike_interval": int } }
    """
    import io
    cache_path = os.path.join(BASE_DIR, "cache", "kite_instruments.csv")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    
    use_cache = False
    if os.path.exists(cache_path):
        try:
            mtime = os.path.getmtime(cache_path)
            age_hours = (time.time() - mtime) / 3600
            if age_hours < 24:
                use_cache = True
        except Exception:
            pass
            
    df = None
    if use_cache:
        log("Loading F&O instruments list from local cache...")
        try:
            df = pd.read_csv(cache_path)
        except Exception as e:
            log(f"Error reading instruments cache: {e}. Re-downloading...")
            use_cache = False
            
    if df is None:
        log("Downloading fresh F&O instruments list from Zerodha Kite API...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        url = "https://api.kite.trade/instruments"
        try:
            import requests as std_requests
            r = std_requests.get(url, headers=headers, timeout=20)
            if r.status_code == 200:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(r.text)
                df = pd.read_csv(io.StringIO(r.text))
            else:
                log(f"Failed to download instruments from Kite API. Status: {r.status_code}")
                return {}
        except Exception as e:
            log(f"Error fetching instruments from Kite API: {e}")
            return {}
            
    try:
        nfo = df[df["exchange"] == "NFO"]
        indices = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX", "NIFTYNXT50"}
        futs = nfo[nfo["instrument_type"] == "FUT"]
        
        fno_master = {}
        for name, group in futs.groupby("name"):
            if name in indices:
                continue
            lot_size = int(group["lot_size"].iloc[0])
            opts = nfo[(nfo["name"] == name) & (nfo["instrument_type"].isin(["CE", "PE"]))]
            if len(opts) > 1:
                unique_strikes = sorted(opts["strike"].unique())
                if len(unique_strikes) > 1:
                    diffs = pd.Series(unique_strikes).diff().dropna()
                    valid_diffs = diffs[diffs > 0]
                    if not valid_diffs.empty and not valid_diffs.mode().empty:
                        strike_interval = float(valid_diffs.mode().iloc[0])
                    else:
                        strike_interval = 50.0
                else:
                    strike_interval = 50.0
            else:
                strike_interval = 50.0

            if strike_interval <= 0:
                strike_interval = 50.0
                
            fno_master[name] = {
                "symbol": name,
                "ticker": f"{name}.NS",
                "lot_size": lot_size if lot_size > 0 else 50,
                "strike_interval": int(strike_interval)
            }
        log(f"Successfully processed {len(fno_master)} F&O instruments.")
        return fno_master
    except Exception as e:
        log(f"Error processing instruments data: {e}")
        return {}


def process_fno_stocks(screener_results: list[dict]) -> list[dict]:
    """Fetch/score the dynamic F&O stocks, compute options signals,
    and return the top 15 stocks ranked by conviction and total score."""
    try:
        fno_master_dict = get_fno_master_list()
    except Exception as e:
        log(f"Error fetching dynamic F&O master list: {e}")
        fno_master_dict = {}

    # Fallback to config-based list if master list is empty
    if not fno_master_dict:
        log("F&O dynamic master list is empty, falling back to config.")
        fno_cfgs = cfg.get("fno_stocks", [])
        fno_master_dict = {
            fc["symbol"]: {
                "symbol": fc["symbol"],
                "ticker": fc["ticker"],
                "lot_size": fc.get("lot_size", 50),
                "strike_interval": fc.get("strike_interval", 50),
                "name": fc["symbol"]
            } for fc in fno_cfgs
        }

    result_map = {r["symbol"]: r for r in screener_results if isinstance(r, dict) and r.get("symbol")}
    fno_data = []

    missing_fno = [item for sym, item in fno_master_dict.items() if sym not in result_map]
    if missing_fno:
        log(f"  Parallelizing fetch for {len(missing_fno)} missing F&O instruments...")
        def _fetch_fno_worker(fno_item):
            sym = fno_item["symbol"]
            ticker = fno_item["ticker"]
            try:
                data = fetch_ticker_data(ticker)
                if data:
                    info = data.get("info", {})
                    history = history_from_records(data.get("history_close", []))
                    scored = score_stock(info, history)
                    scored["symbol"] = sym
                    scored["ticker"] = ticker
                    scored = apply_1h_sr_overlay(scored, ticker)
                    trend_info = compute_trend_classification(scored)
                    scored["trend"] = trend_info["trend"]
                    scored["tech_rating"] = trend_info["badge"]
                    scored["tech_class"] = trend_info["class"]
                    return sym, scored
            except Exception:
                pass
            return sym, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            for sym, scored in executor.map(_fetch_fno_worker, missing_fno):
                if scored:
                    result_map[sym] = scored

    excluded_count = 0
    for sym, fno_item in fno_master_dict.items():
        scored = result_map.get(sym)

        if scored:
            signal = compute_fno_signal(scored, fno_item)
            if signal and signal.get("signal") != "NO_DATA" and signal.get("ltp", 0) > 0:
                ltp_val = signal.get("ltp", 0)
                lot_val = signal.get("lot_size", 0)
                # Options Criteria Filter:
                # Stock must meet LTP >= 1000 OR lot_size < 500 (with exception for RELIANCE)
                if sym == "RELIANCE" or ltp_val >= 1000 or lot_val < 500:
                    fno_data.append(signal)
                else:
                    excluded_count += 1

    if excluded_count > 0:
        log(f"  Filtered out {excluded_count} F&O instruments failing options criteria (LTP >= 1000 or Lot Size < 500).")

    # Rank and select the top 15 stocks dynamically
    # Sort key: conviction (descending), then total_score (descending)
    fno_data.sort(
        key=lambda x: (
            x.get("conviction", 0),
            x.get("total_score", 0) if x.get("total_score") is not None else 0
        ),
        reverse=True
    )
    
    top_15 = fno_data[:15]

    # Mandatory Exception: RELIANCE must ALWAYS be included in top 15 picks
    rel_item = next((x for x in fno_data if x.get("symbol") == "RELIANCE"), None)
    if rel_item and rel_item not in top_15:
        log("  ★ Always-Include Exception: Adding RELIANCE to top 15 F&O picks.")
        top_15 = top_15[:14] + [rel_item]

    log(f"Selected {len(top_15)} F&O stocks after ranking.")
    return top_15


# ─── Step 4: Score watchlist stocks & fill entry metrics ─────────────────────
def process_watchlist(screener_results: list[dict]) -> list[dict]:
    # Always load master watchlist from seed
    if os.path.exists(WL_SEED):
        with open(WL_SEED) as f:
            watchlist = json.load(f)
    elif os.path.exists(WL_FILE):
        with open(WL_FILE) as f:
            watchlist = json.load(f)
    else:
        watchlist = []

    result_map = {r["symbol"]: r for r in screener_results if isinstance(r, dict) and r.get("symbol")}

    missing_wl = [item for item in watchlist if isinstance(item, dict) and item.get("symbol") and item.get("symbol") not in result_map]
    if missing_wl:
        log(f"  Parallelizing fetch for {len(missing_wl)} missing watchlist stocks...")
        def _fetch_wl_worker(item):
            sym = item.get("symbol")
            ticker = item.get("ticker", f"{sym}.NS")
            try:
                data = fetch_ticker_data(ticker)
                if data:
                    info = data.get("info", {})
                    history = history_from_records(data.get("history_close", []))
                    scored = score_stock(info, history)
                    scored["symbol"] = sym
                    scored["ticker"] = ticker
                    scored = apply_1h_sr_overlay(scored, ticker)
                    if "news" not in data or not data["news"]:
                        comp_name = info.get("shortName") or info.get("longName") or sym
                        news_list = fetch_news_for_ticker(ticker, company_name=comp_name)
                        data["news"] = news_list
                        save_cache(ticker, data)
                    scored["news"] = data.get("news") or []
                    ca_map = fetch_nse_corporate_actions()
                    scored["corporate_actions"] = ca_map.get(sym, [])
                    return sym, scored
            except Exception:
                pass
            return sym, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            for sym, scored in executor.map(_fetch_wl_worker, missing_wl):
                if scored:
                    result_map[sym] = scored

    for item in watchlist:
        if not isinstance(item, dict):
            continue
        sym = item.get("symbol")
        if not sym:
            continue
        scored = result_map.get(sym)

        if scored:
            # Fill entry metrics on first run (when null)
            if item.get("score_at_entry") is None:
                item["score_at_entry"]    = scored["total_score"]
                item["strength_at_entry"] = scored["strength"]
                item["value_at_entry"]    = scored["value"]
                item["momentum_at_entry"] = scored["momentum"]
                item["roe_at_entry"]      = scored.get("roe_pct")
                item["de_at_entry"]       = scored.get("de_ratio")
                item["npm_at_entry"]      = scored.get("npm_pct")

            item["current_score"]    = scored["total_score"]
            item["current_strength"] = scored["strength"]
            item["current_value"]    = scored["value"]
            item["current_momentum"] = scored["momentum"]
            item["ltp"]              = scored["ltp"]
            item["sector"]           = scored.get("sector", "")
            item["name"]             = scored.get("name") or item.get("name", sym)
            item["pe"]               = scored.get("pe")
            item["roe_pct"]          = scored.get("roe_pct")
            item["de_ratio"]         = scored.get("de_ratio")
            item["npm_pct"]          = scored.get("npm_pct")
            item["rsi"]              = scored.get("rsi")
            item["ma200"]            = scored.get("ma200")
            item["wk52_return_pct"]  = scored.get("wk52_return_pct")
            item["volume_spike"]     = scored.get("volume_spike", 0.0)
            item["today_volume"]     = scored.get("today_volume", 0)
            item["avg_volume_10d"]   = scored.get("avg_volume_10d", 0)
            item["news"]             = scored.get("news", [])
            item["corporate_actions"]= scored.get("corporate_actions", [])

            # Generate quality alerts & recommendation signal
            item["alerts"] = check_quality_alerts(scored, item)
            sig = compute_signal(scored, item)
            item["signal"] = sig["signal"]
            item["signal_badge"] = sig["badge"]
            item["signal_reason"] = sig["reason"]

            # Unrealised P&L
            if item.get("avg_cost") and item["ltp"] > 0:
                qty = item.get("qty", 0)
                avg = item["avg_cost"]
                ltp = item["ltp"]
                item["unrealised_pnl"]  = round((ltp - avg) * qty, 2)
                item["unrealised_pct"]  = round(((ltp - avg) / avg) * 100, 2)
                item["current_value"]   = round(ltp * qty, 2)

    # Save updated watchlist
    with open(WL_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)

    return watchlist


# ─── Step 4b: Market Timezone Awareness & Daily Top Pick Processing ────────────
DAILY_PICKS_FILE = os.path.join(BASE_DIR, "daily_picks_history.json")


def process_lt_watchlist(screener_results: list[dict]) -> list[dict]:
    """
    Reads lt_watchlist.json, merges live screener data per symbol,
    runs the 3-state status gate (BUY_NOW / WAIT / WATCHLIST), and
    returns an enriched list ready for the UI dashboard.
    """
    # Keep the locked monthly auto-picked cohort in sync before reading the file
    # (no-ops almost instantly if still locked — just a date check against
    # LT_MONTHLY_PICKS_FILE — so this is cheap on the frequent read-only call
    # sites too, not just the full-scan ones).
    sync_monthly_lt_watchlist_additions(screener_results)

    # Load seed file, create if missing
    if not os.path.exists(LT_WL_FILE):
        log(f"⚠ lt_watchlist.json not found at {LT_WL_FILE} — creating empty file")
        with open(LT_WL_FILE, "w") as f:
            json.dump([], f)
        return []

    try:
        with open(LT_WL_FILE, encoding="utf-8") as f:
            lt_stocks = json.load(f)
    except Exception as e:
        log(f"⚠ Could not load lt_watchlist.json: {e}")
        return []

    # Build fast lookup map from screener results
    result_map = {r.get("symbol", "").upper(): r for r in screener_results}

    holding_map = {}
    enriched = []
    buy_now_count = 0
    bought_count = 0
    for entry in lt_stocks:
        sym = (entry.get("symbol") or "").upper()
        active = entry.get("active", True)
        holding = None

        live = result_map.get(sym)
        scored = live or {}

        ltp        = float(live.get("ltp") or 0) if live else 0.0
        rsi        = float(live.get("rsi") or 50) if live else 50.0
        trend      = (live.get("trend") or "Consolidation") if live else "Consolidation"
        trend_badge= (live.get("tech_rating") or "🟡 Consolidation Phase") if live else "🟡 Consolidation Phase"
        rs_rating  = int(live.get("rs_rating") or 50) if live else 50
        rs_badge   = (live.get("rs_badge") or f"⚪ RS {rs_rating}") if live else f"⚪ RS {rs_rating}"
        total_score= float(live.get("total_score") or 0) if live else 0.0
        day_chg    = float(live.get("day_chg_pct") or 0) if live else 0.0

        gtt_mode  = entry.get("gtt_mode", "auto") # "auto" or "manual"
        gtt_level = entry.get("gtt_level")
        if gtt_level is not None:
            gtt_level = float(gtt_level)

        # Fully Dynamic Auto-Trailing GTT Fallback Chain (100% calculated from price history, 0 hardcoded multipliers):
        ema20 = float(live.get("ema20") or 0) if live else 0.0
        sr_sup = float(live.get("sup_level") or 0) if live else 0.0
        low20 = float(live.get("low20") or 0) if live else 0.0
        ma50 = float(live.get("ma50") or 0) if live else 0.0

        auto_gtt = None
        if ema20 > 0 and ema20 < ltp:
            auto_gtt = round(ema20, 2)
        elif sr_sup > 0 and sr_sup < ltp:
            auto_gtt = round(sr_sup, 2)
        elif low20 > 0 and low20 < ltp:
            auto_gtt = round(low20, 2)
        elif ma50 > 0 and ma50 < ltp:
            auto_gtt = round(ma50, 2)
        elif low20 > 0:
            auto_gtt = round(low20, 2)
        elif ema20 > 0:
            auto_gtt = round(ema20, 2)
        elif sr_sup > 0:
            auto_gtt = round(sr_sup, 2)
        elif ltp > 0:
            auto_gtt = round(ltp, 2)

        # Effective GTT Level: Auto-trailing unless user explicitly overrode with manual level
        if gtt_mode == "auto" or gtt_level is None:
            effective_gtt = auto_gtt
            is_auto_gtt = True
        else:
            effective_gtt = gtt_level
            is_auto_gtt = False

        # Check for 1h/Daily Support Reversal Candle (A/E Breakout)
        is_reversal_up = (day_chg > -0.35 or (rsi > 42 and rsi < 70))
        gate = get_lt_watchlist_status(trend, rsi, ltp, effective_gtt, day_chg=day_chg, is_reversal_up=is_reversal_up, holding=holding, scored=scored)
        status = gate["status"]
        if status == "BUY_NOW" and active:
            buy_now_count += 1
        elif status == "BOUGHT" and active:
            bought_count += 1

        # Distance from GTT level (negative = below GTT = triggered)
        dist_from_gtt_pct = None
        if effective_gtt and effective_gtt > 0 and ltp > 0:
            dist_from_gtt_pct = round(((ltp - effective_gtt) / effective_gtt) * 100, 1)

        sector_eval = compute_sector_aware_lt_quality(scored)

        enriched.append({
            **entry,
            "symbol":            sym,
            "ltp":               round(ltp, 2),
            "rsi":               round(rsi, 1),
            "day_chg_pct":       round(day_chg, 2),
            "trend":             trend,
            "trend_badge":       trend_badge,
            "rs_rating":         rs_rating,
            "rs_badge":          rs_badge,
            "total_score":       round(total_score, 1),
            "gtt_level":         effective_gtt,
            "auto_gtt":          auto_gtt,
            "gtt_mode":          "auto" if is_auto_gtt else "manual",
            "is_auto_gtt":       is_auto_gtt,
            "dist_from_gtt_pct": dist_from_gtt_pct,
            "status":            status,
            "status_badge":      gate["badge"],
            "status_badge_class": gate["badge_class"],
            "status_reason":     gate["reason"],
            "holding":           holding,
            "live_data_found":   live is not None,
            **sector_eval
        })

    if buy_now_count > 0:
        log(f"  🔔 LT Watchlist: {buy_now_count} stock(s) are BUY_NOW — GTT level reached!")
    log(f"  LT Watchlist: {sum(1 for e in enriched if e.get('active'))} active / {len(enriched)} total · "
        f"{buy_now_count} BUY_NOW · {sum(1 for e in enriched if e.get('status')=='WAIT' and e.get('active'))} WAIT · {bought_count} BOUGHT")

    # Persist the enriched rows so the mobile API serves the exact signals the web
    # page renders. Without this the API can only see the static lt_watchlist.json
    # config, which carries no status/badge/ltp and would show an empty watchlist.
    enriched_file = os.path.join(BASE_DIR, "lt_watchlist_enriched.json")
    try:
        with open(enriched_file, "w", encoding="utf-8") as f:
            json.dump(sanitize_for_strict_json(enriched), f, indent=2, default=json_serializer)
    except Exception as e:
        log(f"  ⚠ Failed to save lt_watchlist_enriched.json: {e}")

    # Run 4-Stage Universe Discovery & Incumbent Audit Pipeline across 2,414 NSE Stocks
    discovery_res = run_lt_universe_discovery_pipeline(screener_results, enriched)
    discovery_file = os.path.join(BASE_DIR, "lt_discovery_pipeline.json")
    try:
        with open(discovery_file, "w", encoding="utf-8") as f:
            json.dump(discovery_res, f, indent=2)
        log(f"  ⚡ LT Discovery Pipeline: Audited {len(enriched)} incumbents & discovered top {len(discovery_res.get('top_challengers', []))} universe candidates across {discovery_res.get('all_ranked_count', 0)} stocks.")
    except Exception as e:
        log(f"  ⚠ Failed to save lt_discovery_pipeline.json: {e}")

    return enriched


def get_lt_portfolio_summary(screener_results: list[dict] = None) -> dict:
    """Returns LT portfolio trading day status complying with Rule 4."""
    start_date_str = "2026-08-19"
    try:
        s_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
        today_date = datetime.datetime.now().date()
        cur_date = s_date
        days_active = 0
        while cur_date <= today_date:
            if not is_non_trading_day(cur_date.strftime("%Y-%m-%d")):
                days_active += 1
            cur_date += datetime.timedelta(days=1)
        days_active = max(1, days_active)
    except Exception:
        days_active = 1

    return {
        "start_date": start_date_str,
        "days_active": days_active,
        "holdings": [],
        "transactions": []
    }



def get_market_status() -> dict:
    """
    Returns current NSE/BSE & MCX Commodity market phase based on Indian Standard Time (IST = UTC+5:30).
    Includes check for weekends and 2026 NSE Trading Holidays.
    Commodity Trading Hours (MCX): Monday - Friday, 09:00 AM to 11:30 PM IST.
    Equity Trading Hours (NSE/BSE): Monday - Friday, 09:15 AM to 03:30 PM IST.
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = now_utc.astimezone(ist_tz)

    weekday = now_ist.weekday()  # Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    t = now_ist.time()

    eq_open_time = datetime.time(9, 15, 0)
    eq_close_time = datetime.time(15, 30, 0)
    mcx_open_time = datetime.time(9, 0, 0)
    mcx_close_time = datetime.time(23, 30, 0)

    time_str = now_ist.strftime("%I:%M %p IST")
    date_str = now_ist.strftime("%Y-%m-%d")
    display_date = now_ist.strftime("%d %B %Y")

    is_weekend = (weekday >= 5)
    is_holiday = date_str in NSE_HOLIDAYS_2026
    holiday_name = NSE_HOLIDAYS_2026.get(date_str, "")

    is_equity_open = (not is_weekend) and (not is_holiday) and (eq_open_time <= t <= eq_close_time)
    is_equity_pre = (not is_weekend) and (not is_holiday) and (t < eq_open_time)
    is_commodity_open = (not is_weekend) and (mcx_open_time <= t <= mcx_close_time)

    if is_holiday:
        return {
            "status": "HOLIDAY",
            "badge": f"🔴 Market Closed ({holiday_name})",
            "badge_class": "badge-red",
            "message": f"NSE/BSE Equity market is closed today ({display_date}) for {holiday_name}. Showing last official trading session picks.",
            "is_open": False,
            "is_equity_open": False,
            "is_commodity_open": False,
            "is_pre_market": False,
            "is_weekend": False,
            "is_holiday": True,
            "holiday_name": holiday_name,
            "date_str": date_str,
            "display_date": display_date,
            "time_str": time_str
        }

    if is_weekend:
        return {
            "status": "WEEKEND",
            "badge": "🔴 Market Closed (Weekend)",
            "badge_class": "badge-red",
            "message": "NSE/BSE & MCX closed for the weekend. Showing last official trading session picks.",
            "is_open": False,
            "is_equity_open": False,
            "is_commodity_open": False,
            "is_pre_market": False,
            "is_weekend": True,
            "is_holiday": False,
            "holiday_name": "",
            "date_str": date_str,
            "display_date": display_date,
            "time_str": time_str
        }

    if t < mcx_open_time:
        return {
            "status": "PRE_MARKET",
            "badge": "🔴 Market Closed (Opens 09:00 AM MCX / 09:15 AM Stock)",
            "badge_class": "badge-yellow",
            "message": "Pre-market session. MCX Commodity scan starts at 09:00 AM IST. Stock of the Day locks at 09:15 AM IST.",
            "is_open": False,
            "is_equity_open": False,
            "is_commodity_open": False,
            "is_pre_market": True,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": "",
            "date_str": date_str,
            "display_date": display_date,
            "time_str": time_str
        }
    elif is_commodity_open and t < eq_open_time:
        return {
            "status": "COMMODITY_LIVE",
            "badge": "🟢 MCX Commodity Live (Stock Opens 09:15 AM IST)",
            "badge_class": "badge-green",
            "message": f"MCX Commodity session is LIVE ({time_str}). Equity stock session opens at 09:15 AM IST.",
            "is_open": True,
            "is_equity_open": False,
            "is_commodity_open": True,
            "is_pre_market": True,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": "",
            "date_str": date_str,
            "display_date": display_date,
            "time_str": time_str
        }
    elif is_equity_open:
        return {
            "status": "LIVE_MARKET",
            "badge": "🟢 Live Market (Stocks & Commodities Active)",
            "badge_class": "badge-green",
            "message": f"NSE/BSE & MCX Session Active ({time_str}). Live prices & returns updating.",
            "is_open": True,
            "is_equity_open": True,
            "is_commodity_open": True,
            "is_pre_market": False,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": "",
            "date_str": date_str,
            "display_date": display_date,
            "time_str": time_str
        }
    elif is_commodity_open:
        return {
            "status": "COMMODITY_ONLY",
            "badge": "🟢 MCX Commodity Session Active (Stock Session Ended)",
            "badge_class": "badge-green",
            "message": f"Equity stock session ended at 03:30 PM. MCX Commodity market active until 11:30 PM IST ({time_str}).",
            "is_open": True,
            "is_equity_open": False,
            "is_commodity_open": True,
            "is_pre_market": False,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": "",
            "date_str": date_str,
            "display_date": display_date,
            "time_str": time_str
        }
    else:
        return {
            "status": "POST_MARKET",
            "badge": "🔴 Market Closed (All Sessions Ended)",
            "badge_class": "badge-red",
            "message": f"All trading sessions closed for {display_date}. Pick prices & returns finalized.",
            "is_open": False,
            "is_equity_open": False,
            "is_commodity_open": False,
            "is_pre_market": False,
            "is_weekend": False,
            "is_holiday": False,
            "holiday_name": "",
            "date_str": date_str,
            "display_date": display_date,
            "time_str": time_str
        }


def process_daily_top_pick(screener_results: list[dict]) -> tuple[dict, list[dict], dict]:
    if not screener_results:
        return {}, [], get_market_status()

    mkt_info = get_market_status()

    history = []
    if os.path.exists(DAILY_PICKS_FILE):
        try:
            with open(DAILY_PICKS_FILE) as f:
                history = json.load(f)
        except Exception:
            history = []

    # Filter out historical entries added on non-trading days AND any non-Large/Mid Cap or penny stocks
    cleaned_history = [
        item for item in history 
        if not is_non_trading_day(item.get("date", "")) and is_eligible_for_stock_of_the_day(item)
    ]
    if len(cleaned_history) != len(history):
        history = cleaned_history
        with open(DAILY_PICKS_FILE, "w") as f:
            json.dump(history, f, indent=2)

    today_str = mkt_info["date_str"]
    display_date = mkt_info["display_date"]
    is_non_trading = mkt_info.get("is_weekend", False) or mkt_info.get("is_holiday", False)
    require_trading_day = cfg.get("only_add_pick_on_trading_days", True)

    result_map = {r["symbol"]: r for r in screener_results if isinstance(r, dict) and r.get("symbol")}

    # Update live scores, LTP, and status for ALL historical picks
    for item in history:
        sym = item.get("symbol")
        if sym in result_map:
            res = result_map[sym]
            item["current_score"] = res["total_score"]
            item["current_ltp"] = res["ltp"]
            item["ltp"] = res["ltp"]
            st = check_top_pick_status(res)
            if not item.get("is_pre_market"):
                item["status"] = st["status"]
                item["status_badge"] = st["badge"]
                item["status_reason"] = st["reason"]

    # Check if today is a non-trading day (weekend or market holiday)
    if is_non_trading and require_trading_day:
        reason_label = "Weekend" if mkt_info.get("is_weekend") else f"Holiday ({mkt_info.get('holiday_name', 'Market Closed')})"
        log(f"\n🔴 Market is closed today [{reason_label}]. Skipping adding new Stock of the Day for {display_date}.")

        if history:
            top_pick = dict(history[0])
            if top_pick.get("symbol") in result_map:
                res = result_map[top_pick.get("symbol")]
                top_pick["current_ltp"] = res.get("ltp", top_pick.get("current_ltp", 0))
                top_pick["ltp"] = res.get("ltp", top_pick.get("ltp", 0))
                top_pick["pe"] = res.get("pe")
                top_pick["rsi"] = res.get("rsi")

            top_pick["status_badge"] = mkt_info["badge"]
            top_pick["status_reason"] = f"Market is closed today ({display_date}). Showing last official trading session pick from {top_pick.get('display_date')}."
        else:
            eligible_res = [r for r in screener_results if is_eligible_for_stock_of_the_day(r)]
            qualified = [r for r in eligible_res if r.get("qualified")]
            top = qualified[0] if qualified else (eligible_res[0] if eligible_res else screener_results[0])
            top_pick = {
                "date": today_str,
                "display_date": display_date,
                "symbol": top.get("symbol", ""),
                "name": top.get("name") or top.get("symbol", ""),
                "sector": top.get("sector", ""),
                "total_score": top["total_score"],
                "strength": top["strength"],
                "value": top["value"],
                "momentum": top["momentum"],
                "ltp_at_pick": top.get("ltp", 0),
                "current_ltp": top.get("ltp", 0),
                "status": "MARKET_CLOSED",
                "status_badge": mkt_info["badge"],
                "status_reason": f"Market closed today ({reason_label}). Pick selection paused."
            }

        with open(DAILY_PICKS_FILE, "w") as f:
            json.dump(history, f, indent=2)

        return top_pick, history, mkt_info

    # Regular trading day logic
    # If today's pick has already been locked in history, KEEP IT LOCKED FOR TODAY unless score drops severely below 45
    if history and history[0].get("date") == today_str and not history[0].get("is_pre_market"):
        top_pick = dict(history[0])
        sym = top_pick.get("symbol")
        res = result_map.get(sym)
        if res:
            top_pick["current_ltp"] = res["ltp"]
            top_pick["current_score"] = res["total_score"]
            top_pick["pe"] = res.get("pe")
            top_pick["rsi"] = res.get("rsi")
            if res.get("ma50") and res["ltp"]:
                top_pick["dist_ma50_pct"] = round(((res["ltp"] - res["ma50"]) / res["ma50"]) * 100, 1)
            if res.get("ma200") and res["ltp"]:
                top_pick["dist_ma200_pct"] = round(((res["ltp"] - res["ma200"]) / res["ma200"]) * 100, 1)
            st = check_top_pick_status(res)
            
            top_pick["status"] = st["status"]
            top_pick["status_badge"] = st["badge"]
            top_pick["status_reason"] = st["reason"]

            if top_pick.get("status") == "ACTIVE":
                history[0] = top_pick
                with open(DAILY_PICKS_FILE, "w") as f:
                    json.dump(history, f, indent=2)
                return top_pick, history, mkt_info
            
        history.pop(0)

    # STRICT SELECTION: Stock of the Day MUST BE Large Cap or Mid Cap ONLY & MUST BE QUALIFIED (Score >= 55 & Strength >= 50)
    eligible_screener_results = [
        r for r in screener_results 
        if is_eligible_for_stock_of_the_day(r) and (r.get("qualified") or (r.get("total_score", 0) >= 55 and r.get("strength", 0) >= 50))
    ]
    
    # Exclude any stock that has already been Stock of the Day for 2+ consecutive days to ensure fresh rotation
    overused_symbols = set()
    if history:
        for h_item in history[:3]:
            if h_item.get("streak_days", 1) >= 2 or (history[0].get("symbol") == h_item.get("symbol") and len(history) >= 2):
                overused_symbols.add(h_item.get("symbol"))

    qualified_eligible = [
        r for r in eligible_screener_results
        if r.get("symbol") not in overused_symbols
    ]
    
    if qualified_eligible:
        top = qualified_eligible[0]
    elif eligible_screener_results:
        top = eligible_screener_results[0]
    else:
        top = screener_results[0]

    streak_days = 1
    top_open = top.get("open") or top.get("regularMarketOpen")
    top_prev_close = top.get("prev_close") or top.get("previousClose")

    # If open price is missing (e.g., laptop/app was off during 09:15 AM open), fetch official exchange candle Open from history
    if not top_open or float(top_open) <= 0:
        try:
            top_data = fetch_via_curl_cffi(top["ticker"])
            if top_data and top_data.get("history_close"):
                hc = top_data["history_close"]
                if len(hc) > 0:
                    top_open = float(hc[-1].get("open", 0))
                    if not top_prev_close and len(hc) > 1:
                        top_prev_close = float(hc[-2].get("close", 0))
        except Exception:
            pass

    # Sanity filter: If top_open is an exaggerated tick from yfinance (> 5% deviation from current LTP), discard it
    current_price = top.get("ltp", 0)
    if top_open and current_price > 0:
        if abs(float(top_open) - current_price) / current_price > 0.05:
            top_open = current_price

    if top_open and float(top_open) > 0:
        entry_ltp = round(float(top_open), 2)
    else:
        entry_ltp = current_price

    # Compute overnight gap analysis (Pick Open vs Previous Day Close)
    if top_prev_close and float(top_prev_close) > 0 and entry_ltp > 0:
        gap_amt = round(entry_ltp - float(top_prev_close), 2)
        gap_pct = round((gap_amt / float(top_prev_close)) * 100, 2)
    else:
        gap_amt = 0.0
        gap_pct = 0.0

    if gap_amt > 0:
        gap_badge = f"🟢 Gap Up +{gap_pct}% (+₹{gap_amt:.2f})"
        gap_class = "badge-green"
    elif gap_amt < 0:
        gap_badge = f"🔻 Gap Down {gap_pct}% (-₹{abs(gap_amt):.2f})"
        gap_class = "badge-red"
    else:
        gap_badge = "⚪ Flat Open (0.00%)"
        gap_class = "badge-gray"

    if history:
        latest = history[0]
        ref_entry = latest
        if latest.get("date") == today_str and len(history) > 1:
            ref_entry = history[1]
        if ref_entry.get("symbol") == top["symbol"]:
            streak_days = (ref_entry.get("streak_days") or 1) + 1

    ltp = top.get("ltp", 0)
    ma50 = top.get("ma50")
    ma200 = top.get("ma200")
    w52_h = top.get("week_high_52")
    w52_l = top.get("week_low_52")
    rsi = top.get("rsi")

    dist_ma50 = round(((ltp - ma50) / ma50) * 100, 1) if (ma50 and ma50 > 0 and ltp > 0) else None
    dist_ma200 = round(((ltp - ma200) / ma200) * 100, 1) if (ma200 and ma200 > 0 and ltp > 0) else None
    dist_52h = round(((ltp - w52_h) / w52_h) * 100, 1) if (w52_h and w52_h > 0 and ltp > 0) else None
    dist_52l = round(((ltp - w52_l) / w52_l) * 100, 1) if (w52_l and w52_l > 0 and ltp > 0) else None

    if rsi is not None:
        if rsi < 30:
            rsi_status = "Oversold (<30)"
        elif rsi > 70:
            rsi_status = "Overbought (>70)"
        elif rsi >= 45 and rsi <= 65:
            rsi_status = "Bullish Setup (45-65)"
        else:
            rsi_status = "Neutral"
    else:
        rsi_status = "N/A"

    trend_st = compute_trend_classification(top)
    tech_rating = trend_st["badge"]
    tech_class = trend_st["class"]
    pick_st = check_top_pick_status(top)

    ist_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    is_pre_mkt = mkt_info["is_pre_market"] and (ist_now.time() < datetime.time(9, 15))

    if is_pre_mkt:
        status_code = "PENDING"
        status_badge = "⏳ PENDING MARKET OPEN"
        status_reason = f"Pre-market candidate for {display_date}. Will lock at 09:15 AM IST."
        highlight_title = f"⏳ Pre-Market Candidate for {display_date}"
    else:
        status_code = pick_st["status"]
        status_badge = pick_st["badge"]
        status_reason = pick_st["reason"]
        highlight_title = f"#1 Highest-Scoring Stock for {display_date}"

    base_entry = entry_ltp if entry_ltp > 0 else ltp
    sl_price = round(max(base_entry * 0.96, (ma50 or base_entry) * 0.98), 2)
    if sl_price >= base_entry:
        sl_price = round(base_entry * 0.96, 2)
    risk = round(base_entry - sl_price, 2)
    if risk <= 0:
        risk = round(base_entry * 0.04, 2)
        sl_price = round(base_entry - risk, 2)

    target1 = round(base_entry + (1.5 * risk), 2)
    target2 = round(base_entry + (2.5 * risk), 2)
    sl_pct = round(((sl_price - base_entry) / base_entry) * 100, 1) if base_entry > 0 else 0
    t1_pct = round(((target1 - base_entry) / base_entry) * 100, 1) if base_entry > 0 else 0
    t2_pct = round(((target2 - base_entry) / base_entry) * 100, 1) if base_entry > 0 else 0

    top_pick = {
        "date": today_str,
        "display_date": display_date,
        "is_pre_market": is_pre_mkt,
        "symbol": top["symbol"],
        "ticker": top["ticker"],
        "name": top.get("name") or top["symbol"],
        "sector": top.get("sector", ""),
        "total_score": top["total_score"],
        "strength": top["strength"],
        "value": top["value"],
        "momentum": top["momentum"],
        "ltp_at_pick": entry_ltp if not is_pre_mkt else ltp,
        "prev_close": float(top_prev_close) if top_prev_close else None,
        "overnight_gap_amt": gap_amt,
        "overnight_gap_pct": gap_pct,
        "gap_badge": gap_badge,
        "gap_class": gap_class,
        "current_ltp": ltp,
        "pe": top.get("pe"),
        "roe_pct": top.get("roe_pct"),
        "de_ratio": top.get("de_ratio"),
        "npm_pct": top.get("npm_pct"),
        "rsi": rsi,
        "rsi_status": rsi_status,
        "ma50": ma50,
        "ma200": ma200,
        "stop_loss": sl_price,
        "stop_loss_pct": sl_pct,
        "target1": target1,
        "target1_pct": t1_pct,
        "target2": target2,
        "target2_pct": t2_pct,
        "risk_reward_ratio": "1 : 2.0 (T1) / 1 : 3.0 (T2)",
        "timeframe": "3 to 7 Trading Days",
        "dist_ma50_pct": dist_ma50,
        "dist_ma200_pct": dist_ma200,
        "week_high_52": w52_h,
        "week_low_52": w52_l,
        "dist_52w_high_pct": dist_52h,
        "dist_52w_low_pct": dist_52l,
        "tech_rating": tech_rating,
        "tech_class": tech_class,
        "status": status_code,
        "status_badge": status_badge,
        "status_reason": status_reason,
        "streak_days": streak_days,
        "wk52_return_pct": top.get("wk52_return_pct"),
        "volume_spike": top.get("volume_spike", 0.0),
        "today_volume": top.get("today_volume", 0),
        "avg_volume_10d": top.get("avg_volume_10d", 0),
        "news": top.get("news", []),
        "highlights": [
            highlight_title,
            f"Quality Score: {top['total_score']}/100 | Strength: {top['strength']}/100",
            f"Market Trend: {tech_rating}"
        ]
    }

    for item in history:
        if item.get("date") == today_str:
            if not is_pre_mkt and (not item.get("ltp_at_pick") or item.get("ltp_at_pick") == 0):
                item["ltp_at_pick"] = entry_ltp
            item["current_ltp"] = ltp
            if not mkt_info.get("is_equity_open", False):
                item["session_close"] = ltp

    if history and history[0].get("date") == today_str:
        # Preserve original locked entry price if already locked
        if history[0].get("ltp_at_pick") and history[0]["ltp_at_pick"] > 0 and not is_pre_mkt:
            top_pick["ltp_at_pick"] = history[0]["ltp_at_pick"]
        if history[0].get("session_close"):
            top_pick["session_close"] = history[0]["session_close"]
        history[0] = top_pick
    else:
        history.insert(0, top_pick)

    history = history[:90]

    with open(DAILY_PICKS_FILE, "w") as f:
        json.dump(history, f, indent=2)

    log(f"\n🏆 Stock of the Day ({display_date}): {top['symbol']} [{'Pre-Market Candidate' if is_pre_mkt else 'Locked Pick'}] (Score: {top['total_score']}, LTP: ₹{top['ltp']:.2f}, Streak: {streak_days}d)")
    return top_pick, history, mkt_info


# ─── Step 5: Generate self-contained HTML ────────────────────────────────────
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover"/>
<title>Stock Screener — Phase 1 | Quality Watchlist</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap">
<script>
window.onerror = function(msg, url, lineNo, columnNo, error) {
  console.error("Global JS Error:", msg, error);
  var errDiv = document.getElementById("global-error-banner");
  if (!errDiv) {
    errDiv = document.createElement("div");
    errDiv.id = "global-error-banner";
    errDiv.style = "position:fixed;top:0;left:0;right:0;z-index:999999;background:#991b1b;color:#fff;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;font-family:sans-serif;font-size:14px;box-shadow:0 4px 12px rgba(0,0,0,0.5);";
    errDiv.innerHTML = "<span>⚠️ Application encountered an issue: " + (msg || "Unknown error") + "</span> <button onclick='location.reload()' style='background:#fff;color:#991b1b;border:none;padding:6px 14px;border-radius:4px;font-weight:bold;cursor:pointer;'>Reload App</button>";
    if (document.body) { document.body.insertBefore(errDiv, document.body.firstChild); }
    else if (document.documentElement) { document.documentElement.appendChild(errDiv); }
  }
  return false;
};
window.addEventListener('unhandledrejection', function(event) {
  console.error("Unhandled Rejection:", event.reason);
});
</script>
<style>
:root{
  --bg:#06060f;--card:#0e0e1e;--card2:#13132a;--border:#1e1e3a;
  --accent:#6c63ff;--accent2:#00d4aa;--warn:#f59e0b;--danger:#ef4444;
  --green:#10b981;--text:#e2e8f0;--muted:#64748b;--white:#fff;
  --font:'Inter',system-ui,sans-serif;
}
html, body { background: #06060f !important; color: #e2e8f0; font-family: var(--font, sans-serif); }
*{box-sizing:border-box;margin:0;padding:0}

/* ── Layout ── */
.app-header{background:linear-gradient(135deg,#0a0a1a,#12123a);border-bottom:1px solid var(--border);padding:16px 24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.app-title{font-size:22px;font-weight:700;background:linear-gradient(90deg,#6c63ff,#00d4aa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.phase-badge{background:linear-gradient(135deg,#6c63ff22,#00d4aa22);border:1px solid #6c63ff55;color:#a5b4fc;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600}
.run-info{margin-left:auto;color:var(--muted);font-size:12px}

/* ── Commodity Intraday Bar ── */
.commodity-bar{background:linear-gradient(90deg,rgba(15,23,42,0.95),rgba(30,41,59,0.95));border-bottom:1px solid var(--border);padding:10px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
.commodity-bar-title{display:flex;align-items:center;gap:8px}
.commodity-cards{display:flex;gap:16px;flex-wrap:wrap;align-items:center}
.commodity-card{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:6px 14px;display:flex;align-items:center;gap:12px;font-size:12px}
.commodity-card-name{font-weight:600;color:var(--text);display:flex;align-items:center;gap:8px}
.commodity-card-price{font-weight:700;color:#fff;font-family:monospace;font-size:13px}
.commodity-card-emas{font-size:11px;color:var(--muted);margin-top:2px}
.commodity-badge{padding:4px 12px;border-radius:12px;font-weight:700;font-size:11px;letter-spacing:0.02em}

.main{max-width:1600px;margin:0 auto;padding:20px 16px}

/* ── Stats cards ── */
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}
.stat-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;text-align:center}
.stat-val{font-size:28px;font-weight:700;margin-bottom:4px}
.stat-lbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.stat-green{color:var(--green)}
.stat-purple{color:#a5b4fc}
.stat-warn{color:var(--warn)}
.stat-danger{color:var(--danger)}

/* ── Tabs ── */
.tabs{display:flex;gap:4px;margin-bottom:20px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:6px;width:fit-content}
.tab{padding:8px 20px;border-radius:8px;cursor:pointer;font-weight:500;font-size:13px;color:var(--muted);transition:all .2s;border:none;background:none}
.tab.active{background:linear-gradient(135deg,#6c63ff,#5b54e8);color:#fff;box-shadow:0 4px 15px #6c63ff44}
.tab:hover:not(.active){background:var(--card2);color:var(--text)}

/* ── Filters ── */
.filters{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px;display:flex;gap:16px;flex-wrap:wrap;align-items:center}
.filter-group{display:flex;flex-direction:column;gap:4px}
.filter-group label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.filter-group input[type=range]{width:140px;accent-color:var(--accent)}
.filter-group input[type=text]{background:var(--card2);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:8px;font-size:13px;width:180px}
.filter-group select{background:var(--card2);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:8px;font-size:13px}
.filter-val{font-size:12px;color:var(--accent);font-weight:600}
.filter-reset{margin-left:auto;background:none;border:1px solid var(--border);color:var(--muted);padding:6px 14px;border-radius:8px;cursor:pointer;font-size:12px}
.filter-reset:hover{border-color:var(--accent);color:var(--accent)}

/* ── Table ── */
.table-wrap{overflow-x:auto;border-radius:12px;border:1px solid var(--border)}
table{width:100%;border-collapse:collapse;min-width:900px}
thead{background:var(--card2)}
th{padding:10px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600;cursor:pointer;white-space:nowrap;user-select:none}
th:hover{color:var(--accent)}
th.sorted-asc::after{content:' ↑';color:var(--accent)}
th.sorted-desc::after{content:' ↓';color:var(--accent)}
td{padding:10px 12px;border-top:1px solid var(--border);vertical-align:middle}
tr:hover td{background:#ffffff06}
.no-data{text-align:center;padding:40px;color:var(--muted)}

/* ── Score bars ── */
.score-bar-wrap{display:flex;align-items:center;gap:8px}
.score-bar{height:6px;border-radius:3px;background:var(--border);flex:1;overflow:hidden}
.score-fill{height:100%;border-radius:3px;transition:width .3s}
.score-num{font-weight:700;font-size:13px;min-width:32px;text-align:right}

/* ── Badges ── */
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}
.badge-green{background:#10b98122;color:#10b981;border:1px solid #10b98133}
.badge-yellow{background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b33}
.badge-red{background:#ef444422;color:#ef4444;border:1px solid #ef444433}
.badge-purple{background:#6c63ff22;color:#a5b4fc;border:1px solid #6c63ff33}
.badge-gray{background:#64748b22;color:#94a3b8;border:1px solid #64748b33}

/* ── Pill / number coloring ── */
.pos{color:var(--green)}
.neg{color:var(--danger)}
.neu{color:var(--muted)}
.stock-name{font-weight:600;font-size:13px}
.stock-sym{font-size:11px;color:var(--muted)}
.stock-sector{font-size:11px;color:#7c8aaa;margin-top:2px}
.price{font-weight:700;font-size:14px;color:var(--white)}
.partial-tag{font-size:10px;color:var(--muted);background:var(--card2);border-radius:4px;padding:1px 5px;margin-left:4px}

/* ── Add button ── */
.btn-add{background:linear-gradient(135deg,#6c63ff,#5b54e8);color:#fff;border:none;padding:5px 12px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;transition:all .2s;white-space:nowrap}
.btn-add:hover{transform:translateY(-1px);box-shadow:0 4px 12px #6c63ff55}
.btn-add:disabled{background:var(--card2);color:var(--muted);cursor:not-allowed;transform:none;box-shadow:none}
.btn-remove{background:none;border:1px solid #ef444444;color:#ef4444;padding:5px 12px;border-radius:8px;font-size:12px;cursor:pointer;transition:all .2s}
.btn-remove:hover{background:#ef444422}

/* ── Watchlist cards ── */
.wl-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:24px}
.wl-card{
  background: linear-gradient(145deg, #0d0d1f, #12122b);
  border: 1.5px solid rgba(108, 99, 255, 0.35);
  border-radius: 16px;
  padding: 22px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  transition: all .25s ease-in-out;
  position: relative;
  overflow: hidden;
}
.wl-card:hover{
  border-color: rgba(0, 212, 170, 0.7);
  transform: translateY(-4px);
  box-shadow: 0 12px 32px rgba(108, 99, 255, 0.25);
}
.wl-card.has-alert{
  border-color: rgba(239, 68, 68, 0.6);
  box-shadow: 0 8px 24px rgba(239, 68, 68, 0.2);
}
.wl-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,0.06)}
.wl-sym{font-size:16px;font-weight:700}
.wl-name{font-size:11px;color:var(--muted);margin-top:2px}
.wl-ltp{font-size:20px;font-weight:700;color:var(--white);text-align:right}
.wl-pnl{font-size:12px;font-weight:600;text-align:right}
.wl-scores{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin:12px 0}
.wl-score-box{background:var(--card2);border-radius:8px;padding:8px;text-align:center}
.wl-score-box .val{font-size:18px;font-weight:700}
.wl-score-box .lbl{font-size:10px;color:var(--muted);text-transform:uppercase;margin-top:2px}
.wl-metrics{display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:12px;margin:10px 0}
.wl-metric{display:flex;justify-content:space-between;color:var(--muted)}
.wl-metric span:last-child{color:var(--text);font-weight:500}
.wl-alerts{margin-top:12px}
.alert-row{display:flex;align-items:flex-start;gap:8px;padding:8px;border-radius:8px;font-size:12px;margin-top:6px}
.alert-SELL{background:#ef444418;border:1px solid #ef444433;color:#fca5a5}
.alert-REVIEW{background:#f59e0b18;border:1px solid #f59e0b33;color:#fcd34d}
.alert-ALERT{background:#6c63ff18;border:1px solid #6c63ff33;color:#c4b5fd}
.wl-footer{display:flex;justify-content:space-between;align-items:center;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)}
.entry-info{font-size:11px;color:var(--muted)}
.slot-bar-wrap{margin-bottom:20px}
.slot-bar-label{display:flex;justify-content:space-between;font-size:13px;margin-bottom:6px}
.slot-bar{height:8px;background:var(--card2);border-radius:4px;overflow:hidden}
.slot-fill{height:100%;border-radius:4px;background:linear-gradient(90deg,#6c63ff,#00d4aa)}
.budget-bar-wrap{margin-bottom:16px}

/* ── Modal ── */
.modal-bg{position:fixed;inset:0;background:#000000cc;z-index:100;display:flex;align-items:center;justify-content:center;padding:20px}
.modal{background:var(--card);border:1px solid var(--border);border-radius:16px;width:100%;max-width:560px;max-height:90vh;overflow-y:auto;padding:24px}
.modal h3{font-size:18px;font-weight:700;margin-bottom:4px}
.modal-close{float:right;background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;margin-top:-4px}
.modal-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:16px 0}
.modal-metric{background:var(--card2);border-radius:8px;padding:12px}
.modal-metric .lbl{font-size:11px;color:var(--muted);text-transform:uppercase;margin-bottom:4px}
.modal-metric .val{font-size:16px;font-weight:700}
.modal-actions{display:flex;gap:10px;margin-top:16px}

/* ── Progress ── */
.progress-overlay{position:fixed;inset:0;background:#000000ee;z-index:200;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px}
.progress-bar-outer{width:400px;height:8px;background:var(--card2);border-radius:4px;overflow:hidden}
.progress-bar-inner{height:100%;background:linear-gradient(90deg,#6c63ff,#00d4aa);border-radius:4px;transition:width .3s}
.progress-text{color:var(--text);font-size:14px}
.progress-log{color:var(--muted);font-size:12px;max-height:200px;overflow-y:auto;width:500px;text-align:center}

/* ── Mobile-First Responsive Styles & Bottom Navigation ── */
.mobile-nav-bar {
  display: none;
}

@media (max-width: 1024px), (hover: none) and (pointer: coarse) {
  html, body {
    width: 100% !important;
    max-width: 100vw !important;
    overflow-x: hidden !important;
    padding-bottom: 70px !important;
  }

  .app-header {
    flex-direction: column !important;
    align-items: stretch !important;
    gap: 10px !important;
    padding: 14px !important;
    width: 100% !important;
  }

  .main {
    padding: 10px 8px !important;
    max-width: 100% !important;
    width: 100% !important;
    box-sizing: border-box !important;
  }

  .stats-grid {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
    gap: 8px !important;
    width: 100% !important;
    margin: 0 0 16px 0 !important;
    box-sizing: border-box !important;
  }

  .stat-card {
    padding: 12px 8px !important;
    width: 100% !important;
    box-sizing: border-box !important;
  }

  .stat-val {
    font-size: 18px !important;
  }

  /* Completely hide desktop top horizontal tab bar on mobile/touch screens */
  .tabs {
    display: none !important;
  }

  .filters {
    flex-direction: column !important;
    align-items: stretch !important;
    padding: 12px !important;
    width: 100% !important;
  }

  .filter-group input[type=text],
  .filter-group select {
    width: 100% !important;
  }

  .wl-grid {
    grid-template-columns: 1fr !important;
    gap: 12px !important;
    width: 100% !important;
  }

  .wl-card {
    width: 100% !important;
    padding: 14px !important;
    box-sizing: border-box !important;
  }

  .hero-spotlight {
    padding: 14px !important;
    width: 100% !important;
    box-sizing: border-box !important;
  }

  .fno-grid {
    grid-template-columns: 1fr !important;
    width: 100% !important;
  }

  .table-wrap {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    border-radius: 12px;
    width: 100% !important;
  }

  table {
    min-width: 650px !important;
  }

  .main {
    padding-bottom: calc(90px + env(safe-area-inset-bottom, 20px)) !important;
  }

  /* Fixed Mobile Bottom Navigation Bar */
  .mobile-nav-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    min-height: 56px;
    background: rgba(10, 10, 26, 0.98);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-top: 1px solid rgba(255, 255, 255, 0.12);
    display: flex !important;
    justify-content: space-around;
    align-items: center;
    z-index: 9999;
    box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.6);
    padding-top: 6px;
    padding-bottom: max(20px, env(safe-area-inset-bottom, 20px));
    box-sizing: content-box;
  }

  .mobile-nav-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    background: none;
    border: none;
    color: var(--muted);
    font-size: 10px;
    font-weight: 600;
    cursor: pointer;
    padding: 6px 10px;
    border-radius: 10px;
    transition: all 0.2s ease;
    flex: 1;
  }

  .mobile-nav-item.active {
    color: #34D399;
    background: rgba(16, 185, 129, 0.14);
  }

  .mobile-nav-icon {
    font-size: 16px;
    line-height: 1;
  }

  /* ── Mobile readability pass ──────────────────────────────────────────────
     The phone layout was the desktop one scaled down: content ran under the
     status bar, seven nav labels wrapped to two and three lines inside ~77px
     tabs, and card padding left very little data visible per screen. */

  /* The status bar overlaps a fixed header without this. viewport-fit=cover is
     already set on the meta tag, which is what makes the inset resolve. */
  .app-header {
    padding-top: calc(12px + env(safe-area-inset-top, 0px)) !important;
    padding-left: max(14px, env(safe-area-inset-left, 0px)) !important;
    padding-right: max(14px, env(safe-area-inset-right, 0px)) !important;
    padding-bottom: 12px !important;
    gap: 10px !important;
  }
  .app-title { font-size: 18px !important; }

  /* All seven tabs share the width evenly so none is pushed off-screen. An
     earlier attempt let the bar scroll horizontally, but that hid the last tab
     with no visual cue that it existed -- measured at 421px of tabs in a 375px
     viewport. Equal flex basis with min-width:0 lets them compress to fit
     instead, and the label truncates rather than wrapping to a second line. */
  .mobile-nav-bar {
    justify-content: space-between;
    overflow: hidden;
  }

  .mobile-nav-item {
    flex: 1 1 0;
    min-width: 0;
    padding: 6px 2px !important;
    font-size: 9.5px !important;
    line-height: 1.2;
  }
  .mobile-nav-item > span:last-child {
    display: block;
    width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Denser cards: the previous 16px padding and 28px figures meant roughly one
     stat per thumb-scroll. */
  .stats-grid {
    grid-template-columns: repeat(auto-fit, minmax(104px, 1fr)) !important;
    gap: 8px !important;
    margin-bottom: 14px !important;
  }
  .stat-card { padding: 10px 8px !important; border-radius: 10px !important; }
  .stat-val  { font-size: 20px !important; margin-bottom: 2px !important; }
  .stat-lbl  { font-size: 9.5px !important; letter-spacing: .03em !important; }

  /* Long headings such as "Commodities Intraday Signals" broke mid-phrase. */
  h1, h2, h3, .card-title { overflow-wrap: break-word; hyphens: none; }
  h2 { font-size: 16px !important; }
  h3 { font-size: 14px !important; }

  /* This row is flex/nowrap with a long trailing chip ("15m timeframe (15/20
     EMA Crossover)"). At 311px the chip refused to shrink, squeezing the title
     to 131px so it wrapped mid-phrase. Letting the row wrap drops the chip onto
     its own line and gives the title the full width. */
  .commodity-bar-title {
    flex-wrap: wrap !important;
    row-gap: 4px !important;
  }
  .commodity-bar-title > span:last-child {
    flex-basis: 100%;
  }
}

/* ── Details / Summary News Collapsible ── */
details summary {
  list-style: none;
}
details summary::-webkit-details-marker {
  display: none;
}
details summary::before {
  content: "▶ ";
  font-size: 9px;
  color: var(--accent2);
  margin-right: 4px;
  display: inline-block;
  transition: transform 0.2s;
}
details[open] summary::before {
  content: "▼ ";
}

/* ── Live LTP Badge & Pulse Animations ── */
@keyframes priceUpPulse {
  0% { background-color: rgba(16, 185, 129, 0.4); color: #10b981; }
  100% { background-color: transparent; }
}
@keyframes priceDownPulse {
  0% { background-color: rgba(239, 68, 68, 0.4); color: #ef4444; }
  100% { background-color: transparent; }
}
.price-up { animation: priceUpPulse 1.5s ease-out; }
.price-down { animation: priceDownPulse 1.5s ease-out; }

.ltp-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--card2);
  border: 1px solid var(--border);
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 12px;
}
.ltp-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
  display: inline-block;
  box-shadow: 0 0 8px var(--green);
}
.ltp-dot.updating {
  animation: blink 0.5s infinite alternate;
  background: var(--warn);
  box-shadow: 0 0 8px var(--warn);
}
@keyframes blink {
  from { opacity: 0.3; }
  to { opacity: 1; }
}

/* ── Stock of the Day Spotlight Hero ── */
.hero-spotlight {
  background: linear-gradient(135deg, rgba(108, 99, 255, 0.15), rgba(0, 212, 170, 0.1));
  border: 1px solid rgba(108, 99, 255, 0.4);
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 24px;
  position: relative;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(108, 99, 255, 0.15);
}
.hero-badge-tag {
  background: linear-gradient(135deg, #6c63ff, #00d4aa);
  color: #06060f;
  font-weight: 800;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 4px 12px;
  border-radius: 20px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 14px;
}
.hero-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 20px;
  align-items: start;
}
@media (max-width: 900px) {
  .hero-grid { grid-template-columns: 1fr; }
}
.hero-score-ring {
  background: var(--card2);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px;
  text-align: center;
}
.hero-score-val {
  font-size: 42px;
  font-weight: 800;
  line-height: 1;
}

/* ── F&O Options Tab ── */
.fno-header{background:linear-gradient(135deg,#0a0a1a,#1a0a2e);border:1px solid #4c1d95;border-radius:16px;padding:20px 24px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
.fno-header-left{display:flex;align-items:center;gap:16px}
.fno-header-title{font-size:18px;font-weight:700;color:#c4b5fd}
.fno-header-sub{font-size:12px;color:#7c3aed;margin-top:2px}
.fno-expiry-badge{background:rgba(124,58,237,0.15);border:1px solid #7c3aed;border-radius:20px;padding:6px 16px;font-size:12px;font-weight:600;color:#a78bfa}
.fno-disclaimer{background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.3);border-radius:10px;padding:10px 16px;font-size:11px;color:#fbbf24;margin-bottom:20px;display:flex;gap:8px;align-items:flex-start}
.fno-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.fno-card{background:var(--card);border:1px solid var(--border);border-radius:16px;overflow:hidden;transition:box-shadow .2s,transform .2s}
.fno-card:hover{box-shadow:0 8px 32px rgba(124,58,237,0.18);transform:translateY(-2px)}
.fno-card-header{padding:16px 18px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.fno-card-sym{font-size:16px;font-weight:700;color:var(--white)}
.fno-card-name{font-size:11px;color:var(--muted);margin-top:2px}
.fno-card-price{text-align:right}
.fno-card-ltp{font-size:18px;font-weight:800;color:var(--white);font-family:monospace}
.fno-card-chg{font-size:11px;font-weight:600;margin-top:2px}
.fno-signal-row{padding:14px 18px;display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--border)}
.fno-signal-badge{padding:6px 18px;border-radius:20px;font-size:13px;font-weight:800;letter-spacing:.04em;flex-shrink:0}
.fno-signal-ce{background:linear-gradient(135deg,#052e16,#14532d);border:2px solid #16a34a;color:#4ade80}
.fno-signal-pe{background:linear-gradient(135deg,#450a0a,#7f1d1d);border:2px solid #dc2626;color:#f87171}
.fno-signal-neutral{background:rgba(100,116,139,0.12);border:2px solid #475569;color:#94a3b8}
.fno-conviction{flex:1}
.fno-conviction-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;display:flex;justify-content:space-between}
.fno-conviction-bar{height:8px;background:var(--border);border-radius:4px;overflow:hidden}
.fno-conviction-fill{height:100%;border-radius:4px;transition:width .5s}
.fno-body{padding:14px 18px}
.fno-section-title{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px;font-weight:600}
.fno-strikes-table{width:100%;border-collapse:collapse;margin-bottom:14px}
.fno-strikes-table th{font-size:10px;color:var(--muted);text-transform:uppercase;padding:4px 6px;text-align:left;border-bottom:1px solid var(--border)}
.fno-strikes-table td{font-size:12px;padding:5px 6px;border-bottom:1px solid rgba(255,255,255,0.04)}
.fno-strike-val{font-weight:700;font-family:monospace;color:var(--white)}
.fno-strike-otm{font-size:10px;color:var(--muted)}
.fno-rr-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:14px}
.fno-rr-cell{background:var(--card2);border-radius:8px;padding:8px;text-align:center}
.fno-rr-label{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}
.fno-rr-val{font-size:12px;font-weight:700;font-family:monospace}
.fno-tech-row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.fno-tech-pill{font-size:10px;padding:3px 8px;border-radius:10px;font-weight:600}
.fno-lot-info{font-size:10px;color:var(--muted);margin-top:8px;padding-top:8px;border-top:1px solid var(--border);display:flex;justify-content:space-between}
.fno-no-data{text-align:center;padding:60px;color:var(--muted)}

/* ── Swing Radar ── */
.swing-pill{padding:7px 15px;border-radius:20px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid rgba(108,99,255,0.4);background:rgba(108,99,255,0.08);color:#a5b4fc;transition:all .2s;white-space:nowrap}
.swing-pill:hover{background:rgba(108,99,255,0.2);border-color:#6c63ff;transform:translateY(-1px)}
.swing-pill-active{background:linear-gradient(135deg,#6c63ff,#5b54e8)!important;color:#fff!important;border-color:#6c63ff!important;box-shadow:0 4px 14px rgba(108,99,255,0.4)!important}
.swing-card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px;transition:all .2s;cursor:pointer;position:relative;overflow:hidden}
.swing-card:hover{border-color:#6c63ff55;transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,0.3)}
.swing-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,#6c63ff,#00d4aa)}
.swing-card-blast::before{background:linear-gradient(90deg,#10b981,#34d399)}
.swing-card-inflow::before{background:linear-gradient(90deg,#6366f1,#a78bfa)}
.swing-card-momentum::before{background:linear-gradient(90deg,#f59e0b,#fbbf24)}
.swing-card-pullback::before{background:linear-gradient(90deg,#3b82f6,#60a5fa)}
.swing-card-overbought::before{background:linear-gradient(90deg,#ef4444,#f87171)}
.swing-card-overbought{border-color:rgba(239,68,68,0.25)}
.swing-score-ring{width:50px;height:50px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:700;background:conic-gradient(var(--ring-color,#6c63ff) calc(var(--pct,0) * 1%),rgba(255,255,255,0.06) 0);position:relative}
.swing-score-ring::after{content:attr(data-score);position:absolute;font-size:13px;font-weight:700;color:#fff}
.swing-sl{color:#ef4444;font-weight:600}
.swing-t1{color:#10b981;font-weight:600}
.swing-t2{color:#00d4aa;font-weight:600}
</style>
</head>
<body>

<div class="app-header">
  <div>
    <div class="app-title">📊 Quality Stock Screener</div>
    <div style="font-size:12px;color:var(--muted);margin-top:2px">Nifty 500 Universe · Real data from Yahoo Finance</div>
  </div>
  <div class="phase-badge">__PHASE_LABEL__ — ₹__PHASE_BUDGET__/symbol cap</div>
  <div id="mktStatusPillHeader"></div>

  <button class="btn-add" onclick="triggerAppScan()" style="background:linear-gradient(135deg,#00d4aa,#059669);font-size:13px;padding:7px 16px;display:flex;align-items:center;gap:6px;cursor:pointer" title="Trigger full stock and commodity scan now">
    <span>⚡ Scan Now</span>
  </button>

  <div class="ltp-badge">
    <span class="ltp-dot" id="ltpStatusDot"></span>
    <span id="ltpStatusText" style="font-weight:600">Live LTP: 10s</span>
    <select id="pollIntervalSelect" onchange="changePollInterval(this.value)" style="background:var(--card);border:1px solid var(--border);color:var(--text);font-size:11px;border-radius:6px;padding:2px 4px;cursor:pointer;outline:none;margin-left:4px">
      <option value="10000" selected>10s</option>
      <option value="30000">30s</option>
      <option value="60000">60s</option>
      <option value="0">Off</option>
    </select>
    <button onclick="refreshLiveLTP(true)" style="background:none;border:none;color:var(--accent2);cursor:pointer;font-size:14px;margin-left:4px" title="Force Refresh Prices Now">🔄</button>
  </div>

  <div class="run-info">Last scan: __RUN_TIME__ &nbsp;|&nbsp; <span style="color:var(--muted)">Data delay: ~15 min</span></div>
</div>

<div id="scanProgressOverlay" class="progress-overlay" style="display:none">
  <div style="font-size:36px;animation:spin 2s linear infinite">⚡</div>
  <div style="font-size:18px;font-weight:700;color:var(--white)" id="scanProgressText">Scanning Nifty 500 & Commodities...</div>
  <div class="progress-bar-outer">
    <div class="progress-bar-inner" id="scanProgressBarInner" style="width:10%"></div>
  </div>
  <div class="progress-log" id="scanProgressLog">Fetching real-time stock data from Yahoo Finance...</div>
</div>

<div class="main">

  <!-- Macro NIFTY 50 Market Regime & Tactical Stance Banner -->
  <div id="niftyRegimeBanner" style="background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 18px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;box-shadow:0 4px 16px rgba(0,0,0,0.2)">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <span id="niftyRegimeBadge" class="badge badge-yellow" style="font-size:12px;padding:6px 14px;font-weight:700">🟡 NIFTY 50: Analyzing Regime...</span>
      <span id="niftyRegimeLtp" style="font-size:14px;font-weight:800;color:#fff"></span>
      <span id="niftyRegimeStance" style="font-size:11px;font-weight:700;color:#a5b4fc;background:rgba(108,99,255,0.15);border:1px solid rgba(108,99,255,0.3);padding:3px 10px;border-radius:12px"></span>
    </div>
    <div id="niftyRegimeGuidance" style="font-size:12px;color:var(--muted);max-width:650px;line-height:1.4"></div>
  </div>

  <!-- Commodities Intraday Signals Bar -->
  <div class="commodity-bar" id="commodityBar" style="margin-bottom:16px;border-radius:14px">
    <div class="commodity-bar-title">
      <span style="font-size:16px">⛽</span>
      <span style="font-weight:600;font-size:13px;color:var(--text)">Commodities Intraday Signals</span>
      <span style="font-size:10px;background:rgba(255,255,255,0.06);padding:2px 8px;border-radius:10px;color:var(--muted)">15m timeframe (15/20 EMA Crossover)</span>
    </div>
    <div class="commodity-cards" id="commodityCards"></div>
  </div>

  <!-- Desktop Top Tabs (Hidden on mobile where bottom nav is active) -->
  <div class="tabs">
    <button class="tab active" data-tab="screener" onclick="switchTab('screener')">🔍 Full Screener</button>
    <button class="tab" data-tab="swing" onclick="switchTab('swing')">⚡ Swing Top 10</button>
    <button class="tab" data-tab="intraday" onclick="switchTab('intraday')">🎯 Intraday</button>
    <button class="tab" data-tab="watchlist" onclick="switchTab('watchlist')">🛡️ LT Screen (<span id="wlCount">0</span>)</button>
    <button class="tab" data-tab="penny" onclick="switchTab('penny')">💎 Penny Screen</button>
    <button class="tab" data-tab="fno" onclick="switchTab('fno')">📊 F&amp;O Options</button>
    <button class="tab" data-tab="holidays" onclick="switchTab('holidays')">📅 Market Holidays (2026)</button>
  </div>


  <!-- SCREENER TAB -->
  <div id="tab-screener" style="display:none">
    <div class="filters">
      <div class="filter-group">
        <label>Search</label>
        <input type="text" id="fSearch" placeholder="Symbol or name..." oninput="applyFilters()">
      </div>
      <div class="filter-group">
        <label>Show</label>
        <select id="fQual" onchange="applyFilters()">
          <option value="all" selected>All stocks</option>
          <option value="qualified">Qualified only (≥55 score)</option>
          <option value="watch">Watch list (≥45)</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Sector</label>
        <select id="fSector" onchange="applyFilters()">
          <option value="all">All Sectors</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Market Cap</label>
        <select id="fMcap" onchange="applyFilters()">
          <option value="all">All Market Caps</option>
          <option value="large">Large Cap (≥ ₹20k Cr)</option>
          <option value="mid">Mid Cap (₹5k - ₹20k Cr)</option>
          <option value="small">Small Cap (&lt; ₹5k Cr)</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Trend</label>
        <select id="fTrend" onchange="applyFilters()">
          <option value="all">All Trends</option>
          <option value="uptrend_downtrend">⚡ Uptrend & Downtrend Only</option>
__TREND_OPTIONS_HTML__
        </select>
      </div>
      <button class="filter-reset" onclick="resetFilters()">↺ Reset</button>
    </div>
    <div style="font-size:12px;color:var(--muted);margin-bottom:10px" id="resultCount"></div>
    <div id="searchQuickView" style="margin-bottom:16px"></div>
    <div class="pagination-bar" id="tablePagination" style="display:flex;align-items:center;justify-content:space-between;margin:12px 0;padding:10px 14px;background:var(--bg-card,#181c28);border:1px solid var(--border,#2b3245);border-radius:8px;font-size:13px;color:var(--text,#e1e7ef)">
      <div id="paginationInfo" style="font-weight:500">Showing 1-50 of 0 stocks</div>
      <div style="display:flex;align-items:center;gap:10px">
        <button class="btn btn-sm" onclick="changePage(-1)" id="btnPrevPage" style="padding:4px 12px;background:var(--bg-card);border:1px solid var(--border);color:var(--text);border-radius:4px;cursor:pointer">◀ Previous</button>
        <span id="pageNumbers" style="font-weight:600;min-width:90px;text-align:center">Page 1 of 1</span>
        <button class="btn btn-sm" onclick="changePage(1)" id="btnNextPage" style="padding:4px 12px;background:var(--bg-card);border:1px solid var(--border);color:var(--text);border-radius:4px;cursor:pointer">Next ▶</button>
        <select id="pageSizeSelect" onchange="changePageSize(this.value)" style="background:var(--bg-body,#0f121d);color:var(--text,#e1e7ef);border:1px solid var(--border,#2b3245);border-radius:4px;padding:4px 8px;font-size:12px">
          <option value="25">25 per page</option>
          <option value="50" selected>50 per page</option>
          <option value="100">100 per page</option>
          <option value="all">Show All</option>
        </select>
      </div>
    </div>
    <div class="table-wrap">
      <table id="screenerTable">
        <thead>
          <tr>
            <th onclick="sortTable('symbol')" title="Click to sort by Symbol">Symbol <span id="sort_symbol">↕</span></th>
            <th onclick="sortTable('ltp')" title="Click to sort by Price">Price <span id="sort_ltp">↕</span></th>
            <th onclick="sortTable('total_score')" title="Click to sort by Total Score">Total Score <span id="sort_total_score">↕</span></th>
            <th onclick="sortTable('rs_rating')" title="Click to sort by Relative Strength vs Nifty">RS Rating <span id="sort_rs_rating">↕</span></th>
            <th onclick="sortTable('strength')" title="Click to sort by Strength">Strength <span id="sort_strength">↕</span></th>
            <th onclick="sortTable('value')" title="Click to sort by Value">Value <span id="sort_value">↕</span></th>
            <th onclick="sortTable('momentum')" title="Click to sort by Momentum">Momentum <span id="sort_momentum">↕</span></th>
            <th onclick="sortTable('pe')" title="Click to sort by P/E">P/E <span id="sort_pe">↕</span></th>
            <th onclick="sortTable('roe_pct')" title="Click to sort by ROE%">ROE% <span id="sort_roe_pct">↕</span></th>
            <th onclick="sortTable('de_ratio')" title="Click to sort by D/E">D/E <span id="sort_de_ratio">↕</span></th>
            <th onclick="sortTable('npm_pct')" title="Click to sort by Margin%">Margin% <span id="sort_npm_pct">↕</span></th>
            <th onclick="sortTable('wk52_return_pct')" title="Click to sort by 52W Return%">52W Ret% <span id="sort_wk52_return_pct">↕</span></th>
            <th onclick="sortTable('rsi')" title="Click to sort by RSI">RSI <span id="sort_rsi">↕</span></th>
            <th onclick="sortTable('volume_spike')" title="Click to sort by Volume Spike">Vol Spike <span id="sort_volume_spike">↕</span></th>
            <th onclick="sortTable('cmf')" title="Click to sort by Order Flow (CMF)">Order Flow / PA <span id="sort_cmf">↕</span></th>
            <th>Trend</th>
            <th>Status</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody id="screenerBody"></tbody>
      </table>
    </div>
  </div>

  <!-- SWING RADAR TAB -->
  <div id="tab-swing">
    <!-- Header Banner -->
    <div style="background:linear-gradient(135deg,rgba(108,99,255,0.15),rgba(0,212,170,0.10));border:1px solid rgba(108,99,255,0.35);border-radius:16px;padding:20px 24px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px">
      <div>
        <div style="font-size:20px;font-weight:700;background:linear-gradient(90deg,#a78bfa,#00d4aa);-webkit-background-clip:text;-webkit-text-fill-color:transparent">🚀 Swing Trade Radar</div>
        <div style="font-size:12px;color:var(--muted);margin-top:4px">MTF-quality stocks · Zerodha approved · Ranked by Swing Score</div>
      </div>
      <div style="display:flex;align-items:center;gap:12px">
        <div style="text-align:center">
          <div id="swingMtfCount" style="font-size:20px;font-weight:700;color:#a78bfa">0</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">MTF Stocks</div>
        </div>
        <div style="text-align:center">
          <div id="swingRsCount" style="font-size:20px;font-weight:700;color:#10b981">0</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">RS Leaders</div>
        </div>
        <div style="text-align:center">
          <div id="swingBlastCount" style="font-size:20px;font-weight:700;color:#34d399">0</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Blast Alerts</div>
        </div>
        <div style="text-align:center">
          <div id="swingInflowCount" style="font-size:20px;font-weight:700;color:#6366f1">0</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Inflow Setups</div>
        </div>
      </div>
    </div>

    <!-- Preset Filter Pills -->
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px;align-items:center">
      <span style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-right:4px">Quick Filters:</span>
      <button id="swingPill-all" class="swing-pill swing-pill-active" onclick="setSwingPreset('all')">↺ All MTF</button>
      <button id="swingPill-rs" class="swing-pill" onclick="setSwingPreset('rs')" style="border-color:#10b981;background:rgba(16,185,129,0.1);color:#34d399">⚡ RS Leaders (RS ≥ 80)</button>
      <button id="swingPill-blast" class="swing-pill" onclick="setSwingPreset('blast')">💥 Volume Blast</button>
      <button id="swingPill-inflow" class="swing-pill" onclick="setSwingPreset('inflow')">🏛️ Institutional Inflow</button>
      <button id="swingPill-momentum" class="swing-pill" onclick="setSwingPreset('momentum')">🔥 High Momentum</button>
      <button id="swingPill-pullback" class="swing-pill" onclick="setSwingPreset('pullback')">🔄 Pullback Buy</button>
      <button id="swingPill-quality" class="swing-pill" onclick="setSwingPreset('quality')">🏆 Quality + Momentum</button>
    </div>

    <!-- Top 10 Swing Spotlight -->
    <div style="margin-bottom:24px">
      <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:12px;display:flex;align-items:center;gap:8px">
        <span style="background:linear-gradient(135deg,#6c63ff,#00d4aa);-webkit-background-clip:text;-webkit-text-fill-color:transparent">⚡ Top 10 Swing Picks</span>
        <span style="font-size:11px;color:var(--muted);font-weight:400">(current preset)</span>
      </div>
      <div id="swingSpotlight" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px"></div>
    </div>

    <!-- Swing Title & Symbol Filter Bar -->
    <div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
      <div style="position:relative;flex:1;min-width:260px">
        <input type="text" id="swingTitleFilter" placeholder="🔍 Search / Filter stocks by Title, Symbol, Badge, Reason..." oninput="renderSwingRadar()" style="width:100%;padding:8px 14px 8px 34px;border-radius:20px;border:1px solid var(--border);background:var(--card);color:#fff;font-size:13px;outline:none;box-shadow:inset 0 1px 3px rgba(0,0,0,0.3)">
        <span style="position:absolute;left:12px;top:50%;transform:translateY(-50%);font-size:14px;color:var(--muted);pointer-events:none">🔍</span>
      </div>
      <div style="display:flex;gap:6px">
        <button class="btn btn-sm" onclick="document.getElementById('swingTitleFilter').value='';renderSwingRadar()" style="border-radius:20px;font-size:12px;padding:6px 14px;background:var(--card2);border:1px solid var(--border);color:var(--text);cursor:pointer">Clear Filter</button>
      </div>
    </div>

    <!-- Full Swing Table -->
    <div style="font-size:12px;color:var(--muted);margin-bottom:8px" id="swingResultCount"></div>
    <div class="table-wrap">
      <table id="swingTable">
        <thead>
          <tr>
            <th onclick="sortSwingTable('index')" style="cursor:pointer" title="Sort by Index Title"># <span id="swing_sort_index">↕</span></th>
            <th onclick="sortSwingTable('symbol')" style="cursor:pointer" title="Sort by Stock Title / Symbol">SYMBOL <span id="swing_sort_symbol">↕</span></th>
            <th onclick="sortSwingTable('swing_score')" style="cursor:pointer" title="Sort by Swing Score">SWING SCORE <span id="swing_sort_swing_score">↕</span></th>
            <th onclick="sortSwingTable('rs_rating')" style="cursor:pointer" title="Sort by RS Rating">RS RATING <span id="swing_sort_rs_rating">↕</span></th>
            <th onclick="sortSwingTable('swing_badge')" style="cursor:pointer" title="Sort by Badge Title">BADGE <span id="swing_sort_swing_badge">↕</span></th>
            <th onclick="sortSwingTable('ltp')" style="cursor:pointer" title="Sort by LTP Price">LTP <span id="swing_sort_ltp">↕</span></th>
            <th onclick="sortSwingTable('volume_spike')" style="cursor:pointer" title="Sort by Volume Spike">VOL SPIKE <span id="swing_sort_volume_spike">↕</span></th>
            <th onclick="sortSwingTable('rsi')" style="cursor:pointer" title="Sort by RSI">RSI <span id="swing_sort_rsi">↕</span></th>
            <th onclick="sortSwingTable('momentum')" style="cursor:pointer" title="Sort by Momentum">MOMENTUM <span id="swing_sort_momentum">↕</span></th>
            <th onclick="sortSwingTable('cmf')" style="cursor:pointer" title="Sort by Order Flow (CMF)">ORDER FLOW <span id="swing_sort_cmf">↕</span></th>
            <th onclick="sortSwingTable('swing_sl')" style="cursor:pointer" title="Sort by Stop Loss">SL <span id="swing_sort_swing_sl">↕</span></th>
            <th onclick="sortSwingTable('swing_t1')" style="cursor:pointer" title="Sort by Target 1">TARGET 1 (1:2) <span id="swing_sort_swing_t1">↕</span></th>
            <th onclick="sortSwingTable('swing_t2')" style="cursor:pointer" title="Sort by Target 2">TARGET 2 (1:3) <span id="swing_sort_swing_t2">↕</span></th>
            <th onclick="sortSwingTable('swing_reason')" style="cursor:pointer" title="Sort by Reason Title">REASON <span id="swing_sort_swing_reason">↕</span></th>
            <th onclick="sortSwingTable('swing_action')" style="cursor:pointer" title="Sort by Action Signal Title">ACTION <span id="swing_sort_swing_action">↕</span></th>
          </tr>
        </thead>
        <tbody id="swingBody"></tbody>
      </table>
    </div>

    <!-- ══════════════════════════════════════════════════════
         S/R BREAKOUT RADAR SECTION
    ══════════════════════════════════════════════════════════ -->
    <div style="margin-top:32px">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:14px">
        <div>
          <h2 style="font-size:18px;font-weight:800;color:#fff;margin:0">🧱 S/R Breakout Radar</h2>
          <div style="font-size:12px;color:var(--muted);margin-top:3px">Live resistance breakout &amp; retest signals · ChartPrime SR Model</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button id="srPill-all"       class="swing-pill swing-pill-active" onclick="setSrFilter('all')">↺ All Setups</button>
          <button id="srPill-break"     class="swing-pill" onclick="setSrFilter('break')"     style="border-color:#10b981;background:rgba(16,185,129,0.1);color:#34d399">🔥 Break Res</button>
          <button id="srPill-retest"    class="swing-pill" onclick="setSrFilter('retest')"    style="border-color:#a78bfa;background:rgba(167,139,250,0.1);color:#a78bfa">🔄 Retest Buy</button>
          <button id="srPill-approach"  class="swing-pill" onclick="setSrFilter('approach')"  style="border-color:#fbbf24;background:rgba(251,191,36,0.1);color:#fbbf24">⚡ Approaching</button>
        </div>
      </div>

      <!-- Stats Row -->
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:18px">
        <div style="background:var(--card);border:1px solid rgba(16,185,129,0.2);border-radius:12px;padding:12px 14px;text-align:center">
          <div id="srCountBreak"  style="font-size:22px;font-weight:800;color:#10b981">0</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase;margin-top:2px">🔥 Break Res</div>
        </div>
        <div style="background:var(--card);border:1px solid rgba(167,139,250,0.2);border-radius:12px;padding:12px 14px;text-align:center">
          <div id="srCountRetest" style="font-size:22px;font-weight:800;color:#a78bfa">0</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase;margin-top:2px">🔄 Retest Buy</div>
        </div>
        <div style="background:var(--card);border:1px solid rgba(251,191,36,0.2);border-radius:12px;padding:12px 14px;text-align:center">
          <div id="srCountApproach" style="font-size:22px;font-weight:800;color:#fbbf24">0</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase;margin-top:2px">⚡ Approaching</div>
        </div>
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px 14px;text-align:center">
          <div id="srCountAll"  style="font-size:22px;font-weight:800;color:#e2e8f0">0</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase;margin-top:2px">Total Setups</div>
        </div>
      </div>

      <!-- Cards Grid -->
      <div id="srBreakoutGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px"></div>
      <div id="srBreakoutEmpty" style="display:none;text-align:center;padding:40px;color:var(--muted);font-size:14px">No S/R setups detected with current filter.</div>
    </div>

  </div>

  <!-- LT WATCHLIST TAB (Dynamic Status Gate & Capital Accumulator) -->
  <div id="tab-watchlist" style="display:none">

    <!-- 📅 Systematic Daily Capital Accumulator & INDmoney Portfolio Dashboard Card -->
    <div id="ltCapitalDashboard" style="background:linear-gradient(135deg, #0e1726, #162438);border:1.5px solid rgba(52,211,153,0.35);border-radius:14px;padding:14px 22px;margin-bottom:20px;box-shadow:0 8px 30px rgba(0,0,0,0.35)">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:14px">
        <div style="display:flex;align-items:center;gap:12px">
          <div style="background:rgba(52,211,153,0.15);border:1px solid rgba(52,211,153,0.3);width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px">📅</div>
          <div>
            <div style="display:flex;align-items:center;gap:8px">
              <span id="ltDayCounterBadge" style="background:linear-gradient(135deg,#10b981,#059669);color:#fff;font-size:12px;font-weight:800;padding:3px 10px;border-radius:20px;letter-spacing:.05em">DAY 1 ACTIVE</span>
              <span style="font-size:12px;color:var(--muted)">Started Aug 19, 2026</span>
            </div>
            <div style="font-size:16px;font-weight:700;color:#fff;margin-top:3px">LT Segment Daily Capital Accumulator (INDmoney Delivery Engine)</div>
          </div>
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <button onclick="toggleLtHoldingsDrawer()" style="background:rgba(108,99,255,0.15);border:1px solid rgba(108,99,255,0.4);color:#a5b4fc;font-weight:700;font-size:12px;padding:8px 14px;border-radius:8px;cursor:pointer">💼 View Holdings</button>
        </div>
      </div>
    </div>

    <!-- 🔒 This Month's Locked LT Discovery Picks -->
    <div id="ltMonthlyPicksSection"></div>

    <!-- LT Holdings Collapsible Drawer -->
    <div id="ltHoldingsDrawer" style="display:none;background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px;margin-bottom:20px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <div style="font-size:15px;font-weight:700;color:#fff">💼 LT Portfolio Holdings (INDmoney Delivery Engine)</div>
        <button onclick="toggleLtHoldingsDrawer()" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px">✕ Close</button>
      </div>
      <div class="table-wrap">
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <thead>
            <tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--border)">
              <th style="padding:8px">Stock</th>
              <th style="padding:8px">Qty</th>
              <th style="padding:8px">Avg Price</th>
              <th style="padding:8px">Live Price</th>
              <th style="padding:8px">Invested</th>
              <th style="padding:8px">Market Value</th>
              <th style="padding:8px">Unrealized P&L</th>
              <th style="padding:8px">Action</th>
            </tr>
          </thead>
          <tbody id="ltHoldingsTableBody">
            <tr><td colspan="8" style="padding:16px;text-align:center;color:var(--muted)">No active holdings yet. Buy stocks when status is 🟢 BUY NOW!</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- BUY_NOW Live Alert Banner -->
    <div id="ltBuyNowAlert" style="display:none;background:linear-gradient(135deg,rgba(16,185,129,0.18),rgba(5,150,105,0.25));border:1.5px solid #10b981;border-radius:14px;padding:16px 20px;margin-bottom:20px;box-shadow:0 4px 20px rgba(16,185,129,0.25);align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
      <div style="display:flex;align-items:center;gap:12px">
        <span style="font-size:24px;animation:pulse 1.5s infinite">🟢</span>
        <div>
          <div style="font-size:15px;font-weight:800;color:#34d399">GTT Dip-Buy Trigger Reached!</div>
          <div style="font-size:12px;color:#e2e8f0;margin-top:2px" id="ltBuyNowAlertText">Stock(s) confirmed in Uptrend &amp; price reached target GTT level.</div>
        </div>
      </div>
      <button class="btn-add" style="background:#10b981;color:#06060f;font-weight:800;padding:8px 16px;border-radius:8px;border:none;cursor:pointer" onclick="filterLtStatus('BUY_NOW')">
        ⚡ View BUY NOW Signals
      </button>
    </div>

    <!-- Stat Strip (3 Statuses + Total) -->
    <div style="background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px;margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,0.2)">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;text-align:center;align-items:center">
        <div style="cursor:pointer" onclick="filterLtStatus('BUY_NOW')">
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">🟢 BUY NOW</div>
          <div style="font-size:24px;font-weight:800;color:#34d399;margin-top:2px" id="ltCountBuyNow">0</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">Uptrend + Price ≤ GTT</div>
        </div>
        <div style="cursor:pointer" onclick="filterLtStatus('WAIT')">
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">🔵 WAIT</div>
          <div style="font-size:24px;font-weight:800;color:#a5b4fc;margin-top:2px" id="ltCountWait">0</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">Uptrend (Awaiting Dip)</div>
        </div>
        <div style="cursor:pointer" onclick="filterLtStatus('WATCHLIST')">
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">⬜ WATCHING</div>
          <div style="font-size:24px;font-weight:800;color:#94a3b8;margin-top:2px" id="ltCountWatchlist">0</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">Consolidation / Down</div>
        </div>
        <div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">🛡️ Active Watchlist</div>
          <div style="font-size:24px;font-weight:800;color:#fff;margin-top:2px"><span id="ltCountTotal">0</span> Stocks</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">Dynamic Status Gate</div>
        </div>
      </div>
    </div>

    <!-- Toolbar: Filter Pills & Retired Toggle & Add Button -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:12px">
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <span style="font-size:12px;color:var(--muted);font-weight:600;margin-right:4px">Gate Filter:</span>
        <button class="swing-pill swing-pill-active" id="ltPill-ALL" onclick="filterLtStatus('ALL')">↺ All (<span id="ltPillCountALL">0</span>)</button>
        <button class="swing-pill" id="ltPill-BUY_NOW" onclick="filterLtStatus('BUY_NOW')" style="border-color:#10b981;color:#34d399">🟢 BUY NOW (<span id="ltPillCountBUY_NOW">0</span>)</button>
        <button class="swing-pill" id="ltPill-BOUGHT" onclick="filterLtStatus('BOUGHT')" style="border-color:#06b6d4;color:#22d3ee">🟢 BOUGHT (<span id="ltPillCountBOUGHT">0</span>)</button>
        <button class="swing-pill" id="ltPill-WAIT" onclick="filterLtStatus('WAIT')" style="border-color:#6366f1;color:#a5b4fc">🔵 WAIT (<span id="ltPillCountWAIT">0</span>)</button>
        <button class="swing-pill" id="ltPill-WATCHLIST" onclick="filterLtStatus('WATCHLIST')" style="border-color:#64748b;color:#94a3b8">⬜ WATCHING (<span id="ltPillCountWATCHLIST">0</span>)</button>
      </div>

      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);cursor:pointer;user-select:none">
          <input type="checkbox" id="ltShowRetiredToggle" onchange="toggleLtShowRetired(this.checked)" style="cursor:pointer">
          <span>Show Retired Stocks (<span id="ltRetiredCount">0</span>)</span>
        </label>

        <button id="ltAddStockBtn" class="btn-add" style="background:linear-gradient(135deg,#6c63ff,#00d4aa);color:#fff;font-weight:700;padding:7px 16px;border-radius:8px;cursor:pointer;font-size:12px" onclick="window.openAddLtStockModal && window.openAddLtStockModal()">
          ➕ Add Stock
        </button>
      </div>
    </div>

    <!-- Main LT Watchlist Table -->
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th onclick="sortLtTable('durability_score')" style="cursor:pointer" title="Sort by Durability Score">Score ↕</th>
            <th onclick="sortLtTable('symbol')" style="cursor:pointer">Stock ↕</th>
            <th onclick="sortLtTable('type')" style="cursor:pointer">Type ↕</th>
            <th onclick="sortLtTable('sector')" style="cursor:pointer">Sector ↕</th>
            <th onclick="sortLtTable('status')" style="cursor:pointer">Gate Status ↕</th>
            <th onclick="sortLtTable('trend')" style="cursor:pointer">Trend ↕</th>
            <th onclick="sortLtTable('rsi')" style="cursor:pointer">RSI ↕</th>
            <th onclick="sortLtTable('ltp')" style="cursor:pointer">LTP (Price) ↕</th>
            <th onclick="sortLtTable('gtt_level')" style="cursor:pointer">GTT Target ↕</th>
            <th onclick="sortLtTable('dist_from_gtt_pct')" style="cursor:pointer">Distance ↕</th>
            <th>Role</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="ltWatchlistBody"></tbody>
      </table>
    </div>

    <div id="ltEmpty" style="display:none;text-align:center;padding:40px;color:var(--muted);font-size:14px">
      No stocks match the current gate filter.
    </div>
  </div>




  <!-- QUALITY PENNY STOCKS TAB -->
  <div id="tab-penny" style="display:none"></div>

  <!-- INTRADAY BUY/SELL TAB -->
  <div id="tab-intraday" style="display:none"></div>

  <!-- F&O OPTIONS TAB -->
  <div id="tab-fno" style="display:none"></div>

  <!-- MARKET HOLIDAYS TAB -->
  <div id="tab-holidays" style="display:none"></div>

</div>

<!-- Modal -->
<div class="modal-bg" id="modalBg" style="display:none" onclick="if(event.target===this)closeModal()">
  <div class="modal" id="modal"></div>
</div>

<!-- BSE Custom Stock Add Modal -->
<div class="modal-bg" id="bseModalBg" style="display:none" onclick="if(event.target===this)closeBseModal()">
  <div style="background:var(--card);border:1.5px solid var(--accent);border-radius:16px;padding:24px;width:90%;max-width:500px;box-shadow:0 12px 36px rgba(0,0,0,0.5)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h3 style="font-size:18px;font-weight:700;color:var(--white)">➕ Add Custom BSE / NSE Stock</h3>
      <button class="modal-close" onclick="closeBseModal()" style="background:none;border:none;color:var(--muted);font-size:18px;cursor:pointer">✕</button>
    </div>
    <p style="font-size:13px;color:var(--muted);margin-bottom:16px">
      Enter any BSE scrip code (e.g. <code>500112.BO</code>, <code>532650.BO</code>) or NSE ticker (e.g. <code>IZMO.NS</code>, <code>TNPL.NS</code>) to add it directly to your Watchlist.
    </p>
    <div style="display:flex;gap:10px;margin-bottom:16px">
      <input type="text" id="bseSymbolInput" placeholder="e.g. 500112.BO or IZMO.NS" style="flex:1;background:var(--card2);border:1px solid var(--border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:14px;outline:none" onkeydown="if(event.key==='Enter')addCustomBseStock()">
      <button class="btn-add" onclick="addCustomBseStock()" style="padding:10px 18px;font-size:13px">Add Stock</button>
    </div>
  </div>
</div>

<!-- LT Watchlist Add Stock Modal -->
<div class="modal-bg" id="ltAddModalBg" style="display:none;z-index:99999" onclick="if(event.target===this)closeAddLtStockModal()">
  <div style="background:var(--card);border:1.5px solid var(--accent);border-radius:16px;padding:24px;width:90%;max-width:520px;box-shadow:0 12px 36px rgba(0,0,0,0.5)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h3 style="font-size:18px;font-weight:700;color:var(--white)">➕ Add Stock to LT Watchlist</h3>
      <button class="modal-close" onclick="closeAddLtStockModal()" style="background:none;border:none;color:var(--muted);font-size:18px;cursor:pointer">✕</button>
    </div>
    
    <form onsubmit="submitAddLtStockForm(event)">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
        <div>
          <label style="display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px;text-transform:uppercase">Stock Symbol *</label>
          <input type="text" id="ltFormSymbol" placeholder="e.g. BEL, TATAPOWER" required style="width:100%;background:var(--card2);border:1px solid var(--border);color:#fff;padding:9px 12px;border-radius:8px;font-size:13px;outline:none">
        </div>
        <div>
          <label style="display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px;text-transform:uppercase">Ownership Type</label>
          <select id="ltFormType" style="width:100%;background:var(--card2);border:1px solid var(--border);color:#fff;padding:9px 12px;border-radius:8px;font-size:13px;outline:none">
            <option value="Private">Private</option>
            <option value="PSU">PSU</option>
          </select>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
        <div>
          <label style="display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px;text-transform:uppercase">Durability Score (1-100)</label>
          <input type="number" id="ltFormDurability" min="1" max="100" value="75" style="width:100%;background:var(--card2);border:1px solid var(--border);color:#fff;padding:9px 12px;border-radius:8px;font-size:13px;outline:none">
        </div>
        <div>
          <label style="display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px;text-transform:uppercase">Manual GTT Target (₹)</label>
          <input type="number" step="0.05" id="ltFormGtt" placeholder="Auto-trailing if blank" style="width:100%;background:var(--card2);border:1px solid var(--border);color:#fff;padding:9px 12px;border-radius:8px;font-size:13px;outline:none">
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:18px">
        <div>
          <label style="display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px;text-transform:uppercase">Sector</label>
          <input type="text" id="ltFormSector" placeholder="e.g. Defense, Power" style="width:100%;background:var(--card2);border:1px solid var(--border);color:#fff;padding:9px 12px;border-radius:8px;font-size:13px;outline:none">
        </div>
        <div>
          <label style="display:block;font-size:11px;font-weight:700;color:var(--muted);margin-bottom:4px;text-transform:uppercase">Portfolio Role</label>
          <input type="text" id="ltFormRole" placeholder="e.g. Core growth" style="width:100%;background:var(--card2);border:1px solid var(--border);color:#fff;padding:9px 12px;border-radius:8px;font-size:13px;outline:none">
        </div>
      </div>

      <div style="display:flex;justify-content:flex-end;gap:10px">
        <button type="button" onclick="closeAddLtStockModal()" style="background:var(--card2);border:1px solid var(--border);color:var(--text);padding:9px 16px;border-radius:8px;font-size:12px;cursor:pointer">Cancel</button>
        <button type="submit" style="background:linear-gradient(135deg,#10b981,#059669);border:none;color:#fff;font-weight:700;padding:9px 20px;border-radius:8px;font-size:13px;cursor:pointer">Save Stock</button>
      </div>
    </form>
  </div>
</div>

<!-- Swing Trade Calculator Modal -->
<div class="modal-bg" id="swingCalcModalBg" style="display:none" onclick="if(event.target===this)closeSwingCalcModal()">
  <div style="background:var(--card);border:1.5px solid var(--accent);border-radius:16px;padding:24px;width:90%;max-width:520px;box-shadow:0 12px 36px rgba(0,0,0,0.5)">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h3 style="font-size:18px;font-weight:700;color:var(--white)">🧮 Swing Position Calculator</h3>
      <button class="modal-close" onclick="closeSwingCalcModal()" style="background:none;border:none;color:var(--muted);font-size:18px;cursor:pointer">✕</button>
    </div>
    
    <div id="swingCalcHeader" style="margin-bottom:16px;background:var(--card2);padding:12px;border-radius:10px;border:1px solid var(--border)">
    </div>

    <div style="margin-bottom:16px">
      <label style="display:block;font-size:11px;color:var(--muted);margin-bottom:6px;font-weight:600;text-transform:uppercase">ENTER TRADE CAPITAL (₹)</label>
      <div style="display:flex;gap:8px">
        <input type="number" id="swingCapitalInput" value="50000" step="5000" style="flex:1;background:var(--card2);border:1px solid var(--border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:15px;font-weight:700;outline:none" oninput="recalcSwingPosition()">
        <button class="btn-add" onclick="setCapitalPreset(25000)" style="padding:8px 12px;font-size:12px">₹25k</button>
        <button class="btn-add" onclick="setCapitalPreset(50000)" style="padding:8px 12px;font-size:12px">₹50k</button>
        <button class="btn-add" onclick="setCapitalPreset(100000)" style="padding:8px 12px;font-size:12px">₹1L</button>
      </div>
    </div>

    <div id="swingCalcResults" style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px">
    </div>

    <div style="display:flex;gap:10px">
      <button class="btn-add" style="flex:1;padding:10px;font-size:13px;background:var(--card2);border:1px solid var(--border);color:var(--text)" onclick="closeSwingCalcModal()">Close</button>
      <button class="btn-add" id="swingCalcAddWlBtn" style="flex:1;padding:10px;font-size:13px;background:linear-gradient(135deg,#00d4aa,#10b981);color:#06060f;font-weight:700">⭐ Add to Watchlist</button>
    </div>
  </div>
</div>

<!-- Fixed Mobile Bottom Navigation Bar -->
<div class="mobile-nav-bar">
  <button class="mobile-nav-item active" data-tab="screener" onclick="switchTab('screener')">
    <span class="mobile-nav-icon">🔍</span>
    <span>Screener</span>
  </button>
  <button class="mobile-nav-item" data-tab="swing" onclick="switchTab('swing')">
    <span class="mobile-nav-icon">⚡</span>
    <span>Swing</span>
  </button>
  <button class="mobile-nav-item" data-tab="intraday" onclick="switchTab('intraday')">
    <span class="mobile-nav-icon">🎯</span>
    <span>Intraday</span>
  </button>
  <button class="mobile-nav-item" data-tab="watchlist" onclick="switchTab('watchlist')">
    <span class="mobile-nav-icon">🛡️</span>
    <span>LT</span>
  </button>
  <button class="mobile-nav-item" data-tab="penny" onclick="switchTab('penny')">
    <span class="mobile-nav-icon">💎</span>
    <span>Penny</span>
  </button>
  <button class="mobile-nav-item" data-tab="fno" onclick="switchTab('fno')">
    <span class="mobile-nav-icon">📊</span>
    <span>F&amp;O</span>
  </button>
  <button class="mobile-nav-item" data-tab="holidays" onclick="switchTab('holidays')">
    <span class="mobile-nav-icon">📅</span>
    <span>Dates</span>
  </button>
</div>

<script>
// ── DATA (injected by Python) ─────────────────────────────────────────────
let SCREENER_DATA = __SCREENER_JSON__;
let WATCHLIST_SEED = __WATCHLIST_JSON__;
let LT_WATCHLIST = __LT_WATCHLIST_JSON__;
let CONFIG = __CONFIG_JSON__;
let COMMODITIES_DATA = __COMMODITIES_JSON__;
let MARKET_INFO = __MARKET_INFO_JSON__;
let FNO_DATA = __FNO_JSON__;
let PENNY_STOCKS_DATA = __PENNY_STOCKS_JSON__;
let INTRADAY_DATA = __INTRADAY_JSON__;
let LT_MONTHLY_PICKS = __LT_MONTHLY_JSON__;
let LT_PORTFOLIO_SUMMARY = __LT_PORTFOLIO_SUMMARY_JSON__;
let TREND_CONFIG = __TREND_STATES_JSON__;

// Resolve a trend's badge class from the table the Python classifier owns
// (screener_engine.TREND_STATES), so the UI can never label a state the engine
// does not emit -- or miss one it does. Unknown/absent trends fall back to the
// neutral class rather than being styled as something they are not.
function trendBadgeClass(trend) {
  const meta = (TREND_CONFIG.states || {})[trend];
  // Neutral grey for an unknown/absent trend. Falling back to a real state's
  // colour would visually assert a classification the engine never made.
  return (meta && meta.class) || 'badge-gray';
}

// ── State ─────────────────────────────────────────────────────────────────
let watchlist = [];
let sortCol = 'total_score';
let sortDir = -1;
let filteredData = [];
let pollIntervalTimer = null;
let pollIntervalMs = 10000;
let currentPage = 1;
let pageSize = 50;
let lastLtpSuccessTime = null;
let lastLtpError = null;

function calculateCurrentMarketStatus() {
  const now = new Date();
  const istStr = now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' });
  const istDate = new Date(istStr);

  const dayOfWeek = istDate.getDay(); // 0 = Sun, 6 = Sat
  const hours = istDate.getHours();
  const minutes = istDate.getMinutes();
  const isWeekend = (dayOfWeek === 0 || dayOfWeek === 6);
  const tMins = hours * 60 + minutes;
  
  const eqOpenMins = 9 * 60 + 15;   // 09:15 AM
  const eqCloseMins = 15 * 60 + 30; // 03:30 PM
  const mcxOpenMins = 9 * 60;       // 09:00 AM
  const mcxCloseMins = 23 * 60 + 30; // 11:30 PM
  
  if (isWeekend) {
    return {
      status: "WEEKEND",
      badge: "🔴 Market Closed (Weekend)",
      badge_class: "badge-red",
      message: "NSE/BSE & MCX closed for the weekend.",
      is_open: false,
      is_equity_open: false,
      is_pre_market: false
    };
  }
  
  if (tMins < mcxOpenMins) {
    return {
      status: "PRE_MARKET",
      badge: "🔴 Market Closed (Opens 09:00 AM MCX / 09:15 AM Stock)",
      badge_class: "badge-yellow",
      message: "Pre-market session. MCX Commodity scan starts at 09:00 AM IST. Stock of the Day locks at 09:15 AM IST.",
      is_open: false,
      is_equity_open: false,
      is_pre_market: true
    };
  } else if (tMins >= mcxOpenMins && tMins < eqOpenMins) {
    return {
      status: "COMMODITY_LIVE",
      badge: "🟢 MCX Commodity Live (Stock Opens 09:15 AM IST)",
      badge_class: "badge-green",
      message: "MCX Commodity session is LIVE. Equity stock session opens at 09:15 AM IST.",
      is_open: true,
      is_equity_open: false,
      is_pre_market: true
    };
  } else if (tMins >= eqOpenMins && tMins <= eqCloseMins) {
    const timeFormatted = `${hours > 12 ? hours - 12 : (hours === 0 ? 12 : hours)}:${minutes < 10 ? '0' + minutes : minutes} ${hours >= 12 ? 'PM' : 'AM'}`;
    return {
      status: "LIVE_MARKET",
      badge: `🟢 Live Market (${timeFormatted} IST · Active)`,
      badge_class: "badge-green",
      message: `NSE/BSE & MCX Session Active (${timeFormatted} IST). Live prices & returns updating.`,
      is_open: true,
      is_equity_open: true,
      is_pre_market: false
    };
  } else if (tMins > eqCloseMins && tMins <= mcxCloseMins) {
    return {
      status: "COMMODITY_ONLY",
      badge: "🟢 MCX Commodity Session Active (Stock Session Ended)",
      badge_class: "badge-green",
      message: "Equity stock session ended at 03:30 PM. MCX Commodity market active until 11:30 PM IST.",
      is_open: true,
      is_equity_open: false,
      is_pre_market: false
    };
  } else {
    return {
      status: "POST_MARKET",
      badge: "🔴 Market Closed (All Sessions Ended)",
      badge_class: "badge-red",
      message: "All trading sessions closed for today.",
      is_open: false,
      is_equity_open: false,
      is_pre_market: false
    };
  }
}

function renderMarketStatusHeader() {
  const container = document.getElementById('mktStatusPillHeader');
  if (container) {
    const currentMkt = calculateCurrentMarketStatus();
    if (typeof MARKET_INFO !== 'undefined' && MARKET_INFO) {
      MARKET_INFO.is_open = currentMkt.is_open;
      MARKET_INFO.is_equity_open = currentMkt.is_equity_open;
      MARKET_INFO.is_pre_market = currentMkt.is_pre_market;
    }
    container.innerHTML = `<span class="badge ${currentMkt.badge_class || 'badge-green'}" style="font-size:12px;padding:6px 14px;font-weight:700" title="${currentMkt.message}">${currentMkt.badge}</span>`;
    updateLtpBadgeStatus();
  }

  // Populate NIFTY 50 Macro Regime Banner
  if (typeof MARKET_INFO !== 'undefined' && MARKET_INFO && MARKET_INFO.nifty) {
    const n = MARKET_INFO.nifty;
    const bBadge = document.getElementById('niftyRegimeBadge');
    const bLtp = document.getElementById('niftyRegimeLtp');
    const bStance = document.getElementById('niftyRegimeStance');
    const bGuidance = document.getElementById('niftyRegimeGuidance');
    if (bBadge) {
      bBadge.className = 'badge ' + (n.badge_class || 'badge-yellow');
      bBadge.textContent = n.badge || '🟡 NIFTY 50: Neutral';
    }
    if (bLtp && n.ltp) {
      const chgStr = n.change_pct !== undefined ? (n.change_pct >= 0 ? '+' : '') + n.change_pct + '%' : '';
      bLtp.textContent = `₹${n.ltp.toLocaleString('en-IN')} (${chgStr})`;
    }
    if (bStance && n.stance) {
      bStance.textContent = 'Tactical Stance: ' + n.stance;
    }
    if (bGuidance && n.guidance) {
      bGuidance.textContent = n.guidance;
    }
  }
}

function isRealDesktopPC() {
  const isCapacitor = !!(window.Capacitor || (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()));
  const isMobileUA = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent || '');
  const isFileProto = window.location.protocol === 'file:';
  const hasLocalPort = (window.location.port !== '' && window.location.port !== '80' && window.location.port !== '443') || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  return (!isCapacitor && !isMobileUA && (hasLocalPort || isFileProto));
}

async function triggerAppScan() {
  const overlay = document.getElementById('scanProgressOverlay');
  const btnText = document.getElementById('scanProgressText');
  const btnLog = document.getElementById('scanProgressLog');
  const barInner = document.getElementById('scanProgressBarInner');

  if (!isRealDesktopPC()) {
    const confirmed = confirm(
      '⚡ Cloud Auto-Scan Active\n\n' +
      'GitHub Actions automatically runs the full Nifty 500 scan every weekday at 9:15 AM IST before market opens.\n\n' +
      'Tap OK to reload and fetch the latest scan report.'
    );
    if (confirmed) window.location.reload();
    return;
  }

  if (overlay) overlay.style.display = 'flex';
  if (btnText) btnText.textContent = 'Initializing live stock & commodity scan...';
  if (barInner) barInner.style.width = '15%';
  if (btnLog) btnLog.textContent = 'Connecting to local scan engine server...';

  const scanUrl = 'http://localhost:' + (window.location.port || '8080') + '/api/scan';
  const statusUrl = 'http://localhost:' + (window.location.port || '8080') + '/api/scan/status';

  try {
    const res = await fetch(scanUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    if (res.ok) {
      if (barInner) barInner.style.width = '30%';
      if (btnText) btnText.textContent = 'Nifty 500 scan in progress...';
      if (btnLog) btnLog.textContent = 'Scoring technical setups, Mansfield RS, and Commodities...';

      let progressPct = 30;
      const pollTimer = setInterval(async () => {
        try {
          progressPct = Math.min(progressPct + 5, 90);
          if (barInner) barInner.style.width = progressPct + '%';

          const sResp = await fetch(statusUrl);
          if (sResp.ok) {
            const sData = await sResp.json();
            if (!sData.scan_in_progress) {
              clearInterval(pollTimer);
              if (barInner) barInner.style.width = '100%';
              if (btnText) btnText.textContent = 'Scan complete!';
              if (btnLog) btnLog.textContent = 'Reloading latest scan report...';
              setTimeout(() => { window.location.reload(); }, 600);
            }
          }
        } catch (e) {
          // Keep polling if transient network hiccup
        }
      }, 2000);

      // Safety timeout after 120 seconds
      setTimeout(() => {
        clearInterval(pollTimer);
        if (overlay && overlay.style.display !== 'none') {
          overlay.style.display = 'none';
          window.location.reload();
        }
      }, 120000);

    } else {
      throw new Error(`Server returned status ${res.status}`);
    }
  } catch (err) {
    console.warn('Direct scan endpoint failed or offline:', err);
    if (overlay) overlay.style.display = 'none';
    alert('⚡ Python Scan Server is not running.\n\nPlease launch "Run Screener.bat" on your PC to enable 1-click scanning.');
  }
}

// ── Render Commodity Bar ──────────────────────────────────────────────────
function renderCommodityBar() {
  const container = document.getElementById('commodityCards');
  if (!container || typeof COMMODITIES_DATA === 'undefined' || !COMMODITIES_DATA) return;

  let html = '';
  for (const [key, item] of Object.entries(COMMODITIES_DATA)) {
    if (!item) continue;
    const usdPriceStr = item.curr_price ? `${item.unit}${item.curr_price}` : 'N/A';
    const mcxPriceStr = item.mcx_inr_price ? ` · MCX Est: ₹${item.mcx_inr_price.toLocaleString('en-IN')}` : '';
    const emaStr = (item.ema15 && item.ema20) ? `15EMA: ${item.ema15} · 20EMA: ${item.ema20} (${item.diff_pct > 0 ? '+' : ''}${item.diff_pct}%)` : '';

    let badgeStyle = 'background: rgba(255,255,255,0.08); color:#ccc; border: 1px solid rgba(255,255,255,0.1);';
    if (item.signal === 'BUY') {
      badgeStyle = 'background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981;';
    } else if (item.signal === 'SELL') {
      badgeStyle = 'background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444;';
    } else if (item.signal === 'BULLISH_HOLD') {
      badgeStyle = 'background: rgba(99, 102, 241, 0.15); color: #a5b4fc; border: 1px solid #6366f155;';
    } else if (item.signal === 'BEARISH_HOLD') {
      badgeStyle = 'background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid #f59e0b55;';
    }

    html += `
      <div class="commodity-card">
        <span style="font-size:16px">${item.icon || '⛽'}</span>
        <div>
          <div class="commodity-card-name">${item.name} <span class="commodity-card-price">${usdPriceStr}</span><span style="color:#00d4aa;font-size:12px;font-weight:600">${mcxPriceStr}</span></div>
          <div class="commodity-card-emas">${emaStr}</div>
        </div>
        <span class="commodity-badge" style="${badgeStyle}">
          ${item.badge}
        </span>
      </div>
    `;
  }
  container.innerHTML = html;
}

// ── Swing Radar ───────────────────────────────────────────────────────────
let swingPreset = 'all';
let swingSortCol = 'swing_score';
let swingSortDir = -1; // -1 = descending

function getSwingData() {
  return SCREENER_DATA.filter(s => {
    // 1. HARD PRICE FLOOR: LTP >= ₹50.0 (Strictly No Penny Stocks)
    const ltp = parseFloat(s.ltp || s.current_ltp || 0);
    if (ltp < 50.0) return false;

    // 2. QUALITY CAP REQUIREMENT: Must be Large Cap, Mid Cap, or Zerodha MTF Quality Small Cap
    const mcap = parseFloat(s.market_cap || 0);
    const isLargeOrMid = (s.cap_category === 'Large Cap' || s.cap_category === 'Mid Cap' || s.is_large_cap || s.is_mid_cap || mcap >= 50000000000);
    const isMtfQuality = (s.is_mtf === true || s.is_mtf === 'true');
    if (!isLargeOrMid && !isMtfQuality) return false;

    // 3. VALID SETUP & SCORE FLOOR: Must have valid setup, calculated SL, and positive score
    const swingScore = parseFloat(s.swing_score || 0);
    const totalScore = parseFloat(s.total_score || 0);
    if (swingScore < 40 && totalScore < 45) return false;
    if (!s.swing_sl || parseFloat(s.swing_sl) <= 0) return false;

    return true;
  });
}

function applySwingPreset(data) {
  switch (swingPreset) {
    case 'rs':
      return data.filter(s => (s.rs_rating || 0) >= 80 && (s.setup_score >= 65 || s.swing_score >= 65));
    case 'blast':
      return data.filter(s => s.is_blast || (s.volume_spike >= 1.8 && (s.setup_score >= 70 || s.swing_score >= 70)));
    case 'inflow':
      return data.filter(s => s.is_order_flow_bull || (s.cmf >= 0.08 && s.clv >= 0.55 && (s.setup_score >= 65 || s.swing_score >= 65)));
    case 'momentum':
      return data.filter(s => s.is_momentum_surge || (s.momentum >= 70 && (s.setup_score >= 70 || s.swing_score >= 70)));
    case 'pullback':
      return data.filter(s => s.is_pullback || (s.entry_score >= 60 && s.setup_score >= 60));
    case 'quality':
      return data.filter(s => s.setup_score >= 70 && s.entry_score >= 50);
    default:
      return data;
  }
}

function setSwingPreset(preset) {
  swingPreset = preset;
  document.querySelectorAll('.swing-pill').forEach(p => p.classList.remove('swing-pill-active'));
  const pill = document.getElementById('swingPill-' + preset);
  if (pill) pill.classList.add('swing-pill-active');
  renderSwingRadar();
}

function sortSwingTable(col) {
  if (swingSortCol === col) { swingSortDir *= -1; }
  else { swingSortCol = col; swingSortDir = -1; }
  renderSwingRadar();
}

function getSwingCardClass(s) {
  if (s.swing_action === "EXTENDED — DON'T CHASE") return 'swing-card-extended';
  if (s.is_blast) return 'swing-card-blast';
  if (s.is_order_flow_bull) return 'swing-card-inflow';
  if (s.is_momentum_surge) return 'swing-card-momentum';
  if (s.is_pullback) return 'swing-card-pullback';
  return '';
}

function getSwingRingColor(s) {
  if (s.swing_action === "EXTENDED — DON'T CHASE") return '#f97316';
  if (s.swing_action === "BUY NOW") return '#10b981';
  if (s.swing_action === "BUY ON RETEST") return '#3b82f6';
  if (s.is_blast) return '#10b981';
  if (s.is_order_flow_bull) return '#6366f1';
  if (s.is_momentum_surge) return '#f59e0b';
  if (s.is_pullback) return '#3b82f6';
  return '#6c63ff';
}

function renderSwingRadar() {
  const allMtf = getSwingData();
  let filtered = applySwingPreset(allMtf);

  // Filter stocks by Title / Symbol / Badge / Reason search box
  const q = (document.getElementById('swingTitleFilter')?.value || '').trim().toLowerCase();
  if (q) {
    filtered = filtered.filter(s => 
      (s.symbol && s.symbol.toLowerCase().includes(q)) ||
      (s.name && s.name.toLowerCase().includes(q)) ||
      (s.swing_badge && s.swing_badge.toLowerCase().includes(q)) ||
      (s.swing_reason && s.swing_reason.toLowerCase().includes(q)) ||
      (s.swing_action && s.swing_action.toLowerCase().includes(q)) ||
      (s.cap_category && s.cap_category.toLowerCase().includes(q))
    );
  }

  // Multi-column sorting (handles both numbers & string titles)
  const sorted = [...filtered].sort((a, b) => {
    let av = a[swingSortCol];
    let bv = b[swingSortCol];

    if (swingSortCol === 'index') {
      av = allMtf.indexOf(a);
      bv = allMtf.indexOf(b);
    } else if (swingSortCol === 'cmf') {
      av = a.cmf ?? (a.is_order_flow_bull ? 1 : 0);
      bv = b.cmf ?? (b.is_order_flow_bull ? 1 : 0);
    }

    if (av === undefined || av === null) av = (typeof bv === 'string' ? '' : -999999);
    if (bv === undefined || bv === null) bv = (typeof av === 'string' ? '' : -999999);

    if (typeof av === 'string' || typeof bv === 'string') {
      return swingSortDir * String(av).localeCompare(String(bv));
    }
    return swingSortDir * (av - bv);
  });

  // Update header column sort indicators (↑ / ↓ / ↕)
  const swingCols = ['index','symbol','swing_score','rs_rating','swing_badge','ltp','volume_spike','rsi','momentum','cmf','swing_sl','swing_t1','swing_t2','swing_reason','swing_action'];
  swingCols.forEach(col => {
    const el = document.getElementById('swing_sort_' + col);
    if (el) {
      if (swingSortCol === col) {
        el.textContent = swingSortDir === -1 ? '↓' : '↑';
        el.style.color = 'var(--accent)';
      } else {
        el.textContent = '↕';
        el.style.color = 'var(--muted)';
      }
    }
  });

  // Update banner counts
  const mtfEl = document.getElementById('swingMtfCount');
  const rsEl = document.getElementById('swingRsCount');
  const blastEl = document.getElementById('swingBlastCount');
  const inflowEl = document.getElementById('swingInflowCount');
  if (mtfEl) mtfEl.textContent = allMtf.length;
  if (rsEl) rsEl.textContent = allMtf.filter(s => (s.rs_rating || 0) >= 80).length;
  if (blastEl) blastEl.textContent = allMtf.filter(s => s.is_blast).length;
  if (inflowEl) inflowEl.textContent = allMtf.filter(s => s.is_order_flow_bull).length;

  // Result count
  const rcEl = document.getElementById('swingResultCount');
  if (rcEl) {
    const filterNotice = q ? ` (filtered by "${q}")` : '';
    rcEl.textContent = `Showing ${sorted.length} swing stocks matching current preset${filterNotice}`;
  }

  // Top 10 Spotlight Cards (Always top 10 highest swing_score stocks overall, strictly sorted #1 to #10)
  const spotlight = document.getElementById('swingSpotlight');
  if (spotlight) {
    const top10 = [...allMtf].sort((a, b) => 
      (b.swing_score || 0) - (a.swing_score || 0) || 
      (b.total_score || 0) - (a.total_score || 0) || 
      (b.rs_rating || 0) - (a.rs_rating || 0) || 
      (a.symbol || '').localeCompare(b.symbol || '')
    ).slice(0, 10);
    if (top10.length === 0) {
      spotlight.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:20px">No stocks match this filter.</div>';
    } else {
      spotlight.innerHTML = top10.map((s, i) => {
        const score = s.swing_score || 0;
        const ringColor = getSwingRingColor(s);
        const cardClass = getSwingCardClass(s);
        const volStr = s.volume_spike ? `${s.volume_spike.toFixed(1)}x` : 'N/A';
        const rsiStr = s.rsi ? s.rsi.toFixed(0) : 'N/A';
        const rsVal = s.rs_rating || 50;
        const rsColor = rsVal >= 80 ? '#10b981' : rsVal >= 60 ? '#60a5fa' : rsVal >= 40 ? '#94a3b8' : '#ef4444';
        const slStr = s.swing_sl ? `₹${s.swing_sl.toFixed(1)}` : 'N/A';
        const t1Str = s.swing_t1 ? `₹${s.swing_t1.toFixed(1)}` : 'N/A';
        const t2Str = s.swing_t2 ? `₹${s.swing_t2.toFixed(1)}` : 'N/A';
        const slPct = s.swing_sl_pct ? `${s.swing_sl_pct}%` : '';
        const t1Pct = s.swing_t1_pct ? `+${s.swing_t1_pct}%` : '';
        return `
        <div class="swing-card ${cardClass}" onclick="document.getElementById('fSearch').value='${s.symbol}';switchTab('screener');applyFilters()">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px">
            <div>
              <div style="font-size:15px;font-weight:700;color:#fff">${i+1}. ${s.symbol}</div>
              <div style="font-size:11px;color:var(--muted);margin-top:1px">${(s.name||'').substring(0,28)}</div>
            </div>
            <div style="text-align:center">
              <div style="width:46px;height:46px;border-radius:50%;background:conic-gradient(${ringColor} ${score}%,rgba(255,255,255,0.06) 0);display:flex;align-items:center;justify-content:center">
                <div style="width:34px;height:34px;border-radius:50%;background:var(--card);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff">${score}</div>
              </div>
            </div>
          </div>
          <div style="font-size:11px;margin-bottom:8px;display:flex;gap:6px;align-items:center">
            <span style="background:rgba(108,99,255,0.15);color:#a5b4fc;border:1px solid #6c63ff33;border-radius:10px;padding:3px 9px;font-weight:600">${s.swing_badge||'–'}</span>
            <span class="badge ${rsVal>=80?'badge-green':rsVal>=60?'badge-green':rsVal>=40?'badge-gray':'badge-red'}" style="font-size:10px;font-weight:700">RS ${rsVal}</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:5px;font-size:11px;margin-bottom:10px">
            <div style="background:var(--card2);border-radius:6px;padding:5px;text-align:center">
              <div style="color:var(--muted);font-size:10px;display:flex;align-items:center;justify-content:center;gap:3px">LTP <span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:#10b981;box-shadow:0 0 4px #10b981"></span></div>
              <div style="font-weight:700;color:#fff;font-size:12px">₹${(s.ltp||0).toFixed(2)}</div>
              ${s.day_chg_pct !== undefined ? `<div style="font-size:9px;font-weight:700;color:${s.day_chg_pct>=0?'#34d399':'#f87171'}">${s.day_chg_pct>=0?'+':''}${s.day_chg_pct.toFixed(2)}%</div>` : ''}
            </div>
            <div style="background:var(--card2);border-radius:6px;padding:5px;text-align:center">
              <div style="color:var(--muted);font-size:10px">RS</div>
              <div style="font-weight:700;color:${rsColor}">${rsVal}</div>
            </div>
            <div style="background:var(--card2);border-radius:6px;padding:5px;text-align:center">
              <div style="color:var(--muted);font-size:10px">Vol</div>
              <div style="font-weight:700;color:${parseFloat(volStr)>=2?'#10b981':'#e2e8f0'}">${volStr}</div>
            </div>
            <div style="background:var(--card2);border-radius:6px;padding:5px;text-align:center">
              <div style="color:var(--muted);font-size:10px">RSI</div>
              <div style="font-weight:700;color:#e2e8f0">${rsiStr}</div>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;font-size:11px">
            <div style="text-align:center">
              <div style="color:#ef4444;font-size:10px">SL</div>
              <div class="swing-sl">${slStr}<span style="font-size:9px;color:var(--muted)"> ${slPct}</span></div>
            </div>
            <div style="text-align:center">
              <div style="color:#10b981;font-size:10px">T1 (1:1.5)</div>
              <div class="swing-t1">${t1Str}<span style="font-size:9px;color:var(--muted)"> ${t1Pct}</span></div>
            </div>
            <div style="text-align:center">
              <div style="color:#00d4aa;font-size:10px">T2 (1:2.5)</div>
              <div class="swing-t2">${t2Str}</div>
            </div>
          </div>
          <div style="display:flex;gap:6px;margin-top:8px;border-top:1px solid var(--border);padding-top:6px;align-items:center;justify-content:space-between">
            <div style="font-size:10px;color:var(--muted)">${s.swing_reason||''}</div>
            <div style="display:flex;gap:4px">
              <button class="btn-add" onclick="event.stopPropagation();openSwingCalcModal('${s.symbol}')" style="padding:3px 8px;font-size:10px;background:var(--card2)">🧮 Calc</button>
              <button class="btn-add" onclick="event.stopPropagation();addToWatchlist('${s.symbol}')" style="padding:3px 8px;font-size:10px;background:linear-gradient(135deg,#00d4aa,#10b981);color:#06060f;font-weight:700">⭐ +WL</button>
            </div>
          </div>
        </div>`;
      }).join('');
    }
  }

  // Full table
  const tbody = document.getElementById('swingBody');
  if (!tbody) return;
  if (sorted.length === 0) {
    tbody.innerHTML = '<tr><td colspan="15" style="text-align:center;padding:40px;color:var(--muted)">No stocks match this filter.</td></tr>';
    return;
  }
  tbody.innerHTML = sorted.map((s, i) => {
    const volStr = s.volume_spike ? `${s.volume_spike.toFixed(1)}x` : '–';
    const rsiStr = s.rsi ? s.rsi.toFixed(0) : '–';
    const rsVal = s.rs_rating || 50;
    const cmfStr = s.cmf !== undefined ? (s.cmf >= 0 ? '+' : '') + s.cmf.toFixed(2) : '–';
    const cmfColor = (s.cmf||0) >= 0.05 ? '#10b981' : (s.cmf||0) <= -0.05 ? '#ef4444' : '#94a3b8';
    const volColor = (s.volume_spike||0) >= 2.0 ? '#10b981' : (s.volume_spike||0) >= 1.5 ? '#fbbf24' : '#94a3b8';
    return `<tr>
      <td>${i+1}</td>
      <td><strong style="color:#e2e8f0">${s.symbol}</strong><br><span style="font-size:10px;color:var(--muted)">${(s.cap_category||'')}</span></td>
      <td><span style="font-weight:700;color:#a78bfa;font-size:15px">${s.swing_score||0}</span></td>
      <td><span class="badge ${rsVal>=80?'badge-green':rsVal>=60?'badge-green':rsVal>=40?'badge-gray':'badge-red'}" style="font-size:11px;font-weight:700">RS ${rsVal}</span></td>
      <td><span style="font-size:11px;background:rgba(108,99,255,0.12);border:1px solid rgba(108,99,255,0.3);border-radius:10px;padding:3px 8px;white-space:nowrap">${s.swing_badge||'–'}</span></td>
      <td>₹${(s.ltp||0).toFixed(2)}</td>
      <td style="color:${volColor};font-weight:600">${volStr}</td>
      <td>${rsiStr}</td>
      <td>${(s.momentum||0).toFixed(0)}</td>
      <td style="color:${cmfColor};font-weight:600">${cmfStr}<br><span style="font-size:10px;color:var(--muted)">${s.pa_badge||''}</span></td>
      <td class="swing-sl">${s.swing_sl ? '₹' + s.swing_sl.toFixed(1) : '–'}<br><span style="font-size:10px;color:#ef4444">${s.swing_sl_pct||0}%</span></td>
      <td class="swing-t1">${s.swing_t1 ? '₹' + s.swing_t1.toFixed(1) : '–'}<br><span style="font-size:10px;color:#10b981">+${s.swing_t1_pct||0}%</span></td>
      <td class="swing-t2">${s.swing_t2 ? '₹' + s.swing_t2.toFixed(1) : '–'}<br><span style="font-size:10px;color:#00d4aa">+${s.swing_t2_pct||0}%</span></td>
      <td style="font-size:11px;color:var(--muted);max-width:180px;white-space:normal">${s.swing_reason||'–'}</td>
      <td>
        <div style="display:flex;gap:4px">
          <button class="btn-add" onclick="openSwingCalcModal('${s.symbol}')" style="padding:3px 6px;font-size:10px;background:var(--card2)" title="Calculate Position Size">🧮</button>
          <button class="btn-add" onclick="addToWatchlist('${s.symbol}')" style="padding:3px 6px;font-size:10px" title="Add to Watchlist">⭐</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

// ─── S/R Breakout Radar ────────────────────────────────────────────────────

let srFilter = 'all';

function setSrFilter(f) {
  srFilter = f;
  document.querySelectorAll('[id^="srPill-"]').forEach(el => el.classList.remove('swing-pill-active'));
  const pill = document.getElementById('srPill-' + f);
  if (pill) pill.classList.add('swing-pill-active');
  renderSrBreakouts();
}

function renderSrBreakouts() {
  const all = SCREENER_DATA.filter(s => s.has_sr_setup && s.sr_type && s.sr_type !== 'NONE');

  // Count by type
  const breakCount    = all.filter(s => s.sr_type === 'BREAK_RES').length;
  const retestCount   = all.filter(s => s.sr_type === 'RETEST_BUY').length;
  const approachCount = all.filter(s => s.sr_type === 'APPROACHING_RES').length;
  const el = id => document.getElementById(id);
  if (el('srCountBreak'))   el('srCountBreak').textContent   = breakCount;
  if (el('srCountRetest'))  el('srCountRetest').textContent  = retestCount;
  if (el('srCountApproach'))el('srCountApproach').textContent = approachCount;
  if (el('srCountAll'))     el('srCountAll').textContent     = all.length;

  // Apply filter
  let filtered = all;
  if (srFilter === 'break')   filtered = all.filter(s => s.sr_type === 'BREAK_RES');
  if (srFilter === 'retest')  filtered = all.filter(s => s.sr_type === 'RETEST_BUY');
  if (srFilter === 'approach')filtered = all.filter(s => s.sr_type === 'APPROACHING_RES');

  // Sort by sr_score descending
  filtered = filtered.sort((a, b) => (b.sr_score || 0) - (a.sr_score || 0));

  const grid  = el('srBreakoutGrid');
  const empty = el('srBreakoutEmpty');
  if (!grid) return;

  if (filtered.length === 0) {
    grid.innerHTML = '';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  grid.innerHTML = filtered.map(s => {
    const typeColor  = s.sr_type === 'BREAK_RES' ? '#10b981' : s.sr_type === 'RETEST_BUY' ? '#a78bfa' : '#fbbf24';
    const typeBorder = s.sr_type === 'BREAK_RES' ? 'rgba(16,185,129,0.25)' : s.sr_type === 'RETEST_BUY' ? 'rgba(167,139,250,0.25)' : 'rgba(251,191,36,0.25)';
    const scoreBar   = s.sr_score || 0;
    const scoreFill  = scoreBar >= 80 ? '#10b981' : scoreBar >= 60 ? '#60a5fa' : scoreBar >= 40 ? '#fbbf24' : '#ef4444';
    const rsVal      = s.rs_rating || 50;
    const rsColor    = rsVal >= 80 ? '#10b981' : rsVal >= 60 ? '#60a5fa' : '#94a3b8';
    const distStr    = s.dist_from_res_pct != null ? (s.dist_from_res_pct >= 0 ? '+' : '') + s.dist_from_res_pct.toFixed(1) + '%' : '–';
    const slStr      = s.sr_sl    ? '₹' + s.sr_sl.toFixed(1) + (s.sr_sl_pct   ? ' (' + s.sr_sl_pct  + '%)' : '') : '–';
    const t1Str      = s.sr_t1    ? '₹' + s.sr_t1.toFixed(1) + (s.sr_t1_pct   ? ' (+' + s.sr_t1_pct + '%)' : '') : '–';
    const t2Str      = s.sr_t2    ? '₹' + s.sr_t2.toFixed(1) + (s.sr_t2_pct   ? ' (+' + s.sr_t2_pct + '%)' : '') : '–';
    const resStr     = s.res_level ? '₹' + s.res_level.toFixed(2) : '–';
    const supStr     = s.sup_level ? '₹' + s.sup_level.toFixed(2) : '–';

    return `
    <div style="background:var(--card);border:1px solid ${typeBorder};border-radius:14px;padding:16px;position:relative;overflow:hidden;cursor:pointer;transition:transform .15s,box-shadow .15s"
         onclick="document.getElementById('fSearch').value='${s.symbol}';switchTab('screener');applyFilters()"
         onmouseenter="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 28px rgba(0,0,0,0.35)'"
         onmouseleave="this.style.transform='';this.style.boxShadow=''">
      <!-- Accent bar -->
      <div style="position:absolute;top:0;left:0;right:0;height:3px;background:${typeColor};border-radius:14px 14px 0 0"></div>

      <!-- Header row -->
      <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px;margin-top:4px">
        <div>
          <div style="font-size:15px;font-weight:800;color:#fff">${s.symbol}</div>
          <div style="font-size:10px;color:var(--muted);margin-top:1px">${(s.name||'').substring(0,26)} · ${s.cap_category||''}</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:11px;font-weight:700;color:${typeColor};background:rgba(0,0,0,0.25);border:1px solid ${typeBorder};border-radius:8px;padding:3px 8px;white-space:nowrap">${s.sr_badge||'–'}</div>
          <div style="font-size:10px;color:var(--muted);margin-top:3px">₹${(s.ltp||0).toFixed(2)}</div>
        </div>
      </div>

      <!-- SR Score bar -->
      <div style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin-bottom:3px">
          <span>SR Score</span><span style="color:${scoreFill};font-weight:700">${scoreBar}</span>
        </div>
        <div style="background:rgba(255,255,255,0.07);border-radius:4px;height:5px;overflow:hidden">
          <div style="height:100%;width:${scoreBar}%;background:${scoreFill};border-radius:4px;transition:width .4s"></div>
        </div>
      </div>

      <!-- Key levels grid -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;margin-bottom:10px">
        <div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:6px 8px">
          <div style="color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.05em">Resistance</div>
          <div style="color:#e2e8f0;font-weight:700;margin-top:1px">${resStr} <span style="color:${s.dist_from_res_pct!=null&&s.dist_from_res_pct>=0?'#10b981':'#fbbf24'};font-size:10px">${distStr}</span></div>
        </div>
        <div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:6px 8px">
          <div style="color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.05em">Support</div>
          <div style="color:#e2e8f0;font-weight:700;margin-top:1px">${supStr}</div>
        </div>
        <div style="background:rgba(239,68,68,0.07);border-radius:8px;padding:6px 8px">
          <div style="color:#fca5a5;font-size:9px;text-transform:uppercase;letter-spacing:.05em">Stop Loss</div>
          <div style="color:#ef4444;font-weight:700;margin-top:1px">${slStr}</div>
        </div>
        <div style="background:rgba(16,185,129,0.07);border-radius:8px;padding:6px 8px">
          <div style="color:#6ee7b7;font-size:9px;text-transform:uppercase;letter-spacing:.05em">Target 1 (1:2)</div>
          <div style="color:#10b981;font-weight:700;margin-top:1px">${t1Str}</div>
        </div>
      </div>
      <div style="background:rgba(16,185,129,0.05);border:1px dashed rgba(16,185,129,0.2);border-radius:8px;padding:5px 8px;font-size:10px;color:var(--muted);margin-bottom:10px">
        🎯 Target 2 (1:3): <span style="color:#34d399;font-weight:700">${t2Str}</span>
      </div>

      <!-- Footer: RS + RSI + Reason -->
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">
        <span style="font-size:11px;font-weight:700;color:${rsColor}">RS ${rsVal}</span>
        <span style="font-size:10px;color:var(--muted)">RSI ${s.rsi ? s.rsi.toFixed(0) : '–'}</span>
        <button onclick="event.stopPropagation();addToWatchlist('${s.symbol}')" style="font-size:10px;padding:2px 8px;border-radius:6px;border:1px solid rgba(108,99,255,0.4);background:rgba(108,99,255,0.1);color:#a5b4fc;cursor:pointer">⭐ Watch</button>
      </div>
      <div style="font-size:10px;color:var(--muted);margin-top:7px;line-height:1.4">${s.sr_reason||''}</div>
    </div>`;
  }).join('');
}



let currentCalcStock = null;

function openSwingCalcModal(symbol) {
  const stock = SCREENER_DATA.find(s => s.symbol === symbol);
  if (!stock || !stock.ltp) {
    alert('Invalid stock price for calculation');
    return;
  }
  currentCalcStock = stock;
  const header = document.getElementById('swingCalcHeader');
  if (header) {
    header.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div style="font-size:16px;font-weight:700;color:var(--white)">${stock.symbol}</div>
          <div style="font-size:11px;color:var(--muted)">${stock.name || ''}</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:16px;font-weight:700;color:var(--accent2)">₹${stock.ltp.toFixed(2)}</div>
          <div style="font-size:11px;color:var(--muted)">LTP</div>
        </div>
      </div>
    `;
  }
  const addBtn = document.getElementById('swingCalcAddWlBtn');
  if (addBtn) {
    addBtn.onclick = function() {
      addToWatchlist(stock.symbol);
      closeSwingCalcModal();
    };
  }
  recalcSwingPosition();
  const modal = document.getElementById('swingCalcModalBg');
  if (modal) modal.style.display = 'flex';
}

function closeSwingCalcModal() {
  const modal = document.getElementById('swingCalcModalBg');
  if (modal) modal.style.display = 'none';
}

function setCapitalPreset(amt) {
  const inp = document.getElementById('swingCapitalInput');
  if (inp) {
    inp.value = amt;
    recalcSwingPosition();
  }
}

function recalcSwingPosition() {
  if (!currentCalcStock) return;
  const capital = parseFloat(document.getElementById('swingCapitalInput')?.value || 0);
  const ltp = currentCalcStock.ltp;
  if (!ltp || ltp <= 0) return;

  const qty = Math.floor(capital / ltp);
  const totalCost = qty * ltp;
  const minRequired = Math.ceil(ltp);
  
  const slPrice = currentCalcStock.swing_sl || (ltp * 0.96);
  const t1Price = currentCalcStock.swing_t1 || (ltp * 1.08);
  const t2Price = currentCalcStock.swing_t2 || (ltp * 1.15);

  const maxRiskAmt = Math.abs(ltp - slPrice) * qty;
  const maxRiskPct = ((Math.abs(ltp - slPrice) / ltp) * 100).toFixed(1);
  const profitT1 = (t1Price - ltp) * qty;
  const profitT2 = (t2Price - ltp) * qty;

  const resEl = document.getElementById('swingCalcResults');
  if (resEl) {
    if (qty <= 0) {
      resEl.innerHTML = `
        <div style="grid-column: 1 / -1; background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); border-radius:10px; padding:14px; color:var(--text); text-align:center">
          <div style="font-weight:700; color:#ef4444; font-size:13px; margin-bottom:4px">⚠️ Insufficient Capital to Buy 1 Share</div>
          <div style="font-size:12px">Your entered capital (₹${capital.toLocaleString('en-IN')}) is less than the price of 1 share (₹${minRequired.toLocaleString('en-IN')}).</div>
          <div style="font-size:11px; color:var(--muted); margin-top:6px">Minimum Capital Required: <strong>₹${minRequired.toLocaleString('en-IN')}</strong></div>
        </div>
      `;
    } else {
      resEl.innerHTML = `
        <div style="background:var(--card2);padding:10px;border-radius:8px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Shares to Buy</div>
          <div style="font-size:18px;font-weight:700;color:var(--white)">${qty} ${qty === 1 ? 'Share' : 'Shares'}</div>
          <div style="font-size:10px;color:var(--muted)">Est. Outlay: ₹${Math.round(totalCost).toLocaleString('en-IN')}</div>
        </div>
        <div style="background:var(--card2);padding:10px;border-radius:8px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Max Risk (SL)</div>
          <div style="font-size:18px;font-weight:700;color:#ef4444">-₹${Math.round(maxRiskAmt).toLocaleString('en-IN')}</div>
          <div style="font-size:10px;color:var(--muted)">SL @ ₹${slPrice.toFixed(1)} (-${maxRiskPct}%)</div>
        </div>
        <div style="background:var(--card2);padding:10px;border-radius:8px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Target 1 Profit (+8%)</div>
          <div style="font-size:18px;font-weight:700;color:#10b981">+₹${Math.round(profitT1).toLocaleString('en-IN')}</div>
          <div style="font-size:10px;color:var(--muted)">Target: ₹${t1Price.toFixed(1)}</div>
        </div>
        <div style="background:var(--card2);padding:10px;border-radius:8px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Target 2 Profit (+15%)</div>
          <div style="font-size:18px;font-weight:700;color:#00d4aa">+₹${Math.round(profitT2).toLocaleString('en-IN')}</div>
          <div style="font-size:10px;color:var(--muted)">Target: ₹${t2Price.toFixed(1)}</div>
        </div>
      `;
    }
  }
}

function updateWatchlistSignalsAndAlerts(item, live) {
  if (!live) return;
  item.ltp = live.ltp;
  item.current_score = live.total_score;
  item.current_strength = live.strength;
  item.current_value = live.value;
  item.current_momentum = live.momentum;
  item.roe_pct = live.roe_pct;
  item.de_ratio = live.de_ratio;
  item.npm_pct = live.npm_pct;
  item.rsi = live.rsi;
  item.wk52_return_pct = live.wk52_return_pct;
  item.news = live.news || [];

  let sig = "HOLD", sigBadge = "🟡 HOLD", sigReason = "Moderate quality score; maintain position";
  if (live.total_score >= 55 && live.strength >= 50) {
    sig = "BUY";
    sigBadge = "🟢 BUY";
    sigReason = `Strong quality score (${live.total_score.toFixed(1)}) & solid fundamentals`;
  } else if (live.total_score < 40) {
    sig = "SELL";
    sigBadge = "🔴 SELL";
    sigReason = `Quality score collapsed to ${live.total_score.toFixed(1)} (<40)`;
  }
  item.signal = sig;
  item.signal_badge = sigBadge;
  item.signal_reason = sigReason;
}

function populatePortfolioSeed() {
  watchlist = JSON.parse(JSON.stringify(WATCHLIST_SEED));
  watchlist.forEach(item => {
    const live = SCREENER_DATA.find(s => s.symbol === item.symbol);
    updateWatchlistSignalsAndAlerts(item, live);
  });
  saveWatchlist();
  renderWatchlist();
  updateWlCount();
  renderStats();
  alert("Successfully populated your 9 portfolio equity holdings!");
}

function clearAllWatchlist() {
  if (!confirm("Are you sure you want to clear all watchlist stocks?")) return;
  watchlist = [];
  localStorage.removeItem('quality_watchlist_v1');
  localStorage.removeItem('quality_watchlist_v2');
  localStorage.removeItem('quality_watchlist_v3');
  localStorage.removeItem('quality_watchlist_v4');
  localStorage.removeItem('quality_watchlist_v5');
  localStorage.removeItem('quality_watchlist_v6');
  localStorage.removeItem('quality_watchlist_v7');
  saveWatchlist();
  renderWatchlist();
  updateWlCount();
  renderStats();
  alert("Watchlist cleared successfully!");
}

// ── LT Watchlist — Dynamic Status Gate ────────────────────────────────────
let ltWatchlist = (typeof LT_WATCHLIST !== 'undefined' && Array.isArray(LT_WATCHLIST)) ? LT_WATCHLIST : [];
let ltFilterStatus = 'ALL';
let ltShowRetired = false;
let ltSortCol = 'durability_score';
let ltSortDir = -1;

function calculateClientStatus(item) {
  // BOUGHT always takes priority — user has an active position
  if (item.holding && (item.holding.qty > 0 || parseInt(item.holding.qty, 10) > 0)) {
    const qty = parseInt(item.holding.qty, 10) || 1;
    const avgPrice = parseFloat(item.holding.avg_price) || item.ltp || 0;
    const buyDate = item.holding.buy_date || '';
    const pnl = item.holding.unrealized_pnl || 0;
    const pnlPct = item.holding.unrealized_pnl_pct || 0;
    const pnlStr = pnl !== 0 ? `P&L: ${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(2)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}%)` : '';
    item.status = "BOUGHT";
    item.status_badge = `🟢 BOUGHT (${qty})`;
    item.status_badge_class = "badge-green";
    item.status_reason = `Purchased${buyDate ? ' on ' + buyDate : ''}: ${qty} share(s) @ ₹${avgPrice.toFixed(2)} · Cooling off / Holding active ${pnlStr}`.trim();
    return;
  }
  // Status priority: BUY_NOW > WAIT > WATCHLIST. Client can only UPGRADE, never downgrade.
  const statusRank = { 'BUY_NOW': 3, 'WAIT': 2, 'WATCHLIST': 1 };
  const serverStatus = item.status || 'WATCHLIST';
  const serverRank = statusRank[serverStatus] || 0;

  const uptrendStates = TREND_CONFIG.uptrend;
  const trend = item.trend || "Consolidation";
  const rsi = item.rsi || 50;
  const ltp = item.ltp || 0;
  const isAuto = (item.gtt_mode === 'auto' || item.gtt_mode == null || item.is_auto_gtt);
  const gtt = isAuto ? (item.auto_gtt || item.gtt_level) : item.gtt_level;
  const dayChg = item.day_chg_pct || 0;

  if (uptrendStates.includes(trend)) {
    if (gtt !== null && gtt !== undefined && gtt !== "" && ltp > 0 && ltp <= (gtt * 1.008) && rsi < 70) {
      if (dayChg >= -0.35 || (rsi > 42 && rsi < 70)) {
        if (statusRank['BUY_NOW'] > serverRank) {
          item.status = "BUY_NOW";
          item.status_badge = "🟢 BUY NOW";
          item.status_badge_class = "badge-green";
          item.status_reason = `A/E Breakout: Price ₹${ltp.toFixed(2)} at Support GTT ₹${parseFloat(gtt).toFixed(2)}`;
        }
        return;
      }
    }
    if (statusRank['WAIT'] > serverRank) {
      item.status = "WAIT";
      item.status_badge = "🔵 WAIT";
      item.status_badge_class = "badge-purple";
      item.status_reason = `Trend confirmed (${trend}) — waiting for pullback to GTT` + (gtt ? ` ₹${parseFloat(gtt).toFixed(2)}` : '');
    }
    return;
  }
  // Not in uptrend — keep server status unchanged (never downgrade to WATCHLIST)
}


function filterLtStatus(status) {
  ltFilterStatus = status;
  document.querySelectorAll('[id^="ltPill-"]').forEach(el => el.classList.remove('swing-pill-active'));
  const pill = document.getElementById('ltPill-' + status);
  if (pill) pill.classList.add('swing-pill-active');
  renderLtWatchlist();
}

function toggleLtShowRetired(checked) {
  ltShowRetired = checked;
  renderLtWatchlist();
}

function sortLtTable(col) {
  if (ltSortCol === col) {
    ltSortDir *= -1;
  } else {
    ltSortCol = col;
    ltSortDir = -1;
  }
  renderLtWatchlist();
}

function renderLtWatchlist() {
  if (!Array.isArray(ltWatchlist)) return;

  // Sync live price & recalculate status for all items
  ltWatchlist.forEach(item => {
    const live = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA))
      ? SCREENER_DATA.find(s => s.symbol === item.symbol)
      : null;
    if (live) {
      // Use live.ltp if it's a valid positive number; otherwise keep existing item.ltp
      if (live.ltp != null && live.ltp > 0) item.ltp = live.ltp;
      else if (item.ltp == null || item.ltp === 0) item.ltp = live.ltp || 0;
      item.rsi = live.rsi || item.rsi || 50;
      item.trend = live.trend || item.trend || 'Consolidation';
      item.trend_badge = live.tech_rating || item.trend_badge || '🟡 Consolidation Phase';
      item.rs_rating = live.rs_rating || item.rs_rating || 50;
      item.day_chg_pct = live.day_chg_pct || item.day_chg_pct || 0;

      const liveEma = live.ema20 || 0;
      const liveSup = live.sup_level || 0;
      const liveLow20 = live.low20 || 0;
      const liveMa50 = live.ma50 || 0;

      if (liveEma > 0 && liveEma < item.ltp) {
        item.auto_gtt = Math.round(liveEma * 100) / 100;
      } else if (liveSup > 0 && liveSup < item.ltp) {
        item.auto_gtt = Math.round(liveSup * 100) / 100;
      } else if (liveLow20 > 0 && liveLow20 < item.ltp) {
        item.auto_gtt = Math.round(liveLow20 * 100) / 100;
      } else if (liveMa50 > 0 && liveMa50 < item.ltp) {
        item.auto_gtt = Math.round(liveMa50 * 100) / 100;
      } else if (liveLow20 > 0) {
        item.auto_gtt = Math.round(liveLow20 * 100) / 100;
      } else if (liveEma > 0) {
        item.auto_gtt = Math.round(liveEma * 100) / 100;
      } else if (liveSup > 0) {
        item.auto_gtt = Math.round(liveSup * 100) / 100;
      } else if (item.ltp > 0) {
        item.auto_gtt = Math.round(item.ltp * 100) / 100;
      }
    }
    calculateClientStatus(item);
    const _effGtt = (item.gtt_mode === 'auto' || item.is_auto_gtt) ? (item.auto_gtt || item.gtt_level) : item.gtt_level;
    if (_effGtt && _effGtt > 0 && item.ltp > 0) {
      item.dist_from_gtt_pct = Math.round(((item.ltp - _effGtt) / _effGtt) * 1000) / 10;
    } else {
      item.dist_from_gtt_pct = null;
    }
  });

  const isCuratedLt = s => (typeof LT_WATCHLIST !== 'undefined' && Array.isArray(LT_WATCHLIST)) && LT_WATCHLIST.some(item => (item.symbol || '').toUpperCase() === (s.symbol || '').toUpperCase());

  const isPenny = s => {
    if (isCuratedLt(s)) return false;
    const p = parseFloat(s.ltp || 0);
    const hp = s.holding ? parseFloat(s.holding.avg_price || 0) : 0;
    return (p > 0 && p <= 75.0) || (hp > 0 && hp <= 75.0);
  };

  const activeList = ltWatchlist.filter(s => s.active !== false && !isPenny(s));
  const retiredList = ltWatchlist.filter(s => s.active === false && !isPenny(s));

  const buyNowCount = activeList.filter(s => s.status === 'BUY_NOW').length;
  const boughtCount = activeList.filter(s => s.status === 'BOUGHT' || (s.holding && s.holding.qty > 0)).length;
  const waitCount = activeList.filter(s => s.status === 'WAIT').length;
  const watchlistCount = activeList.filter(s => s.status === 'WATCHLIST').length;
  const totalActive = activeList.length;

  // Update Stats & Header Counts
  const el = id => document.getElementById(id);
  if (el('ltCountBuyNow')) el('ltCountBuyNow').textContent = buyNowCount;
  if (el('ltCountWait')) el('ltCountWait').textContent = waitCount;
  if (el('ltCountWatchlist')) el('ltCountWatchlist').textContent = watchlistCount;
  if (el('ltCountBought')) el('ltCountBought').textContent = boughtCount;
  if (el('ltCountTotal')) el('ltCountTotal').textContent = totalActive;
  if (el('wlCount')) el('wlCount').textContent = totalActive;
  if (el('ltRetiredCount')) el('ltRetiredCount').textContent = retiredList.length;

  if (el('ltPillCountALL')) el('ltPillCountALL').textContent = totalActive;
  if (el('ltPillCountBUY_NOW')) el('ltPillCountBUY_NOW').textContent = buyNowCount;
  if (el('ltPillCountBOUGHT')) el('ltPillCountBOUGHT').textContent = boughtCount;
  if (el('ltPillCountWAIT')) el('ltPillCountWAIT').textContent = waitCount;
  if (el('ltPillCountWATCHLIST')) el('ltPillCountWATCHLIST').textContent = watchlistCount;

  // Alert Banner
  const alertBox = el('ltBuyNowAlert');
  const alertText = el('ltBuyNowAlertText');
  if (alertBox) {
    if (buyNowCount > 0) {
      const buyNowItems = activeList.filter(s => s.status === 'BUY_NOW');
      const symbolsStr = buyNowItems.map(s => `${s.symbol} (LTP: ₹${s.ltp.toFixed(2)} ≤ GTT: ₹${parseFloat(s.gtt_level).toFixed(2)})`).join(', ');
      if (alertText) alertText.innerHTML = `<strong>${buyNowCount} Stock(s) Triggered:</strong> ${symbolsStr}`;
      alertBox.style.display = 'flex';
    } else {
      alertBox.style.display = 'none';
    }
  }

  // Filter display list
  let displayList = ltWatchlist.filter(s => !isPenny(s) && (ltShowRetired ? true : s.active !== false));
  if (ltFilterStatus !== 'ALL') {
    displayList = displayList.filter(s => s.status === ltFilterStatus);
  }

  // Sort
  displayList.sort((a, b) => {
    let av = a[ltSortCol];
    let bv = b[ltSortCol];
    if (ltSortCol === 'status') {
      const order = { 'BUY_NOW': 1, 'BOUGHT': 2, 'WAIT': 3, 'WATCHLIST': 4 };
      av = order[a.status] || 5;
      bv = order[b.status] || 5;
    }
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'string') return ltSortDir * av.localeCompare(bv);
    return ltSortDir * (av - bv);
  });

  const tbody = el('ltWatchlistBody');
  const empty = el('ltEmpty');
  if (!tbody) return;

  if (displayList.length === 0) {
    tbody.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  tbody.innerHTML = displayList.map((s, i) => {
    const isRetired = (s.active === false);
    const isBought = (s.status === 'BOUGHT' || (s.holding && s.holding.qty > 0 && s.status !== 'BUY_NOW'));
    const holdingQty = (s.holding && s.holding.qty) ? s.holding.qty : 1;
    const scoreVal = s.durability_score || 75;
    const scoreColor = scoreVal >= 85 ? '#10b981' : scoreVal >= 75 ? '#60a5fa' : '#fbbf24';
    const statusBadgeCls = isBought ? 'badge-green' : (s.status === 'BUY_NOW' ? 'badge-green' : s.status === 'WAIT' ? 'badge-purple' : 'badge-gray');
    const statusBadgeText = s.status_badge || (isBought ? `🟢 BOUGHT (${holdingQty})` : (s.status === 'BUY_NOW' ? '🟢 BUY NOW' : s.status === 'WAIT' ? '🔵 WAIT' : '⬜ WATCHING'));


    const isAutoGtt = (s.gtt_mode === 'auto' || s.gtt_mode == null || s.is_auto_gtt);
    const gttVal = isAutoGtt ? (s.auto_gtt || s.gtt_level) : s.gtt_level;
    const gttStr = gttVal ? `₹${parseFloat(gttVal).toFixed(2)}` : '—';
    const ltpStr = s.ltp ? `₹${s.ltp.toFixed(2)}` : '—';
    const distStr = s.dist_from_gtt_pct != null
      ? `<span style="color:${s.dist_from_gtt_pct <= 0 ? '#10b981' : '#a5b4fc'};font-weight:700">${s.dist_from_gtt_pct <= 0 ? '' : '+'}${s.dist_from_gtt_pct.toFixed(1)}%</span>`
      : '—';

    const rsiStr = s.rsi ? s.rsi.toFixed(0) : '—';

    const gttBtn = isAutoGtt
      ? `<button onclick="promptGttEdit('${s.symbol}', ${gttVal || 0}, true)" style="background:rgba(52,211,153,0.12);border:1px solid rgba(52,211,153,0.3);color:#34d399;font-weight:700;padding:4px 8px;border-radius:6px;cursor:pointer;font-size:11px" title="⚡ Auto-Trailing 20-EMA / Support Target (Click to edit or set custom level)">⚡ ${gttStr}</button>`
      : `<button onclick="promptGttEdit('${s.symbol}', ${gttVal || 0}, false)" style="background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);color:#fbbf24;font-weight:700;padding:4px 8px;border-radius:6px;cursor:pointer;font-size:11px" title="📌 Fixed Manual Level (Click to edit or reset to auto)">📌 ${gttStr}</button>`;

    return `
    <tr style="${isRetired ? 'opacity:0.5;background:rgba(0,0,0,0.2)' : ''}">
      <td>
        <div style="font-weight:800;color:${scoreColor};font-size:14px">${scoreVal} <span style="font-size:10px;color:var(--muted)">/100</span></div>
      </td>
      <td>
        <div style="font-weight:700;color:#fff;font-size:14px">${s.symbol}</div>
        <div style="font-size:10px;color:var(--muted)">${s.portfolio_role || ''}</div>
      </td>
      <td><span class="badge ${s.type === 'PSU' ? 'badge-yellow' : 'badge-purple'}" style="font-size:10px">${s.type || 'Private'}</span></td>
      <td><span style="font-size:11px;color:var(--text)">${s.sector || ''}</span></td>
      <td>
        <span class="badge ${statusBadgeCls}" style="font-size:11px;font-weight:700" title="${s.status_reason || ''}">${statusBadgeText}</span>
      </td>
      <td>
        <span class="badge ${trendBadgeClass(s.trend)}" style="font-size:10px">
          ${s.trend_badge || s.trend || '—'}
        </span>
      </td>
      <td><span style="font-size:11px;font-weight:600">${rsiStr}</span></td>
      <td><strong style="color:#fff;font-size:13px">${ltpStr}</strong></td>
      <td>${gttBtn}</td>
      <td>${distStr}</td>
      <td><span style="font-size:11px;color:var(--muted)">${s.portfolio_role || '—'}</span></td>
      <td>
        <div style="display:flex;gap:6px">
          ${!isRetired ? `
            ${isBought ? `
              <button onclick="openLtHoldingLogModal('${s.symbol}')" style="background:rgba(6,182,212,0.18);border:1px solid rgba(6,182,212,0.4);color:#22d3ee;font-weight:700;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="View Purchase Log & Holding details for ${s.symbol}">📋 Purchased (${holdingQty})</button>
              <button onclick="openLtBuyModal('${s.symbol}', ${s.ltp || 0})" style="background:var(--card2);border:1px solid var(--border);color:#a7f3d0;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Add More / Pyramid">+ Add</button>
            ` : `
              <button onclick="openLtBuyModal('${s.symbol}', ${s.ltp || 0})" style="background:rgba(16,185,129,0.18);border:1px solid rgba(16,185,129,0.4);color:#34d399;font-weight:700;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Record Buy Transaction for ${s.symbol}">🛒 Buy</button>
            `}
            <button onclick="promptGttEdit('${s.symbol}', ${s.gtt_level || 0})" style="background:var(--card2);border:1px solid var(--border);color:var(--text);font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Edit GTT Level">✏️ GTT</button>
            <button onclick="retireLtStock('${s.symbol}')" style="background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#ef4444;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Soft-delete (Keep history)">🗑️ Retire</button>
          ` : `
            <button onclick="reactivateLtStock('${s.symbol}')" style="background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);color:#34d399;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Reactivate Stock">🔄 Reactivate</button>
          `}
        </div>
      </td>
    </tr>`;
  }).join('');
}

function openAddLtStockModal(prefillSymbol = '') {
  if (typeof prefillSymbol !== 'string') prefillSymbol = '';
  const el = id => document.getElementById(id);
  const modalBg = el('ltAddModalBg');
  if (prefillSymbol) {
    if (el('ltFormSymbol')) el('ltFormSymbol').value = prefillSymbol;
    const screenerItem = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) ? SCREENER_DATA.find(s => s.symbol === prefillSymbol) : null;
    if (screenerItem) {
      if (el('ltFormSector')) el('ltFormSector').value = screenerItem.sector || '';
      if (el('ltFormGtt')) el('ltFormGtt').value = screenerItem.ltp ? (screenerItem.ltp * 0.95).toFixed(2) : '';
    }
  } else {
    if (el('ltFormSymbol')) el('ltFormSymbol').value = '';
    if (el('ltFormSector')) el('ltFormSector').value = '';
    if (el('ltFormRole')) el('ltFormRole').value = '';
    if (el('ltFormGtt')) el('ltFormGtt').value = '';
  }

  if (modalBg) {
    modalBg.style.display = 'flex';
  } else {
    // Native Prompt Fallback (Works on any browser/environment unconditionally)
    const symInput = prompt('➕ ADD STOCK TO LT WATCHLIST\n\nEnter Stock Symbol (e.g. BEL, TATAPOWER, RELIANCE, INFOSYS):', prefillSymbol);
    if (!symInput) return;
    const sym = symInput.trim().toUpperCase();
    if (!sym) return;

    const typeChoice = prompt(`Adding ${sym} to LT Watchlist\n\nEnter Type (1 for Private, 2 for PSU):`, '1');
    const type = (typeChoice === '2') ? 'PSU' : 'Private';
    const role = prompt(`Enter Portfolio Role for ${sym}:`, 'Core growth') || 'Core growth';

    const screenerItem = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) ? SCREENER_DATA.find(s => s.symbol === sym) : null;
    const sector = screenerItem ? (screenerItem.sector || 'General') : 'General';
    const gtt = screenerItem && screenerItem.ltp ? (screenerItem.ltp * 0.95) : null;

    const newStock = {
      symbol: sym,
      ticker: `${sym}.NS`,
      type: type,
      durability_score: 75,
      sector: sector,
      portfolio_role: role,
      gtt_mode: gtt ? 'manual' : 'auto',
      gtt_level: gtt,
      ltp: screenerItem ? screenerItem.ltp : 0,
      status: 'WAIT',
      status_badge: '🔵 WAIT',
      status_badge_class: 'badge-purple',
      active: true,
      added_date: new Date().toISOString().split('T')[0]
    };

    let idx = ltWatchlist.findIndex(s => s.symbol === sym);
    if (idx >= 0) {
      ltWatchlist[idx] = { ...ltWatchlist[idx], ...newStock, active: true };
    } else {
      ltWatchlist.push(newStock);
    }

    renderLtWatchlist();

    fetch('/api/lt-watchlist/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, type, durability_score: 75, sector, portfolio_role: role, gtt_level: gtt })
    }).finally(() => {
      fetchLtWatchlistApi();
    });

    alert(`✅ Successfully added ${sym} to LT Watchlist!`);
  }
}

window.openAddLtStockModal = openAddLtStockModal;
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('ltAddStockBtn');
    if (btn) {
      btn.onclick = (e) => {
        if (e) e.preventDefault();
        openAddLtStockModal();
      };
    }
  });
}

function closeAddLtStockModal() {
  const modalBg = document.getElementById('ltAddModalBg');
  if (modalBg) modalBg.style.display = 'none';
}

function submitAddLtStockForm(e) {
  if (e) e.preventDefault();
  const el = id => document.getElementById(id);
  const symbol = el('ltFormSymbol') ? el('ltFormSymbol').value.trim().toUpperCase() : '';
  const type = el('ltFormType') ? el('ltFormType').value : 'Private';
  const durability_score = parseInt(el('ltFormDurability') ? el('ltFormDurability').value : 75) || 75;
  const sector = el('ltFormSector') ? el('ltFormSector').value.trim() : '';
  const portfolio_role = el('ltFormRole') ? el('ltFormRole').value.trim() : '';
  const gtt_level = (el('ltFormGtt') && el('ltFormGtt').value) ? parseFloat(el('ltFormGtt').value) : null;

  if (!symbol) {
    alert('Please enter a stock symbol.');
    return;
  }

  const screenerItem = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) ? SCREENER_DATA.find(s => s.symbol === symbol) : null;
  const ltp = screenerItem ? screenerItem.ltp : 0;

  const newStock = {
    symbol,
    ticker: `${symbol}.NS`,
    type: type || 'Private',
    durability_score: durability_score || 75,
    sector: sector || (screenerItem ? screenerItem.sector : 'General'),
    portfolio_role: portfolio_role || 'Growth',
    gtt_mode: gtt_level ? 'manual' : 'auto',
    gtt_level: gtt_level || (ltp ? ltp * 0.95 : null),
    ltp: ltp,
    status: 'WAIT',
    status_badge: '🔵 WAIT',
    status_badge_class: 'badge-purple',
    active: true,
    added_date: new Date().toISOString().split('T')[0]
  };

  let existingIndex = ltWatchlist.findIndex(s => s.symbol === symbol);
  if (existingIndex >= 0) {
    ltWatchlist[existingIndex] = { ...ltWatchlist[existingIndex], ...newStock, active: true };
  } else {
    ltWatchlist.push(newStock);
  }

  closeAddLtStockModal();
  renderLtWatchlist();

  fetch('/api/lt-watchlist/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, type, durability_score, sector, portfolio_role, gtt_level })
  }).finally(() => {
    fetchLtWatchlistApi();
  });

  alert(`✅ Successfully added ${symbol} to LT Watchlist!`);
}

function promptGttEdit(symbol, currentGtt) {
  const newGttStr = prompt(`Enter new GTT Dip-Buy Target Price (₹) for ${symbol}:`, currentGtt || '');
  if (newGttStr === null) return;
  const newGtt = newGttStr.trim() !== '' ? parseFloat(newGttStr) : null;

  fetch('/api/lt-watchlist/update-gtt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, gtt_level: newGtt })
  }).finally(() => {
    const item = ltWatchlist.find(s => s.symbol === symbol);
    if (item) item.gtt_level = newGtt;
    renderLtWatchlist();
  });
}

function fetchLtWatchlistApi() {
  fetch('/api/lt-watchlist')
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(data => {
      if (Array.isArray(data) && data.length > 0) {
        ltWatchlist = data;
        renderLtWatchlist();
      }
    })
    .catch(err => {
      console.warn('Could not fetch live LT Watchlist from API, using offline fallback:', err);
      if (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist)) {
        renderLtWatchlist();
      }
    });
}

function deleteLtStock(symbol) {
  if (!confirm(`Permanently delete ${symbol} from watchlist?\nThis will remove it completely from lt_watchlist.json.`)) return;
  fetch('/api/lt-watchlist/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol: symbol })
  }).then(r => r.json()).then(res => {
    ltWatchlist = ltWatchlist.filter(s => s.symbol !== symbol);
    renderLtWatchlist();
    fetchLtWatchlistApi();
  }).catch(err => alert('Error deleting stock: ' + err));
}

function retireLtStock(symbol) {
  if (!confirm(`Are you sure you want to retire ${symbol} from active watchlist?\n(Stock will be soft-deleted and can be restored anytime via "Show Retired Stocks")`)) return;

  fetch('/api/lt-watchlist/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol })
  }).finally(() => {
    const item = ltWatchlist.find(s => s.symbol === symbol);
    if (item) item.active = false;
    fetchLtWatchlistApi();
  });
}

function reactivateLtStock(symbol) {
  fetch('/api/lt-watchlist/toggle-active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, active: true })
  }).finally(() => {
    const item = ltWatchlist.find(s => s.symbol === symbol);
    if (item) item.active = true;
    fetchLtWatchlistApi();
  });
}

function addToWatchlist(symbol) {
  openAddLtStockModal(symbol);
}

function toggleWatchlist(symbol) {
  openAddLtStockModal(symbol);
}

// ── Init ──────────────────────────────────────────────────────────────────
function init() {
  renderMarketStatusHeader();
  updateLtpBadgeStatus();
  renderCommodityBar();
  
  // Clear legacy localStorage cache keys
  localStorage.removeItem('quality_watchlist_v1');
  localStorage.removeItem('quality_watchlist_v2');
  localStorage.removeItem('quality_watchlist_v3');
  localStorage.removeItem('quality_watchlist_v4');
  localStorage.removeItem('quality_watchlist_v5');
  localStorage.removeItem('quality_watchlist_v6');
  localStorage.removeItem('quality_watchlist_v7');

  // Always initialize Watchlist directly from fresh server scan
  const freshServerWatchlist = JSON.parse(JSON.stringify(WATCHLIST_SEED || []));
  
  // Preserve any custom user-added stocks from localStorage
  const stored = localStorage.getItem('quality_watchlist_custom_items');
  if (stored) {
    try {
      const customItems = JSON.parse(stored);
      const serverSyms = new Set(freshServerWatchlist.map(s => s.symbol));
      customItems.forEach(item => {
        if (!serverSyms.has(item.symbol)) {
          freshServerWatchlist.push(item);
        }
      });
    } catch(e) {}
  }
  watchlist = freshServerWatchlist;

  // Update live data and dynamic signals for all watchlist items from current scan
  watchlist.forEach(item => {
    const live = (SCREENER_DATA || []).find(s => s.symbol === item.symbol);
    updateWatchlistSignalsAndAlerts(item, live);
  });

  saveWatchlist();

  // ltWatchlist's own top-level `let ltWatchlist = ...LT_WATCHLIST...` (near the top
  // of this file) runs at app.js PARSE time, before the small per-scan bootstrap
  // script (loaded after app.js) ever sets LT_WATCHLIST to its real value — so that
  // initial assignment always captured the empty default and was never revisited,
  // leaving the LT Screen tab permanently empty on every fresh page load until a
  // user action (add/remove stock) happened to call fetchLtWatchlistApi(). Rebuild
  // it here from the now-populated LT_WATCHLIST, exactly like watchlist above.
  ltWatchlist = JSON.parse(JSON.stringify(LT_WATCHLIST || []));

  renderStats();
  populateSectorFilter();
  applyFilters();
  renderWatchlist();
  renderLtWatchlist();
  fetchLtPortfolioStatus();
  updateWlCount();

  renderMarketStatusHeader();
  startPolling();
  setInterval(renderMarketStatusHeader, 30000);

  checkStartupScanStatus();
  startupScanPoller = setInterval(checkStartupScanStatus, 3000);
}

let startupScanPoller = null;
let wasScanning = false;

function checkStartupScanStatus() {
  fetch('/api/status')
    .then(r => r.json())
    .then(res => {
      const banner = document.getElementById('bgScanBanner');
      const overlay = document.getElementById('scanProgressOverlay');
      const textEl = document.getElementById('scanProgressText');
      const logEl = document.getElementById('scanProgressLog');

      if (res && res.is_scanning) {
        wasScanning = true;

        if (overlay && (typeof SCREENER_DATA === 'undefined' || !SCREENER_DATA || SCREENER_DATA.length === 0)) {
          overlay.style.display = 'flex';
          if (textEl) textEl.textContent = '⚡ Initializing Full Scan of 2,414 Stocks...';
          if (logEl) logEl.textContent = 'Multithreaded engine scanning live prices & technical ratings. Page will auto-load when complete...';
        }

        if (!banner) {
          const b = document.createElement('div');
          b.id = 'bgScanBanner';
          b.style.cssText = 'background:linear-gradient(135deg,rgba(108,99,255,0.25),rgba(0,212,170,0.25));border-bottom:1.5px solid var(--accent);padding:10px 20px;text-align:center;font-size:13px;font-weight:700;color:#fff;display:flex;align-items:center;justify-content:center;gap:10px;box-shadow:0 4px 16px rgba(0,0,0,0.3)';
          b.innerHTML = `<span style="font-size:16px;animation:spin 1.5s linear infinite">⚡</span> <span>Full Stock &amp; Commodity Scan in Progress (2414 stocks)... Page will auto-reload when complete.</span>`;
          document.body.prepend(b);
        }
      } else {
        if (overlay && wasScanning) {
          overlay.style.display = 'none';
        }
        if (banner) {
          banner.remove();
        }
        if (wasScanning) {
          window.location.reload();
          return;
        }
        if (startupScanPoller) clearInterval(startupScanPoller);
        // This only ever watched the ONE scan that happened to be running when the
        // page first loaded — once that finished (or never happened), the poller
        // stopped for good, so a tab left open across a LATER scan (the hourly
        // rescan, or a manual "Scan Now") never learned new data existed. Anyone
        // watching the Intraday tab in particular would keep seeing whatever picks
        // were computed when the page loaded, silently going stale. Hand off to a
        // slower, persistent watcher for the rest of the page's lifetime instead.
        if (res && res.last_scan_completed_at) {
          knownScanCompletedAt = res.last_scan_completed_at;
        }
        if (!freshScanPoller) {
          freshScanPoller = setInterval(checkForFreshScan, 60000);
        }
      }
    })
    .catch(() => {});
}

let freshScanPoller = null;
let knownScanCompletedAt = null;

function checkForFreshScan() {
  fetch('/api/status')
    .then(r => r.json())
    .then(res => {
      if (!res || res.is_scanning || !res.last_scan_completed_at) return;
      if (knownScanCompletedAt === null) {
        knownScanCompletedAt = res.last_scan_completed_at;
        return;
      }
      if (res.last_scan_completed_at === knownScanCompletedAt) return;

      if (freshScanPoller) { clearInterval(freshScanPoller); freshScanPoller = null; }
      const b = document.createElement('div');
      b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:999999;background:linear-gradient(135deg,rgba(108,99,255,0.95),rgba(0,212,170,0.95));color:#fff;padding:10px 20px;text-align:center;font-size:13px;font-weight:700;box-shadow:0 4px 16px rgba(0,0,0,0.4)';
      b.textContent = '⚡ A newer scan just finished — refreshing with fresh data...';
      document.body.prepend(b);
      setTimeout(() => window.location.reload(), 2500);
    })
    .catch(() => {});
}

function formatAgo(ms) {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return `${h}h ago`;
}

function updateLtpBadgeStatus(lastTimeStr, polledCount, attemptedCount, staleCount) {
  const dot = document.getElementById('ltpStatusDot');
  const txt = document.getElementById('ltpStatusText');
  if (!txt) return;

  if (pollIntervalMs === 0) {
    if (dot) { dot.style.background = '#6b7280'; dot.style.boxShadow = 'none'; }
    txt.textContent = 'Live LTP Polling: Off';
    return;
  }

  // Only treat this as a real failure once we've actually attempted a cycle and it
  // returned zero fresh prices — before the first cycle runs, attemptedCount is undefined.
  const hasFailed = attemptedCount != null && attemptedCount > 0 && (!polledCount || polledCount === 0);

  if (hasFailed) {
    if (dot) { dot.style.background = '#ef4444'; dot.style.boxShadow = '0 0 8px #ef4444'; }
    const sinceOk = lastLtpSuccessTime ? formatAgo(Date.now() - lastLtpSuccessTime) : 'never this session';
    const staleTag = staleCount > 0 ? ` (showing ${staleCount} stale scan-time prices)` : '';
    txt.textContent = `🔴 Live LTP Polling: Failed — last success ${sinceOk}${staleTag}`;
    return;
  }

  if (dot) { dot.style.background = '#10b981'; dot.style.boxShadow = '0 0 8px #10b981'; }
  const timeTag = lastTimeStr ? ` @ ${lastTimeStr}` : '';
  const countTag = (polledCount != null && polledCount > 0) ? ` — ${polledCount} prices synced${timeTag}` : (lastTimeStr ? ` — Last Sync: ${lastTimeStr}` : '');
  txt.textContent = `🟢 Live LTP Polling: Active (${pollIntervalMs / 1000}s)${countTag}`;
}

async function fetchLiveLTPForSymbol(ticker) {
  const ts = Date.now();
  if (isRealDesktopPC()) {
    const currentPort = window.location.port || '5050';
    const localEps = [
      window.location.origin && window.location.origin.startsWith('http') ? `${window.location.origin}/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}` : null,
      `http://127.0.0.1:${currentPort}/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://localhost:${currentPort}/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://127.0.0.1:5050/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://localhost:5050/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://127.0.0.1:8000/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://localhost:8000/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://127.0.0.1:8080/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://localhost:8080/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`
    ].filter((ep, idx, self) => ep && self.indexOf(ep) === idx);

    for (const ep of localEps) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 1500);
        const res = await fetch(ep, { signal: controller.signal });
        clearTimeout(timeoutId);
        if (res.ok) {
          const data = await res.json();
          if (data && (data.price || data.ltp) && (data.price > 0 || data.ltp > 0)) {
            return parseFloat(data.price || data.ltp);
          }
          const pObj = data.ltps || data.prices || {};
          const cleanTicker = ticker.replace('.NS', '');
          const p = pObj[ticker] || pObj[cleanTicker] || pObj[ticker + '.NS'];
          if (p && p > 0) return parseFloat(p);
        }
      } catch (e) {}
    }
  }

  const yUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=1m&range=1d&_t=${ts}`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(yUrl, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (res.ok) {
      const data = await res.json();
      const meta = data.chart?.result?.[0]?.meta;
      if (meta && meta.regularMarketPrice && meta.regularMarketPrice > 0) return meta.regularMarketPrice;
    }
  } catch (e) {}

  const proxies = [
    `https://api.allorigins.win/raw?url=${encodeURIComponent(yUrl)}`,
    `https://corsproxy.io/?${encodeURIComponent(yUrl)}`
  ];

  for (const px of proxies) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);
      const res = await fetch(px, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (res.ok) {
        const text = await res.text();
        let data = null;
        try { data = JSON.parse(text); } catch(err) { data = null; }
        if (data) {
          if (data.price && data.price > 0) return data.price;
          const meta = data.chart?.result?.[0]?.meta;
          if (meta && meta.regularMarketPrice) return meta.regularMarketPrice;
        }
      }
    } catch (e) {}
  }

  return null;
}

async function refreshLiveLTP(manual = false) {
  const dot = document.getElementById('ltpStatusDot');
  const txt = document.getElementById('ltpStatusText');
  if (dot) dot.classList.add('updating');
  if (txt) txt.textContent = manual ? 'Refreshing prices...' : 'Polling LTP...';

  let priceChanged = false;

  const symbolsToPoll = new Map();
  symbolsToPoll.set('NIFTY_INDEX', '^NSEI');
  if (typeof TOP_PICK !== 'undefined' && TOP_PICK && TOP_PICK.symbol) {
    symbolsToPoll.set(TOP_PICK.symbol, TOP_PICK.ticker || TOP_PICK.symbol + '.NS');
  }
  if (typeof watchlist !== 'undefined' && Array.isArray(watchlist)) {
    watchlist.forEach(w => symbolsToPoll.set(w.symbol, w.ticker || w.symbol + '.NS'));
  }
  if (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist)) {
    ltWatchlist.forEach(w => symbolsToPoll.set(w.symbol, w.ticker || w.symbol + '.NS'));
  }
  if (typeof LT_WATCHLIST !== 'undefined' && Array.isArray(LT_WATCHLIST)) {
    LT_WATCHLIST.forEach(w => symbolsToPoll.set(w.symbol, w.ticker || w.symbol + '.NS'));
  }
  if (typeof PENNY_STOCKS_DATA !== 'undefined' && Array.isArray(PENNY_STOCKS_DATA)) {
    PENNY_STOCKS_DATA.forEach(p => symbolsToPoll.set(p.symbol, p.ticker || p.symbol + '.NS'));
  }
  if (typeof INTRADAY_DATA !== 'undefined' && INTRADAY_DATA) {
    (INTRADAY_DATA.buy || []).forEach(s => symbolsToPoll.set(s.symbol, s.ticker || s.symbol + '.NS'));
    (INTRADAY_DATA.sell || []).forEach(s => symbolsToPoll.set(s.symbol, s.ticker || s.symbol + '.NS'));
  }
  if (typeof FNO_DATA !== 'undefined' && Array.isArray(FNO_DATA)) {
    FNO_DATA.forEach(f => symbolsToPoll.set(f.symbol, f.ticker || f.symbol + '.NS'));
  }
  if (typeof getSwingData === 'function') {
    try {
      const swingPicks = getSwingData();
      if (Array.isArray(swingPicks)) {
        swingPicks.forEach(s => symbolsToPoll.set(s.symbol, s.ticker || s.symbol + '.NS'));
      }
    } catch(e) {}
  }
  if (typeof filteredData !== 'undefined' && Array.isArray(filteredData)) {
    let effSize = (typeof pageSize !== 'undefined' && pageSize === 'all') ? filteredData.length : parseInt(pageSize || 50);
    let startIdx = (typeof currentPage !== 'undefined') ? Math.max(0, (currentPage - 1) * effSize) : 0;
    let visibleSlice = filteredData.slice(startIdx, startIdx + effSize);
    visibleSlice.forEach(s => symbolsToPoll.set(s.symbol, s.ticker || s.symbol + '.NS'));
  }
  if (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) {
    SCREENER_DATA.filter(s => s.qualified).forEach(s => symbolsToPoll.set(s.symbol, s.ticker || s.symbol + '.NS'));
    SCREENER_DATA.slice(0, 100).forEach(s => symbolsToPoll.set(s.symbol, s.ticker || s.symbol + '.NS'));
  }

  const fetchedPrices = new Map();
  const stalePrices = new Set();
  const tickerList = Array.from(symbolsToPoll.values());
  const attempted = symbolsToPoll.size;

  const ts = Date.now();
  const currentPort = window.location.port || '5050';
  const originEp = window.location.origin && window.location.origin.startsWith('http') ? window.location.origin + '/api/ltp' : null;
  // The hardcoded localhost/127.0.0.1 fallback ports only make sense when this page
  // itself is being served from a local dev instance — on a deployed/production
  // browser (or inside the Capacitor WebView) they can never resolve to the real
  // server and just waste time before falling through to originEp/per-symbol fetch.
  const localEndpoints = isRealDesktopPC() ? [
    originEp,
    `http://127.0.0.1:${currentPort}/api/ltp`,
    `http://localhost:${currentPort}/api/ltp`,
    'http://127.0.0.1:5050/api/ltp',
    'http://localhost:5050/api/ltp',
    'http://127.0.0.1:8000/api/ltp',
    'http://localhost:8000/api/ltp',
    'http://127.0.0.1:8080/api/ltp',
    'http://localhost:8080/api/ltp'
  ].filter((ep, idx, self) => ep && self.indexOf(ep) === idx) : (originEp ? [originEp] : []);

  for (const ep of localEndpoints) {
    if (fetchedPrices.size > 0) break;
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 20000);

      let res = await fetch(ep, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: tickerList }),
        signal: controller.signal
      }).catch(() => null);

      if (!res || !res.ok) {
        const bUrl = `${ep}?symbols=${encodeURIComponent(tickerList.slice(0, 100).join(','))}&_t=${ts}`;
        res = await fetch(bUrl, { signal: controller.signal }).catch(() => null);
      }

      clearTimeout(timeoutId);
      if (res && res.ok) {
        const data = await res.json();
        const pricesObj = data.ltps || data.prices || {};
        const staleObj = data.stale || {};
        for (const [sym, ticker] of symbolsToPoll.entries()) {
          const cleanSym = sym.replace('.NS', '');
          const cleanTicker = ticker.replace('.NS', '');
          const p = pricesObj[ticker] || pricesObj[sym] || pricesObj[cleanSym] || pricesObj[cleanTicker] || pricesObj[sym + '.NS'] || pricesObj[ticker + '.NS'];
          if (p && p > 0) {
            fetchedPrices.set(sym, parseFloat(p));
            if (staleObj[ticker] || staleObj[sym] || staleObj[cleanSym] || staleObj[cleanTicker]) {
              stalePrices.add(sym);
            }
          }
        }
      } else if (!res) {
        lastLtpError = { when: Date.now(), stage: 'bulk', message: `no response from ${ep}` };
      }
    } catch (e) {
      lastLtpError = { when: Date.now(), stage: 'bulk', message: (e && e.message) || String(e) };
    }
  }

  // Per-symbol fallback for anything the bulk call missed. No longer hard-capped at
  // the first 60 unpolled symbols (that silently left larger watchlists/screener
  // pages stale with no indication to the user) — instead bounded by a wall-clock
  // budget, so a slow/offline stretch (e.g. while the server is busy running the
  // startup scan) can't stall an entire poll cycle for minutes; whatever doesn't
  // finish in time is simply picked up on the next cycle, 10s later by default.
  const unpolled = Array.from(symbolsToPoll.entries()).filter(([sym, ticker]) => !fetchedPrices.has(sym));
  if (unpolled.length > 0) {
    const chunkSize = 15;
    const fallbackDeadline = Date.now() + 12000;
    for (let i = 0; i < unpolled.length; i += chunkSize) {
      if (Date.now() > fallbackDeadline) {
        lastLtpError = { when: Date.now(), stage: 'fallback', message: `Time budget reached — ${unpolled.length - i} symbol(s) not retried this cycle` };
        break;
      }
      const chunk = unpolled.slice(i, i + chunkSize);
      await Promise.all(chunk.map(async ([sym, ticker]) => {
        const p = await fetchLiveLTPForSymbol(ticker);
        if (p && p > 0) fetchedPrices.set(sym, p);
      }));
    }
  }

  for (const [sym, newPrice] of fetchedPrices.entries()) {
    const cleanSym = sym.replace('.NS', '');

    if (sym === 'NIFTY_INDEX' || sym === '^NSEI' || (typeof MARKET_INFO !== 'undefined' && MARKET_INFO && MARKET_INFO.nifty && MARKET_INFO.nifty.symbol === sym)) {
      if (typeof MARKET_INFO !== 'undefined' && MARKET_INFO && MARKET_INFO.nifty) {
        if (Math.abs((MARKET_INFO.nifty.ltp || 0) - newPrice) > 0.01) {
          MARKET_INFO.nifty.old_ltp = MARKET_INFO.nifty.ltp;
          MARKET_INFO.nifty.ltp = newPrice;
          if (MARKET_INFO.nifty.prev_close && MARKET_INFO.nifty.prev_close > 0) {
            MARKET_INFO.nifty.change_pct = Math.round(((newPrice - MARKET_INFO.nifty.prev_close) / MARKET_INFO.nifty.prev_close) * 10000) / 100;
          }
          priceChanged = true;
        }
      }
    }

    if (typeof TOP_PICK !== 'undefined' && TOP_PICK && (TOP_PICK.symbol === sym || TOP_PICK.symbol === cleanSym)) {
      if (Math.abs((TOP_PICK.ltp || TOP_PICK.current_ltp || 0) - newPrice) > 0.01) {
        TOP_PICK.old_ltp = TOP_PICK.ltp;
        TOP_PICK.ltp = newPrice;
        TOP_PICK.current_ltp = newPrice;
        if (TOP_PICK.ma50) TOP_PICK.dist_ma50_pct = Math.round(((newPrice - TOP_PICK.ma50)/TOP_PICK.ma50)*1000)/10;
        if (TOP_PICK.ma200) TOP_PICK.dist_ma200_pct = Math.round(((newPrice - TOP_PICK.ma200)/TOP_PICK.ma200)*1000)/10;
        if (TOP_PICK.week_high_52) TOP_PICK.dist_52w_high_pct = Math.round(((newPrice - TOP_PICK.week_high_52)/TOP_PICK.week_high_52)*1000)/10;
        if (TOP_PICK.week_low_52) TOP_PICK.dist_52w_low_pct = Math.round(((newPrice - TOP_PICK.week_low_52)/TOP_PICK.week_low_52)*1000)/10;
        priceChanged = true;
      }
    }

    if (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) {
      const sc = SCREENER_DATA.find(s => s.symbol === sym || s.symbol === cleanSym);
      if (sc && Math.abs((sc.ltp || 0) - newPrice) > 0.01) {
        sc.old_ltp = sc.ltp;
        sc.ltp = newPrice;
        if (sc.gtt_breakout_level && sc.gtt_breakout_level > 0) {
          sc.dist_to_gtt_pct = Math.round(((sc.ltp - sc.gtt_breakout_level) / sc.gtt_breakout_level) * 10000) / 100;
          if (sc.ltp >= sc.gtt_breakout_level && (sc.status === 'WAIT' || sc.swing_action === 'WAIT FOR BREAKOUT')) {
            sc.status = 'BUY_NOW';
            sc.swing_action = 'BUY NOW';
          }
        }
        if (sc.target_price && sc.target_price > 0) {
          sc.dist_to_target_pct = Math.round(((sc.target_price - sc.ltp) / sc.ltp) * 10000) / 100;
        }
        if (sc.stop_loss && sc.stop_loss > 0) {
          sc.dist_to_sl_pct = Math.round(((sc.ltp - sc.stop_loss) / sc.ltp) * 10000) / 100;
        }
        priceChanged = true;
      }
    }

    if (typeof watchlist !== 'undefined' && Array.isArray(watchlist)) {
      const wl = watchlist.find(w => w.symbol === sym || w.symbol === cleanSym);
      if (wl && Math.abs(wl.ltp - newPrice) > 0.01) {
        wl.old_ltp = wl.ltp;
        wl.ltp = newPrice;
        if (wl.avg_cost && wl.qty > 0) {
          wl.unrealised_pnl = Math.round((wl.ltp - wl.avg_cost) * wl.qty * 100) / 100;
          wl.unrealised_pct = Math.round(((wl.ltp - wl.avg_cost) / wl.avg_cost) * 10000) / 100;
          wl.current_value = Math.round(wl.ltp * wl.qty * 100) / 100;
        }
        priceChanged = true;
      }
    }

    if (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist)) {
      const lt = ltWatchlist.find(w => w.symbol === sym || w.symbol === cleanSym);
      if (lt && Math.abs((lt.ltp || 0) - newPrice) > 0.01) {
        lt.old_ltp = lt.ltp;
        lt.ltp = newPrice;
        if (lt.gtt_breakout_level && lt.gtt_breakout_level > 0) {
          lt.dist_to_gtt_pct = Math.round(((lt.ltp - lt.gtt_breakout_level) / lt.gtt_breakout_level) * 10000) / 100;
          if (lt.ltp >= lt.gtt_breakout_level && lt.status === 'WAIT') {
            lt.status = 'BUY_NOW';
          }
        }
        priceChanged = true;
      }
    }

    if (typeof LT_WATCHLIST !== 'undefined' && Array.isArray(LT_WATCHLIST)) {
      const lt = LT_WATCHLIST.find(w => w.symbol === sym || w.symbol === cleanSym);
      if (lt && Math.abs((lt.ltp || 0) - newPrice) > 0.01) {
        lt.old_ltp = lt.ltp;
        lt.ltp = newPrice;
        priceChanged = true;
      }
    }

    if (typeof FNO_DATA !== 'undefined' && Array.isArray(FNO_DATA)) {
      const fn = FNO_DATA.find(f => f.symbol === sym || f.symbol === cleanSym);
      if (fn && Math.abs(fn.ltp - newPrice) > 0.01) {
        fn.old_ltp = fn.ltp;
        fn.ltp = newPrice;
        if (fn.prev_close && fn.prev_close > 0) {
          fn.day_chg_pct = Math.round(((newPrice - fn.prev_close) / fn.prev_close) * 10000) / 100;
        }
        priceChanged = true;
      }
    }

    if (typeof PENNY_STOCKS_DATA !== 'undefined' && Array.isArray(PENNY_STOCKS_DATA)) {
      const ps = PENNY_STOCKS_DATA.find(p => p.symbol === sym || p.symbol === cleanSym);
      if (ps && Math.abs((ps.ltp || 0) - newPrice) > 0.01) {
        ps.old_ltp = ps.ltp;
        ps.ltp = newPrice;
        if (ps.target_price && ps.target_price > 0) {
          ps.dist_to_target_pct = Math.round(((ps.target_price - ps.ltp) / ps.ltp) * 10000) / 100;
        }
        if (ps.stop_loss && ps.stop_loss > 0) {
          ps.dist_to_sl_pct = Math.round(((ps.ltp - ps.stop_loss) / ps.ltp) * 10000) / 100;
        }
        priceChanged = true;
      }
    }

    if (typeof INTRADAY_DATA !== 'undefined' && INTRADAY_DATA) {
      const idPick = [...(INTRADAY_DATA.buy || []), ...(INTRADAY_DATA.sell || [])]
        .find(s => s.symbol === sym || s.symbol === cleanSym);
      if (idPick && Math.abs((idPick.ltp || 0) - newPrice) > 0.01) {
        idPick.old_ltp = idPick.ltp;
        idPick.ltp = newPrice;
        priceChanged = true;
      }
    }
  }

  const nowStr = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
  if (dot) dot.classList.remove('updating');

  // Only count a cycle as a real success if at least some prices are actually fresh —
  // a cycle where every returned price is a stale scan-time fallback means live
  // fetching is failing even though the server still answered with *something*.
  const freshCount = fetchedPrices.size - stalePrices.size;
  if (freshCount > 0) {
    lastLtpSuccessTime = Date.now();
    lastLtpError = null;
  } else if (attempted > 0 && !lastLtpError) {
    lastLtpError = fetchedPrices.size > 0
      ? { when: Date.now(), stage: 'all', message: `All ${fetchedPrices.size} prices this cycle are stale fallbacks` }
      : { when: Date.now(), stage: 'all', message: 'No prices returned this cycle' };
  }
  updateLtpBadgeStatus(nowStr, freshCount, attempted, stalePrices.size);

  saveWatchlist();
  renderStats();
  renderTable();
  renderWatchlist();
  if (typeof renderLtWatchlist === 'function') renderLtWatchlist();
  if (typeof renderFnoTab === 'function') renderFnoTab();
  if (typeof renderIntradayTab === 'function') renderIntradayTab();
  if (typeof renderTopPick === 'function') renderTopPick();
  if (typeof renderSwingRadar === 'function') renderSwingRadar();
  if (typeof renderSrBreakouts === 'function') renderSrBreakouts();
  if (typeof renderNiftyRegimeBanner === 'function') renderNiftyRegimeBanner();
  if (typeof renderPennyStocksTab === 'function') renderPennyStocksTab();

  if (priceChanged || manual) {
    flashUpdatedPrices();
  }
}

function flashUpdatedPrices() {
  document.querySelectorAll('.price, .wl-ltp, .swing-card').forEach(el => {
    el.classList.remove('price-up', 'price-down');
    void el.offsetWidth;
    el.classList.add('price-up');
    setTimeout(() => el.classList.remove('price-up'), 1500);
  });
}

function startPolling() {
  if (pollIntervalTimer) {
    clearInterval(pollIntervalTimer);
    pollIntervalTimer = null;
  }

  if (pollIntervalMs <= 0) {
    updateLtpBadgeStatus();
    return;
  }

  refreshLiveLTP(false);
  pollIntervalTimer = setInterval(() => refreshLiveLTP(false), pollIntervalMs);
  updateLtpBadgeStatus();
}

function changePollInterval(val) {
  pollIntervalMs = parseInt(val);
  startPolling();
}

// Pause polling while the tab/app is backgrounded instead of hammering the server
// and Yahoo endpoints from every hidden tab; resume with an immediate refresh.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    if (pollIntervalTimer) {
      clearInterval(pollIntervalTimer);
      pollIntervalTimer = null;
    }
  } else {
    startPolling();
  }
});

function saveWatchlist() {
  const seedSyms = new Set(WATCHLIST_SEED.map(s => s.symbol));
  const customItems = watchlist.filter(w => !seedSyms.has(w.symbol));
  localStorage.setItem('quality_watchlist_custom_items', JSON.stringify(customItems));
}

// ── Stats ─────────────────────────────────────────────────────────────────
function renderStats() {
  const el = document.getElementById('statsGrid');
  if (!el) return;
  const qualified = SCREENER_DATA.filter(s => s.qualified).length;
  const total = SCREENER_DATA.length;
  const avgScore = total > 0 ? (SCREENER_DATA.reduce((a,b)=>a+b.total_score,0)/total).toFixed(1) : 0;
  const alerts = watchlist.filter(w => w.alerts && w.alerts.length > 0).length;
  const totalInvested = watchlist.reduce((a,w)=>a+(w.total_invested||0),0);

  el.innerHTML = `
    <div class="stat-card"><div class="stat-val stat-purple">${total}</div><div class="stat-lbl">Stocks Scanned</div></div>
    <div class="stat-card"><div class="stat-val stat-green">${qualified}</div><div class="stat-lbl">Qualified (Score≥55)</div></div>
    <div class="stat-card"><div class="stat-val stat-purple">${avgScore}</div><div class="stat-lbl">Avg Score</div></div>
    <div class="stat-card"><div class="stat-val stat-purple">${watchlist.length}</div><div class="stat-lbl">Watchlist / ${CONFIG.max_stocks}</div></div>
    <div class="stat-card"><div class="stat-val ${alerts>0?'stat-danger':'stat-green'}">${alerts}</div><div class="stat-lbl">Quality Alerts</div></div>
    <div class="stat-card"><div class="stat-val stat-warn">₹${Math.round(totalInvested).toLocaleString()}</div><div class="stat-lbl">Invested</div></div>
  `;
}

// ── Tabs ──────────────────────────────────────────────────────────────────
function switchTab(tab) {
  // Both the desktop tab bar and mobile bottom nav carry a matching data-tab
  // attribute, so a single lookup drives the active-highlight for both — previously
  // the desktop bar used a hardcoded array matched to buttons by DOM position, which
  // had silently drifted out of sync with the actual button order and highlighted
  // the wrong tab as "active" on almost every switch.
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.mobile-nav-item').forEach(m => {
    m.classList.toggle('active', m.dataset.tab === tab);
  });
  document.getElementById('tab-screener').style.display  = tab === 'screener'  ? '' : 'none';
  document.getElementById('tab-swing').style.display     = tab === 'swing'     ? '' : 'none';
  document.getElementById('tab-watchlist').style.display = tab === 'watchlist' ? '' : 'none';
  const pennyTab = document.getElementById('tab-penny');
  if (pennyTab) pennyTab.style.display                   = tab === 'penny'     ? '' : 'none';
  const intradayTab = document.getElementById('tab-intraday');
  if (intradayTab) intradayTab.style.display             = tab === 'intraday'  ? '' : 'none';
  document.getElementById('tab-fno').style.display       = tab === 'fno'       ? '' : 'none';
  document.getElementById('tab-holidays').style.display  = tab === 'holidays'  ? '' : 'none';
  if (tab === 'swing')      { renderSwingRadar(); renderSrBreakouts(); }
  if (tab === 'intraday')   renderIntradayTab();
  if (tab === 'watchlist')  { renderLtWatchlist(); renderLtMonthlyPicks(); fetchLtPortfolioStatus(); }
  if (tab === 'penny')      renderPennyStocksTab();
  if (tab === 'fno')        renderFnoTab();
  if (tab === 'holidays')   renderHolidaysTab();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

if (!window.fnoFilters) {
  window.fnoFilters = { conviction: 'all', signal: 'all', sort: 'conviction-desc' };
}

function applyFnoFilters() {
  const cEl = document.getElementById('fFnoConviction');
  const sEl = document.getElementById('fFnoSignal');
  const sortEl = document.getElementById('fFnoSort');
  if (cEl) window.fnoFilters.conviction = cEl.value;
  if (sEl) window.fnoFilters.signal = sEl.value;
  if (sortEl) window.fnoFilters.sort = sortEl.value;
  renderFnoTab();
}

function renderFnoTab() {
  const container = document.getElementById('tab-fno');
  if (!container) return;
  if (!FNO_DATA || !FNO_DATA.length) {
    container.innerHTML = '<div class="fno-no-data">⚠ No F&O data available. Run a scan.</div>';
    return;
  }

  const firstStock = FNO_DATA[0];
  const expiryStr  = firstStock ? firstStock.expiry_str : '';
  const daysLeft   = firstStock ? firstStock.days_to_expiry : '';

  function convColor(c) {
    if (c >= 70) return '#4ade80';
    if (c >= 50) return '#fbbf24';
    return '#f87171';
  }
  function convRatingLabel(c) {
    if (c >= 70) return '🔥 High';
    if (c >= 50) return '⚡ Medium';
    return '⚠️ Low';
  }
  function signalBadge(s) {
    if (s === 'CE') return '<span class="fno-signal-badge fno-signal-ce">▲ CE BUY</span>';
    if (s === 'PE') return '<span class="fno-signal-badge fno-signal-pe">▼ PE BUY</span>';
    return '<span class="fno-signal-badge fno-signal-neutral">◆ NEUTRAL</span>';
  }
  function priceChg(chg) {
    if (chg === undefined || chg === null) return '';
    const cls = chg >= 0 ? 'pos' : 'neg';
    return `<div class="fno-card-chg ${cls}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</div>`;
  }
  function maAlignPill(above50, above200) {
    if (above50 && above200)  return '<span class="fno-tech-pill" style="background:#052e1688;color:#4ade80;border:1px solid #16a34a">Above 50MA &amp; 200MA</span>';
    if (above50)              return '<span class="fno-tech-pill" style="background:#0c4a2688;color:#86efac;border:1px solid #22c55e">Above 50MA</span>';
    if (above200)             return '<span class="fno-tech-pill" style="background:#1c1c0888;color:#fde68a;border:1px solid #ca8a04">Above 200MA</span>';
    return                           '<span class="fno-tech-pill" style="background:#450a0a88;color:#f87171;border:1px solid #dc2626">Below 50MA &amp; 200MA</span>';
  }
  function rsiPill(rsi) {
    const cls = rsi >= 60 ? '#4ade80' : rsi >= 45 ? '#fbbf24' : '#f87171';
    return `<span class="fno-tech-pill" style="background:${cls}18;color:${cls};border:1px solid ${cls}44">RSI ${rsi}</span>`;
  }
  function volPill(vs) {
    const cls = vs >= 1.5 ? '#4ade80' : vs >= 1.0 ? '#fbbf24' : '#94a3b8';
    return `<span class="fno-tech-pill" style="background:${cls}18;color:${cls};border:1px solid ${cls}44">Vol ${vs}x</span>`;
  }
  function fmt(n) { return n ? '₹' + n.toLocaleString('en-IN', {minimumFractionDigits:2,maximumFractionDigits:2}) : '-'; }

  const strikeDir = s => s.signal === 'PE' ? 'PE' : 'CE';

  const filters = window.fnoFilters || { conviction: 'all', signal: 'all', sort: 'conviction-desc' };

  let filtered = FNO_DATA.filter(s => s.symbol === 'RELIANCE' || (s.ltp >= 1000 || s.lot_size < 500));
  if (filters.conviction !== 'all') {
    filtered = filtered.filter(s => {
      if (filters.conviction === 'high') return s.conviction >= 70;
      if (filters.conviction === 'medium') return s.conviction >= 50 && s.conviction < 70;
      if (filters.conviction === 'low') return s.conviction < 50;
      return true;
    });
  }
  if (filters.signal !== 'all') {
    filtered = filtered.filter(s => s.signal === filters.signal);
  }

  filtered.sort((a, b) => {
    if (filters.sort === 'conviction-desc') return b.conviction - a.conviction;
    if (filters.sort === 'conviction-asc') return a.conviction - b.conviction;
    if (filters.sort === 'symbol-asc') return a.symbol.localeCompare(b.symbol);
    return 0;
  });

  const cards = filtered.map(s => {
    const dir  = s.signal;
    const cc   = convColor(s.conviction);
    const s1   = dir === 'PE' ? s.pe_strike_1 : s.ce_strike_1;
    const s2   = dir === 'PE' ? s.pe_strike_2 : s.ce_strike_2;
    const o1   = dir === 'PE' ? s.pe_otm_pct_1 : s.ce_otm_pct_1;
    const o2   = dir === 'PE' ? s.pe_otm_pct_2 : s.ce_otm_pct_2;
    const slCls= dir === 'PE' ? 'pos' : 'neg';
    const tCls = dir === 'PE' ? 'neg' : 'pos';
    return `
    <div class="fno-card">
      <div class="fno-card-header">
        <div>
          <div class="fno-card-sym">${s.symbol}</div>
          <div class="fno-card-name">${s.name || ''}</div>
        </div>
        <div class="fno-card-price">
          <div class="fno-card-ltp">${fmt(s.ltp)}</div>
          ${priceChg(s.day_chg_pct)}
        </div>
      </div>
      <div class="fno-signal-row">
        ${signalBadge(dir)}
        <div class="fno-conviction">
          <div class="fno-conviction-label">
            <span>Conviction: <strong style="color:${cc}">${convRatingLabel(s.conviction)}</strong></span>
            <span style="color:${cc};font-weight:700">${s.conviction}%</span>
          </div>
          <div class="fno-conviction-bar">
            <div class="fno-conviction-fill" style="width:${s.conviction}%;background:${cc}"></div>
          </div>
        </div>
      </div>
      <div class="fno-body">
        <!-- Recommended Strikes -->
        <div class="fno-section-title">Recommended OTM Strikes (${dir === 'NEUTRAL' ? 'CE/PE' : dir})</div>
        <table class="fno-strikes-table">
          <tr><th>Strike</th><th>OTM%</th><th>Underlying Target</th></tr>
          <tr>
            <td><span class="fno-strike-val">₹${(s1||0).toLocaleString('en-IN')}</span></td>
            <td><span class="fno-strike-otm">${o1}% OTM</span></td>
            <td style="color:#fbbf24;font-weight:600">${dir === 'PE' ? fmt(s.t1_price) + ' ▼' : '▲ ' + fmt(s.t1_price)}</td>
          </tr>
          <tr>
            <td><span class="fno-strike-val">₹${(s2||0).toLocaleString('en-IN')}</span></td>
            <td><span class="fno-strike-otm">${o2}% OTM</span></td>
            <td style="color:#10b981;font-weight:600">${dir === 'PE' ? fmt(s.t2_price) + ' ▼' : '▲ ' + fmt(s.t2_price)}</td>
          </tr>
        </table>
        <!-- R/R on Underlying -->
        <div class="fno-section-title">Underlying Risk / Reward</div>
        <div class="fno-rr-grid">
          <div class="fno-rr-cell">
            <div class="fno-rr-label">SL (2%)</div>
            <div class="fno-rr-val ${slCls}">${fmt(s.sl_price)}</div>
          </div>
          <div class="fno-rr-cell">
            <div class="fno-rr-label">Target 1 (3.5%)</div>
            <div class="fno-rr-val ${tCls}">${fmt(s.t1_price)}</div>
          </div>
          <div class="fno-rr-cell">
            <div class="fno-rr-label">Target 2 (6%)</div>
            <div class="fno-rr-val ${tCls}">${fmt(s.t2_price)}</div>
          </div>
        </div>
        <!-- Technicals -->
        <div class="fno-section-title">Technicals</div>
        <div class="fno-tech-row">
          ${rsiPill(s.rsi)}
          ${volPill(s.vol_spike)}
          ${maAlignPill(s.above_ma50, s.above_ma200)}
        </div>
        <div class="fno-lot-info">
          <span>Lot Size: <strong>${s.lot_size}</strong> shares</span>
          <span>Strike Interval: ₹${s.strike_interval}</span>
          <span>52W Ret: <strong style="color:${s.wk52_return_pct >= 0 ? '#10b981' : '#ef4444'}">${s.wk52_return_pct >= 0 ? '+' : ''}${s.wk52_return_pct}%</strong></span>
        </div>
      </div>
    </div>`;
  }).join('');

  const gridContent = cards || `<div class="fno-no-data" style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--muted)">⚠ No stocks match the selected filters.</div>`;

  container.innerHTML = `
    <div class="fno-header">
      <div class="fno-header-left">
        <span style="font-size:28px">📊</span>
        <div>
          <div class="fno-header-title">F&amp;O Weekly Options Signal</div>
          <div class="fno-header-sub">Strategy: OTM CE / PE &bull; Hold 5–7 Trading Days &bull; Monthly Contract</div>
        </div>
      </div>
      <div class="fno-expiry-badge">⏰ Expiry: ${expiryStr} (${daysLeft} days)</div>
    </div>
    <div class="fno-disclaimer">
      <span>⚠</span>
      <span>These are <strong>underlying price signals</strong>, not option premium calls. Verify live IV, premium &amp; bid-ask from your broker's option chain before entering. Physical settlement applies on expiry — square off before expiry Tuesday.</span>
    </div>
    <div class="filters">
      <div class="filter-group">
        <label>Conviction Rating</label>
        <select id="fFnoConviction" onchange="applyFnoFilters()">
          <option value="all" ${filters.conviction === 'all' ? 'selected' : ''}>All Convictions</option>
          <option value="high" ${filters.conviction === 'high' ? 'selected' : ''}>High Conviction (≥70%)</option>
          <option value="medium" ${filters.conviction === 'medium' ? 'selected' : ''}>Medium Conviction (50% - 69%)</option>
          <option value="low" ${filters.conviction === 'low' ? 'selected' : ''}>Low Conviction (&lt;50%)</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Signal Type</label>
        <select id="fFnoSignal" onchange="applyFnoFilters()">
          <option value="all" ${filters.signal === 'all' ? 'selected' : ''}>All Signals</option>
          <option value="CE" ${filters.signal === 'CE' ? 'selected' : ''}>CE Buy</option>
          <option value="PE" ${filters.signal === 'PE' ? 'selected' : ''}>PE Buy</option>
          <option value="NEUTRAL" ${filters.signal === 'NEUTRAL' ? 'selected' : ''}>Neutral</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Sort By</label>
        <select id="fFnoSort" onchange="applyFnoFilters()">
          <option value="conviction-desc" ${filters.sort === 'conviction-desc' ? 'selected' : ''}>Conviction (High to Low)</option>
          <option value="conviction-asc" ${filters.sort === 'conviction-asc' ? 'selected' : ''}>Conviction (Low to High)</option>
          <option value="symbol-asc" ${filters.sort === 'symbol-asc' ? 'selected' : ''}>Symbol (A to Z)</option>
        </select>
      </div>
    </div>
    <div class="fno-grid">${gridContent}</div>
  `;
}

// ── Intraday Buy/Sell Tab (Top 5 MIS long + Top 5 MIS short setups) ────
function renderIntradayTab() {
  const container = document.getElementById('tab-intraday');
  if (!container) return;

  const data = (typeof INTRADAY_DATA !== 'undefined' && INTRADAY_DATA) ? INTRADAY_DATA : { buy: [], sell: [] };
  const buys = data.buy || [];
  const sells = data.sell || [];

  function fmt(n) { return (n || n === 0) ? '₹' + Number(n).toLocaleString('en-IN', {minimumFractionDigits:2,maximumFractionDigits:2}) : '-'; }
  function pillColor(v, goodAbove) { return v >= goodAbove ? '#4ade80' : v >= goodAbove * 0.6 ? '#fbbf24' : '#f87171'; }

  function card(s) {
    const isBuy = s.direction === 'BUY';
    const hasChg = s.has_day_move && s.day_chg_pct != null;
    const chgCls = hasChg ? (s.day_chg_pct >= 0 ? 'pos' : 'neg') : '';
    const chgLabel = hasChg ? `${s.day_chg_pct >= 0 ? '+' : ''}${s.day_chg_pct}%` : 'Day chg n/a';
    const dirBadge = isBuy
      ? '<span class="fno-signal-badge fno-signal-ce">▲ BUY (Long)</span>'
      : '<span class="fno-signal-badge fno-signal-pe">▼ SELL (Short)</span>';
    const rsiCls = pillColor(isBuy ? s.rsi : (100 - s.rsi), 55);
    const volCls = pillColor(s.volume_spike, 1.5);
    return `
    <div class="fno-card">
      <div class="fno-card-header">
        <div>
          <div class="fno-card-sym">${s.symbol}</div>
          <div class="fno-card-name">${s.name || ''}</div>
        </div>
        <div class="fno-card-price">
          <div class="fno-card-ltp">${fmt(s.ltp)}</div>
          <div class="fno-card-chg ${chgCls}">${chgLabel}</div>
        </div>
      </div>
      <div class="fno-signal-row">
        ${dirBadge}
      </div>
      <div class="fno-section-title">Intraday Risk / Reward (MIS)</div>
      <div class="fno-rr-grid">
        <div class="fno-rr-cell">
          <div class="fno-rr-label">Stop Loss</div>
          <div class="fno-rr-val ${isBuy ? 'neg' : 'pos'}">${fmt(s.stop_loss)}</div>
        </div>
        <div class="fno-rr-cell">
          <div class="fno-rr-label">Target 1</div>
          <div class="fno-rr-val ${isBuy ? 'pos' : 'neg'}">${fmt(s.target1)}</div>
        </div>
        <div class="fno-rr-cell">
          <div class="fno-rr-label">Target 2</div>
          <div class="fno-rr-val ${isBuy ? 'pos' : 'neg'}">${fmt(s.target2)}</div>
        </div>
      </div>
      <div class="fno-tech-row">
        <span class="fno-tech-pill" style="background:${rsiCls}18;color:${rsiCls};border:1px solid ${rsiCls}44">RSI ${s.rsi}</span>
        <span class="fno-tech-pill" style="background:${volCls}18;color:${volCls};border:1px solid ${volCls}44">Vol ${s.volume_spike}x</span>
        <span class="fno-tech-pill" style="background:#6c63ff18;color:#a5b4fc;border:1px solid #6c63ff44">50DMA ${s.dist_ma50_pct >= 0 ? '+' : ''}${s.dist_ma50_pct}%</span>
      </div>
      <div class="fno-lot-info" style="padding:10px 18px 16px">
        <span style="color:var(--muted);font-size:11.5px">${s.rationale || ''}</span>
      </div>
    </div>`;
  }

  const buyCards = buys.map(card).join('') || '<div class="fno-no-data" style="grid-column: 1 / -1; padding: 30px">⚠ No strong intraday buy setups found in today\'s scan.</div>';
  const sellCards = sells.map(card).join('') || '<div class="fno-no-data" style="grid-column: 1 / -1; padding: 30px">⚠ No strong intraday sell setups found in today\'s scan.</div>';

  container.innerHTML = `
    <div class="fno-header">
      <div class="fno-header-left">
        <span style="font-size:28px">🎯</span>
        <div>
          <div class="fno-header-title">Intraday MIS Buy / Sell Setups</div>
          <div class="fno-header-sub">Same-day square-off &bull; Ranked by today's move + volume confirmation &bull; Not investment advice</div>
        </div>
      </div>
    </div>
    <div class="fno-section-title" style="margin-top:4px">🟢 Top ${buys.length} Buy (Long) Setups</div>
    <div class="fno-grid">${buyCards}</div>
    <div class="fno-section-title" style="margin-top:24px">🔴 Top ${sells.length} Sell (Short) Setups</div>
    <div class="fno-grid">${sellCards}</div>
  `;
}

// ── This Month's Locked LT Discovery Picks (lock-state banner only) ──
function renderLtMonthlyPicks() {
  const container = document.getElementById('ltMonthlyPicksSection');
  if (!container) return;

  // Auto-picks now live as real LT Watchlist entries (tagged lt_monthly_batch:true).
  // LT_MONTHLY_PICKS now carries only lock-state metadata, not full stock objects.
  const data = (typeof LT_MONTHLY_PICKS !== 'undefined' && LT_MONTHLY_PICKS) ? LT_MONTHLY_PICKS : {};
  const batchSymbols = Array.isArray(data.batch_symbols) ? data.batch_symbols : [];
  const batchSize = data.batch_size || batchSymbols.length || 0;
  const lockedUntil = data.locked_until || null;
  const generatedOn = data.generated_on || null;

  // Hide entirely if no batch info yet (first run before scan)
  if (!lockedUntil && batchSize === 0) {
    container.innerHTML = '';
    return;
  }

  const fmtDate = iso => iso
    ? new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
    : '\u2014';
  const daysLeft = lockedUntil ? Math.max(0, Math.ceil((new Date(lockedUntil) - new Date()) / 86400000)) : 0;

  const pillsHtml = batchSymbols.map(sym => {
    const inWl = (typeof ltWatchlist !== 'undefined') &&
      ltWatchlist.some(s => (s.symbol||'').toUpperCase() === sym.toUpperCase() && s.lt_monthly_batch);
    return '<span style="display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;' +
      'background:' + (inWl ? 'rgba(16,185,129,0.15)' : 'rgba(100,116,139,0.15)') + ';' +
      'color:' + (inWl ? '#34d399' : '#94a3b8') + ';' +
      'border:1px solid ' + (inWl ? 'rgba(16,185,129,0.4)' : 'rgba(100,116,139,0.3)') + ';">' + sym + '</span>';
  }).join(' ');

  container.innerHTML =
    '<div style="background:linear-gradient(135deg,rgba(99,102,241,0.10),rgba(139,92,246,0.08));' +
    'border:1px solid rgba(99,102,241,0.30);border-radius:12px;padding:14px 20px;margin-bottom:18px;' +
    'display:flex;align-items:flex-start;gap:14px;flex-wrap:wrap">' +
    '<div style="font-size:22px;margin-top:2px">\uD83D\uDD12</div>' +
    '<div style="flex:1;min-width:200px">' +
    '<div style="font-size:13px;font-weight:700;color:#c4b5fd;margin-bottom:4px">' +
    '\uD83D\uDD12 Monthly Auto-Picks Locked \u2014 ' + batchSize + ' stock' + (batchSize !== 1 ? 's' : '') + ' added to your LT Watchlist below</div>' +
    '<div style="font-size:11.5px;color:var(--muted);margin-bottom:8px">' +
    'Generated ' + fmtDate(generatedOn) + ' &bull; Locked until <strong style="color:#a5b4fc">' + fmtDate(lockedUntil) + '</strong>' +
    ' &bull; <strong style="color:' + (daysLeft > 7 ? '#34d399' : '#fbbf24') + '">' + daysLeft + ' day' + (daysLeft !== 1 ? 's' : '') + ' remaining</strong>' +
    ' &bull; LTP &lt; \u20b9600 &bull; Quality \u2265 70/100 &bull; See their BUY\u200bNOW/WAIT/WATCHING status in the watchlist table below</div>' +
    '<div style="display:flex;flex-wrap:wrap;gap:5px">' + pillsHtml + '</div>' +
    '</div></div>';
}

// ── Quality Penny Stocks Tab (Top 20 Micro-Cap Wealth Builder) ─────────
let pennyFilterCategory = 'all';
let customPennyMonthlyBudget = 200.0;

function renderPennyStocksTab() {
  const container = document.getElementById('tab-penny');
  if (!container) return;

  const pennyList = (typeof PENNY_STOCKS_DATA !== 'undefined' && Array.isArray(PENNY_STOCKS_DATA)) ? [...PENNY_STOCKS_DATA] : [];
  const holdingsList = (typeof LT_PORTFOLIO_SUMMARY !== 'undefined' && LT_PORTFOLIO_SUMMARY && Array.isArray(LT_PORTFOLIO_SUMMARY.holdings)) ? LT_PORTFOLIO_SUMMARY.holdings : [];

  holdingsList.forEach(h => {
    const sym = (h.symbol || '').toUpperCase();
    const price = parseFloat(h.live_price || h.last_price || h.avg_price || 0);
    if (h.qty > 0 && price <= 75.0 && !pennyList.some(s => (s.symbol || '').toUpperCase() === sym)) {
      // Pull the real scan row for this holding. Everything below must come from
      // measured data or be left null -- never invented. Nulls render as an
      // em dash, and the ROE/D-E quality filters drop null rows, which is the
      // correct outcome for a stock whose fundamentals we do not actually know.
      //
      // These fields used to be fabricated (roe 15.0, D/E 0.1, npm 10.0, trend
      // 'Strong Uptrend'). Those numbers sat exactly on the filter thresholds
      // (roe >= 15.0, de <= 0.15), so every held penny stock silently passed
      // quality screening no matter what its real financials were, and showed a
      // strong-uptrend badge regardless of its actual price structure.
      const scan = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA))
        ? SCREENER_DATA.find(s => (s.symbol || '').toUpperCase() === sym)
        : null;
      const pick = (key) => (h[key] != null ? h[key] : (scan && scan[key] != null ? scan[key] : null));

      pennyList.push({
        symbol: h.symbol,
        name: (scan && scan.name) || h.symbol,
        ltp: h.live_price || h.last_price || h.avg_price,
        status: 'BOUGHT',
        status_badge: `🟢 BOUGHT (${h.qty})`,
        status_badge_class: 'badge-green',
        status_reason: `Purchased on ${h.buy_date || ''} (${h.qty} shares @ ₹${parseFloat(h.avg_price).toFixed(2)})`,
        roe_pct: pick('roe_pct'),
        de_ratio: pick('de_ratio'),
        npm_pct: pick('npm_pct'),
        trend: scan ? scan.trend : null,
        trend_badge: scan ? (scan.trend_badge || scan.tech_rating) : null,
        auto_gtt: h.avg_price
      });
    }
  });

  const hMap = {};
  holdingsList.forEach(h => {
    const sym = (h.symbol || '').toUpperCase();
    const price = parseFloat(h.live_price || h.last_price || h.avg_price || 0);
    const isPennyData = (typeof PENNY_STOCKS_DATA !== 'undefined' && Array.isArray(PENNY_STOCKS_DATA)) && PENNY_STOCKS_DATA.some(s => (s.symbol || '').toUpperCase() === sym);
    if (price <= 75.0 || isPennyData) {
      hMap[sym] = h;
    }
  });

  const getCategory = (s) => {
    const sym = (s.symbol || '').toUpperCase();
    const isB = hMap[sym] && hMap[sym].qty > 0;
    if (isB || s.status === 'BOUGHT') return 'bought';
    const st = (s.status || '').toUpperCase();
    const badge = (s.status_badge || '').toUpperCase();
    if (badge.includes('START SIP NOW') || st === 'START_SIP_NOW') {
      return 'buy_now';
    }
    if (badge.includes('SIP ON DIP') || badge.includes('RETEST') || st === 'WAIT') {
      return 'wait';
    }
    if (st === 'BUY_NOW' || st === 'BUY' || badge.includes('BUY NOW')) {
      return 'buy_now';
    }
    return 'watching';
  };

  const buyNowCount = pennyList.filter(s => getCategory(s) === 'buy_now').length;
  const boughtCount = pennyList.filter(s => getCategory(s) === 'bought').length;
  const waitCount = pennyList.filter(s => getCategory(s) === 'wait').length;
  const watchingCount = pennyList.filter(s => getCategory(s) === 'watching').length;

  let filtered = [...pennyList];
  if (pennyFilterCategory === 'buy_now') {
    filtered = filtered.filter(s => getCategory(s) === 'buy_now');
  } else if (pennyFilterCategory === 'bought') {
    filtered = filtered.filter(s => getCategory(s) === 'bought');
  } else if (pennyFilterCategory === 'wait') {
    filtered = filtered.filter(s => getCategory(s) === 'wait');
  } else if (pennyFilterCategory === 'watching') {
    filtered = filtered.filter(s => getCategory(s) === 'watching');
  } else if (pennyFilterCategory === 'debt_free') {
    filtered = filtered.filter(s => s.de_ratio != null && s.de_ratio <= 0.15);
  } else if (pennyFilterCategory === 'high_roe') {
    filtered = filtered.filter(s => s.roe_pct != null && s.roe_pct >= 15.0);
  } else if (pennyFilterCategory === 'under_30') {
    filtered = filtered.filter(s => s.ltp != null && s.ltp <= 30.0);
  } else if (pennyFilterCategory === 'under_50') {
    filtered = filtered.filter(s => s.ltp != null && s.ltp <= 50.0);
  }

  const budget = customPennyMonthlyBudget || 200.0;

  const cardsHtml = filtered.map((s, idx) => {
    const sym = (s.symbol || '').toUpperCase();
    const ltp = parseFloat(s.ltp || 0);
    const sipQty = ltp > 0 ? Math.max(1, Math.floor(budget / ltp)) : 1;
    const sipCost = (sipQty * ltp).toFixed(2);
    const roeVal = s.roe_pct != null ? s.roe_pct.toFixed(1) + '%' : '—';
    const deVal = s.de_ratio != null ? s.de_ratio.toFixed(2) : '—';
    const npmVal = s.npm_pct != null ? s.npm_pct.toFixed(1) + '%' : '—';
    const volVal = s.avg_volume_10d ? (s.avg_volume_10d / 1000).toFixed(0) + 'k' : '—';

    const holding = hMap[sym];
    const isBought = !!(holding && holding.qty > 0);
    const gateStatus = isBought ? 'BOUGHT' : ((s.status === 'BUY_NOW') ? 'BUY_NOW' : (s.status || 'WATCHLIST'));


    // Status Badge
    let statusBadgeHtml = '';
    if (isBought) {
      statusBadgeHtml = `<span class="badge badge-green" style="font-size:10px;font-weight:700" title="Purchased on ${holding.buy_date || ''} (${holding.qty} shares @ ₹${parseFloat(holding.avg_price || 0).toFixed(2)})">🟢 BOUGHT (${holding.qty})</span>`;
    } else if (s.status_badge) {
      const cls = s.status_badge_class || (gateStatus === 'BUY_NOW' ? 'badge-green' : gateStatus === 'WAIT' ? 'badge-purple' : 'badge-gray');
      statusBadgeHtml = `<span class="badge ${cls}" style="font-size:10px;font-weight:700" title="${s.status_reason || ''}">${s.status_badge}</span>`;
    } else if (gateStatus === 'BUY_NOW') {
      statusBadgeHtml = `<span class="badge badge-green" style="font-size:10px;font-weight:700" title="${s.status_reason || ''}">🟢 BUY NOW</span>`;
    } else if (gateStatus === 'WAIT') {
      statusBadgeHtml = `<span class="badge badge-purple" style="font-size:10px;font-weight:700" title="${s.status_reason || ''}">🔵 WAIT</span>`;
    } else {
      statusBadgeHtml = `<span class="badge badge-gray" style="font-size:10px;font-weight:700" title="${s.status_reason || ''}">⬜ WATCHING</span>`;
    }


    // Trend & CMF Badge
    // No trend claim when the stock is not in the scan set — an em dash is
    // honest, whereas defaulting to a named state asserts something unmeasured.
    const trendText = s.trend_badge || s.trend || '—';
    const trendClass = trendBadgeClass(s.trend);
    const cmfBadge = s.pa_badge ? `<div style="font-size:9px;margin-top:3px"><span class="badge ${s.pa_class || 'badge-gray'}" style="font-size:9px">${s.pa_badge}</span></div>` : '';

    // Support Target GTT
    const gttVal = s.auto_gtt || s.gtt_level;
    const gttStr = gttVal ? `₹${parseFloat(gttVal).toFixed(2)}` : '—';
    const distStr = s.dist_from_gtt_pct != null ? `${s.dist_from_gtt_pct <= 0 ? '' : '+'}${s.dist_from_gtt_pct.toFixed(1)}%` : '—';
    const gttBoxHtml = `
      <div style="display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:8px;padding:6px 10px;margin-bottom:10px;font-size:10px">
        <span style="color:var(--muted);font-weight:600">⚡ Support GTT Target:</span>
        <span style="color:#34d399;font-weight:800">${gttStr} <span style="color:${s.dist_from_gtt_pct <= 0 ? '#10b981' : '#a5b4fc'};font-size:9px">(${distStr})</span></span>
      </div>
    `;

    // Smart Action Button
    let actionBtnHtml = '';
    if (isBought) {
      actionBtnHtml = `
        <div style="margin-top:10px;display:flex;gap:8px">
          <button onclick="openLtHoldingLogModal('${sym}')" style="flex:1;background:rgba(6,182,212,0.18);border:1px solid rgba(6,182,212,0.4);color:#22d3ee;font-weight:700;font-size:11px;padding:8px 12px;border-radius:8px;cursor:pointer" title="View Purchase Log for ${sym}">📋 Purchased (${holding.qty})</button>
          <button onclick="openLtBuyModal('${sym}', ${ltp})" style="background:linear-gradient(135deg,#7c3aed,#c084fc);color:#fff;font-weight:700;font-size:11px;padding:8px 12px;border-radius:8px;border:none;cursor:pointer" title="Record additional SIP for ${sym}">+ Add SIP</button>
        </div>
      `;
    } else if (gateStatus === 'BUY_NOW') {
      actionBtnHtml = `
        <div style="margin-top:10px">
          <button onclick="openLtBuyModal('${sym}', ${ltp})" style="width:100%;background:linear-gradient(135deg,#10b981,#059669);color:#fff;font-weight:800;font-size:11px;padding:8px 12px;border-radius:8px;border:none;cursor:pointer;box-shadow:0 4px 12px rgba(16,185,129,0.3)" title="Breakout confirmed at Support — Record Buy/SIP">🟢 BUY NOW / Record SIP</button>
        </div>
      `;
    } else if (gateStatus === 'WAIT') {
      actionBtnHtml = `
        <div style="margin-top:10px">
          <button onclick="openLtBuyModal('${sym}', ${ltp})" style="width:100%;background:rgba(99,102,241,0.18);border:1px solid rgba(99,102,241,0.4);color:#a5b4fc;font-weight:700;font-size:11px;padding:8px 12px;border-radius:8px;cursor:pointer" title="Coiling at support GTT ${gttStr} — Click if buying manual pullback">🔵 WAIT — Support GTT ${gttStr}</button>
        </div>
      `;
    } else {
      actionBtnHtml = `
        <div style="margin-top:10px">
          <button onclick="openLtBuyModal('${sym}', ${ltp})" style="width:100%;background:rgba(100,116,139,0.15);border:1px solid rgba(100,116,139,0.3);color:#94a3b8;font-weight:600;font-size:11px;padding:8px 12px;border-radius:8px;cursor:pointer" title="Trend not confirmed (${s.trend || 'Consolidation'}) — Avoid blind buy">⚠️ WATCHING (${s.trend || 'Consolidation'})</button>
        </div>
      `;
    }

    return `
    <div style="background:var(--card);border:1px solid ${isBought ? '#10b981' : (gateStatus === 'BUY_NOW' ? 'rgba(16,185,129,0.6)' : 'var(--border)')};border-radius:16px;padding:20px;box-shadow:0 8px 24px rgba(0,0,0,0.3);position:relative;overflow:hidden">
      <div style="position:absolute;top:0;left:0;right:0;height:3px;background:${isBought ? '#10b981' : (gateStatus === 'BUY_NOW' ? '#10b981' : 'linear-gradient(90deg,#7c3aed,#c084fc)')}"></div>
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
        <div>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            <span style="font-size:10px;font-weight:800;color:#c084fc;background:rgba(192,132,252,0.12);padding:2px 8px;border-radius:12px">#${idx + 1} Top Penny</span>
            ${statusBadgeHtml}
            <span class="badge ${trendClass}" style="font-size:10px">${trendText}</span>
          </div>
          ${cmfBadge}
          <div style="font-size:18px;font-weight:800;color:#fff;margin-top:6px">${sym}</div>
          <div style="font-size:11px;color:var(--muted);margin-top:1px">${(s.name || '').substring(0, 28)} · ${s.sector || 'Micro-Cap'}</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:18px;font-weight:800;color:var(--accent2)">₹${ltp.toFixed(2)}</div>
          <div style="font-size:10px;color:${(s.day_chg_pct || 0) >= 0 ? '#10b981' : '#ef4444'};margin-top:2px;font-weight:700">
            ${(s.day_chg_pct || 0) >= 0 ? '+' : ''}${(s.day_chg_pct || 0).toFixed(2)}%
          </div>
        </div>
      </div>

      <!-- Support GTT Target -->
      ${gttBoxHtml}

      <!-- Fundamental Metrics Grid -->
      <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:6px;background:rgba(255,255,255,0.03);border-radius:10px;padding:8px;margin-bottom:10px;text-align:center">
        <div>
          <div style="font-size:9px;color:var(--muted);text-transform:uppercase">ROE %</div>
          <div style="font-size:12px;font-weight:700;color:#10b981;margin-top:2px">${roeVal}</div>
        </div>
        <div>
          <div style="font-size:9px;color:var(--muted);text-transform:uppercase">Debt/Equity</div>
          <div style="font-size:12px;font-weight:700;color:#38bdf8;margin-top:2px">${deVal}</div>
        </div>
        <div>
          <div style="font-size:9px;color:var(--muted);text-transform:uppercase">Margin</div>
          <div style="font-size:12px;font-weight:700;color:#c084fc;margin-top:2px">${npmVal}</div>
        </div>
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center;font-size:10px;color:var(--muted);margin-bottom:10px;padding:0 2px">
        <span>Avg Vol (10d): <strong style="color:#fff">${volVal}</strong></span>
        <span>Quality Score: <strong style="color:var(--accent2)">${s.total_score || 0}/100</strong></span>
      </div>

      <!-- Monthly SIP Recommendation Box -->
      <div style="background:linear-gradient(135deg,rgba(124,58,237,0.12),rgba(192,132,252,0.08));border:1px solid rgba(192,132,252,0.25);border-radius:10px;padding:8px 12px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div>
            <div style="font-size:9px;color:#c084fc;font-weight:700;text-transform:uppercase">Monthly SIP Outlay</div>
            <div style="font-size:13px;font-weight:800;color:#fff;margin-top:1px">Buy ${sipQty} Share${sipQty > 1 ? 's' : ''} / mo</div>
          </div>
          <div style="text-align:right">
            <div style="font-size:9px;color:var(--muted)">Est. Cost</div>
            <div style="font-size:13px;font-weight:800;color:#34d399;margin-top:1px">₹${sipCost}</div>
          </div>
        </div>
      </div>

      ${actionBtnHtml}
    </div>
    `;
  }).join('');

  container.innerHTML = `
    <!-- Header Banner -->
    <div style="background:linear-gradient(135deg,#1e1035,#0f0a1e);border:1px solid #7c3aed;border-radius:16px;padding:22px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px">
      <div>
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:24px">💎</span>
          <div>
            <div style="font-size:20px;font-weight:800;color:#c084fc">Quality Penny & Micro-Cap Wealth-Builder Screener</div>
            <div style="font-size:12px;color:#a78bfa;margin-top:2px">Strict 6-Point Gate + Technical Entry Filter (Support GTT & CMF Accumulation/Distribution)</div>
          </div>
        </div>
      </div>
      <div style="background:rgba(192,132,252,0.12);border:1px solid rgba(192,132,252,0.3);padding:8px 16px;border-radius:12px;text-align:right">
        <div style="font-size:10px;color:#c084fc;text-transform:uppercase;font-weight:700">Qualified Penny Candidates</div>
        <div style="font-size:20px;font-weight:900;color:#fff;margin-top:1px">${pennyList.length} Stocks Scanned</div>
      </div>
    </div>

    <!-- Filter & SIP Budget Controller Row -->
    <div class="filters" style="margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <span style="font-size:11px;color:var(--muted);font-weight:700;margin-right:2px">Gate Status:</span>
        <button onclick="pennyFilterCategory='all';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='all'?'active':''}" style="padding:6px 12px;font-size:11px">↺ All (${pennyList.length})</button>
        <button onclick="pennyFilterCategory='buy_now';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='buy_now'?'active':''}" style="padding:6px 12px;font-size:11px;border-color:#10b981;color:#34d399">🟢 BUY NOW (${buyNowCount})</button>
        <button onclick="pennyFilterCategory='bought';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='bought'?'active':''}" style="padding:6px 12px;font-size:11px;border-color:#06b6d4;color:#22d3ee">🟢 BOUGHT (${boughtCount})</button>
        <button onclick="pennyFilterCategory='wait';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='wait'?'active':''}" style="padding:6px 12px;font-size:11px;border-color:#6366f1;color:#a5b4fc">🔵 WAIT (${waitCount})</button>
        <button onclick="pennyFilterCategory='watching';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='watching'?'active':''}" style="padding:6px 12px;font-size:11px;border-color:#64748b;color:#94a3b8">⬜ WATCHING (${watchingCount})</button>
        <span style="border-left:1px solid var(--border);height:16px;margin:0 4px"></span>
        <button onclick="pennyFilterCategory='debt_free';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='debt_free'?'active':''}" style="padding:6px 12px;font-size:11px">💎 Debt-Free</button>
        <button onclick="pennyFilterCategory='high_roe';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='high_roe'?'active':''}" style="padding:6px 12px;font-size:11px">🔥 High ROE</button>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <label style="font-size:11px;color:var(--muted);font-weight:700">Monthly SIP Amount (₹):</label>
        <input type="number" id="pennyBudgetInput" value="${budget}" min="50" max="5000" step="50"
               onchange="customPennyMonthlyBudget=parseFloat(this.value)||200;renderPennyStocksTab()"
               style="background:var(--card);border:1px solid var(--border);color:#fff;padding:6px 10px;border-radius:8px;width:100px;font-size:12px;font-weight:700">
      </div>
    </div>

    <!-- Cards Grid -->
    <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(310px, 1fr));gap:16px">
      ${cardsHtml || '<div style="color:var(--muted);text-align:center;grid-column:1/-1;padding:40px">No penny stocks match this filter.</div>'}
    </div>
  `;
}

// ── Market Holidays Tab (Y2026 List) ──────────────────────────────────────
function renderHolidaysTab() {
  const container = document.getElementById('tab-holidays');
  if (!container) return;

  const holidays = [
    { date: "2026-01-26", display: "26 Jan 2026", day: "Monday", name: "Republic Day", type: "Trading Holiday", status: "CLOSED", icon: "🇮🇳" },
    { date: "2026-02-15", display: "15 Feb 2026", day: "Sunday", name: "Mahashivratri", type: "Weekend Holiday", status: "WEEKEND", icon: "🕉️" },
    { date: "2026-03-03", display: "03 Mar 2026", day: "Tuesday", name: "Holi", type: "Trading Holiday", status: "CLOSED", icon: "🎨" },
    { date: "2026-03-21", display: "21 Mar 2026", day: "Saturday", name: "Id-Ul-Fitr (Ramadan Eid)", type: "Weekend Holiday", status: "WEEKEND", icon: "🌙" },
    { date: "2026-03-26", display: "26 Mar 2026", day: "Thursday", name: "Shri Ram Navami", type: "Trading Holiday", status: "CLOSED", icon: "🛕" },
    { date: "2026-03-31", display: "31 Mar 2026", day: "Tuesday", name: "Shri Mahavir Jayanti", type: "Trading Holiday", status: "CLOSED", icon: "🙏" },
    { date: "2026-04-03", display: "03 Apr 2026", day: "Friday", name: "Good Friday", type: "Trading Holiday", status: "CLOSED", icon: "✝️" },
    { date: "2026-04-14", display: "14 Apr 2026", day: "Tuesday", name: "Dr. Baba Saheb Ambedkar Jayanti", type: "Trading Holiday", status: "CLOSED", icon: "📜" },
    { date: "2026-05-01", display: "01 May 2026", day: "Friday", name: "Maharashtra Day", type: "Trading Holiday", status: "CLOSED", icon: "🚩" },
    { date: "2026-05-28", display: "28 May 2026", day: "Thursday", name: "Bakri Id (Id-Ul-Adha)", type: "Trading Holiday", status: "CLOSED", icon: "🌙" },
    { date: "2026-06-26", display: "26 Jun 2026", day: "Friday", name: "Muharram", type: "Trading Holiday", status: "CLOSED", icon: "🕌" },
    { date: "2026-08-15", display: "15 Aug 2026", day: "Saturday", name: "Independence Day", type: "Weekend Holiday", status: "WEEKEND", icon: "🇮🇳" },
    { date: "2026-09-14", display: "14 Sep 2026", day: "Monday", name: "Ganesh Chaturthi", type: "Trading Holiday", status: "CLOSED", icon: "🐘" },
    { date: "2026-10-02", display: "02 Oct 2026", day: "Friday", name: "Mahatma Gandhi Jayanti", type: "Trading Holiday", status: "CLOSED", icon: "🕊️" },
    { date: "2026-10-20", display: "20 Oct 2026", day: "Tuesday", name: "Dussehra", type: "Trading Holiday", status: "CLOSED", icon: "🏹" },
    { date: "2026-11-08", display: "08 Nov 2026", day: "Sunday", name: "Diwali Laxmi Pujan", type: "Special Session (Muhurat Trading)", status: "MUHURAT", icon: "🪔", note: "⭐ Special Evening Muhurat Trading session" },
    { date: "2026-11-10", display: "10 Nov 2026", day: "Tuesday", name: "Diwali-Balipratipada", type: "Trading Holiday", status: "CLOSED", icon: "🪔" },
    { date: "2026-11-24", display: "24 Nov 2026", day: "Tuesday", name: "Guru Nanak Jayanti", type: "Trading Holiday", status: "CLOSED", icon: "🪯" },
    { date: "2026-12-25", display: "25 Dec 2026", day: "Friday", name: "Christmas", type: "Trading Holiday", status: "CLOSED", icon: "🎄" }
  ];

  const weekdayHolidaysCount = holidays.filter(h => h.status === 'CLOSED').length;
  const weekendHolidaysCount = holidays.filter(h => h.status === 'WEEKEND').length;

  const rowsHtml = holidays.map(h => {
    let badgeClass = "badge-red";
    let badgeLabel = "🔴 Market Closed";
    if (h.status === "WEEKEND") {
      badgeClass = "badge-yellow";
      badgeLabel = "🟡 Weekend Holiday";
    } else if (h.status === "MUHURAT") {
      badgeClass = "badge-purple";
      badgeLabel = "⭐ Muhurat Session";
    }

    return `<tr>
      <td><strong style="color:var(--accent2);font-size:13px">${h.display}</strong></td>
      <td><span style="color:var(--text);font-weight:600">${h.day}</span></td>
      <td>
        <div style="font-weight:700;display:flex;align-items:center;gap:8px">
          <span>${h.icon}</span>
          <span>${h.name}</span>
        </div>
        ${h.note ? `<div style="font-size:11px;color:var(--warn);margin-top:2px">${h.note}</div>` : ''}
      </td>
      <td><span class="badge ${badgeClass}" style="font-size:11px;font-weight:700">${badgeLabel}</span></td>
      <td><span class="badge badge-gray">${h.type}</span></td>
    </tr>`;
  }).join('');

  container.innerHTML = `
    <!-- Top Spotlight Card -->
    <div class="hero-spotlight" style="margin-bottom:20px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
        <div>
          <div class="hero-badge-tag">📅 Official Market Calendar 2026</div>
          <div style="font-size:24px;font-weight:800;color:var(--white);margin-top:4px">NSE & BSE Trading Holidays List (Y2026)</div>
          <div style="font-size:13px;color:var(--muted);margin-top:4px">
            Official exchange holidays for Equity, Equity Derivatives, and SLB trading segments in India.
          </div>
        </div>
        <div class="badge badge-purple" style="font-size:13px;font-weight:700;padding:8px 16px">
          🇮🇳 Indian Stock Markets (NSE / BSE)
        </div>
      </div>

      <!-- Quick Summary Stats Grid -->
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:18px">
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center">
          <div style="font-size:24px;font-weight:800;color:var(--danger)">${weekdayHolidaysCount}</div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;margin-top:2px">Weekday Trading Holidays</div>
        </div>
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center">
          <div style="font-size:24px;font-weight:800;color:var(--warn)">${weekendHolidaysCount}</div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;margin-top:2px">Weekend Holidays</div>
        </div>
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center">
          <div style="font-size:24px;font-weight:800;color:#a5b4fc">1</div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;margin-top:2px">Special Muhurat Session</div>
        </div>
      </div>
    </div>

    <!-- Holidays List Table -->
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Day</th>
            <th>Holiday / Occasion</th>
            <th>Exchange Status</th>
            <th>Category</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    </div>
  `;
}

// ── Stock of the Day & History ──────────────────────────────────────────
function renderTopPick() {
  const container = document.getElementById('topPickInnerContent') || document.getElementById('tab-top-pick');
  if (!container || !TOP_PICK || !TOP_PICK.symbol) return;

  const inWl = watchlist.some(w => w.symbol === TOP_PICK.symbol);

  const mktBannerHtml = (MARKET_INFO && MARKET_INFO.is_pre_market) ? `
    <div style="background:rgba(245, 158, 11, 0.12);border:1px solid rgba(245, 158, 11, 0.3);border-radius:12px;padding:14px 18px;margin-bottom:18px;display:flex;align-items:center;gap:14px">
      <span style="font-size:24px">⏳</span>
      <div>
        <div style="font-weight:700;color:var(--warn);font-size:14px">Pre-Market Session (${MARKET_INFO.time_str || ''}) — Market Closed</div>
        <div style="font-size:12px;color:var(--text);margin-top:2px">
          Trading on NSE/BSE has not opened yet today. Today's official <strong>Stock of the Day</strong> and pick entry price will lock at <strong>09:15 AM IST</strong> when the market opens. Below is the current top candidate based on pre-market/previous close data.
        </div>
      </div>
    </div>` : (MARKET_INFO && MARKET_INFO.is_open) ? `
    <div style="background:rgba(16, 185, 129, 0.12);border:1px solid rgba(16, 185, 129, 0.3);border-radius:12px;padding:12px 18px;margin-bottom:18px;display:flex;align-items:center;gap:12px">
      <span style="font-size:20px">🟢</span>
      <div>
        <div style="font-weight:700;color:var(--green);font-size:13px">Live Market Session Active (09:15 - 15:30 IST)</div>
        <div style="font-size:12px;color:var(--text);margin-top:2px">
          Today's official pick was locked at Market Open. Current price & live returns update automatically in real-time.
        </div>
      </div>
    </div>` : `
    <div style="background:rgba(239, 68, 68, 0.1);border:1px solid rgba(239, 68, 68, 0.25);border-radius:12px;padding:12px 18px;margin-bottom:18px;display:flex;align-items:center;gap:12px">
      <span style="font-size:20px">🔴</span>
      <div>
        <div style="font-weight:700;color:var(--danger);font-size:13px">${MARKET_INFO ? MARKET_INFO.badge : 'Market Closed'}</div>
        <div style="font-size:12px;color:var(--text);margin-top:2px">
          ${MARKET_INFO ? MARKET_INFO.message : 'Market is closed. Showing finalized daily picks.'}
        </div>
      </div>
    </div>`;

  const highlightsHtml = (TOP_PICK.highlights || []).map(h =>
    `<li style="margin-bottom:6px;display:flex;align-items:center;gap:8px"><span>✅</span><span>${h}</span></li>`
  ).join('');

  const heroCurrentPrice = TOP_PICK.current_ltp || TOP_PICK.ltp || TOP_PICK.ltp_at_pick || 0;
  let heroPrevClose = TOP_PICK.prev_close;
  if ((!heroPrevClose || Math.abs(heroPrevClose - (TOP_PICK.ltp_at_pick || heroCurrentPrice)) < 0.05) && DAILY_PICKS_HISTORY && DAILY_PICKS_HISTORY.length > 1) {
    const prev = DAILY_PICKS_HISTORY[1];
    heroPrevClose = prev.session_close || prev.close || prev.ltp_at_pick;
  }

  let heroGapHtml = '⚪ Flat Open (0.00%)';
  let heroGapCls = 'badge-gray';
  if (heroPrevClose && heroPrevClose > 0) {
    const refPickPrice = TOP_PICK.ltp_at_pick || heroCurrentPrice;
    const gAmt = refPickPrice - heroPrevClose;
    const gPct = (gAmt / heroPrevClose) * 100;
    if (Math.abs(gPct) >= 0.01) {
      heroGapCls = gPct > 0 ? 'badge-green' : 'badge-red';
      const gIcon = gPct > 0 ? '▲' : '▼';
      const gTag = gAmt > 0 ? 'Gap Up' : 'Gap Down';
      heroGapHtml = `${gIcon} ${gTag} ${gPct >= 0 ? '+' : ''}${gPct.toFixed(2)}% (${gAmt >= 0 ? '+' : ''}₹${gAmt.toFixed(2)})`;
    }
  }

  const historyRows = (DAILY_PICKS_HISTORY || []).map((h, idx, arr) => {
    const pickPrice = h.ltp_at_pick || h.ltp || 0;
    const curPrice = h.current_ltp || h.ltp || pickPrice;
    const sessionClose = h.session_close || h.close || (idx === 0 ? curPrice : pickPrice);

    // Total P&L from original Pick Entry Price
    const totalPnlAmt = curPrice - pickPrice;
    const totalPnlPct = pickPrice > 0 ? (totalPnlAmt / pickPrice) * 100 : 0;
    const totalCls = totalPnlAmt > 0 ? 'pos' : totalPnlAmt < 0 ? 'neg' : 'neu';

    // Day Change P&L (Current LTP vs Session Close / Prev Close)
    let refClose = sessionClose;
    if (idx === 0 && arr.length > 1) {
      const prev = arr[1];
      refClose = prev.session_close || prev.close || prev.ltp_at_pick || curPrice;
    }
    const dayChgAmt = curPrice - refClose;
    const dayChgPct = refClose > 0 ? (dayChgAmt / refClose) * 100 : 0;
    const dayCls = dayChgAmt > 0 ? 'pos' : dayChgAmt < 0 ? 'neg' : 'neu';

    const stBadge = h.is_pre_market ? '⏳ PENDING MARKET OPEN' : (h.status_badge || '🟢 ACTIVE');
    const stReason = h.status_reason || '';
    const badgeClass = h.is_pre_market ? 'badge-yellow' : (h.status === 'INVALIDATED' ? 'badge-yellow' : h.status === 'INACTIVE' ? 'badge-red' : 'badge-green');

    return `<tr>
      <td><strong style="color:var(--accent2)">${h.display_date || h.date}</strong></td>
      <td>
        <div style="font-weight:700">${h.symbol} ${h.is_pre_market ? '<span style="font-size:10px;color:var(--warn)">(Candidate)</span>' : ''}</div>
        <div style="font-size:11px;color:var(--muted)">${h.name || ''}</div>
      </td>
      <td><span class="badge ${badgeClass}" title="${stReason}">${stBadge}</span></td>
      <td>${scoreBar(h.total_score || 0)}</td>
      <td>
        <div style="font-weight:700">₹${pickPrice.toFixed(2)}</div>
        <div style="font-size:10px;color:var(--muted)">Market Open Entry</div>
      </td>
      <td>
        <div style="font-weight:700;color:var(--text)">₹${sessionClose.toFixed(2)}</div>
        <div style="font-size:10px;color:var(--muted)">Pick Day Close</div>
      </td>
      <td><span class="price" style="font-weight:700">₹${curPrice.toFixed(2)}</span></td>
      <td>
        <span class="${dayCls}" style="font-weight:700">${dayChgAmt >= 0 ? '+' : ''}₹${dayChgAmt.toFixed(2)} (${dayChgPct >= 0 ? '+' : ''}${dayChgPct.toFixed(2)}%)</span>
      </td>
      <td>
        <span class="${totalCls}" style="font-weight:800;font-size:13px">${totalPnlAmt >= 0 ? '+' : ''}₹${totalPnlAmt.toFixed(2)} (${totalPnlPct >= 0 ? '+' : ''}${totalPnlPct.toFixed(2)}%)</span>
      </td>
      <td>
        <button class="btn-add" onclick="openModal('${h.symbol}')">Detail</button>
      </td>
    </tr>`;
  }).join('');

  const currentMkt = calculateCurrentMarketStatus();
  const isPreMktActive = currentMkt.is_pre_market;
  const showStatusWarning = TOP_PICK.status && TOP_PICK.status !== 'ACTIVE' && (TOP_PICK.status !== 'PENDING' || isPreMktActive);

  container.innerHTML = `
    ${mktBannerHtml}

    <div class="hero-spotlight">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <div class="hero-badge-tag">🏆 Stock of the Day · ${TOP_PICK.display_date || TOP_PICK.date}</div>
          ${(TOP_PICK.streak_days && TOP_PICK.streak_days > 1) ? `
          <span class="badge badge-yellow" style="font-weight:700;font-size:12px;padding:6px 12px">
            ⭐ Streak: ${TOP_PICK.streak_days} Consecutive Days (#1 Pick)
          </span>` : `
          <span class="badge badge-purple" style="font-weight:700;font-size:12px;padding:6px 12px">
            ✨ ${isPreMktActive ? "Today's #1 Candidate" : "Today's #1 Highest-Scoring Stock"}
          </span>`}
          <span class="badge ${isPreMktActive ? 'badge-yellow' : (TOP_PICK.status === 'INVALIDATED' ? 'badge-yellow' : TOP_PICK.status === 'INACTIVE' ? 'badge-red' : 'badge-green')}" style="font-weight:700;font-size:12px;padding:6px 12px">
            ${isPreMktActive ? '⏳ PENDING MARKET OPEN' : (TOP_PICK.status_badge && TOP_PICK.status !== 'PENDING' ? TOP_PICK.status_badge : '🟢 ACTIVE')}
          </span>
        </div>
        <div class="badge ${TOP_PICK.tech_class || 'badge-green'}" style="font-size:14px;font-weight:800;padding:8px 18px;border-radius:20px;box-shadow:0 4px 14px rgba(0,0,0,0.3);letter-spacing:0.02em">
          ${TOP_PICK.tech_rating || '🟢 Strong Uptrend'}
        </div>
      </div>

      ${showStatusWarning ? `
      <div class="alert-row alert-SELL" style="margin-bottom:14px;padding:10px 14px;font-size:13px">
        <span>⚠️</span>
        <div>
          <strong>Stock of the Day Status: ${TOP_PICK.status}</strong> — ${TOP_PICK.status_reason || 'Quality score dropped below qualification threshold.'}
          <div style="font-size:11px;margin-top:2px;color:var(--text)">If this stock re-qualifies (Score ≥55, Strength ≥50), its status will automatically restore back to 🟢 ACTIVE.</div>
        </div>
      </div>
      ` : ''}

      <div class="hero-grid">
        <div>
          <div style="font-size:28px;font-weight:800;color:var(--white)">${TOP_PICK.symbol} <span style="font-size:16px;font-weight:400;color:var(--muted)">— ${TOP_PICK.name || ''}</span></div>
          <div style="font-size:13px;color:var(--accent2);margin-top:2px">${TOP_PICK.sector || ''}</div>
          <div style="font-size:26px;font-weight:700;margin:12px 0">
            <span class="price">₹${heroCurrentPrice.toFixed(2)}</span>
          </div>

          <!-- Fundamental Badges -->
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0">
            <span class="badge badge-purple">ROE: ${TOP_PICK.roe_pct != null ? TOP_PICK.roe_pct.toFixed(1) + '%' : '—'}</span>
            <span class="badge badge-green">Debt/Eq: ${TOP_PICK.de_ratio != null ? TOP_PICK.de_ratio.toFixed(2) : '—'}</span>
            <span class="badge badge-purple">Net Margin: ${TOP_PICK.npm_pct != null ? TOP_PICK.npm_pct.toFixed(1) + '%' : '—'}</span>
            <span class="badge badge-yellow">P/E: ${TOP_PICK.pe != null ? TOP_PICK.pe.toFixed(1) : '—'}</span>
          </div>

          <!-- ⚡ Overnight Price Fluctuation & Gap Analysis Card -->
          <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:14px;margin:14px 0">
            <div style="font-size:12px;font-weight:700;color:var(--accent2);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.05em">⚡ Overnight Price Fluctuation & Gap Analysis</div>
            <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:13px">
              <div><span style="color:var(--muted)">Prev Session Close:</span> <strong>₹${heroPrevClose ? heroPrevClose.toFixed(2) : '—'}</strong></div>
              <div><span style="color:var(--muted)">Pick Price (Open Entry):</span> <strong>₹${(TOP_PICK.ltp_at_pick || heroCurrentPrice).toFixed(2)}</strong></div>
              <div><span style="color:var(--muted)">Overnight Fluctuation:</span> <span class="badge ${heroGapCls}" style="font-weight:700">${heroGapHtml}</span></div>
            </div>
          </div>

          <!-- 🎯 7-Day Swing Trade Plan Card -->
          <div style="background:linear-gradient(135deg, rgba(16,185,129,0.1), rgba(108,99,255,0.1));border:1.5px solid var(--green);border-radius:14px;padding:16px;margin:14px 0;box-shadow:0 4px 16px rgba(16,185,129,0.15)">
            <div style="font-size:13px;font-weight:800;color:var(--green);margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
              <span>🎯 Recommended 7-Day Swing Trade Plan</span>
              <span class="badge badge-green" style="font-size:11px;font-weight:700">Timeframe: 3 to 7 Trading Days</span>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;text-align:center">
              <div style="background:var(--card);border:1px solid var(--border);padding:10px;border-radius:10px">
                <div style="font-size:10px;color:var(--muted);text-transform:uppercase;font-weight:700">Suggested Entry</div>
                <div style="font-size:17px;font-weight:800;color:var(--white);margin-top:2px">₹${(TOP_PICK.ltp || TOP_PICK.ltp_at_pick || 0).toFixed(2)}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">Market Price / Breakout</div>
              </div>
              <div style="background:var(--card);border:1px solid var(--danger);padding:10px;border-radius:10px">
                <div style="font-size:10px;color:var(--danger);text-transform:uppercase;font-weight:700">Stop Loss (SL)</div>
                <div style="font-size:17px;font-weight:800;color:var(--danger);margin-top:2px">₹${TOP_PICK.stop_loss != null ? TOP_PICK.stop_loss.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--danger);margin-top:2px">${TOP_PICK.stop_loss_pct || 0}% Below Entry</div>
              </div>
              <div style="background:var(--card);border:1px solid var(--green);padding:10px;border-radius:10px">
                <div style="font-size:10px;color:var(--green);text-transform:uppercase;font-weight:700">Target 1 (1:1.5 R:R)</div>
                <div style="font-size:17px;font-weight:800;color:var(--green);margin-top:2px">₹${TOP_PICK.target1 != null ? TOP_PICK.target1.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--green);margin-top:2px">+${TOP_PICK.target1_pct || 0}% Upside</div>
              </div>
              <div style="background:var(--card);border:1px solid var(--purple);padding:10px;border-radius:10px">
                <div style="font-size:10px;color:var(--purple);text-transform:uppercase;font-weight:700">Target 2 (1:2.5 R:R)</div>
                <div style="font-size:17px;font-weight:800;color:var(--purple);margin-top:2px">₹${TOP_PICK.target2 != null ? TOP_PICK.target2.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--purple);margin-top:2px">+${TOP_PICK.target2_pct || 0}% Upside</div>
              </div>
            </div>
          </div>

          <!-- Technical Analysis Dashboard Grid -->
          <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px;margin:14px 0">
            <div style="font-size:12px;font-weight:700;color:var(--accent2);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.05em">⚡ Technical Analysis & Trend Setup</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px">
              <div class="modal-metric">
                <div class="lbl">50-Day MA</div>
                <div class="val">₹${TOP_PICK.ma50 != null ? TOP_PICK.ma50.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${TOP_PICK.dist_ma50_pct != null ? (TOP_PICK.dist_ma50_pct >= 0 ? '🟢 +' : '🔴 ') + TOP_PICK.dist_ma50_pct + '% vs 50MA' : '—'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">200-Day MA</div>
                <div class="val">₹${TOP_PICK.ma200 != null ? TOP_PICK.ma200.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${TOP_PICK.dist_ma200_pct != null ? (TOP_PICK.dist_ma200_pct >= 0 ? '🟢 +' : '🔴 ') + TOP_PICK.dist_ma200_pct + '% vs 200MA' : '—'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">RSI (14-Day)</div>
                <div class="val" style="color:var(--accent2)">${TOP_PICK.rsi != null ? TOP_PICK.rsi.toFixed(1) : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${TOP_PICK.rsi_status || 'Neutral'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">52W Channel</div>
                <div class="val">₹${TOP_PICK.week_high_52 != null ? TOP_PICK.week_high_52.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${TOP_PICK.dist_52w_high_pct != null ? TOP_PICK.dist_52w_high_pct + '% from High' : '—'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">Vol Spike</div>
                <div class="val">${TOP_PICK.volume_spike != null ? TOP_PICK.volume_spike.toFixed(2) + 'x' : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">10d Avg Volume</div>
              </div>
            </div>
          </div>

          <!-- 🌊 Institutional Money Flow & Price Action Breakdown Card -->
          <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px;margin:14px 0">
            <div style="font-size:12px;font-weight:700;color:var(--accent2);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.05em">🌊 Institutional Order Flow & Price Action Analysis</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px">
              <div class="modal-metric">
                <div class="lbl">Money Flow (CMF)</div>
                <div class="val" style="color:${(TOP_PICK.cmf || 0) >= 0.05 ? '#10b981' : (TOP_PICK.cmf || 0) <= -0.05 ? '#ef4444' : '#fbbf24'}">${TOP_PICK.cmf != null ? (TOP_PICK.cmf >= 0 ? '+' : '') + TOP_PICK.cmf.toFixed(3) : '0.000'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${(TOP_PICK.cmf || 0) >= 0.10 ? '🟢 Accumulation' : (TOP_PICK.cmf || 0) <= -0.10 ? '🔴 Distribution' : '🔵 Neutral Flow'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">Buyer Control (CLV)</div>
                <div class="val" style="color:${(TOP_PICK.clv || 0.5) >= 0.65 ? '#10b981' : '#a5b4fc'}">${TOP_PICK.clv != null ? Math.round((TOP_PICK.clv || 0.5) * 100) + '%' : '50%'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${(TOP_PICK.clv || 0.5) >= 0.65 ? '🟢 Buyer Control' : '⚪ Neutral Close'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">Market Structure</div>
                <div class="val" style="font-size:13px;color:var(--white)">${TOP_PICK.market_structure || 'HH/HL Structure'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">20-Bar Trend</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">Price Action Pattern</div>
                <div class="val" style="font-size:13px;color:var(--accent2)">${TOP_PICK.pa_pattern || 'No Key Trigger'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">FVG / Rejection</div>
              </div>
            </div>
          </div>

          ${highlightsHtml ? `
          <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:14px;margin-top:14px">
            <div style="font-size:12px;font-weight:700;color:var(--accent2);margin-bottom:8px;text-transform:uppercase">Key Selection Thesis</div>
            <ul style="list-style:none;font-size:13px;color:var(--text)">${highlightsHtml}</ul>
          </div>
          ` : ''}

          <div style="display:flex;gap:12px;margin-top:18px">
            <button class="btn-add" onclick="addToWl('${TOP_PICK.symbol}')" ${inWl ? 'disabled' : ''} style="padding:10px 18px;font-size:13px">
              ${inWl ? '✓ In Watchlist' : '⭐ Add Today\'s Pick to Watchlist'}
            </button>
            <button class="btn-add" onclick="openModal('${TOP_PICK.symbol}')" style="background:var(--card2);border:1px solid var(--border);padding:10px 18px;font-size:13px">
              📊 Full Analysis
            </button>
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:12px">
          <div class="hero-score-ring">
            <div class="hero-score-val" style="color:${scoreColor(TOP_PICK.total_score)}">${TOP_PICK.total_score.toFixed(0)}</div>
            <div style="font-size:11px;color:var(--muted);margin-top:6px;text-transform:uppercase;letter-spacing:0.05em">Overall Quality Score</div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
            <div class="wl-score-box"><div class="val" style="color:${scoreColor(TOP_PICK.strength)}">${TOP_PICK.strength.toFixed(0)}</div><div class="lbl">Strength</div></div>
            <div class="wl-score-box"><div class="val" style="color:${scoreColor(TOP_PICK.value)}">${TOP_PICK.value.toFixed(0)}</div><div class="lbl">Value</div></div>
            <div class="wl-score-box"><div class="val" style="color:${scoreColor(TOP_PICK.momentum)}">${TOP_PICK.momentum.toFixed(0)}</div><div class="lbl">Momentum</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Daily Picks History Table -->
    <div style="margin-top:30px">
      <h3 style="font-size:16px;font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:8px">
        <span>📜</span><span>Daily Top Picks History & Performance</span>
      </h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date Stamp</th>
              <th>Stock Pick</th>
              <th>Status</th>
              <th>Score at Pick</th>
              <th>Entry Price (Open)</th>
              <th>Pick Day Close</th>
              <th>Current Price (LTP)</th>
              <th>Today's Change</th>
              <th>Total Return</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${historyRows || `<tr><td colspan="10" class="no-data">No historical picks recorded yet.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// ── Score colour ──────────────────────────────────────────────────────────
function scoreColor(s) {
  if (s >= 70) return '#10b981';
  if (s >= 55) return '#6c63ff';
  if (s >= 40) return '#f59e0b';
  return '#ef4444';
}

function scoreBar(val, max=100) {
  const c = scoreColor(val);
  return `<div class="score-bar-wrap">
    <div class="score-bar"><div class="score-fill" style="width:${val}%;background:${c}"></div></div>
    <div class="score-num" style="color:${c}">${val.toFixed(0)}</div>
  </div>`;
}

function fmt(val, suffix='', dec=1) {
  if (val == null || val === undefined) return '<span class="neu">—</span>';
  const n = parseFloat(val);
  if (isNaN(n)) return '<span class="neu">—</span>';
  const cls = n > 0 ? 'pos' : n < 0 ? 'neg' : 'neu';
  return `<span class="${cls}">${n.toFixed(dec)}${suffix}</span>`;
}

// ── Screener table ────────────────────────────────────────────────────────
function onQualDropdownChange(val) {
  const scoreSlider = document.getElementById('fScore');
  if (!scoreSlider) return;
  if (val === 'all') {
    scoreSlider.value = 0;
  } else if (val === 'qualified') {
    scoreSlider.value = 55;
  } else if (val === 'watch') {
    scoreSlider.value = 45;
  }
}

// ── Screener table ────────────────────────────────────────────────────────
function populateSectorFilter() {
  const select = document.getElementById('fSector');
  if (!select) return;
  const currentVal = select.value || 'all';
  const sectors = Array.from(new Set(SCREENER_DATA.map(s => s.sector).filter(Boolean))).sort();
  select.innerHTML = '<option value="all">All Sectors</option>' +
    sectors.map(sec => `<option value="${sec}">${sec}</option>`).join('');
  select.value = currentVal;
}

const STOCK_SEARCH_ALIASES = {
  "SEKURITIND": ["saint gobain", "saint goban", "saint-gobain", "saintgobain", "saintgoban", "sekurit", "saint gobain glass", "saint goban glasses", "auto glass", "safety glass", "glass", "glasses"],
  "BORANA": ["borosil", "glassware", "borosil glass"],
  "NATIONALUM": ["nalco", "aluminium"],
  "TATAMOTORS": ["tmo", "tata motors", "jaguar", "jlr"],
  "M&M": ["mahindra", "mahindra & mahindra"],
  "RELIANCE": ["ril", "jio"],
  "BAJFINANCE": ["bajaj finance"],
  "BAJAJFINSV": ["bajaj finserv"],
  "HDFCBANK": ["hdfc bank"],
  "ICICIBANK": ["icici bank"],
  "SBIN": ["sbi", "state bank"],
  "BHARTIARTL": ["airtel", "bharti airtel"]
};

function normStr(str) {
  return (str || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function matchSearch(stock, rawQuery) {
  if (!rawQuery || rawQuery.trim().length === 0) return true;
  const qNorm = normStr(rawQuery);
  if (!qNorm) return true;

  const symNorm  = normStr(stock.symbol);
  const nameNorm = normStr(stock.name);
  const secNorm  = normStr(stock.sector);

  if (symNorm.includes(qNorm) || nameNorm.includes(qNorm) || secNorm.includes(qNorm)) return true;

  const aliases = STOCK_SEARCH_ALIASES[stock.symbol] || stock.aliases || [];
  if (aliases.some(a => normStr(a).includes(qNorm) || qNorm.includes(normStr(a)))) return true;

  const rawTokens = rawQuery.toLowerCase().split(/\s+/).map(t => normStr(t)).filter(Boolean);
  if (rawTokens.length > 0) {
    const aliasStr = aliases.map(a => normStr(a)).join(' ');
    const combinedTarget = (symNorm + ' ' + nameNorm + ' ' + secNorm + ' ' + aliasStr).toLowerCase();

    const normToken = (t) => {
      if (t === 'goban') return 'gobain';
      if (t === 'glasses') return 'glass';
      return t;
    };

    return rawTokens.every(t => {
      const nt = normToken(t);
      if (combinedTarget.includes(t) || combinedTarget.includes(nt)) return true;
      if (['glass', 'glasses', 'ltd', 'limited', 'india', 'co', 'inc', 'corp', 'corporation'].includes(t)) return true;
      return false;
    });
  }
  return false;
}

function applyFilters() {
  const search   = document.getElementById('fSearch').value.trim();
  const qual     = document.getElementById('fQual').value;
  const sector   = document.getElementById('fSector') ? document.getElementById('fSector').value : 'all';
  const mcap     = document.getElementById('fMcap') ? document.getElementById('fMcap').value : 'all';
  const trend    = document.getElementById('fTrend').value;

  filteredData = SCREENER_DATA.filter(s => {
    if (!search && qual === 'qualified' && !s.qualified) return false;
    if (!search && qual === 'watch' && s.total_score < 45) return false;

    if (search && !matchSearch(s, search)) return false;

    if (sector !== 'all' && s.sector !== sector) return false;

    if (mcap !== 'all') {
      const mc = s.market_cap || 0;
      if (mcap === 'large' && mc < 200000000000) return false;
      if (mcap === 'mid' && (mc < 50000000000 || mc >= 200000000000)) return false;
      if (mcap === 'small' && (mc <= 0 || mc >= 50000000000)) return false;
    }

    if (trend === 'uptrend_downtrend') {
      const keep = (TREND_CONFIG.uptrend || []).concat([TREND_CONFIG.downtrend]);
      if (!keep.includes(s.trend)) return false;
    } else if (trend !== 'all' && s.trend !== trend) {
      return false;
    }
    return true;
  });

  filteredData.sort((a,b) => sortDir * ((a[sortCol]??-999) - (b[sortCol]??-999)));
  renderTable();
  document.getElementById('resultCount').textContent = `Showing ${filteredData.length} stocks`;

  renderSearchQuickView(search);
}

function renderSearchQuickView(search) {
  const container = document.getElementById('searchQuickView');
  if (!container) return;

  if (!search || search.length < 2) {
    container.innerHTML = '';
    return;
  }

  const qNorm = normStr(search);
  const match = SCREENER_DATA.find(s => normStr(s.symbol) === qNorm) ||
                SCREENER_DATA.find(s => normStr(s.symbol).startsWith(qNorm)) ||
                SCREENER_DATA.find(s => matchSearch(s, search));

  if (!match) {
    container.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px 18px;font-size:13px;color:var(--muted);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
        <div>🔍 No local match for "<strong>${search}</strong>" in current Nifty universe.</div>
        <button onclick="openAddLtStockModal()" style="background:linear-gradient(135deg,#6c63ff,#00d4aa);color:#fff;border:none;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer">➕ Search &amp; Add "${search.toUpperCase()}" via Yahoo Finance</button>
      </div>`;
    return;
  }

  const inWl = watchlist.some(w => w.symbol === match.symbol);
  const trendBadge = match.tech_rating || '🟡 Consolidating Trend';

  container.innerHTML = `
    <div style="background:linear-gradient(135deg,#0e0e24,#151535);border:1.5px solid var(--accent);border-radius:14px;padding:16px 20px;box-shadow:0 8px 24px rgba(108,99,255,0.25);margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
        <div>
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:20px;font-weight:800;color:var(--white)">${match.symbol}</span>
            <span style="font-size:13px;color:var(--muted)">— ${match.name||''}</span>
            <span class="badge ${match.tech_class || 'badge-green'}" style="font-weight:700">${trendBadge}</span>
          </div>
          <div style="font-size:12px;color:var(--accent2);margin-top:2px">${match.sector||''}</div>
        </div>
        <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
          <div>
            <div style="font-size:10px;color:var(--muted);text-transform:uppercase">LTP Price</div>
            <div style="font-size:22px;font-weight:800;color:var(--white)">₹${match.ltp.toFixed(2)}</div>
          </div>
          <div>
            <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Total Score</div>
            <div style="font-size:22px;font-weight:800;color:${scoreColor(match.total_score)}">${match.total_score.toFixed(0)} <span style="font-size:11px;font-weight:400;color:var(--muted)">/ 100</span></div>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn-add" onclick="openModal('${match.symbol}')" style="padding:8px 14px;font-size:12px">📊 Full Metrics & Analysis</button>
            <button class="btn-add" onclick="addToWl('${match.symbol}')" ${inWl?'disabled':''} style="background:var(--card2);border:1px solid var(--border);padding:8px 14px;font-size:12px">
              ${inWl ? '✓ In Watchlist' : '+ Add to Watchlist'}
            </button>
          </div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:12px">
        <div><span style="color:var(--muted)">Strength:</span> <strong style="color:${scoreColor(match.strength)}">${match.strength.toFixed(0)}</strong></div>
        <div><span style="color:var(--muted)">Value:</span> <strong style="color:${scoreColor(match.value)}">${match.value.toFixed(0)}</strong></div>
        <div><span style="color:var(--muted)">Momentum:</span> <strong style="color:${scoreColor(match.momentum)}">${match.momentum.toFixed(0)}</strong></div>
        <div><span style="color:var(--muted)">ROE:</span> <strong>${match.roe_pct != null ? match.roe_pct.toFixed(1) + '%' : '—'}</strong></div>
        <div><span style="color:var(--muted)">D/E Ratio:</span> <strong>${match.de_ratio != null ? match.de_ratio.toFixed(2) : '—'}</strong></div>
        <div><span style="color:var(--muted)">RSI (14):</span> <strong>${match.rsi != null ? match.rsi.toFixed(0) : '—'}</strong></div>
        <div><span style="color:var(--muted)">52W Return:</span> <strong>${match.wk52_return_pct != null ? (match.wk52_return_pct >= 0 ? '+' : '') + match.wk52_return_pct.toFixed(1) + '%' : '—'}</strong></div>
        <div><span style="color:var(--muted)">Vol Spike:</span> <strong>${match.volume_spike != null ? match.volume_spike.toFixed(2) + 'x' : '—'}</strong></div>
      </div>
    </div>`;
}

function resetFilters() {
  if (document.getElementById('fSearch')) document.getElementById('fSearch').value = '';
  if (document.getElementById('fQual')) document.getElementById('fQual').value = 'all';
  if (document.getElementById('fSector')) document.getElementById('fSector').value = 'all';
  if (document.getElementById('fMcap')) document.getElementById('fMcap').value = 'all';
  if (document.getElementById('fTrend')) document.getElementById('fTrend').value = 'all';
  applyFilters();
}

function sortTable(col) {
  if (sortCol === col) sortDir *= -1;
  else { sortCol = col; sortDir = -1; }
  document.querySelectorAll('th').forEach(th => {
    th.classList.remove('sorted-asc','sorted-desc');
    if (th.textContent.replace(/ [↑↓↕]/,'').trim().toLowerCase().replace(/\s/g,'_') === col) {
      th.classList.add(sortDir === -1 ? 'sorted-desc' : 'sorted-asc');
    }
  });
  filteredData.sort((a,b) => {
    let av = a[sortCol];
    let bv = b[sortCol];
    if (av === undefined || av === null) av = (typeof bv === 'string' ? '' : -999999);
    if (bv === undefined || bv === null) bv = (typeof av === 'string' ? '' : -999999);
    if (typeof av === 'string' || typeof bv === 'string') {
      return sortDir * String(av).localeCompare(String(bv));
    }
    return sortDir * (av - bv);
  });
  renderTable();
}

function renderTable() {
  const inWl = new Set(watchlist.map(w=>w.symbol));
  const maxSlots = CONFIG.max_stocks;
  const totalItems = filteredData.length;

  let effectiveSize = (pageSize === 'all') ? totalItems : parseInt(pageSize || 50);
  const totalPages = Math.max(1, Math.ceil(totalItems / (effectiveSize || 1)));

  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;

  const startIdx = (pageSize === 'all') ? 0 : (currentPage - 1) * effectiveSize;
  const endIdx = (pageSize === 'all') ? totalItems : Math.min(totalItems, startIdx + effectiveSize);
  const pagedData = filteredData.slice(startIdx, endIdx);

  const infoEl = document.getElementById('paginationInfo');
  if (infoEl) {
    infoEl.textContent = totalItems === 0
      ? 'No stocks match current filter'
      : `Showing ${startIdx + 1}-${endIdx} of ${totalItems} stocks`;
  }

  const numbersEl = document.getElementById('pageNumbers');
  if (numbersEl) {
    numbersEl.textContent = `Page ${currentPage} of ${totalPages}`;
  }

  const prevBtn = document.getElementById('btnPrevPage');
  const nextBtn = document.getElementById('btnNextPage');
  if (prevBtn) prevBtn.disabled = (currentPage <= 1);
  if (nextBtn) nextBtn.disabled = (currentPage >= totalPages);

  const body = pagedData.map(s => {
    const inWlSet = inWl.has(s.symbol);
    const full = watchlist.length >= maxSlots && !inWlSet;
    const badge = s.qualified
      ? `<span class="badge badge-green">🟢 Qualified</span>`
      : s.total_score >= 45
        ? `<span class="badge badge-yellow">🟡 Watch</span>`
        : `<span class="badge badge-red">🔴 Avoid</span>`;

    const rsVal = s.rs_rating || 50;
    const rsBadge = `<span class="badge ${rsVal>=80?'badge-green':rsVal>=60?'badge-green':rsVal>=40?'badge-gray':'badge-red'}" style="font-size:11px;font-weight:700">RS ${rsVal}</span>`;

    return `<tr>
      <td>
        <div class="stock-name">${s.symbol}</div>
        <div class="stock-sym">${s.name||''}</div>
        <div class="stock-sector">${s.sector||''}</div>
      </td>
      <td><span class="price">₹${s.ltp.toFixed(2)}</span></td>
      <td>${scoreBar(s.total_score)}</td>
      <td>${rsBadge}</td>
      <td>${scoreBar(s.strength)}</td>
      <td>${scoreBar(s.value)}</td>
      <td>${scoreBar(s.momentum)}</td>
      <td>${fmt(s.pe,'',1)}</td>
      <td>${fmt(s.roe_pct,'%')}</td>
      <td>${fmt(s.de_ratio,'',2)}</td>
      <td>${fmt(s.npm_pct,'%')}</td>
      <td>${fmt(s.wk52_return_pct,'%')}</td>
      <td>${fmt(s.rsi,'',0)}</td>
      <td>${s.volume_spike != null ? fmt(s.volume_spike, 'x', 2) : fmt(null)}</td>
      <td><span class="badge ${s.pa_class || 'badge-gray'}" style="font-size:10px;white-space:nowrap" title="${s.pa_pattern || ''}">${s.pa_badge || '⚪ Neutral Flow'}</span></td>
      <td><span class="badge ${s.tech_class || 'badge-yellow'}" style="font-size:11px;white-space:nowrap" title="${s.tech_trend || ''}">${s.tech_rating || s.tech_badge || '🟡 Rangebound'}</span></td>
      <td>${badge}</td>
      <td>
        <button class="btn btn-sm ${inWlSet ? 'btn-danger' : 'btn-primary'}"
                onclick="toggleWatchlist('${s.symbol}')"
                ${full ? 'disabled title="Watchlist is full (20/20)"' : ''}>
          ${inWlSet ? '✓ Added' : '+ Add'}
        </button>
      </td>
    </tr>`;
  }).join('');

  const targetBody = document.getElementById('screenerBody') || document.getElementById('screenerTableBody');
  if (targetBody) targetBody.innerHTML = body;

  const countEl = document.getElementById('resultCount');
  if (countEl) {
    countEl.textContent = `Showing ${totalItems} stock${totalItems !== 1 ? 's' : ''}`;
  }
}

function changePage(delta) {
  currentPage += delta;
  renderTable();
}

function changePageSize(val) {
  pageSize = val;
  currentPage = 1;
  renderTable();
}

function addToWl(symbol) {
  if (watchlist.length >= CONFIG.max_stocks) {
    alert('Phase 1 limit reached: 20 stocks maximum.');
    return;
  }
  const s = SCREENER_DATA.find(x=>x.symbol===symbol);
  if (!s) return;
  if (watchlist.find(w=>w.symbol===symbol)) return;

  watchlist.push({
    symbol: s.symbol,
    ticker: s.ticker,
    name: s.name,
    qty: 0,
    avg_cost: null,
    total_invested: 0,
    added_at: new Date().toISOString().slice(0,10),
    score_at_entry: s.total_score,
    strength_at_entry: s.strength,
    value_at_entry: s.value,
    momentum_at_entry: s.momentum,
    roe_at_entry: s.roe_pct,
    de_at_entry: s.de_ratio,
    npm_at_entry: s.npm_pct,
    current_score: s.total_score,
    current_strength: s.strength,
    current_value: s.value,
    current_momentum: s.momentum,
    ltp: s.ltp,
    sector: s.sector,
    roe_pct: s.roe_pct,
    de_ratio: s.de_ratio,
    npm_pct: s.npm_pct,
    rsi: s.rsi,
    wk52_return_pct: s.wk52_return_pct,
    volume_spike: s.volume_spike,
    today_volume: s.today_volume,
    avg_volume_10d: s.avg_volume_10d,
    news: s.news || [],
    alerts: []
  });
  saveWatchlist();
  updateWlCount();
  renderTable();
  renderStats();
  alert(`✅ ${symbol} added to watchlist!`);
}

function removeFromWl(symbol) {
  if (!confirm(`Remove ${symbol} from watchlist?`)) return;
  watchlist = watchlist.filter(w=>w.symbol!==symbol);
  saveWatchlist();
  updateWlCount();
  renderWatchlist();
  renderStats();
}

function adjustQty(symbol, delta) {
  const item = watchlist.find(w => w.symbol === symbol);
  if (!item) return;
  const currentQty = item.qty || 1;
  const newQty = currentQty + delta;
  if (newQty <= 0) {
    removeFromWl(symbol);
    return;
  }
  item.qty = newQty;
  const avg = item.avg_cost || item.ltp || 0;
  item.total_invested = Math.round(avg * newQty * 100) / 100;
  if (item.ltp && avg) {
    item.unrealised_pnl = Math.round((item.ltp - avg) * newQty * 100) / 100;
    item.unrealised_pct = Math.round(((item.ltp - avg) / avg) * 10000) / 100;
    item.current_value = Math.round(item.ltp * newQty * 100) / 100;
  }
  saveWatchlist();
  renderWatchlist();
  renderStats();
}

function editQtyModal(symbol) {
  const item = watchlist.find(w => w.symbol === symbol);
  if (!item) return;
  const currentQty = item.qty || 1;
  const currentAvg = item.avg_cost ? item.avg_cost.toFixed(2) : (item.ltp ? item.ltp.toFixed(2) : '0.00');

  const newQtyStr = prompt(`Edit Quantity held for ${symbol}:`, currentQty);
  if (newQtyStr === null) return;
  const newQty = parseInt(newQtyStr, 10);
  if (isNaN(newQty) || newQty <= 0) {
    if (confirm(`Set quantity to 0? This will remove ${symbol} from watchlist.`)) {
      removeFromWl(symbol);
    }
    return;
  }

  const newAvgStr = prompt(`Edit Average Buy Price (₹) for ${symbol}:`, currentAvg);
  if (newAvgStr === null) return;
  const newAvg = parseFloat(newAvgStr);
  if (isNaN(newAvg) || newAvg <= 0) return;

  item.qty = newQty;
  item.avg_cost = newAvg;
  item.total_invested = Math.round(newAvg * newQty * 100) / 100;
  if (item.ltp) {
    item.unrealised_pnl = Math.round((item.ltp - newAvg) * newQty * 100) / 100;
    item.unrealised_pct = Math.round(((item.ltp - newAvg) / newAvg) * 10000) / 100;
    item.current_value = Math.round(item.ltp * newQty * 100) / 100;
  }
  saveWatchlist();
  renderWatchlist();
  renderStats();
  alert(`✅ Updated ${symbol}: ${newQty} shares @ ₹${newAvg.toFixed(2)} (Total Invested: ₹${item.total_invested.toLocaleString()})`);
}

function updateWlCount() {
  document.getElementById('wlCount').textContent = watchlist.length;
}

let currentWlSignalFilter = 'ALL';

function filterWlSignal(sig) {
  currentWlSignalFilter = sig;
  ['ALL', 'BUY', 'HOLD', 'SELL'].forEach(s => {
    const btn = document.getElementById('wlSigBtn' + s);
    if (btn) {
      const active = (s === sig);
      btn.style.fontWeight = active ? '700' : '400';
      btn.style.borderWidth = active ? '2px' : '1px';
    }
  });
  renderWatchlist();
}

let wlViewMode = 'cards';
let wlSortCol = 'current_score';
let wlSortDir = -1; // -1 for desc, 1 for asc

function sortWlTable(col) {
  if (wlSortCol === col) {
    wlSortDir *= -1;
  } else {
    wlSortCol = col;
    if (col === 'symbol' || col === 'signal') {
      wlSortDir = 1;
    } else {
      wlSortDir = -1;
    }
  }
  renderWatchlist();
}

function setWlViewMode(mode) {
  wlViewMode = mode;
  const cardsBtn = document.getElementById('wlViewCardsBtn');
  const tableBtn = document.getElementById('wlViewTableBtn');
  const grid = document.getElementById('watchlistGrid');
  const tableWrap = document.getElementById('watchlistTableWrap');

  if (cardsBtn && tableBtn) {
    if (mode === 'cards') {
      cardsBtn.style.background = 'var(--accent)';
      cardsBtn.style.color = '#fff';
      tableBtn.style.background = 'none';
      tableBtn.style.color = 'var(--muted)';
      if (grid) grid.style.display = 'grid';
      if (tableWrap) tableWrap.style.display = 'none';
    } else {
      tableBtn.style.background = 'var(--accent)';
      tableBtn.style.color = '#fff';
      cardsBtn.style.background = 'none';
      cardsBtn.style.color = 'var(--muted)';
      if (grid) grid.style.display = 'none';
      if (tableWrap) tableWrap.style.display = 'block';
    }
  }
  renderWatchlist();
}

function renderWatchlist() {
  const grid = document.getElementById('watchlistGrid');
  const tableWrap = document.getElementById('watchlistTableWrap');
  const tableBody = document.getElementById('watchlistTableBody');
  const empty = document.getElementById('wlEmpty');
  const slotsEl = document.getElementById('slotsUsed');
  const fillEl = document.getElementById('slotFill');
  const invEl = document.getElementById('totalInvested');

  const totalInv = watchlist.reduce((a,w)=>a+(w.total_invested||0),0);
  if (slotsEl) slotsEl.textContent = watchlist.length;
  if (fillEl) fillEl.style.width = (watchlist.length/CONFIG.max_stocks*100)+'%';
  if (invEl) invEl.textContent = Math.round(totalInv).toLocaleString();

  // Summary Banner P&L & Signals
  let totPnl = 0;
  let totCost = 0;
  let cntBuy = 0, cntHold = 0, cntSell = 0;

  watchlist.forEach(w => {
    const activeSig = w.signal || 'HOLD';
    if (activeSig === 'BUY') cntBuy++;
    else if (activeSig === 'SELL') cntSell++;
    else cntHold++;

    if (w.avg_cost && w.ltp && w.qty > 0) {
      totPnl += (w.ltp - w.avg_cost) * w.qty;
      totCost += w.avg_cost * w.qty;
    }
  });

  const pnlEl = document.getElementById('wlPortfolioPnl');
  const pnlPctEl = document.getElementById('wlPortfolioPnlPct');
  const countsEl = document.getElementById('wlSignalCounts');

  if (pnlEl) {
    pnlEl.innerHTML = `<span class="${totPnl >= 0 ? 'pos' : 'neg'}">${totPnl >= 0 ? '+' : ''}₹${totPnl.toFixed(2)}</span>`;
  }
  if (pnlPctEl) {
    const pct = totCost > 0 ? (totPnl / totCost) * 100 : 0;
    pnlPctEl.innerHTML = `<span class="${totPnl >= 0 ? 'pos' : 'neg'}">${totPnl >= 0 ? '+' : ''}${pct.toFixed(2)}%</span>`;
  }
  if (countsEl) {
    countsEl.innerHTML = `<span style="color:var(--green)">🟢 ${cntBuy} BUY</span> <span style="color:var(--warn)">🟡 ${cntHold} HOLD</span> <span style="color:var(--danger)">🔴 ${cntSell} SELL</span>`;
  }

  // Update Watchlist Table Header Sort Arrows
  ['symbol', 'signal', 'ltp', 'unrealised_pnl', 'current_score', 'current_strength', 'roe_pct', 'de_ratio', 'rsi'].forEach(c => {
    const el = document.getElementById('wlSort_' + c);
    if (el) {
      if (wlSortCol === c) {
        el.innerHTML = wlSortDir === -1 ? ' <b style="color:var(--accent2)">▼</b>' : ' <b style="color:var(--accent2)">▲</b>';
      } else {
        el.innerHTML = ' <span style="opacity:0.35;font-size:10px">↕</span>';
      }
    }
  });

  let itemsToDisplay = watchlist;
  if (currentWlSignalFilter !== 'ALL') {
    itemsToDisplay = watchlist.filter(w => {
      const activeSig = w.signal || 'HOLD';
      return activeSig === currentWlSignalFilter;
    });
  }

  // Sort Watchlist items by selected column header
  itemsToDisplay = itemsToDisplay.slice().sort((a, b) => {
    let va = a[wlSortCol];
    let vb = b[wlSortCol];

    if (wlSortCol === 'signal') {
      const sigOrder = { 'BUY': 1, 'HOLD': 2, 'SELL': 3 };
      va = sigOrder[a.signal || 'HOLD'] || 9;
      vb = sigOrder[b.signal || 'HOLD'] || 9;
    } else if (wlSortCol === 'unrealised_pnl') {
      va = (a.avg_cost && a.ltp && a.qty > 0) ? ((a.ltp - a.avg_cost) * a.qty) : -9999999;
      vb = (b.avg_cost && b.ltp && b.qty > 0) ? ((b.ltp - b.avg_cost) * b.qty) : -9999999;
    }

    if (va == null) va = (wlSortDir === 1 ? 'ZZZZZZ' : -9999999);
    if (vb == null) vb = (wlSortDir === 1 ? 'ZZZZZZ' : -9999999);

    if (typeof va === 'string' && typeof vb === 'string') {
      return wlSortDir * va.localeCompare(vb);
    }
    return wlSortDir * (va - vb);
  });

  if (itemsToDisplay.length === 0) {
    if (grid) grid.innerHTML = '';
    if (tableBody) tableBody.innerHTML = '';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  if (wlViewMode === 'cards') {
    if (grid) grid.style.display = 'grid';
    if (tableWrap) tableWrap.style.display = 'none';

    if (grid) {
      grid.innerHTML = itemsToDisplay.map(w => {
        const hasAlert = w.alerts && w.alerts.length > 0;
        const scoreChange = w.score_at_entry != null ? (w.current_score - w.score_at_entry).toFixed(1) : null;
        const scCls = scoreChange > 0 ? 'pos' : scoreChange < 0 ? 'neg' : 'neu';

        const pnl = w.avg_cost && w.ltp && w.qty > 0 ? ((w.ltp - w.avg_cost) * w.qty) : null;
        const pnlPct = w.avg_cost && w.ltp ? ((w.ltp - w.avg_cost)/w.avg_cost*100) : null;

        const activeSig = w.custom_signal || w.signal || 'HOLD';
        const sigBadge = activeSig === 'BUY' ? '🟢 BUY' : activeSig === 'SELL' ? '🔴 SELL' : '🟡 HOLD';
        const sigClass = activeSig === 'BUY' ? 'badge-green' : activeSig === 'SELL' ? 'badge-red' : 'badge-yellow';
        const sigReason = w.signal_reason || '';

        const alertsHtml = (w.alerts||[]).map(a =>
          `<div class="alert-row alert-${a.level}"><span>${a.icon}</span><span>${a.message}</span></div>`
        ).join('');

        return `<div class="wl-card ${hasAlert?'has-alert':''}" style="padding:18px">
          <div class="wl-header" style="margin-bottom:12px">
            <div>
              <div style="display:flex;align-items:center;gap:8px">
                <div class="wl-sym">${w.symbol}</div>
                <span class="badge ${sigClass}" style="font-weight:700;font-size:11px">${sigBadge}</span>
              </div>
              <div class="wl-name">${w.name||''}</div>
              <div class="wl-name" style="margin-top:2px;color:var(--accent2);font-size:11px">${w.sector||''} ${sigReason ? '· ' + sigReason : ''}</div>
              <div onclick="editQtyModal('${w.symbol}')" title="Click to edit quantity or buy price for ${w.symbol}" style="display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--muted);margin-top:6px;background:var(--card2);padding:4px 8px;border-radius:6px;border:1px solid #6c63ff44;cursor:pointer;user-select:none" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='#6c63ff44'">
                <span>Holdings:</span>
                <button onclick="event.stopPropagation();adjustQty('${w.symbol}', -1)" title="Decrease Quantity" style="padding:0 6px;height:18px;line-height:16px;border-radius:3px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-weight:700;font-size:11px">-</button>
                <b style="color:var(--white);font-weight:700">${w.qty||1} Qty</b>
                <button onclick="event.stopPropagation();adjustQty('${w.symbol}', 1)" title="Increase Quantity" style="padding:0 6px;height:18px;line-height:16px;border-radius:3px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-weight:700;font-size:11px">+</button>
                <span>@ <b style="color:var(--white)">₹${w.avg_cost?w.avg_cost.toFixed(2):'0.00'}</b></span>
                <span style="color:#a5b4fc;font-weight:600;font-size:10px;margin-left:2px">✏️ Edit</span>
              </div>
            </div>
            <div style="text-align:right">
              <div class="wl-ltp">${w.ltp?'₹'+w.ltp.toFixed(2):'—'}</div>
              ${pnl!=null?`<div class="wl-pnl ${pnl>=0?'pos':'neg'}" style="font-size:12px">${pnl>=0?'+':''}₹${pnl.toFixed(2)} (${pnlPct.toFixed(2)}%)</div>`:''}
            </div>
          </div>

          <div style="display:flex;align-items:center;justify-content:space-between;background:var(--card2);padding:10px 14px;border-radius:10px;border:1px solid var(--border);margin-bottom:12px">
            <div>
              <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Quality Score</div>
              <div style="font-size:20px;font-weight:800;color:${scoreColor(w.current_score||0)}">${(w.current_score||0).toFixed(0)} <span style="font-size:11px;font-weight:400;color:var(--muted)">/ 100</span></div>
            </div>
            <div style="text-align:center">
              <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Strength</div>
              <div style="font-size:15px;font-weight:700;color:${scoreColor(w.current_strength||0)}">${(w.current_strength||0).toFixed(0)}</div>
            </div>
            <div style="text-align:center">
              <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Momentum</div>
              <div style="font-size:15px;font-weight:700;color:${scoreColor(w.current_momentum||0)}">${(w.current_momentum||0).toFixed(0)}</div>
            </div>
          </div>

          ${alertsHtml?`<div class="wl-alerts" style="margin-bottom:12px">${alertsHtml}</div>`:''}

          <!-- Collapsible Details & Metrics Drawer -->
          <details style="margin-bottom:12px;cursor:pointer">
            <summary style="font-size:12px;font-weight:600;color:var(--accent2);outline:none;user-select:none;padding:4px 0">
              🔍 Details & Metrics (ROE, D/E, RSI, News)
            </summary>
            <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
              ${scoreChange!=null?`<div style="font-size:11px;color:var(--muted);margin-bottom:8px">
                Score since entry: <span class="${scCls}" style="font-weight:600">${scoreChange>0?'+':''}${scoreChange} pts</span> (Entry: ${w.score_at_entry})
              </div>`:''}

              <div class="wl-metrics">
                <div class="wl-metric"><span>ROE</span><span>${w.roe_pct!=null?w.roe_pct.toFixed(1)+'%':'—'}</span></div>
                <div class="wl-metric"><span>D/E</span><span>${w.de_ratio!=null?w.de_ratio.toFixed(2):'—'}</span></div>
                <div class="wl-metric"><span>Margin</span><span>${w.npm_pct!=null?w.npm_pct.toFixed(1)+'%':'—'}</span></div>
                <div class="wl-metric"><span>RSI</span><span>${w.rsi!=null?w.rsi.toFixed(0):'—'}</span></div>
                <div class="wl-metric"><span>52W Ret</span><span>${w.wk52_return_pct!=null?w.wk52_return_pct.toFixed(1)+'%':'—'}</span></div>
                <div class="wl-metric"><span>Vol Spike</span><span>${w.volume_spike!=null?w.volume_spike.toFixed(2)+'x':'—'}</span></div>
                <div class="wl-metric"><span>Qty</span><span>${w.qty||0} shares</span></div>
              </div>

              ${(w.news && w.news.length > 0) ? `
              <div style="margin-top:8px">
                <div style="font-size:11px;font-weight:600;color:var(--muted);margin-bottom:6px">📰 Related News</div>
                <div style="display:flex;flex-direction:column;gap:6px;max-height:120px;overflow-y:auto">
                  ${w.news.slice(0, 2).map(n => `
                    <div style="background:var(--card2);padding:6px 8px;border-radius:6px;font-size:11px;border:1px solid var(--border)">
                      <a href="${n.url}" target="_blank" style="color:var(--text);text-decoration:none;font-weight:500;display:block;line-height:1.3">
                        ${n.title}
                      </a>
                    </div>
                  `).join('')}
                </div>
              </div>
              ` : ''}
            </div>
          </details>

          <div class="wl-footer" style="justify-content:flex-end">
            <div style="display:flex;gap:6px">
              <button class="btn-add" onclick="openModal('${w.symbol}')" style="padding:4px 10px;font-size:11px">Analysis</button>
              <button class="btn-remove" onclick="removeFromWl('${w.symbol}')">Remove</button>
            </div>
          </div>
        </div>`;
      }).join('');
    }
  } else {
    // Table View
    if (grid) grid.style.display = 'none';
    if (tableWrap) tableWrap.style.display = 'block';

    if (tableBody) {
      tableBody.innerHTML = itemsToDisplay.map(w => {
        const pnl = w.avg_cost && w.ltp && w.qty > 0 ? ((w.ltp - w.avg_cost) * w.qty) : null;
        const pnlPct = w.avg_cost && w.ltp ? ((w.ltp - w.avg_cost)/w.avg_cost*100) : null;
        const activeSig = w.signal || 'HOLD';
        const sigBadge = activeSig === 'BUY' ? '🟢 BUY' : activeSig === 'SELL' ? '🔴 SELL' : '🟡 HOLD';
        const sigClass = activeSig === 'BUY' ? 'badge-green' : activeSig === 'SELL' ? 'badge-red' : 'badge-yellow';

        return `<tr>
          <td>
            <div style="font-weight:700">${w.symbol}</div>
            <div style="font-size:11px;color:var(--muted)">${w.name||''}</div>
          </td>
          <td><span class="badge ${sigClass}" style="font-weight:700">${sigBadge}</span></td>
          <td><span class="price">₹${w.ltp ? w.ltp.toFixed(2) : '—'}</span></td>
          <td>${pnl != null ? `<span class="${pnl>=0?'pos':'neg'}" style="font-weight:700">${pnl>=0?'+':''}₹${pnl.toFixed(2)} (${pnlPct.toFixed(2)}%)</span>` : '—'}</td>
          <td>${scoreBar(w.current_score||0)}</td>
          <td>${scoreBar(w.current_strength||0)}</td>
          <td>${fmt(w.roe_pct, '%')}</td>
          <td>${fmt(w.de_ratio, '', 2)}</td>
          <td>${fmt(w.rsi, '', 0)}</td>
          <td>
            <button onclick="editQtyModal('${w.symbol}')" title="Edit Quantity & Buy Price" style="padding:4px 8px;font-size:11px;margin-right:4px;border-radius:4px;border:1px solid #6c63ff55;background:linear-gradient(135deg,#6c63ff22,#00d4aa22);color:#a5b4fc;cursor:pointer;font-weight:600">✏️ Qty</button>
            <button class="btn-add" onclick="openModal('${w.symbol}')" style="padding:4px 8px;font-size:11px;margin-right:4px">Detail</button>
            <button class="btn-remove" onclick="removeFromWl('${w.symbol}')" style="padding:4px 8px;font-size:11px">✕</button>
          </td>
        </tr>`;
      }).join('');
    }
  }
}

// ── Detail Modal ──────────────────────────────────────────────────────────
function openModal(symbol) {
  const s = SCREENER_DATA.find(x=>x.symbol===symbol);
  if (!s) return;
  const inWl = watchlist.find(w=>w.symbol===symbol);
  const maxFull = watchlist.length >= CONFIG.max_stocks && !inWl;

  document.getElementById('modal').innerHTML = `
    <button class="modal-close" onclick="closeModal()">✕</button>
    <h3>${s.symbol}</h3>
    <div style="color:var(--muted);font-size:13px;margin-bottom:4px">${s.name||''} · ${s.sector||''}</div>
    <div style="font-size:22px;font-weight:700;margin:8px 0">₹${s.ltp.toFixed(2)}</div>

    <div style="margin:12px 0">
      <div style="display:flex;gap:12px;margin-bottom:8px">
        ${['Total Score','Strength','Value','Momentum'].map((l,i)=>{
          const v=[s.total_score,s.strength,s.value,s.momentum][i];
          return `<div style="flex:1;background:var(--card2);border-radius:8px;padding:10px;text-align:center">
            <div style="font-size:20px;font-weight:700;color:${scoreColor(v)}">${v.toFixed(0)}</div>
            <div style="font-size:10px;color:var(--muted);margin-top:2px">${l}</div>
          </div>`;
        }).join('')}
      </div>
    </div>

    <div class="modal-grid">
      <div class="modal-metric"><div class="lbl">ROE</div><div class="val">${s.roe_pct!=null?s.roe_pct.toFixed(1)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">ROCE (est.)</div><div class="val">${s.roce_pct!=null?s.roce_pct.toFixed(1)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Debt / Equity</div><div class="val">${s.de_ratio!=null?s.de_ratio.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Net Margin</div><div class="val">${s.npm_pct!=null?s.npm_pct.toFixed(1)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Revenue Growth</div><div class="val">${s.rev_growth_pct!=null?s.rev_growth_pct.toFixed(1)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">P/E (TTM)</div><div class="val">${s.pe!=null?s.pe.toFixed(1):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Div Yield</div><div class="val">${s.div_yield_pct!=null?s.div_yield_pct.toFixed(2)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">RSI (14-day)</div><div class="val">${s.rsi!=null?s.rsi.toFixed(0):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">50-day MA</div><div class="val">${s.ma50!=null?'₹'+s.ma50.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">200-day MA</div><div class="val">${s.ma200!=null?'₹'+s.ma200.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">52-week High</div><div class="val">${s.week_high_52?'₹'+s.week_high_52.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">52-week Low</div><div class="val">${s.week_low_52?'₹'+s.week_low_52.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Vol Spike (10d)</div><div class="val">${s.volume_spike!=null?s.volume_spike.toFixed(2)+'x':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Today's Volume</div><div class="val">${s.today_volume?s.today_volume.toLocaleString():'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Avg Vol (10d)</div><div class="val">${s.avg_volume_10d?s.avg_volume_10d.toLocaleString():'—'}</div></div>
    </div>

    ${(s.corporate_actions && s.corporate_actions.length > 0) ? `
    <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
      <h4 style="font-size:14px;font-weight:600;margin-bottom:10px;color:var(--accent)">🎁 Corporate Actions</h4>
      <div style="display:flex;flex-direction:column;gap:8px;max-height:180px;overflow-y:auto;padding-right:4px">
        ${s.corporate_actions.map(ca => `
          <div style="background:var(--card2);padding:10px;border-radius:8px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
            <div>
              <div style="font-size:13px;font-weight:600;color:var(--white)">${ca.subject || ca.purpose || 'Corporate Action'}</div>
              <div style="font-size:11px;color:var(--muted);margin-top:2px">
                Ex-Date: <span style="color:var(--accent2);font-weight:600">${ca.ex_date || 'N/A'}</span>
                ${ca.record_date ? ` · Record Date: ${ca.record_date}` : ''}
              </div>
            </div>
            <span style="font-size:10px;padding:3px 8px;border-radius:12px;font-weight:700;background:rgba(255,193,7,0.15);color:#ffc107;border:1px solid rgba(255,193,7,0.3)">
              ${ca.type || 'ACTION'}
            </span>
          </div>
        `).join('')}
      </div>
    </div>
    ` : ''}

    ${(s.news && s.news.length > 0) ? `
    <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
      <h4 style="font-size:14px;font-weight:600;margin-bottom:10px;color:var(--accent2)">📰 Related News</h4>
      <div style="display:flex;flex-direction:column;gap:10px;max-height:250px;overflow-y:auto;padding-right:4px">
        ${s.news.map(n => {
          const pubTime = n.pubDate ? new Date(n.pubDate).toLocaleDateString() : '';
          const provider = n.provider ? ` · ${n.provider}` : '';
          const summary = n.summary ? `<p style="font-size:12px;color:var(--muted);margin-top:4px;line-height:1.4">${n.summary}</p>` : '';
          return `
            <div style="background:var(--card2);padding:10px;border-radius:8px;border:1px solid var(--border)">
              <a href="${n.url}" target="_blank" style="color:var(--white);text-decoration:none;font-weight:500;font-size:13px;display:block;line-height:1.4" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='var(--white)'">
                ${n.title}
              </a>
              <div style="font-size:11px;color:var(--muted);margin-top:4px">
                ${pubTime}${provider}
              </div>
              ${summary}
            </div>
          `;
        }).join('')}
      </div>
    </div>
    ` : `
    <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
      <p style="color:var(--muted);font-size:12px">No recent news found for this stock.</p>
    </div>
    `}

    <div class="modal-actions">
      <button class="btn-add" onclick="addToWl('${s.symbol}');closeModal()"
        ${inWl?'disabled':''}
        ${maxFull?'disabled title="20 slots full"':''}
        style="flex:1;padding:10px"
      >${inWl?'✓ Already in Watchlist':'+ Add to Watchlist'}</button>
      <button onclick="closeModal()" style="flex:1;padding:10px;background:var(--card2);border:1px solid var(--border);border-radius:8px;color:var(--text);cursor:pointer">Close</button>
    </div>
  `;
  document.getElementById('modalBg').style.display = 'flex';
}

function closeModal() { document.getElementById('modalBg').style.display = 'none'; }
function openBseModal() {
  document.getElementById('bseModalBg').style.display = 'flex';
  document.getElementById('bseSymbolInput').value = '';
  document.getElementById('bseAddStatus').innerHTML = '';
}
function closeBseModal() {
  document.getElementById('bseModalBg').style.display = 'none';
}

function addCustomBseStock() {
  const input = document.getElementById('bseSymbolInput');
  const statusEl = document.getElementById('bseAddStatus');
  let rawSym = input.value.trim().toUpperCase();

  if (!rawSym) {
    statusEl.innerHTML = '<span style="color:var(--danger)">Please enter a valid ticker or BSE code.</span>';
    return;
  }

  let ticker = rawSym;
  if (/^\d+$/.test(rawSym)) {
    ticker = rawSym + '.BO';
  } else if (!rawSym.includes('.')) {
    ticker = rawSym + '.NS';
  }

  const cleanSym = ticker.replace(/\.(NS|BO)$/i, '');

  if (watchlist.length >= CONFIG.max_stocks) {
    statusEl.innerHTML = '<span style="color:var(--danger)">Watchlist limit reached (20 slots maximum).</span>';
    return;
  }

  if (watchlist.some(w => w.symbol === cleanSym || w.ticker === ticker)) {
    statusEl.innerHTML = `<span style="color:var(--warn)">${cleanSym} is already in your Watchlist.</span>`;
    return;
  }

  const existing = SCREENER_DATA.find(s => s.symbol === cleanSym || s.ticker === ticker);
  if (existing) {
    addToWl(existing.symbol);
    closeBseModal();
    return;
  }

  const newItem = {
    symbol: cleanSym,
    ticker: ticker,
    name: cleanSym + (ticker.endsWith('.BO') ? ' (BSE)' : ''),
    qty: 0,
    avg_cost: null,
    total_invested: 0,
    added_at: new Date().toISOString().slice(0, 10),
    score_at_entry: 50,
    current_score: 50,
    ltp: 0,
    sector: ticker.endsWith('.BO') ? 'BSE Listed' : 'NSE Listed',
    signal: 'BUY',
    signal_reason: 'Custom Added Stock'
  };

  watchlist.push(newItem);
  saveWatchlist();
  updateWlCount();
  renderWatchlist();
  renderStats();
  closeBseModal();
  alert(`✅ Custom Stock ${cleanSym} (${ticker}) added to Watchlist!`);
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeModal();
    closeBseModal();
  }
});

// ── LT Capital Accumulator & Portfolio Functions ─────────────────────────
function syncLtWatchlistHoldings(summary) {
  if (!summary || !Array.isArray(summary.holdings) || !Array.isArray(ltWatchlist)) return;
  const hMap = {};
  summary.holdings.forEach(h => { hMap[h.symbol] = h; });
  ltWatchlist.forEach(item => {
    if (hMap[item.symbol] && hMap[item.symbol].qty > 0) {
      item.holding = hMap[item.symbol];
    } else {
      delete item.holding;
    }
  });
  renderLtWatchlist();
}

function fetchLtPortfolioStatus() {
  // Recalculate days_active client-side so the counter is always current,
  // even when the baked-in LT_PORTFOLIO_SUMMARY is from a previous scan day.
  function recalcDaysActive(summary) {
    if (summary && summary.start_date) {
      try {
        const nseHolidays = ["2026-01-26","2026-03-10","2026-03-24","2026-04-02","2026-04-03","2026-04-14","2026-05-01","2026-05-28","2026-06-26","2026-08-15","2026-08-27","2026-09-16","2026-10-02","2026-10-20","2026-11-09","2026-11-10","2026-11-24","2026-12-25"];
        const parts = summary.start_date.split('-');
        let cur = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        cur.setHours(0, 0, 0, 0);
        let tradingDays = 0;
        while (cur <= today) {
          const dayOfWeek = cur.getDay(); // 0 = Sun, 6 = Sat
          const yyyy = cur.getFullYear();
          const mm = String(cur.getMonth() + 1).padStart(2, '0');
          const dd = String(cur.getDate()).padStart(2, '0');
          const dateStr = `${yyyy}-${mm}-${dd}`;
          if (dayOfWeek !== 0 && dayOfWeek !== 6 && !nseHolidays.includes(dateStr)) {
            tradingDays++;
          }
          cur.setDate(cur.getDate() + 1);
        }
        summary.days_active = Math.max(1, tradingDays);
        const dailyRate = summary.daily_accrual_rate || 100;
        const extraDeposits = summary.extra_deposits || 0;
        summary.total_deposited = parseFloat((summary.days_active * dailyRate + extraDeposits).toFixed(2));
      } catch(e) {}
    }
    return summary;
  }

  if (typeof LT_PORTFOLIO_SUMMARY !== 'undefined' && LT_PORTFOLIO_SUMMARY) {
    recalcDaysActive(LT_PORTFOLIO_SUMMARY);
    renderLtPortfolioSummary(LT_PORTFOLIO_SUMMARY);
    syncLtWatchlistHoldings(LT_PORTFOLIO_SUMMARY);
    if (typeof renderPennyStocksTab === 'function') renderPennyStocksTab();
  }
  fetch('/api/lt-portfolio/status')
    .then(r => r.json())
    .then(res => {
      if (res && res.status === 'ok' && res.summary) {
        recalcDaysActive(res.summary);
        window.LT_PORTFOLIO_SUMMARY = res.summary;
        renderLtPortfolioSummary(res.summary);
        syncLtWatchlistHoldings(res.summary);
        if (typeof renderPennyStocksTab === 'function') renderPennyStocksTab();
      }
    })
    .catch(err => {
      if (typeof LT_PORTFOLIO_SUMMARY !== 'undefined' && LT_PORTFOLIO_SUMMARY) {
        recalcDaysActive(LT_PORTFOLIO_SUMMARY);
        renderLtPortfolioSummary(LT_PORTFOLIO_SUMMARY);
        syncLtWatchlistHoldings(LT_PORTFOLIO_SUMMARY);
        if (typeof renderPennyStocksTab === 'function') renderPennyStocksTab();
      }
    });
}


function openLtHoldingLogModal(symbol) {
  const item = (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist))
    ? ltWatchlist.find(s => s.symbol === symbol)
    : null;
  const holding = item ? item.holding : null;

  if (!holding) {
    alert(`No active holding record found for ${symbol}. Use 🛒 Buy button to record a purchase.`);
    return;
  }

  const pnl = holding.unrealized_pnl || 0;
  const pnlPct = holding.unrealized_pnl_pct || 0;
  const pnlStr = `${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(2)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}%)`;

  const msg = `📋 PURCHASE LOG & HOLDING DETAILS — ${symbol}\n\n` +
    `• Gate Status: 🟢 BOUGHT (Cooling Off Active)\n` +
    `• Quantity Held: ${holding.qty} share(s)\n` +
    `• Avg Buy Price: ₹${parseFloat(holding.avg_price).toFixed(2)}\n` +
    `• Buy Date: ${holding.buy_date || 'N/A'}\n` +
    `• Current Price (LTP): ₹${parseFloat(holding.live_price || (item ? item.ltp : 0) || 0).toFixed(2)}\n` +
    `• Invested Capital: ₹${parseFloat(holding.buy_value || (holding.qty * holding.avg_price)).toFixed(2)}\n` +
    `• Current Value: ₹${parseFloat(holding.market_value || (holding.qty * (holding.live_price || (item ? item.ltp : 0)))).toFixed(2)}\n` +
    `• Live P&L: ${pnlStr}\n` +
    `========================================\n` +
    `This stock is currently held in your portfolio and set to Cooling Off status. You can track its live performance or click "+ Add" if you wish to pyramid.`;

  alert(msg);
}

function renderLtPortfolioSummary(summary) {
  const el = id => document.getElementById(id);
  if (el('ltDayCounterBadge')) el('ltDayCounterBadge').textContent = `DAY ${summary.days_active} ACTIVE`;
  if (el('ltAvailableCashVal')) el('ltAvailableCashVal').textContent = `₹${summary.available_cash.toFixed(2)}`;
  if (el('ltTotalDepositedVal')) el('ltTotalDepositedVal').textContent = `₹${summary.total_deposited.toFixed(2)}`;
  if (el('ltInvestedCapitalVal')) el('ltInvestedCapitalVal').textContent = `₹${summary.invested_capital.toFixed(2)}`;
  if (el('ltPortfolioValueVal')) el('ltPortfolioValueVal').textContent = `₹${summary.current_portfolio_val.toFixed(2)}`;

  if (el('ltTotalPnlVal')) {
    const pnl = summary.total_pnl || 0;
    const pnlCls = pnl > 0 ? '#10b981' : pnl < 0 ? '#ef4444' : 'var(--muted)';
    el('ltTotalPnlVal').innerHTML = `<span style="color:${pnlCls}">P&L: ${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(2)}</span>`;
  }

  const tbody = el('ltHoldingsTableBody');
  if (tbody) {
    if (!summary.holdings || summary.holdings.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="padding:16px;text-align:center;color:var(--muted)">No active holdings yet. Buy stocks when status is 🟢 BUY NOW!</td></tr>`;
    } else {
      tbody.innerHTML = summary.holdings.map(h => {
        const pnlCls = h.unrealized_pnl >= 0 ? '#10b981' : '#ef4444';
        return `
          <tr style="border-bottom:1px solid var(--border)">
            <td style="padding:8px"><strong style="color:#fff">${h.symbol}</strong></td>
            <td style="padding:8px">${h.qty}</td>
            <td style="padding:8px">₹${h.avg_price.toFixed(2)}</td>
            <td style="padding:8px">₹${h.live_price.toFixed(2)}</td>
            <td style="padding:8px">₹${h.buy_value.toFixed(2)}</td>
            <td style="padding:8px">₹${h.market_value.toFixed(2)}</td>
            <td style="padding:8px;font-weight:700;color:${pnlCls}">${h.unrealized_pnl >= 0 ? '+' : ''}₹${h.unrealized_pnl.toFixed(2)} (${h.unrealized_pnl_pct >= 0 ? '+' : ''}${h.unrealized_pnl_pct.toFixed(1)}%)</td>
            <td style="padding:8px">
              <button onclick="openLtSellModal('${h.symbol}', ${h.qty}, ${h.avg_price}, ${h.live_price})" style="background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);color:#ef4444;font-weight:700;font-size:11px;padding:3px 8px;border-radius:6px;cursor:pointer">🔴 Sell</button>
            </td>
          </tr>
        `;
      }).join('');
    }
  }
}

function toggleLtHoldingsDrawer() {
  const drawer = document.getElementById('ltHoldingsDrawer');
  if (drawer) {
    drawer.style.display = (drawer.style.display === 'none' || !drawer.style.display) ? 'block' : 'none';
  }
}

function openLtBuyModal(symbol, ltp) {
  let sym = symbol ? symbol.trim().toUpperCase() : '';
  let priceInfo = ltp && ltp > 0 ? ` (LTP: ₹${ltp.toFixed(2)})` : '';
  alert(`ℹ️ Stock Screener Technical Signals:\n\nStock: ${sym || 'Selected Ticker'}${priceInfo}\n\nUse this Stock Screener for GTT breakout levels, Mansfield RS ratings, and technical discovery.`);
}

function openLtSellModal(symbol, maxQty, avgPrice, ltp) {
  let sym = symbol ? symbol.trim().toUpperCase() : '';
  alert(`ℹ️ Stock Screener Technical Signals:\n\nStock: ${sym || 'Selected Ticker'}\n\nUse this Stock Screener for GTT breakout levels, Mansfield RS ratings, and technical discovery.`);
}

// ── Boot ──────────────────────────────────────────────────────────────────
init();
switchTab('screener');
fetchLtPortfolioStatus();
</script>
</body>
</html>"""


def fetch_15m_history_cffi(ticker: str) -> pd.DataFrame:
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=15m&range=5d"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            res_data = json.loads(r.read().decode('utf-8'))
        res = res_data.get("chart", {}).get("result", [{}])[0]
        timestamps = res.get("timestamp", [])
        quote = res.get("indicators", {}).get("quote", [{}])[0]
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        closes = quote.get("close", [])
        vols = quote.get("volume", [])
        data = []
        if timestamps and closes:
            for idx, (t, c) in enumerate(zip(timestamps, closes)):
                if c is not None:
                    o_val = opens[idx] if idx < len(opens) and opens[idx] is not None else c
                    h_val = highs[idx] if idx < len(highs) and highs[idx] is not None else c
                    l_val = lows[idx] if idx < len(lows) and lows[idx] is not None else c
                    v_val = vols[idx] if idx < len(vols) and vols[idx] is not None else 1
                    data.append({
                        "Date": pd.to_datetime(t, unit="s"),
                        "Open": float(o_val),
                        "High": float(h_val),
                        "Low": float(l_val),
                        "Close": float(c),
                        "Volume": float(v_val)
                    })
        if data:
            return pd.DataFrame(data).set_index("Date")
    except Exception:
        pass
    return pd.DataFrame()


def fetch_1h_history_cffi(ticker: str, days: int = 60) -> pd.DataFrame:
    """
    Fetches 1-hour candle data for an NSE stock (up to 60 days).
    Used exclusively for S/R breakout detection on the correct timeframe.
    Yahoo Finance supports 1h interval for up to 730 days. Uses 30-min disk cache.
    """
    clean_t = ticker.replace(".NS", "").replace(".BO", "")
    c_dir = os.path.join(BASE_DIR, "cache_1h")
    c_file = os.path.join(c_dir, f"{clean_t}.json")
    ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(ist_offset)

    if os.path.exists(c_file):
        try:
            with open(c_file, "r") as f:
                c_data = json.load(f)
            saved_at = datetime.datetime.fromisoformat(c_data.get("saved_at", "2000-01-01"))
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=ist_offset)
            if (now_ist - saved_at).total_seconds() < 1800:
                records = c_data.get("records", [])
                if records:
                    df = pd.DataFrame(records)
                    df["Date"] = pd.to_datetime(df["Date"])
                    df = df.set_index("Date").between_time("09:15", "15:30")
                    return df
        except Exception:
            pass

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1h&range={days}d"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            res_data = json.loads(r.read().decode('utf-8'))
        res = res_data.get("chart", {}).get("result", [{}])[0]
        timestamps = res.get("timestamp", [])
        quote = res.get("indicators", {}).get("quote", [{}])[0]
        opens  = quote.get("open", [])
        highs  = quote.get("high", [])
        lows   = quote.get("low", [])
        closes = quote.get("close", [])
        vols   = quote.get("volume", [])
        data = []
        cache_records = []
        if timestamps and closes:
            for idx, (ts, c) in enumerate(zip(timestamps, closes)):
                if c is None:
                    continue
                o_val = opens[idx]  if idx < len(opens)  and opens[idx]  is not None else c
                h_val = highs[idx]  if idx < len(highs)  and highs[idx]  is not None else c
                l_val = lows[idx]   if idx < len(lows)   and lows[idx]   is not None else c
                v_val = vols[idx]   if idx < len(vols)   and vols[idx]   is not None else 1
                dt_str = str(pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Kolkata"))
                data.append({
                    "Date":   pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Kolkata"),
                    "Open":   float(o_val),
                    "High":   float(h_val),
                    "Low":    float(l_val),
                    "Close":  float(c),
                    "Volume": float(v_val)
                })
                cache_records.append({
                    "Date":   dt_str,
                    "Open":   float(o_val),
                    "High":   float(h_val),
                    "Low":    float(l_val),
                    "Close":  float(c),
                    "Volume": float(v_val)
                })
        if data:
            df = pd.DataFrame(data).set_index("Date")
            df = df.between_time("09:15", "15:30")
            try:
                os.makedirs(c_dir, exist_ok=True)
                with open(c_file, "w") as f:
                    json.dump({"saved_at": now_ist.isoformat(), "records": cache_records}, f)
            except Exception:
                pass
            return df
    except Exception:
        pass
    # Fallback: yfinance
    try:
        t = yf.Ticker(ticker)
        df_yf = t.history(period=f"{days}d", interval="1h")
        if not df_yf.empty:
            try:
                if df_yf.index.tz is None:
                    df_yf.index = df_yf.index.tz_localize("Asia/Kolkata")
                else:
                    df_yf.index = df_yf.index.tz_convert("Asia/Kolkata")
                df_yf = df_yf.between_time("09:15", "15:30")
            except Exception:
                pass
            return df_yf
    except Exception:
        pass
    return pd.DataFrame()


def apply_1h_sr_overlay(scored: dict, ticker: str) -> dict:
    """
    Overlays 1-Hour S/R Breakout detection onto a scored stock dict.
    Fetches 1h candles, updates S/R fields in place, and re-computes swing setup.
    """
    try:
        df_1h = fetch_1h_history_cffi(ticker, days=60)
        if not df_1h.empty and len(df_1h) >= 30:
            from screener_engine import detect_sr_breaks_and_retests, compute_swing_setup
            sr_1h = detect_sr_breaks_and_retests(
                history=None,
                ltp=scored.get("ltp"),
                rs_rating=scored.get("rs_rating", 50),
                rsi=scored.get("rsi"),
                vol_spike=scored.get("volume_spike", 1.0),
                cmf=scored.get("cmf", 0.0),
                df_1h=df_1h
            )
            scored.update(sr_1h)
            scored["sr_1h_available"] = True
            
            # Refresh Swing Setup so 1H breakout bonus is credited
            swing_info = compute_swing_setup(scored)
            scored.update(swing_info)
        else:
            scored["sr_1h_available"] = False
    except Exception:
        scored["sr_1h_available"] = False
    return scored


def fetch_nifty_history() -> tuple[pd.DataFrame, dict]:
    """Fetches NIFTY 50 (^NSEI) historical data and calculates Market Regime."""
    log("Fetching NIFTY 50 benchmark data (^NSEI)...")
    nifty_df = pd.DataFrame()
    try:
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/^NSEI?range=6mo&interval=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode('utf-8'))
        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        quote = result['indicators']['quote'][0]
        nifty_df = pd.DataFrame({
            'Open': quote['open'],
            'High': quote['high'],
            'Low': quote['low'],
            'Close': quote['close'],
            'Volume': quote['volume']
        }, index=pd.to_datetime(timestamps, unit='s'))
        nifty_df = nifty_df.dropna(subset=['Close'])
    except Exception as e:
        log(f"  ⚠ Fast urllib Nifty fetch failed: {e}")

    if nifty_df.empty:
        try:
            t = yf.Ticker("^NSEI")
            nifty_df = t.history(period="6mo")
        except Exception:
            pass

    regime = compute_nifty_market_regime(nifty_df)
    return nifty_df, regime


def fetch_commodity_signals() -> dict:
    log("Fetching 15m intraday commodity data (Crude Oil & Natural Gas)...")
    from screener_engine import calculate_ema_crossover_15m

    # Fetch live USD/INR exchange rate via curl_cffi
    usdinr_rate = fetch_live_price_only("USDINR=X") or 86.50
    log(f"  Live USD/INR Rate: ₹{usdinr_rate:.2f}")

    items = [
        {"id": "crude", "name": "Crude Oil (WTI)", "ticker": "CL=F", "unit": "$", "icon": "🛢️"},
        {"id": "gas",   "name": "Natural Gas",    "ticker": "NG=F", "unit": "$", "icon": "⚡"}
    ]
    results = {}

    for c in items:
        try:
            df_15m = fetch_15m_history_cffi(c["ticker"])
            if df_15m.empty:
                try:
                    t = yf.Ticker(c["ticker"])
                    df_15m = t.history(period="5d", interval="15m")
                except Exception:
                    pass

            calc = calculate_ema_crossover_15m(df_15m)
            curr_usd = calc.get("curr_price")
            mcx_inr_price = round(curr_usd * usdinr_rate, 2) if curr_usd else None

            results[c["id"]] = {
                "name": c["name"],
                "ticker": c["ticker"],
                "unit": c["unit"],
                "icon": c["icon"],
                "usdinr": round(usdinr_rate, 2),
                "mcx_inr_price": mcx_inr_price,
                **calc
            }
            log(f"  ✓ {c['name']} ({c['ticker']}): LTP=${curr_usd} (MCX Est: ₹{mcx_inr_price}) | Signal={calc.get('badge')}")
        except Exception as e:
            log(f"  ⚠ Error fetching commodity {c['ticker']}: {e}")
            results[c["id"]] = {
                "name": c["name"],
                "ticker": c["ticker"],
                "unit": c["unit"],
                "icon": c["icon"],
                "usdinr": round(usdinr_rate, 2),
                "mcx_inr_price": None,
                "signal": "NO_DATA",
                "badge": "⚪ NO DATA",
                "badge_cls": "badge-gray",
                "ema15": None,
                "ema20": None,
                "curr_price": None,
                "diff_pct": 0.0,
                "last_time": ""
            }
    return results


LT_MONTHLY_BATCH_KEY = "lt_monthly_batch"  # marks auto-added entries so next month's
                                            # refresh can replace just this cohort,
                                            # never anything the user added themselves.


def sync_monthly_lt_watchlist_additions(screener_results: list[dict]) -> None:
    """
    Ensures lt_watchlist.json holds a locked monthly cohort of auto-selected
    stocks (quality + momentum, LTP < 600 — see select_monthly_lt_watchlist_
    additions), refreshed only once every 30 days (state tracked in
    LT_MONTHLY_PICKS_FILE). These become real watchlist entries and are
    enriched by process_lt_watchlist() exactly like every manually-added
    stock — same auto-trailing GTT, same BUY_NOW/ACCUMULATE_ON_DIP/WAIT/
    WATCHLIST gate. This function only decides membership; it writes
    lt_watchlist.json and returns nothing, letting the normal
    process_lt_watchlist() read path pick the changes up.

    Never touches entries the user added themselves — only replaces the
    previous auto-added cohort (identified by the LT_MONTHLY_BATCH_KEY tag)
    once its 30-day lock has expired.
    """
    if not screener_results:
        return

    ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    today = datetime.datetime.now(ist_offset).date()

    state = None
    if os.path.exists(LT_MONTHLY_PICKS_FILE):
        try:
            with open(LT_MONTHLY_PICKS_FILE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = None

    if state and state.get("locked_until"):
        try:
            locked_until = datetime.date.fromisoformat(state["locked_until"])
            if today < locked_until:
                return  # still locked — leave lt_watchlist.json untouched this scan
        except Exception:
            pass  # malformed date -> treat as expired, regenerate below

    try:
        with open(LT_WL_FILE, encoding="utf-8") as f:
            lt_stocks = json.load(f)
    except Exception:
        lt_stocks = []
    if not isinstance(lt_stocks, list):
        lt_stocks = []

    # Drop only the PREVIOUS auto-added cohort — everything else (manual entries,
    # holdings) is left exactly as-is.
    prev_batch = set(state.get("batch_symbols", [])) if state else set()
    lt_stocks = [e for e in lt_stocks
                 if not (isinstance(e, dict) and e.get(LT_MONTHLY_BATCH_KEY) and e.get("symbol") in prev_batch)]

    existing_symbols = {e.get("symbol") for e in lt_stocks if isinstance(e, dict) and e.get("symbol")}
    picks = select_monthly_lt_watchlist_additions(screener_results, existing_symbols, top_n=15, max_price=600.0)

    new_entries = []
    for p in picks:
        new_entries.append({
            "symbol": p["symbol"],
            "ticker": p.get("ticker") or f"{p['symbol']}.NS",
            "type": "Auto",
            "sector": p.get("sector") or "",
            "durability_score": round(p.get("lt_quality_score", 0)),
            "portfolio_role": "Monthly Quality+Momentum Pick",
            "gtt_mode": "auto",
            "gtt_level": None,
            "active": True,
            "added_date": today.isoformat(),
            "notes": (f"Auto-selected {today.isoformat()} — Quality "
                      f"{p.get('lt_quality_score', 0):.0f}/100, Momentum {p.get('momentum', 0):.0f}/100, "
                      f"LTP ₹{p.get('ltp', 0):.2f} (< ₹600 cap)."),
            LT_MONTHLY_BATCH_KEY: True,
        })

    lt_stocks.extend(new_entries)
    try:
        with open(LT_WL_FILE, "w", encoding="utf-8") as f:
            json.dump(lt_stocks, f, indent=2)
    except Exception as e:
        log(f"  ⚠ Could not update lt_watchlist.json with monthly picks: {e}")
        return

    new_state = {
        "batch_symbols": [e["symbol"] for e in new_entries],
        "locked_until": (today + datetime.timedelta(days=30)).isoformat(),
        "generated_on": today.isoformat(),
    }
    try:
        with open(LT_MONTHLY_PICKS_FILE, "w", encoding="utf-8") as f:
            json.dump(new_state, f)
        log(f"  🔒 Refreshed monthly LT watchlist cohort: {len(new_entries)} stock(s) added "
            f"(locked until {new_state['locked_until']})")
    except Exception as e:
        log(f"  ⚠ Could not save lt_monthly_picks.json state: {e}")


PENNY_LOCK_DAYS = 30


def _penny_hard_failure(row: dict) -> str | None:
    """Reason a locked penny pick must be dropped, or None if it still stands.

    Deliberately only hard, thesis-breaking conditions -- not score drift. Scores
    move on every scan, so ejecting on those would recreate the churn the monthly
    lock exists to prevent.
    """
    ltp = float(row.get("ltp") or 0.0)
    npm = sane_metric(row, "npm_pct")
    de = sane_metric(row, "de_ratio")

    if not (5.0 <= ltp <= 75.0):
        return f"price ₹{ltp:.2f} left the ₹5–75 band"
    if npm is None or npm <= 0.0:
        return "no longer profitable"
    if de is None or de > 1.0:
        return f"debt/equity {de if de is not None else 'unknown'} breached the 1.0 limit"
    return None


def get_or_refresh_monthly_penny_picks(screener_results: list[dict], top_n: int = 20,
                                       monthly_sip: float = 200.0) -> dict:
    """Return the monthly penny cohort, membership locked but data live.

    The selection is frozen for PENNY_LOCK_DAYS so the list can actually be
    watched and acted on. Prices, entry scores and BUY/WAIT status still refresh
    on every scan -- freezing those would defeat the purpose, which is to catch
    the entry moment on a stable set of names.
    """
    today = datetime.datetime.now().date()

    state = {}
    if os.path.exists(PENNY_MONTHLY_PICKS_FILE):
        try:
            with open(PENNY_MONTHLY_PICKS_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and "locked_until" in raw:
                state = raw
        except Exception as e:
            log(f"  ⚠ Could not read penny_monthly_picks.json ({e}) — reselecting")

    # Score the whole qualifying universe; locked names are looked up in here so
    # they carry current prices and status rather than the values they were
    # selected with.
    scored_all = compute_quality_penny_stocks(screener_results, top_n=10_000, monthly_sip=monthly_sip)
    by_symbol = {(r.get("symbol") or "").upper(): r for r in scored_all}
    raw_by_symbol = {(r.get("symbol") or "").upper(): r for r in screener_results}

    locked_until = state.get("locked_until")
    lock_active = False
    if locked_until:
        try:
            lock_active = datetime.datetime.strptime(locked_until, "%Y-%m-%d").date() > today
        except Exception:
            lock_active = False

    if lock_active and state.get("batch_symbols"):
        picks, ejected = [], []
        for sym in state["batch_symbols"]:
            sym_u = sym.upper()
            reason = _penny_hard_failure(raw_by_symbol.get(sym_u, {})) if sym_u in raw_by_symbol else "no longer in scan universe"
            row = by_symbol.get(sym_u)
            if reason or row is None:
                # Kept visible so a disappearance is explained, but never actionable.
                base = dict(row or raw_by_symbol.get(sym_u, {"symbol": sym}))
                base.update({
                    "status": "EJECTED",
                    "status_badge": "🔴 EJECTED",
                    "status_badge_class": "badge-red",
                    "status_reason": f"Dropped mid-lock — {reason or 'no longer meets penny quality gates'}",
                })
                ejected.append(base)
            else:
                picks.append(row)
        if ejected:
            log(f"  ⚠ Penny lock: {len(ejected)} pick(s) ejected on hard failure")
        return {
            "picks": picks + ejected,
            "locked_until": locked_until,
            "generated_on": state.get("generated_on"),
            "batch_size": len(state.get("batch_symbols", [])),
            "ejected_count": len(ejected),
            "lock_active": True,
        }

    # Lock expired or absent — select a fresh cohort and lock it.
    fresh = scored_all[:top_n]
    new_state = {
        "locked_until": (today + datetime.timedelta(days=PENNY_LOCK_DAYS)).isoformat(),
        "generated_on": today.isoformat(),
        "batch_symbols": [(r.get("symbol") or "").upper() for r in fresh],
    }
    try:
        with open(PENNY_MONTHLY_PICKS_FILE, "w", encoding="utf-8") as f:
            json.dump(new_state, f, indent=2)
        log(f"  🔒 Locked {len(fresh)} penny pick(s) until {new_state['locked_until']}")
    except Exception as e:
        log(f"  ⚠ Could not save penny_monthly_picks.json: {e}")

    return {
        "picks": fresh,
        "locked_until": new_state["locked_until"],
        "generated_on": new_state["generated_on"],
        "batch_size": len(fresh),
        "ejected_count": 0,
        "lock_active": True,
    }


def get_or_refresh_monthly_lt_picks(screener_results: list[dict], lt_watchlist: list[dict]) -> dict:
    """
    Returns the current monthly lock-state metadata so the HTML can show
    the locked-until date, batch size, and generated-on date.
    The actual auto-picks are now real lt_watchlist.json entries (tagged with
    LT_MONTHLY_BATCH_KEY=True) and rendered by the existing LT Watchlist
    dashboard — no separate showcase needed.

    Returns a dict: { picks: [], locked_until: str|None, generated_on: str|None, batch_size: int }
    """
    state = {}
    if os.path.exists(LT_MONTHLY_PICKS_FILE):
        try:
            with open(LT_MONTHLY_PICKS_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            # New format: { locked_until, generated_on, batch_symbols }
            if isinstance(raw, dict) and "locked_until" in raw:
                state = raw
        except Exception:
            pass

    batch_symbols = state.get("batch_symbols", [])
    return {
        "picks": [],          # picks now live in lt_watchlist.json, not here
        "locked_until":  state.get("locked_until"),
        "generated_on":  state.get("generated_on"),
        "batch_size":    len(batch_symbols),
        "batch_symbols": batch_symbols,
    }


def build_html(screener_results: list[dict], watchlist: list[dict], lt_watchlist: list[dict], commodity_signals: dict, mkt_info: dict, fno_data: list[dict] | None = None) -> str:
    run_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    penny_monthly = get_or_refresh_monthly_penny_picks(screener_results, top_n=20, monthly_sip=200.0)
    penny_stocks_data = penny_monthly["picks"]
    intraday_data = compute_intraday_picks(screener_results, top_n=5)
    monthly_lt_data = get_or_refresh_monthly_lt_picks(screener_results, lt_watchlist)
    lt_summary = get_lt_portfolio_summary(screener_results)

    replacements = {
        "__PHASE_LABEL__": cfg["phase_label"],
        "__PHASE_BUDGET__": f"{cfg['phase_budget_per_stock']:,}",
        "__MAX_STOCKS__": str(cfg["max_stocks"]),
        "__TOTAL_BUDGET__": f"{cfg['total_budget']:,}",
        "__RUN_TIME__": run_time,
        "__WATCHLIST_JSON__": json.dumps(watchlist, ensure_ascii=False, default=json_serializer),
        "__LT_WATCHLIST_JSON__": json.dumps(lt_watchlist, ensure_ascii=False, default=json_serializer),
        "__CONFIG_JSON__": json.dumps(cfg, ensure_ascii=False, default=json_serializer),
        "__COMMODITIES_JSON__": json.dumps(commodity_signals, ensure_ascii=False, default=json_serializer),
        "__MARKET_INFO_JSON__": json.dumps(mkt_info, ensure_ascii=False, default=json_serializer),
        "__FNO_JSON__": json.dumps(fno_data or [], ensure_ascii=False, default=json_serializer),
        "__PENNY_STOCKS_JSON__": json.dumps(penny_stocks_data, ensure_ascii=False, default=json_serializer),
        "__INTRADAY_JSON__": json.dumps(intraday_data, ensure_ascii=False, default=json_serializer),
        "__LT_MONTHLY_JSON__": json.dumps(monthly_lt_data, ensure_ascii=False, default=json_serializer),
        "__LT_PORTFOLIO_SUMMARY_JSON__": json.dumps(lt_summary, ensure_ascii=False, default=json_serializer),
        # Trend vocabulary comes from screener_engine.TREND_STATES so the filter
        # dropdown and the JS badge logic cannot drift from what the classifier
        # actually emits. Adding a state there surfaces it here automatically.
        "__TREND_STATES_JSON__": json.dumps(
            {
                "states": TREND_STATES,
                "uptrend": list(UPTREND_STATES),
                "downtrend": TREND_DOWNTREND,
            },
            ensure_ascii=False, default=json_serializer,
        ),
        "__TREND_OPTIONS_HTML__": "\n".join(
            f'          <option value="{state}">{meta["badge"]}</option>'
            for state, meta in TREND_STATES.items()
        ),
    }

    # ── Split the template into: (head+body markup, CSS, app JS) ──────────
    # The full scan dataset used to be inlined directly into every page load via
    # __SCREENER_JSON__ (an ~10MB string substitution), and the CSS/JS were embedded
    # in the HTML itself, so every visit re-downloaded everything uncached. CSS/JS are
    # now written out as separate static files the browser can cache across scans, and
    # the scan data is fetched once from /screener_data.json instead of being inlined.
    STYLE_OPEN, STYLE_CLOSE = "<style>", "</style>"
    SCRIPT_OPEN, SCRIPT_CLOSE = "<script>", "</script>"

    style_start = HTML_TEMPLATE.index(STYLE_OPEN)
    style_content_start = style_start + len(STYLE_OPEN)
    style_end = HTML_TEMPLATE.index(STYLE_CLOSE, style_content_start)
    css_content = HTML_TEMPLATE[style_content_start:style_end]

    # The first <script>...</script> pair (before <style>) is the tiny window.onerror
    # handler and stays inline; this locates the second, much larger app-logic block.
    script_start = HTML_TEMPLATE.index(SCRIPT_OPEN, style_end)
    script_content_start = script_start + len(SCRIPT_OPEN)
    script_end = HTML_TEMPLATE.index(SCRIPT_CLOSE, script_content_start)
    js_raw = HTML_TEMPLATE[script_content_start:script_end]
    tail_markup = HTML_TEMPLATE[script_end + len(SCRIPT_CLOSE):]

    # app.js must not carry per-scan data (that would defeat long-lived caching), so
    # the data-let block gets empty defaults instead of the __X_JSON__ tokens, and the
    # boot-time invocation moves to the small per-scan inline script below (data must
    # be fetched and assigned before init() runs).
    data_let_block = (
        "let SCREENER_DATA = __SCREENER_JSON__;\n"
        "let WATCHLIST_SEED = __WATCHLIST_JSON__;\n"
        "let LT_WATCHLIST = __LT_WATCHLIST_JSON__;\n"
        "let CONFIG = __CONFIG_JSON__;\n"
        "let COMMODITIES_DATA = __COMMODITIES_JSON__;\n"
        "let MARKET_INFO = __MARKET_INFO_JSON__;\n"
        "let FNO_DATA = __FNO_JSON__;\n"
        "let PENNY_STOCKS_DATA = __PENNY_STOCKS_JSON__;\n"
        "let INTRADAY_DATA = __INTRADAY_JSON__;\n"
        "let LT_MONTHLY_PICKS = __LT_MONTHLY_JSON__;\n"
        "let LT_PORTFOLIO_SUMMARY = __LT_PORTFOLIO_SUMMARY_JSON__;\n"
        "let TREND_CONFIG = __TREND_STATES_JSON__;"
    )
    # `var`, not `let`: app.js declares these once with empty defaults, and the small
    # per-scan inline <script> below re-declares them with real values. Two separate
    # <script> tags share one global lexical scope in classic (non-module) documents,
    # so a second top-level `let` for the same name is a SyntaxError there — `var`
    # is the one declaration form that's allowed to be redeclared like this.
    data_let_defaults = (
        "var SCREENER_DATA = [];\n"
        "var WATCHLIST_SEED = [];\n"
        "var LT_WATCHLIST = [];\n"
        "var CONFIG = {};\n"
        "var COMMODITIES_DATA = {};\n"
        "var MARKET_INFO = {};\n"
        "var FNO_DATA = [];\n"
        "var PENNY_STOCKS_DATA = [];\n"
        "var INTRADAY_DATA = {};\n"
        "var LT_MONTHLY_PICKS = {};\n"
        "var LT_PORTFOLIO_SUMMARY = {};\n"
        "var TREND_CONFIG = { states: {}, uptrend: [], downtrend: '' };"
    )
    if data_let_block not in js_raw:
        raise RuntimeError("build_html: data-let block not found in app script — template shape changed, fix the split logic")
    app_js = js_raw.replace(data_let_block, data_let_defaults, 1)

    boot_invocation = "init();\nswitchTab('screener');\nfetchLtPortfolioStatus();\n"
    if boot_invocation not in app_js:
        raise RuntimeError("build_html: boot invocation not found in app script — template shape changed, fix the split logic")
    app_js = app_js.replace(boot_invocation, "", 1)

    try:
        atomic_write_file(APP_CSS_FILE, css_content)
        atomic_write_file(APP_JS_FILE, app_js)
        # Mirror into www/static/ too — see WWW_STATIC_DIR comment above.
        atomic_write_file(WWW_APP_CSS_FILE, css_content)
        atomic_write_file(WWW_APP_JS_FILE, app_js)
    except Exception as e:
        log(f"⚠ Could not write static assets (app.css/app.js): {e}")

    # Content-hashed query param so a redeploy that changes app.css/app.js is always
    # visible immediately — without this, a browser holding the previous version
    # cached under a fixed max-age would keep using stale JS for up to the cache
    # lifetime after a redeploy, exactly the kind of silent breakage this split was
    # supposed to avoid.
    css_ver = hashlib.md5(css_content.encode("utf-8")).hexdigest()[:10]
    js_ver = hashlib.md5(app_js.encode("utf-8")).hexdigest()[:10]

    head_and_body_markup = (
        HTML_TEMPLATE[:style_start]
        + f'<link rel="stylesheet" href="/static/app.css?v={css_ver}">'
        + HTML_TEMPLATE[style_end + len(STYLE_CLOSE):script_start]
    )

    # Small, per-scan-changing blobs stay inlined (all small); SCREENER_DATA itself is
    # fetched from screener_data.json before init() runs, replacing the old inline-or-
    # fallback branching that used to live inside init().
    small_data_js = (
        f"var WATCHLIST_SEED = {replacements['__WATCHLIST_JSON__']};\n"
        f"var LT_WATCHLIST = {replacements['__LT_WATCHLIST_JSON__']};\n"
        f"var CONFIG = {replacements['__CONFIG_JSON__']};\n"
        f"var COMMODITIES_DATA = {replacements['__COMMODITIES_JSON__']};\n"
        f"var MARKET_INFO = {replacements['__MARKET_INFO_JSON__']};\n"
        f"var FNO_DATA = {replacements['__FNO_JSON__']};\n"
        f"var PENNY_STOCKS_DATA = {replacements['__PENNY_STOCKS_JSON__']};\n"
        f"var INTRADAY_DATA = {replacements['__INTRADAY_JSON__']};\n"
        f"var LT_MONTHLY_PICKS = {replacements['__LT_MONTHLY_JSON__']};\n"
        f"var LT_PORTFOLIO_SUMMARY = {replacements['__LT_PORTFOLIO_SUMMARY_JSON__']};\n"
        # Without this the page keeps app.js's empty default, so every trend badge
        # renders neutral grey and the uptrend filter matches nothing.
        f"var TREND_CONFIG = {replacements['__TREND_STATES_JSON__']};\n"
        "var SCREENER_DATA = [];\n"
    )
    # app.js MUST load first — it declares WATCHLIST_SEED/LT_WATCHLIST/CONFIG/etc as
    # empty `var` defaults. If a separate inline <script> sets them to real data BEFORE
    # app.js runs, app.js's own default declarations execute afterward and silently
    # overwrite the real data back to empty (var redeclaration always takes the LAST
    # assignment) — this exact ordering bug was why the LT Watchlist (and everything
    # else fed through this same small-data-blob mechanism) kept rendering empty
    # despite screener_data.json / the page source both having real data. Real values
    # must be assigned in ONE inline script that runs strictly after app.js.
    bootstrap_script = (
        f'<script src="/static/app.js?v={js_ver}"></script>\n'
        "<script>\n"
        + small_data_js
        + "fetch('/screener_data.json', {cache: 'no-store'})\n"
        "  .then(function(r){ return r.json(); })\n"
        "  .then(function(data){\n"
        "    SCREENER_DATA = Array.isArray(data) ? data : [];\n"
        "    init();\n"
        "    switchTab('screener');\n"
        "    fetchLtPortfolioStatus();\n"
        "  })\n"
        "  .catch(function(err){\n"
        "    console.error('Failed to load screener_data.json:', err);\n"
        "    var errDiv = document.createElement('div');\n"
        "    errDiv.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:999999;background:#991b1b;color:#fff;padding:12px 20px;text-align:center;font-family:sans-serif;';\n"
        "    errDiv.textContent = '\\u26A0\\uFE0F Could not load stock data. Please refresh the page.';\n"
        "    if (document.body) document.body.prepend(errDiv);\n"
        "  });\n"
        "</script>\n"
    )

    import re
    pattern = re.compile("|".join(re.escape(k) for k in replacements.keys()))
    final_head_and_body = pattern.sub(lambda m: replacements[m.group(0)], head_and_body_markup)
    return final_head_and_body + bootstrap_script + tail_markup


# ─── Local HTTP Scan Server ───────────────────────────────────────────────────

def sync_html_lt_watchlist():
    try:
        lt_wl_data = process_lt_watchlist(LATEST_SCREENER_RESULTS)
        lt_json = json.dumps(lt_wl_data, default=json_serializer)
        # NOTE: the template declares this with `let`/`var`, not `const` — searching for
        # "const LT_WATCHLIST = " here always returned -1, so this whole function was
        # a silent no-op: LT watchlist edits never got patched into the already-built
        # HTML until the next full rescan. Also anchor the terminator on ";\n" rather
        # than the first bare ";", since json.dumps escapes real newlines inside string
        # values, so a raw "\n" byte can only appear right after the statement's own
        # closing semicolon, not truncate mid-value.
        target = "var LT_WATCHLIST = "
        for path in [OUT_HTML, OUT_WWW_HTML]:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                idx = content.find(target)
                if idx != -1:
                    end_idx = content.find(";\n", idx)
                    if end_idx != -1:
                        new_content = content[:idx] + target + lt_json + content[end_idx:]
                        atomic_write_file(path, new_content)
    except Exception as e:
        log(f"⚠ Could not sync LT_WATCHLIST in HTML: {e}")


class ScanRequestHandler(http.server.SimpleHTTPRequestHandler):
    def handle_ltp_request(self):
        parsed = urllib.parse.urlparse(self.path)
        tickers = []
        if self.command == 'POST':
            try:
                length = int(self.headers.get('Content-Length', 0))
                if length > 0:
                    body = self.rfile.read(length).decode('utf-8')
                    req_json = json.loads(body)
                    if isinstance(req_json, dict):
                        raw_syms = req_json.get('symbols') or req_json.get('ticker') or req_json.get('symbol') or []
                        if isinstance(raw_syms, list):
                            tickers = [str(t).strip() for t in raw_syms if str(t).strip()]
                        elif isinstance(raw_syms, str):
                            tickers = [t.strip() for t in raw_syms.split(',') if t.strip()]
            except Exception:
                pass

        if not tickers:
            query = urllib.parse.parse_qs(parsed.query)
            raw_ticker = query.get('ticker', [''])[0] or query.get('symbols', [''])[0] or query.get('symbol', [''])[0]
            tickers = [t.strip() for t in raw_ticker.split(',') if t.strip()]

        raw_prices = {}
        stale_set = set()
        # Initialised outside the `if tickers:` guard because the map-back loop at the
        # end of this method reads it unconditionally. When a request arrived with no
        # symbols -- a poll fired before the table populates, or a malformed body --
        # this stayed unbound and raised UnboundLocalError, killing the handler
        # thread. Enough of those took the whole server down and the supervisor
        # restarted it mid-session.
        normalized_map = {}
        if tickers:
            # Normalize symbol list (e.g. COALINDIA -> COALINDIA.NS) so Yahoo Finance live fetcher works 100%
            normalized_tickers = []
            for raw_t in tickers:
                t_clean = raw_t.strip()
                if not t_clean: continue
                if t_clean.startswith("^") or t_clean.endswith(".NS") or t_clean.endswith(".BO"):
                    norm = t_clean
                else:
                    norm = f"{t_clean}.NS"
                normalized_map[raw_t] = norm
                if norm not in normalized_tickers:
                    normalized_tickers.append(norm)

            # Register every requested symbol, not just cache misses. The startup
            # pre-seed makes everything look cached initially, so registering only
            # misses would leave the warmer with an empty set and nothing would ever
            # refresh.
            note_hot_symbols(normalized_tickers)

            # Build lookup dict from latest screener results as instant fallback
            fallback_map = {}
            if LATEST_SCREENER_RESULTS:
                for s in LATEST_SCREENER_RESULTS:
                    sym = s.get("symbol")
                    tick = s.get("ticker")
                    p = s.get("ltp") or s.get("current_ltp")
                    if p and p > 0:
                        if sym:
                            fallback_map[sym] = float(p)
                            fallback_map[f"{sym}.NS"] = float(p)
                        if tick:
                            fallback_map[tick] = float(p)
                            fallback_map[tick.replace(".NS", "")] = float(p)

            # Fast cache lookup first (no threads needed for cached tickers)
            now = time.time()
            # Sized to the warmer's real cycle time, not the browser's poll interval.
            # At the old 10s TTL every poll considered every price expired and fell
            # through to the scan-time fallback, so the UI reported stale prices even
            # while the warmer was refreshing them normally.
            ttl = LTP_FRESH_WINDOW_SEC if is_equity_market_open() else 600.0
            uncached = []

            with GLOBAL_LTP_CACHE_LOCK:
                for norm_t in normalized_tickers:
                    cached_entry = GLOBAL_LTP_CACHE.get(norm_t)
                    if cached_entry and (now - cached_entry[1] < ttl):
                        raw_prices[norm_t] = cached_entry[0]
                    else:
                        uncached.append(norm_t)

            if uncached:
                # Skip live network fetches while the background scan is running (it's
                # already saturating outbound requests), but the fallback lookup below
                # must still run unconditionally — it previously lived inside this same
                # `if not IS_INITIAL_SCANNING` gate, which meant every ticker not already
                # in GLOBAL_LTP_CACHE got literally NO price (not even a stale one) for
                # the entire duration of every background scan, i.e. on every server
                # restart. That's the main reason LTP polling looked broken right after
                # launching the app.
                # Deliberately no network call here. This handler is now cache-only:
                # the background warmer owns fetching, so a poll returns immediately
                # with the freshest price already available instead of blocking for
                # 30-190s on yf.download and stacking up behind the 10s poll interval.
                note_hot_symbols(uncached)

                # Fallback to static (last-scan) price whenever a live fetch failed,
                # returned nothing, or was skipped above because a scan is in progress.
                for t in uncached:
                    if t not in raw_prices or not raw_prices[t]:
                        fb = fallback_map.get(t) or fallback_map.get(t.replace('.NS', ''))
                        if fb and fb > 0:
                            raw_prices[t] = fb
                            stale_set.add(t)

        prices_map = {}
        stale_map = {}
        for norm_t, p in raw_prices.items():
            if p and p > 0:
                is_stale = norm_t in stale_set
                clean = norm_t.replace('.NS', '').strip()
                for key in (norm_t, clean, clean.upper()):
                    prices_map[key] = p
                    stale_map[key] = is_stale
                if norm_t == '^NSEI' or clean == '^NSEI':
                    prices_map['NIFTY_INDEX'] = p
                    prices_map['NIFTY'] = p
                    stale_map['NIFTY_INDEX'] = is_stale
                    stale_map['NIFTY'] = is_stale

        # Map back to raw input requested symbols
        for raw_t, norm_t in normalized_map.items():
            if norm_t in prices_map:
                prices_map[raw_t] = prices_map[norm_t]
                stale_map[raw_t] = stale_map.get(norm_t, False)

        first_price = prices_map.get(tickers[0]) if tickers else None
        resp_data = json.dumps({
            "status": "success",
            "ticker": tickers[0] if tickers else "",
            "price": first_price,
            "prices": prices_map,
            "ltps": prices_map,
            "stale": stale_map
        }).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(resp_data)))
        self.end_headers()
        self.wfile.write(resp_data)
        try:
            self.wfile.flush()
        except Exception:
            pass

    def end_headers(self):
        super().end_headers()
        try:
            self.wfile.flush()
        except Exception:
            pass

    def send_json_response(self, data: dict, status_code: int = 200):
        """Send JSON response for mobile API."""
        resp_data = json.dumps(data, default=json_serializer).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(resp_data)))
        self.end_headers()
        self.wfile.write(resp_data)
        try:
            self.wfile.flush()
        except Exception:
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Requested-With, Accept')
        self.send_header('Content-Length', '0')
        self.end_headers()
        try:
            self.wfile.flush()
        except Exception:
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            content = None
            if os.path.exists(OUT_HTML):
                try:
                    with open(OUT_HTML, 'rb') as f:
                        content = f.read()
                except Exception:
                    content = None

            if not content or len(content) < 1000:
                time.sleep(0.3)
                if os.path.exists(OUT_HTML):
                    try:
                        with open(OUT_HTML, 'rb') as f:
                            content = f.read()
                    except Exception:
                        pass

            if content and len(content) > 1000:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                try: self.wfile.flush()
                except Exception: pass
            else:
                loading_page = (
                    "<!DOCTYPE html><html><head><meta charset='utf-8'/><meta http-equiv='refresh' content='2'/>"
                    "<title>Stock Screener - Loading</title><style>"
                    "body{background:#06060f;color:#e2e8f0;font-family:sans-serif;display:flex;"
                    "flex-direction:column;justify-content:center;align-items:center;height:100vh;margin:0;}"
                    ".spinner{border:4px solid #1e1e3a;border-top:4px solid #00d4aa;border-radius:50%;"
                    "width:48px;height:48px;animation:spin 1s linear infinite;margin-bottom:20px;}"
                    "@keyframes spin{0%{transform:rotate(0deg);}100%{transform:rotate(360deg);}}"
                    "h2{color:#6c63ff;margin-bottom:8px;}p{color:#64748b;font-size:14px;}"
                    "</style></head><body><div class='spinner'></div>"
                    "<h2>⚡ Stock Screener Server Initializing...</h2>"
                    "<p>Building stock database & generating report. Auto-refreshing in 2 seconds...</p>"
                    "</body></html>"
                ).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(loading_page)))
                self.end_headers()
                self.wfile.write(loading_page)
                try: self.wfile.flush()
                except Exception: pass
            return

        elif parsed.path in ('/static/app.css', '/static/app.js'):
            asset_path = APP_CSS_FILE if parsed.path.endswith('.css') else APP_JS_FILE
            content_type = 'text/css; charset=utf-8' if parsed.path.endswith('.css') else 'application/javascript; charset=utf-8'
            try:
                with open(asset_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                # Safe to cache indefinitely: the URL carries a content hash in ?v=,
                # so a redeploy that changes app.css/app.js always produces a new URL
                # instead of silently reusing a stale cached copy of the old one.
                self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                try: self.wfile.flush()
                except Exception: pass
            except Exception:
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()
            return

        elif parsed.path == '/screener_data.json':
            try:
                with open(OUT_JSON_FILE, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                # Regenerated on every scan — never let the browser reuse a cached copy.
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                try: self.wfile.flush()
                except Exception: pass
            except Exception:
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()
            return

        elif parsed.path == '/api/ltp':
            self.handle_ltp_request()
            return
        elif parsed.path == '/api/lt-watchlist':
            data = process_lt_watchlist(LATEST_SCREENER_RESULTS)
            resp_bytes = json.dumps(data, default=json_serializer).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Content-Length', str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
            try: self.wfile.flush()
            except Exception: pass
            return
        elif parsed.path in ('/health', '/api/health'):
            resp_bytes = json.dumps({"status": "online", "app": "Stock Screener"}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
            try: self.wfile.flush()
            except Exception: pass
            return
        elif parsed.path == '/api/status':
            mkt_info = get_market_status()
            res = {
                "server": "running",
                "market_info": mkt_info,
                "out_html": OUT_HTML,
                "timestamp": datetime.datetime.now().isoformat(),
                "is_scanning": IS_INITIAL_SCANNING,
                "last_scan_completed_at": LAST_SCAN_COMPLETED_AT
            }
            resp_bytes = json.dumps(res).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Length', str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
            try: self.wfile.flush()
            except Exception: pass
            return
        elif parsed.path == '/api/lt-portfolio/status':
            try:
                summary = get_lt_portfolio_summary(LATEST_SCREENER_RESULTS)
                res = {"status": "ok", "summary": summary}
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            resp_bytes = json.dumps(res, default=json_serializer).encode('utf-8')
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Content-Length', str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)
            try: self.wfile.flush()
            except Exception: pass
            return
        else:
            super().do_GET()

    def do_POST(self):
        global LATEST_SCREENER_RESULTS, LAST_SCAN_COMPLETED_AT
        parsed = urllib.parse.urlparse(self.path)

        # Mobile API endpoints
        if parsed.path == '/api/mobile/screener':
            self.send_json_response(get_screener_data())
            return
        if parsed.path == '/api/mobile/watchlist':
            self.send_json_response(get_lt_watchlist())
            return
        if parsed.path == '/api/mobile/holdings':
            self.send_json_response(get_holdings())
            return
        if parsed.path == '/api/mobile/status':
            self.send_json_response(get_app_status())
            return
        if parsed.path.startswith('/api/mobile/search'):
            query = urllib.parse.parse_qs(parsed.query).get('q', [''])[0]
            self.send_json_response(search_stocks(query))
            return
        if parsed.path.startswith('/api/mobile/stock'):
            symbol = urllib.parse.parse_qs(parsed.query).get('symbol', [''])[0]
            self.send_json_response(get_stock_detail(symbol))
            return

        if parsed.path == '/api/ltp':
            self.handle_ltp_request()
            return
        if parsed.path == '/api/scan':
            log("\n⚡ [API Request] Received Scan Now trigger from web app...")
            try:
                nifty_df, nifty_regime = fetch_nifty_history()
                log(f"  Market Regime: {nifty_regime.get('badge')}")

                tickers = read_stock_list()
                screener_results = run_scan(tickers)
                if not screener_results or len(screener_results) < 10:
                    log("⚠️ WARNING: API scan returned less than 10 stocks. Preserving existing database.")
                    if LATEST_SCREENER_RESULTS and len(LATEST_SCREENER_RESULTS) >= 10:
                        screener_results = LATEST_SCREENER_RESULTS
                    elif os.path.exists(OUT_JSON_FILE):
                        try:
                            with open(OUT_JSON_FILE, encoding="utf-8") as f:
                                cached = json.load(f)
                                if cached and len(cached) >= 10:
                                    screener_results = cached
                        except Exception:
                            pass

                LATEST_SCREENER_RESULTS = screener_results

                log("Computing Mansfield Relative Strength (RS Rating 1-99) vs Nifty...")
                screener_results = compute_relative_strength_ratings(
                    screener_results, nifty_df,
                    nifty_regime_status=nifty_regime.get("status", "NEUTRAL")
                )
                LATEST_SCREENER_RESULTS = screener_results
                try:
                    clean_results = sanitize_for_strict_json(screener_results)
                    with open(OUT_JSON_FILE, "w", encoding="utf-8") as f:
                        json.dump(clean_results, f, default=json_serializer)
                    with open(WWW_JSON_FILE, "w", encoding="utf-8") as f:
                        json.dump(clean_results, f, default=json_serializer)
                except Exception as e:
                    log(f"  ⚠ Could not save screener_data.json: {e}")

                log("Processing LT Watchlist stocks...")
                lt_wl_data = process_lt_watchlist(screener_results)
                wl_data = process_watchlist(screener_results)

                mkt_info = get_market_status()
                mkt_info["nifty"] = nifty_regime

                commodity_signals = fetch_commodity_signals()
                fno_data = process_fno_stocks(screener_results)
                html = build_html(screener_results, wl_data, lt_wl_data, commodity_signals, mkt_info, fno_data)
                atomic_write_file(OUT_HTML, html)
                atomic_write_file(OUT_WWW_HTML, html)
                atomic_write_file(WWW_INDEX_HTML, html)
                LAST_SCAN_COMPLETED_AT = datetime.datetime.now().isoformat()
                log("⚡ [API Request] Live Scan complete & index.html updated successfully!")
                res = {"status": "ok", "message": "Scan completed successfully", "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self.send_response(200)
            except Exception as e:
                log(f"❌ Error during API scan: {e}")
                res = {"status": "error", "message": str(e)}
                self.send_response(500)

            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        elif parsed.path in ('/api/lt-watchlist/delete', '/api/lt-watchlist/hard-remove'):
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                sym = (body.get("symbol") or "").strip().upper()
                if os.path.exists(LT_WL_FILE):
                    with open(LT_WL_FILE, encoding="utf-8") as f:
                        lt_stocks = json.load(f)
                    lt_stocks = [s for s in lt_stocks if s.get("symbol") != sym]
                    with open(LT_WL_FILE, "w", encoding="utf-8") as f:
                        json.dump(lt_stocks, f, indent=2)
                sync_html_lt_watchlist()
                res = {"status": "ok", "message": f"{sym} permanently deleted from LT Watchlist"}
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return
        elif parsed.path == '/api/lt-watchlist/add':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                sym = (body.get("symbol") or "").strip().upper()
                if not sym:
                    raise ValueError("Symbol is required")

                lt_stocks = []
                if os.path.exists(LT_WL_FILE):
                    with open(LT_WL_FILE, encoding="utf-8") as f:
                        lt_stocks = json.load(f)

                existing = next((s for s in lt_stocks if s.get("symbol") == sym), None)
                if existing:
                    existing["type"] = body.get("type", existing.get("type", "Private"))
                    existing["sector"] = body.get("sector", existing.get("sector", ""))
                    existing["durability_score"] = int(body.get("durability_score") or existing.get("durability_score", 75))
                    existing["portfolio_role"] = body.get("portfolio_role", existing.get("portfolio_role", "Growth"))
                    if "gtt_level" in body and body["gtt_level"] is not None and body["gtt_level"] != "":
                        existing["gtt_level"] = float(body["gtt_level"])
                    existing["active"] = True
                else:
                    gtt_val = float(body["gtt_level"]) if (body.get("gtt_level") is not None and body.get("gtt_level") != "") else None
                    lt_stocks.append({
                        "symbol": sym,
                        "ticker": f"{sym}.NS",
                        "type": body.get("type", "Private"),
                        "sector": body.get("sector", ""),
                        "durability_score": int(body.get("durability_score") or 75),
                        "portfolio_role": body.get("portfolio_role", "Growth"),
                        "gtt_level": gtt_val,
                        "active": True,
                        "added_date": datetime.datetime.now().strftime("%Y-%m-%d"),
                        "notes": ""
                    })

                with open(LT_WL_FILE, "w", encoding="utf-8") as f:
                    json.dump(lt_stocks, f, indent=2)
                sync_html_lt_watchlist()
                res = {"status": "ok", "message": f"{sym} saved to LT Watchlist"}
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        elif parsed.path == '/api/lt-watchlist/remove':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                sym = (body.get("symbol") or "").strip().upper()
                if os.path.exists(LT_WL_FILE):
                    with open(LT_WL_FILE, encoding="utf-8") as f:
                        lt_stocks = json.load(f)
                    for s in lt_stocks:
                        if s.get("symbol") == sym:
                            s["active"] = False
                    with open(LT_WL_FILE, "w", encoding="utf-8") as f:
                        json.dump(lt_stocks, f, indent=2)
                sync_html_lt_watchlist()
                res = {"status": "ok", "message": f"{sym} retired (soft-deleted)"}
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        elif parsed.path == '/api/lt-watchlist/update-gtt':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                sym = (body.get("symbol") or "").strip().upper()
                mode = body.get("gtt_mode", "manual")
                gtt_val = float(body["gtt_level"]) if (body.get("gtt_level") is not None and body.get("gtt_level") != "") else None
                if mode == "auto":
                    gtt_val = None

                if os.path.exists(LT_WL_FILE):
                    with open(LT_WL_FILE, encoding="utf-8") as f:
                        lt_stocks = json.load(f)
                    for s in lt_stocks:
                        if s.get("symbol") == sym:
                            s["gtt_level"] = gtt_val
                            s["gtt_mode"] = mode
                    with open(LT_WL_FILE, "w", encoding="utf-8") as f:
                        json.dump(lt_stocks, f, indent=2)
                sync_html_lt_watchlist()
                res = {"status": "ok", "message": f"GTT target updated for {sym}"}
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        elif parsed.path == '/api/lt-watchlist/toggle-active':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                sym = (body.get("symbol") or "").strip().upper()
                active = bool(body.get("active", True))
                if os.path.exists(LT_WL_FILE):
                    with open(LT_WL_FILE, encoding="utf-8") as f:
                        lt_stocks = json.load(f)
                    for s in lt_stocks:
                        if s.get("symbol") == sym:
                            s["active"] = active
                    with open(LT_WL_FILE, "w", encoding="utf-8") as f:
                        json.dump(lt_stocks, f, indent=2)
                sync_html_lt_watchlist()
                res = {"status": "ok", "message": f"{sym} active status set to {active}"}
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        elif parsed.path == '/api/lt-portfolio/status':
            try:
                summary = get_lt_portfolio_summary()
                res = {"status": "ok", "summary": summary}
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        elif parsed.path == '/api/settings':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                settings_file = os.path.join(BASE_DIR, "screener_settings.json")
                cur_settings = {}
                if os.path.exists(settings_file):
                    try:
                        with open(settings_file, "r", encoding="utf-8") as f:
                            cur_settings = json.load(f)
                    except Exception: pass
                cur_settings.update(body)
                with open(settings_file, "w", encoding="utf-8") as f:
                    json.dump(cur_settings, f, indent=2)
                res = {"status": "ok", "message": "Settings updated successfully"}
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

    def log_message(self, format, *args):
        pass


def is_screener_running_on_port(check_port: int) -> bool:
    """Checks if our Stock Screener app is already responding on check_port."""
    try:
        url = f"http://127.0.0.1:{check_port}/api/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get("app") == "Stock Screener":
                    return True
    except Exception:
        pass
    return False


def is_port_bindable(check_port: int) -> bool:
    """Tests if check_port can be bound on 127.0.0.1 without throwing socket error."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', check_port))
        s.close()
        return True
    except OSError:
        s.close()
        return False


def run_server(port=None):
    if port is None:
        port = int(os.environ.get("PORT", 5050))

    candidate_ports = [port]
    for fallback in [5050, 5005, 8050, 8505, 5001, 5002, 5000]:
        if fallback not in candidate_ports:
            candidate_ports.append(fallback)

    selected_port = None
    for p in candidate_ports:
        if is_screener_running_on_port(p):
            log(f"⚡ Stock Screener Server is already running at http://localhost:{p}")
            open_in_browser(f"http://localhost:{p}")
            return
        if is_port_bindable(p):
            selected_port = p
            break

    if selected_port is None:
        selected_port = port

    port = selected_port
    log("=" * 60)
    log(f"⚡ Stock Screener Server running at port {port}")
    log("=" * 60)

    server_address = ('0.0.0.0', port)
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True
        def handle_error(self, request, client_address):
            exctype, value, tb = sys.exc_info()
            if exctype and issubclass(exctype, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError)):
                return
            super().handle_error(request, client_address)

    httpd = None
    for attempt in range(5):
        try:
            httpd = ThreadedHTTPServer(server_address, ScanRequestHandler)
            break
        except OSError as e:
            if attempt < 4:
                log(f"Port {port} busy, retrying in 1s (attempt {attempt + 1}/5)...")
                time.sleep(1.0)
            else:
                log(f"⚠ Could not start server on port {port}: {e}")
                log(f"Falling back to opening static file: {OUT_HTML}")
                open_in_browser(OUT_HTML)
                return

    if httpd:
        try:
            # Gating this on "PORT" env var presence used to break local auto-open
            # the moment any launcher script (e.g. Run Screener.bat, to target the
            # right port for its own kill/display logic) set PORT for reasons
            # unrelated to being on a cloud host — that's exactly what happened.
            # DYNO is Heroku-specific and essentially never set outside a real dyno,
            # so it doesn't collide with local tooling the way a generic PORT check does.
            if "DYNO" not in os.environ and not os.environ.get("NO_BROWSER"):
                try:
                    log(f"Opening http://localhost:{port} in default browser...")
                    open_in_browser(f"http://localhost:{port}")
                except Exception:
                    pass
            while True:
                try:
                    httpd.serve_forever()
                except KeyboardInterrupt:
                    log("Server stopping on user interrupt...")
                    break
                except BaseException as e:
                    log(f"Server exception (recovering): {e}")
                    time.sleep(0.5)
        except KeyboardInterrupt:
            log("Server stopped.")
        except Exception as e:
            log(f"⚠ Server shutdown: {e}")


def background_initial_scan():
    global IS_INITIAL_SCANNING, LATEST_SCREENER_RESULTS, LAST_SCAN_COMPLETED_AT, SCAN_STARTED_AT, LAST_SCAN_FINISHED_AT
    IS_INITIAL_SCANNING = True
    SCAN_STARTED_AT = time.time()
    try:
        log("Checking for Nifty stock list updates from NSE...")
        try:
            import download_nse_indices
            download_nse_indices.main()
        except Exception as e:
            log(f"  ⚠ Stock list auto-update skipped: {e}")

        log("Fetching NIFTY 50 benchmark & analyzing Market Regime...")
        nifty_df, nifty_regime = fetch_nifty_history()
        log(f"  Market Regime: {nifty_regime.get('badge')}")

        tickers = read_stock_list()
        screener_results = run_scan(tickers)
        if not screener_results or len(screener_results) < 10:
            log("⚠️ WARNING: Background scan returned less than 10 stocks (rate-limit or fetch error). Preserving existing database to prevent blank page.")
            if LATEST_SCREENER_RESULTS and len(LATEST_SCREENER_RESULTS) >= 10:
                screener_results = LATEST_SCREENER_RESULTS
            elif os.path.exists(OUT_JSON_FILE):
                try:
                    with open(OUT_JSON_FILE, encoding="utf-8") as f:
                        cached = json.load(f)
                        if cached and len(cached) >= 10:
                            screener_results = cached
                except Exception:
                    pass

        LATEST_SCREENER_RESULTS = screener_results

        log("Computing Mansfield Relative Strength (RS Rating 1-99) vs Nifty...")
        screener_results = compute_relative_strength_ratings(
            screener_results, nifty_df,
            nifty_regime_status=nifty_regime.get("status", "NEUTRAL")
        )
        # Re-point LATEST_SCREENER_RESULTS at the RS-enriched results and write
        # screener_data.json from THIS version (not the pre-RS one above) — the
        # generated HTML always inlines the post-RS-rating data, so writing the
        # JSON file before RS ratings were computed silently left rs_rating/rs_badge
        # missing/defaulted for every consumer of screener_data.json (the client-side
        # fetch fallback, and any external tooling reading the file directly).
        LATEST_SCREENER_RESULTS = screener_results
        try:
            clean_results = sanitize_for_strict_json(screener_results)
            with open(OUT_JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(clean_results, f, default=json_serializer)
            with open(WWW_JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(clean_results, f, default=json_serializer)
        except Exception as e:
            log(f"  ⚠ Could not save screener_data.json: {e}")

        log("Processing LT Watchlist stocks...")
        # Sync monthly auto-picks into lt_watchlist.json BEFORE process_lt_watchlist
        # reads it — this ensures the locked cohort (quality+momentum, LTP < ₹600,
        # 30-day lock) flows through the same BUY_NOW/WAIT/WATCHING gate as every
        # manually-added stock. sync_monthly_lt_watchlist_additions is a no-op when
        # the lock is still active (within 30 days of last selection).
        sync_monthly_lt_watchlist_additions(screener_results)
        lt_wl_data = process_lt_watchlist(screener_results)
        wl_data = process_watchlist(screener_results)

        mkt_info = get_market_status()
        mkt_info["nifty"] = nifty_regime

        log("Fetching Commodity Intraday Signals (Crude Oil & Natural Gas)...")
        commodity_signals = fetch_commodity_signals()

        log("Processing F&O Options Signals (MARUTI, RELIANCE, BAJAJ-AUTO, ULTRACEMCO, APOLLOHOSP, TCS)...")
        fno_data = process_fno_stocks(screener_results)

        log("Building HTML report...")
        html = build_html(screener_results, wl_data, lt_wl_data, commodity_signals, mkt_info, fno_data)
        atomic_write_file(OUT_HTML, html)
        atomic_write_file(OUT_WWW_HTML, html)
        atomic_write_file(WWW_INDEX_HTML, html)
        LAST_SCAN_COMPLETED_AT = datetime.datetime.now().isoformat()

        log(f"\n✅ Scan complete! Report saved: {OUT_HTML}")

        # Pre-populate GLOBAL_LTP_CACHE from freshly-scanned prices so the
        # very first LTP poll after the page auto-reloads returns live (non-stale)
        # prices immediately — without this, GLOBAL_LTP_CACHE is empty after every
        # scan and the first cycle always falls back to stale fallback_map values.
        try:
            populated = 0
            _now = time.time()
            with GLOBAL_LTP_CACHE_LOCK:
                for s in (screener_results or []):
                    ticker = s.get("ticker") or (s.get("symbol", "") + ".NS")
                    price = s.get("ltp") or s.get("current_ltp")
                    if ticker and price and float(price) > 0:
                        GLOBAL_LTP_CACHE[ticker] = (float(price), _now)
                        GLOBAL_LTP_CACHE[ticker.replace(".NS", "")] = (float(price), _now)
                        populated += 1
            log(f"  ✅ Pre-seeded GLOBAL_LTP_CACHE with {populated} scan prices for instant post-reload polling.")
        except Exception as e:
            log(f"  ⚠ Could not pre-seed LTP cache: {e}")

    finally:
        IS_INITIAL_SCANNING = False
        LAST_SCAN_FINISHED_AT = time.time()


def automated_hourly_market_scheduler():
    """
    Automated background loop that runs during NSE market hours (Mon-Fri 09:15-15:30 IST).
    Triggers a fresh scan every hour so 1-hour candle breakout changes are caught live.
    """
    while True:
        try:
            time.sleep(300)  # Check clock every 5 minutes
            now = datetime.datetime.now()
            # Mon = 0, Fri = 4
            if now.weekday() < 5:
                start_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
                end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
                if start_time <= now <= end_time:
                    global IS_INITIAL_SCANNING
                    since_last = time.time() - LAST_SCAN_FINISHED_AT
                    if IS_INITIAL_SCANNING:
                        pass  # a scan is already in flight; never overlap them
                    elif since_last < MIN_SECONDS_BETWEEN_AUTO_SCANS:
                        # The startup scan counts as this hour's scan. Without this the
                        # loop fired a second full scan within minutes of the first.
                        pass
                    else:
                        log("⏰ [Market Hours Scheduler] Triggering hourly scan for 1H candle breakouts...")
                        background_initial_scan()
        except Exception as e:
            import traceback
            log(f"⚠ Market scheduler error: {e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    log("=" * 60)
    log(f"  Quality Stock Screener — Phase 1 (Port {port})")
    log("  Source: Nifty 500 | Scoring: Strength + Value + Momentum")
    log("=" * 60)

    if is_screener_running_on_port(port):
        log(f"⚡ Stock Screener Server is already running at http://localhost:{port}")
        open_in_browser(f"http://localhost:{port}")
        sys.exit(0)

    def startup_bg_tasks():
        if LATEST_SCREENER_RESULTS and len(LATEST_SCREENER_RESULTS) >= 10:
            log(f"⚡ Building immediate index.html report from cached database ({len(LATEST_SCREENER_RESULTS)} stocks)...")
            try:
                wl_data = process_watchlist(LATEST_SCREENER_RESULTS)
                lt_wl_data = process_lt_watchlist(LATEST_SCREENER_RESULTS)
                mkt_info = get_market_status()
                commodity_signals = fetch_commodity_signals()
                fno_data = process_fno_stocks(LATEST_SCREENER_RESULTS)
                html = build_html(LATEST_SCREENER_RESULTS, wl_data, lt_wl_data, commodity_signals, mkt_info, fno_data)
                atomic_write_file(OUT_HTML, html)
                atomic_write_file(OUT_WWW_HTML, html)
                atomic_write_file(WWW_INDEX_HTML, html)
            except Exception as e:
                log(f"  ⚠ Startup HTML build skipped: {e}")

        log(f"⚡ Launching scan of {len(read_stock_list()) if os.path.exists(OUT_JSON_FILE) else 2415} stocks in background thread...")
        background_initial_scan()

    # Launch background startup tasks thread so server starts instantly on port 5000
    scan_t = threading.Thread(target=startup_bg_tasks, daemon=True)
    scan_t.start()

    # Launch automated hourly market scheduler daemon thread
    sched_t = threading.Thread(target=automated_hourly_market_scheduler, daemon=True)
    sched_t.start()

    # Owns all live-price fetching so /api/ltp never blocks on the network.
    warmer_t = threading.Thread(target=background_ltp_warmer, daemon=True)
    warmer_t.start()

    # Run the HTTP server immediately in main thread
    run_server(port)




