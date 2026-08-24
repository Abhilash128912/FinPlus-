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
import webbrowser
import http.server
import socketserver
import urllib.parse
import threading
import pandas as pd
import yfinance as yf

from screener_engine import score_stock, check_quality_alerts, compute_signal, check_top_pick_status, compute_trend_classification, compute_fno_signal, compute_nifty_market_regime, compute_relative_strength_ratings, get_lt_watchlist_status, calc_indmoney_charges

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CACHE_DIR  = os.path.join(BASE_DIR, "cache")
WL_SEED    = os.path.join(BASE_DIR, "watchlist_seed.json")
WL_FILE    = os.path.join(BASE_DIR, "watchlist_data.json")
LT_WL_FILE = os.path.join(BASE_DIR, "lt_watchlist.json")
LT_CAPITAL_LEDGER_FILE = os.path.join(BASE_DIR, "lt_capital_ledger.json")
OUT_HTML   = os.path.join(BASE_DIR, "index.html")
OUT_WWW_HTML = os.path.join(BASE_DIR, "www", "index.html")

os.makedirs(CACHE_DIR, exist_ok=True)
IS_INITIAL_SCANNING = False
LATEST_SCREENER_RESULTS = []
OUT_JSON_FILE = os.path.join(BASE_DIR, "screener_data.json")
if os.path.exists(OUT_JSON_FILE):
    try:
        with open(OUT_JSON_FILE, encoding="utf-8") as f:
            LATEST_SCREENER_RESULTS = json.load(f)
    except Exception:
        LATEST_SCREENER_RESULTS = []

def json_serializer(o):
    if hasattr(o, 'item'):
        return o.item()
    if hasattr(o, 'isoformat'):
        return o.isoformat()
    if isinstance(o, (bool, type(True))):
        return bool(o)
    return str(o)

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


# ─── Helpers ──────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or 'ascii'
        safe_msg = str(msg).encode(enc, errors='replace').decode(enc)
        print(f"[{ts}] {safe_msg}", flush=True)


def open_in_browser(target: str) -> bool:
    """Robust browser launcher for Windows shell + default browser fallback."""
    import platform, subprocess
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
        age_hrs = (datetime.datetime.now() - cached_at).total_seconds() / 3600
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

    data["cached_at"] = datetime.datetime.now().isoformat()
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
def fetch_news_for_ticker(ticker: str) -> list[dict]:
    news_list = []
    try:
        from curl_cffi import requests
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, impersonate="chrome120", headers=headers, timeout=5)
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


def fetch_via_curl_cffi(ticker: str) -> dict | None:
    try:
        from curl_cffi import requests
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1y"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, impersonate="chrome120", headers=headers, timeout=8)
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
                "previousClose": meta.get("previousClose"),
                "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
                "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
                "shortName": meta.get("shortName") or ticker.replace(".NS", ""),
                "longName": meta.get("longName") or ticker.replace(".NS", ""),
                "currency": meta.get("currency", "INR"),
                "exchange": meta.get("exchangeName", "NSE")
            }

            # Fetch genuine fundamental ratios via Yahoo Finance quoteSummary
            sess, crumb = get_yahoo_crumb_session()
            if sess and crumb:
                try:
                    summary_url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
                                   f"?modules=financialData,defaultKeyStatistics,summaryDetail,assetProfile&crumb={crumb}")
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
    Finance chart API (1-minute interval, intraday).  Returns None on failure.

    This is intentionally lightweight — it never touches the cache and is
    only called during live equity sessions to patch a stale cached LTP.
    """
    try:
        from curl_cffi import requests as cffi_req
        url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?interval=1m&range=1d")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36"}
        r = cffi_req.get(url, impersonate="chrome120", headers=headers, timeout=6)
        if r.status_code == 200:
            meta = (r.json().get("chart", {}).get("result") or [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
            if price and float(price) > 0:
                return float(price)
    except Exception:
        pass
    return None


def fetch_ticker_data(ticker: str) -> dict | None:
    cached = load_cache(ticker)
    if cached:
        cached_at_str = cached.get("cached_at", "2000-01-01")
        if is_price_stale(cached_at_str):
            live_price = fetch_live_price_only(ticker)
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
                watchlist_symbols = {w["symbol"] for w in wl}
        except Exception:
            pass
    if not watchlist_symbols and os.path.exists(WL_SEED):
        try:
            with open(WL_SEED) as f:
                wl = json.load(f)
                watchlist_symbols = {w["symbol"] for w in wl}
        except Exception:
            pass

    # Symbols exempt from the ₹5000 price cap (F&O stocks traded as options)
    try:
        fno_master_dict = get_fno_master_list()
        fno_symbols = set(fno_master_dict.keys())
    except Exception as e:
        log(f"Error initializing dynamic fno_symbols: {e}")
        fno_symbols = {s["symbol"] for s in cfg.get("fno_stocks", [])}

    def process_single_ticker(args):
        i, ticker = args
        clean = ticker.replace(".NS", "").replace(".BO", "")
        data = fetch_ticker_data(ticker)
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
        if ("news" not in data or data["news"] is None) and (qualified or is_wl):
            news_list = fetch_news_for_ticker(ticker)
            data["news"] = news_list
            save_cache(ticker, data)
        scored["news"] = data.get("news") or []
        time.sleep(0.04)
        return scored, "ok"

    log(f"\nMultithreaded scanning {total} stocks (6 parallel workers, rate-limit safe)...")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as executor:
        scan_items = list(enumerate(tickers, 1))
        futures = [executor.submit(process_single_ticker, item) for item in scan_items]
        for f in futures:
            res, status = f.result()
            if status == "nodata":
                skipped_nodata += 1
            elif status == "price":
                skipped_price += 1
            elif res:
                results.append(res)

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

    results.sort(key=lambda x: x["total_score"], reverse=True)
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

    result_map = {r["symbol"]: r for r in screener_results}
    fno_data = []

    for sym, fno_item in fno_master_dict.items():
        ticker = fno_item["ticker"]
        scored = result_map.get(sym)

        if scored is None:
            # Not found in the main scan results — fetch individually
            data = fetch_ticker_data(ticker)
            if data:
                info    = data.get("info", {})
                history = history_from_records(data.get("history_close", []))
                scored  = score_stock(info, history)
                scored["symbol"] = sym
                scored["ticker"] = ticker
                trend_info = compute_trend_classification(scored)
                scored["trend"]       = trend_info["trend"]
                scored["tech_rating"] = trend_info["badge"]
                scored["tech_class"]  = trend_info["class"]

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
                    log(f"  ℹ F&O Excluded: {sym} (LTP ₹{ltp_val}, Lot Size {lot_val} fails LTP>=1000 or lot_size<500)")
        else:
            log(f"  ⚠ F&O: could not fetch data for {sym}")

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

    result_map = {r["symbol"]: r for r in screener_results}

    for item in watchlist:
        sym = item["symbol"]
        scored = result_map.get(sym)

        if scored is None:
            # Not in screener results — fetch individually
            log(f"  Fetching watchlist stock individually: {sym}")
            data = fetch_ticker_data(item["ticker"])
            if data:
                info = data.get("info", {})
                history = history_from_records(data.get("history_close", []))
                scored = score_stock(info, history)
                scored["symbol"] = sym
                scored["ticker"] = item["ticker"]
                
                # Fetch news on-the-fly if missing
                if "news" not in data or data["news"] is None:
                    log(f"  Fetching news on-the-fly for watchlist stock individually: {sym}")
                    news_list = fetch_news_for_ticker(item["ticker"])
                    data["news"] = news_list
                    save_cache(item["ticker"], data)
                
                scored["news"] = data.get("news") or []

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

    enriched = []
    buy_now_count = 0
    for entry in lt_stocks:
        sym = (entry.get("symbol") or "").upper()
        active = entry.get("active", True)

        live = result_map.get(sym)

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
        gate = get_lt_watchlist_status(trend, rsi, ltp, effective_gtt, day_chg=day_chg, is_reversal_up=is_reversal_up)
        status = gate["status"]
        if status == "BUY_NOW" and active:
            buy_now_count += 1

        # Distance from GTT level (negative = below GTT = triggered)
        dist_from_gtt_pct = None
        if effective_gtt and effective_gtt > 0 and ltp > 0:
            dist_from_gtt_pct = round(((ltp - effective_gtt) / effective_gtt) * 100, 1)

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
            "live_data_found":   live is not None,
        })

    if buy_now_count > 0:
        log(f"  🔔 LT Watchlist: {buy_now_count} stock(s) are BUY_NOW — GTT level reached!")
    log(f"  LT Watchlist: {sum(1 for e in enriched if e.get('active'))} active / {len(enriched)} total · "
        f"{buy_now_count} BUY_NOW · {sum(1 for e in enriched if e.get('status')=='WAIT' and e.get('active'))} WAIT")
    return enriched


def load_lt_capital_ledger() -> dict:
    if os.path.exists(LT_CAPITAL_LEDGER_FILE):
        try:
            with open(LT_CAPITAL_LEDGER_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "start_date": "2026-08-19",
        "daily_accrual_rate": 100.0,
        "extra_deposits": 0.0,
        "holdings": [],
        "transactions": []
    }


def save_lt_capital_ledger(ledger: dict):
    with open(LT_CAPITAL_LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2)


def get_lt_portfolio_summary(screener_results: list[dict] = None) -> dict:
    ledger = load_lt_capital_ledger()
    start_date_str = ledger.get("start_date", "2026-08-19")
    daily_rate = float(ledger.get("daily_accrual_rate", 100.0))
    extra_deposits = float(ledger.get("extra_deposits", 0.0))
    
    try:
        s_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
        today_date = datetime.datetime.now().date()
        days_active = max(1, (today_date - s_date).days + 1)
    except Exception:
        days_active = 1

    total_deposited = round((days_active * daily_rate) + extra_deposits, 2)
    
    holdings = ledger.get("holdings", [])
    transactions = ledger.get("transactions", [])
    
    realized_pnl = 0.0
    total_charges_paid = 0.0
    total_buy_cash_spent = 0.0
    total_sell_cash_received = 0.0
    
    for tx in transactions:
        total_charges_paid += float(tx.get("total_charges", 0))
        if tx.get("type") == "BUY":
            total_buy_cash_spent += float(tx.get("net_value", 0))
        elif tx.get("type") == "SELL":
            total_sell_cash_received += float(tx.get("net_value", 0))
            realized_pnl += float(tx.get("realized_pnl", 0))

    available_cash = round(total_deposited + total_sell_cash_received - total_buy_cash_spent, 2)
    
    price_map = {}
    if screener_results:
        for s in screener_results:
            price_map[s["symbol"]] = float(s.get("ltp", 0.0))

    enriched_holdings = []
    invested_capital = 0.0
    current_portfolio_val = 0.0

    for h in holdings:
        sym = h["symbol"]
        qty = int(h.get("qty", 0))
        avg_price = float(h.get("avg_price", 0.0))
        buy_value = round(qty * avg_price, 2)
        
        live_price = price_map.get(sym) or float(h.get("last_price", avg_price))
        mkt_val = round(qty * live_price, 2)
        unrealized_pnl = round(mkt_val - buy_value, 2)
        unrealized_pnl_pct = round((unrealized_pnl / buy_value * 100), 2) if buy_value > 0 else 0.0
        
        invested_capital += buy_value
        current_portfolio_val += mkt_val

        enriched_holdings.append({
            **h,
            "live_price": round(live_price, 2),
            "buy_value": buy_value,
            "market_value": mkt_val,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct
        })

    total_unrealized_pnl = round(current_portfolio_val - invested_capital, 2)
    total_pnl = round(realized_pnl + total_unrealized_pnl, 2)

    return {
        "start_date": start_date_str,
        "days_active": days_active,
        "daily_accrual_rate": daily_rate,
        "extra_deposits": extra_deposits,
        "total_deposited": total_deposited,
        "available_cash": available_cash,
        "invested_capital": round(invested_capital, 2),
        "current_portfolio_val": round(current_portfolio_val, 2),
        "total_unrealized_pnl": total_unrealized_pnl,
        "realized_pnl": round(realized_pnl, 2),
        "total_pnl": total_pnl,
        "total_charges_paid": round(total_charges_paid, 2),
        "holdings": enriched_holdings,
        "transactions": transactions
    }


def execute_lt_buy_order(symbol: str, qty: int, price: float) -> dict:
    symbol = symbol.strip().upper()
    qty = int(qty)
    price = float(price)
    if qty <= 0 or price <= 0:
        raise ValueError("Quantity and price must be greater than zero")

    gross_val = round(qty * price, 2)
    fees = calc_indmoney_charges(gross_val, "BUY")
    net_cost = fees["net_value"]

    summary = get_lt_portfolio_summary()
    available_cash = summary["available_cash"]

    if net_cost > available_cash:
        raise ValueError(f"Insufficient cash balance. Required: ₹{net_cost:.2f} (incl. INDmoney charges ₹{fees['total_charges']:.2f}), Available: ₹{available_cash:.2f}")

    ledger = load_lt_capital_ledger()
    holdings = ledger.get("holdings", [])
    transactions = ledger.get("transactions", [])

    existing = next((h for h in holdings if h["symbol"] == symbol), None)
    if existing:
        old_qty = int(existing["qty"])
        old_avg = float(existing["avg_price"])
        new_qty = old_qty + qty
        new_avg = round(((old_qty * old_avg) + gross_val) / new_qty, 2)
        existing["qty"] = new_qty
        existing["avg_price"] = new_avg
        existing["last_price"] = price
    else:
        holdings.append({
            "symbol": symbol,
            "qty": qty,
            "avg_price": price,
            "buy_date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "last_price": price
        })

    tx_id = f"TX-BUY-{int(datetime.datetime.now().timestamp())}"
    tx_record = {
        "id": tx_id,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": "BUY",
        "symbol": symbol,
        "qty": qty,
        "price": price,
        "gross_value": gross_val,
        "total_charges": fees["total_charges"],
        "net_value": net_cost,
        "charges_breakdown": fees
    }
    transactions.append(tx_record)

    ledger["holdings"] = holdings
    ledger["transactions"] = transactions
    save_lt_capital_ledger(ledger)

    return {
        "status": "ok",
        "message": f"Successfully bought {qty} shares of {symbol} @ ₹{price:.2f} (Net Cost: ₹{net_cost:.2f})",
        "transaction": tx_record
    }


def execute_lt_sell_order(symbol: str, qty: int, price: float) -> dict:
    symbol = symbol.strip().upper()
    qty = int(qty)
    price = float(price)
    if qty <= 0 or price <= 0:
        raise ValueError("Quantity and price must be greater than zero")

    ledger = load_lt_capital_ledger()
    holdings = ledger.get("holdings", [])
    transactions = ledger.get("transactions", [])

    existing = next((h for h in holdings if h["symbol"] == symbol), None)
    if not existing or int(existing.get("qty", 0)) < qty:
        avail_qty = int(existing.get("qty", 0)) if existing else 0
        raise ValueError(f"Insufficient holding for {symbol}. Requested: {qty}, Available: {avail_qty}")

    old_qty = int(existing["qty"])
    avg_price = float(existing["avg_price"])
    cost_of_sold = round(qty * avg_price, 2)
    gross_val = round(qty * price, 2)
    
    fees = calc_indmoney_charges(gross_val, "SELL")
    net_proceeds = fees["net_value"]
    realized_pnl = round(net_proceeds - cost_of_sold, 2)

    rem_qty = old_qty - qty
    if rem_qty <= 0:
        holdings = [h for h in holdings if h["symbol"] != symbol]
    else:
        existing["qty"] = rem_qty
        existing["last_price"] = price

    tx_id = f"TX-SELL-{int(datetime.datetime.now().timestamp())}"
    tx_record = {
        "id": tx_id,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": "SELL",
        "symbol": symbol,
        "qty": qty,
        "price": price,
        "gross_value": gross_val,
        "total_charges": fees["total_charges"],
        "net_value": net_proceeds,
        "realized_pnl": realized_pnl,
        "charges_breakdown": fees
    }
    transactions.append(tx_record)

    ledger["holdings"] = holdings
    ledger["transactions"] = transactions
    save_lt_capital_ledger(ledger)

    return {
        "status": "ok",
        "message": f"Successfully sold {qty} shares of {symbol} @ ₹{price:.2f} (Net Proceeds ₹{net_proceeds:.2f} credited to Cash Balance)",
        "transaction": tx_record
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

    result_map = {r["symbol"]: r for r in screener_results}

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
                res = result_map[top_pick["symbol"]]
                top_pick["current_ltp"] = res["ltp"]
                top_pick["ltp"] = res["ltp"]
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
                "symbol": top["symbol"],
                "name": top.get("name") or top["symbol"],
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

    target1 = round(base_entry + (2.0 * risk), 2)
    target2 = round(base_entry + (3.0 * risk), 2)
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
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Stock Screener — Phase 1 | Quality Watchlist</title>
<style>
:root{
  --bg:#06060f;--card:#0e0e1e;--card2:#13132a;--border:#1e1e3a;
  --accent:#6c63ff;--accent2:#00d4aa;--warn:#f59e0b;--danger:#ef4444;
  --green:#10b981;--text:#e2e8f0;--muted:#64748b;--white:#fff;
  --font:'Inter',system-ui,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:14px;min-height:100vh}
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

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

  /* Fixed Mobile Bottom Navigation Bar */
  .mobile-nav-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 60px;
    background: rgba(10, 10, 26, 0.96);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-top: 1px solid rgba(255, 255, 255, 0.12);
    display: flex !important;
    justify-content: space-around;
    align-items: center;
    z-index: 9999;
    box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.6);
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
    <button class="tab active" onclick="switchTab('screener')">🔍 Screener Results</button>
    <button class="tab" onclick="switchTab('swing')">⚡ Swing Trading</button>
    <button class="tab" onclick="switchTab('watchlist')">🛡️ LT Watchlist (<span id="wlCount">0</span>)</button>
    <button class="tab" onclick="switchTab('fno')">📊 F&amp;O Options</button>
    <button class="tab" onclick="switchTab('holidays')">📅 Market Holidays (2026)</button>
  </div>


  <!-- SCREENER TAB -->
  <div id="tab-screener">
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
          <option value="Uptrend">🟢 Strong Uptrend</option>
          <option value="Downtrend">🔴 Downtrend</option>
          <option value="Accumulation">🔵 Accumulation</option>
          <option value="Consolidation">🟡 Consolidation</option>
          <option value="Distribution">🟠 Distribution</option>
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
  <div id="tab-swing" style="display:none">
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

    <!-- Full Swing Table -->
    <div style="font-size:12px;color:var(--muted);margin-bottom:8px" id="swingResultCount"></div>
    <div class="table-wrap">
      <table id="swingTable">
        <thead>
          <tr>
            <th>#</th>
            <th>Symbol</th>
            <th onclick="sortSwingTable('swing_score')" style="cursor:pointer">Swing Score ↕</th>
            <th onclick="sortSwingTable('rs_rating')" style="cursor:pointer">RS Rating ↕</th>
            <th>Badge</th>
            <th onclick="sortSwingTable('ltp')" style="cursor:pointer">LTP ↕</th>
            <th onclick="sortSwingTable('volume_spike')" style="cursor:pointer">Vol Spike ↕</th>
            <th onclick="sortSwingTable('rsi')" style="cursor:pointer">RSI ↕</th>
            <th onclick="sortSwingTable('momentum')" style="cursor:pointer">Momentum ↕</th>
            <th>Order Flow</th>
            <th>SL</th>
            <th>Target 1 (1:2)</th>
            <th>Target 2 (1:3)</th>
            <th>Reason</th>
            <th>Action</th>
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
    <div id="ltCapitalDashboard" style="background:linear-gradient(135deg, #0e1726, #162438);border:1.5px solid rgba(52,211,153,0.35);border-radius:14px;padding:18px 22px;margin-bottom:20px;box-shadow:0 8px 30px rgba(0,0,0,0.35)">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:14px;margin-bottom:16px">
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
          <button onclick="openLtBuyModal('', 0)" style="background:linear-gradient(135deg,#10b981,#059669);color:#fff;font-weight:700;font-size:12px;padding:8px 14px;border-radius:8px;border:none;cursor:pointer">🛒 Record Buy</button>
          <button onclick="promptLtDeposit()" style="background:rgba(52,211,153,0.12);border:1px solid rgba(52,211,153,0.4);color:#34d399;font-weight:700;font-size:12px;padding:8px 14px;border-radius:8px;cursor:pointer">➕ Top-Up Capital</button>
          <button onclick="toggleLtHoldingsDrawer()" style="background:rgba(108,99,255,0.15);border:1px solid rgba(108,99,255,0.4);color:#a5b4fc;font-weight:700;font-size:12px;padding:8px 14px;border-radius:8px;cursor:pointer">💼 View Holdings</button>
        </div>
      </div>

      <!-- Metric Grid -->
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px">
        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:12px 14px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Daily Accrual Rate</div>
          <div style="font-size:20px;font-weight:800;color:#34d399;margin-top:2px">+₹100.00 <span style="font-size:10px;color:var(--muted)">/ day</span></div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">Auto-credits EOD</div>
        </div>

        <div style="background:rgba(52,211,153,0.1);border:1.5px solid rgba(52,211,153,0.35);border-radius:10px;padding:12px 14px">
          <div style="font-size:10px;color:#34d399;text-transform:uppercase;letter-spacing:.05em;font-weight:700">Available Cash</div>
          <div id="ltAvailableCashVal" style="font-size:22px;font-weight:800;color:#34d399;margin-top:2px">₹100.00</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">Ready for 🟢 BUY NOW</div>
        </div>

        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:12px 14px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Total Deposited</div>
          <div id="ltTotalDepositedVal" style="font-size:20px;font-weight:800;color:#fff;margin-top:2px">₹100.00</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">Cumulative Capital</div>
        </div>

        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:12px 14px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Invested Capital</div>
          <div id="ltInvestedCapitalVal" style="font-size:20px;font-weight:800;color:#e2e8f0;margin-top:2px">₹0.00</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">In Active Holdings</div>
        </div>

        <div style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:12px 14px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">Portfolio Value</div>
          <div id="ltPortfolioValueVal" style="font-size:20px;font-weight:800;color:#fff;margin-top:2px">₹0.00</div>
          <div id="ltTotalPnlVal" style="font-size:10px;font-weight:700;color:var(--muted);margin-top:2px">P&L: ₹0.00 (0.0%)</div>
        </div>
      </div>
    </div>

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
        <button class="swing-pill" id="ltPill-WAIT" onclick="filterLtStatus('WAIT')" style="border-color:#6366f1;color:#a5b4fc">🔵 WAIT (<span id="ltPillCountWAIT">0</span>)</button>
        <button class="swing-pill" id="ltPill-WATCHLIST" onclick="filterLtStatus('WATCHLIST')" style="border-color:#64748b;color:#94a3b8">⬜ WATCHING (<span id="ltPillCountWATCHLIST">0</span>)</button>
      </div>

      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);cursor:pointer;user-select:none">
          <input type="checkbox" id="ltShowRetiredToggle" onchange="toggleLtShowRetired(this.checked)" style="cursor:pointer">
          <span>Show Retired Stocks (<span id="ltRetiredCount">0</span>)</span>
        </label>

        <button class="btn-add" style="background:linear-gradient(135deg,#6c63ff,#00d4aa);color:#fff;font-weight:700;padding:7px 16px;border-radius:8px;cursor:pointer;font-size:12px" onclick="openAddLtStockModal()">
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
    <div id="bseAddStatus" style="font-size:12px;margin-top:8px"></div>
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
  <button class="mobile-nav-item" data-tab="watchlist" onclick="switchTab('watchlist')">
    <span class="mobile-nav-icon">🛡️</span>
    <span>LT Watchlist</span>
  </button>
  <button class="mobile-nav-item" data-tab="fno" onclick="switchTab('fno')">
    <span class="mobile-nav-icon">📊</span>
    <span>F&amp;O</span>
  </button>
  <button class="mobile-nav-item" data-tab="holidays" onclick="switchTab('holidays')">
    <span class="mobile-nav-icon">📅</span>
    <span>Holidays</span>
  </button>
</div>

<script>
// ── DATA (injected by Python) ─────────────────────────────────────────────
const SCREENER_DATA = __SCREENER_JSON__;
const WATCHLIST_SEED = __WATCHLIST_JSON__;
const LT_WATCHLIST = __LT_WATCHLIST_JSON__;
const CONFIG = __CONFIG_JSON__;
const COMMODITIES_DATA = __COMMODITIES_JSON__;
const MARKET_INFO = __MARKET_INFO_JSON__;
const FNO_DATA = __FNO_JSON__;

// ── State ─────────────────────────────────────────────────────────────────
let watchlist = [];
let sortCol = 'total_score';
let sortDir = -1;
let filteredData = [];
let pollIntervalTimer = null;
let pollIntervalMs = 10000;
let currentPage = 1;
let pageSize = 50;

function calculateCurrentMarketStatus() {
  const now = new Date();
  const options = { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
  const formatter = new Intl.DateTimeFormat('en-US', options);
  const parts = formatter.formatToParts(now);
  const p = {};
  parts.forEach(item => { p[item.type] = item.value; });
  
  const year = parseInt(p.year);
  const month = parseInt(p.month) - 1;
  const day = parseInt(p.day);
  const hours = parseInt(p.hour % 24);
  const minutes = parseInt(p.minute);
  
  const istDate = new Date(year, month, day, hours, minutes);
  const dayOfWeek = istDate.getDay(); // 0 = Sun, 6 = Sat
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
    return {
      status: "LIVE_MARKET",
      badge: "🟢 Live Market (Stocks & Commodities Active)",
      badge_class: "badge-green",
      message: "NSE/BSE & MCX Session Active. Live prices & returns updating.",
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
  const hasLocalPort = (window.location.port === '5000' || window.location.port === '3000');
  return (!isCapacitor && !isMobileUA && hasLocalPort);
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
  if (barInner) barInner.style.width = '20%';
  if (btnLog) btnLog.textContent = 'Connecting to local scan engine server...';

  const scanUrl = 'http://localhost:' + window.location.port + '/api/scan';

  try {
    if (barInner) barInner.style.width = '40%';
    if (btnLog) btnLog.textContent = 'Fetching Nifty 500 prices & scoring stocks...';
    const res = await fetch(scanUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    if (res.ok) {
      if (barInner) barInner.style.width = '100%';
      if (btnText) btnText.textContent = 'Scan complete! Reloading latest data...';
      if (btnLog) btnLog.textContent = 'Updating watchlist and daily picks...';
      setTimeout(() => { window.location.reload(); }, 800);
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
      return data.filter(s => (s.rs_rating || 0) >= 80 && (!s.rsi || s.rsi <= 72));
    case 'blast':
      return data.filter(s => (s.is_blast || (s.volume_spike >= 2.0 && s.momentum >= 60)) && (!s.rsi || s.rsi <= 72));
    case 'inflow':
      return data.filter(s => s.is_order_flow_bull || (s.cmf >= 0.08 && s.clv >= 0.55 && (!s.rsi || s.rsi <= 72)));
    case 'momentum':
      return data.filter(s => (s.is_momentum_surge || s.momentum >= 75) && (!s.rsi || s.rsi <= 72));
    case 'pullback':
      return data.filter(s => s.is_pullback || (s.rsi >= 38 && s.rsi <= 53));
    case 'quality':
      return data.filter(s => s.total_score >= 55 && s.momentum >= 60 && (!s.rsi || s.rsi <= 72));
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
  if (s.is_overbought || (s.rsi && s.rsi > 72)) return 'swing-card-overbought';
  if (s.is_blast) return 'swing-card-blast';
  if (s.is_order_flow_bull) return 'swing-card-inflow';
  if (s.is_momentum_surge) return 'swing-card-momentum';
  if (s.is_pullback) return 'swing-card-pullback';
  return '';
}

function getSwingRingColor(s) {
  if (s.is_overbought || (s.rsi && s.rsi > 72)) return '#ef4444';
  if (s.is_blast) return '#10b981';
  if (s.is_order_flow_bull) return '#6366f1';
  if (s.is_momentum_surge) return '#f59e0b';
  if (s.is_pullback) return '#3b82f6';
  return '#6c63ff';
}

function renderSwingRadar() {
  const allMtf = getSwingData();
  const filtered = applySwingPreset(allMtf);

  // Sort
  const sorted = [...filtered].sort((a, b) => {
    const av = a[swingSortCol] ?? -999;
    const bv = b[swingSortCol] ?? -999;
    return swingSortDir * (av - bv);
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
  if (rcEl) rcEl.textContent = `Showing ${sorted.length} swing stocks matching current preset`;

  // Top 10 Spotlight Cards
  const spotlight = document.getElementById('swingSpotlight');
  if (spotlight) {
    const top10 = sorted.slice(0, 10);
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
              <div style="color:var(--muted);font-size:10px">LTP</div>
              <div style="font-weight:700;color:#fff">₹${(s.ltp||0).toFixed(1)}</div>
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
              <div style="color:#10b981;font-size:10px">T1 (1:2)</div>
              <div class="swing-t1">${t1Str}<span style="font-size:9px;color:var(--muted)"> ${t1Pct}</span></div>
            </div>
            <div style="text-align:center">
              <div style="color:#00d4aa;font-size:10px">T2 (1:3)</div>
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
  const uptrendStates = ["Uptrend", "Accumulation", "Strong Uptrend"];
  const trend = item.trend || "Consolidation";
  const rsi = item.rsi || 50;
  const ltp = item.ltp || 0;
  const isAuto = (item.gtt_mode === 'auto' || item.gtt_mode == null || item.is_auto_gtt);
  const gtt = isAuto ? (item.auto_gtt || item.gtt_level) : item.gtt_level;
  const dayChg = item.day_chg_pct || 0;

  if (uptrendStates.includes(trend)) {
    if (gtt !== null && gtt !== undefined && gtt !== "" && ltp > 0 && ltp <= (gtt * 1.008) && rsi < 70) {
      if (dayChg >= -0.35 || (rsi > 42 && rsi < 70)) {
        item.status = "BUY_NOW";
        item.status_badge = "🟢 BUY NOW";
        item.status_badge_class = "badge-green";
        item.status_reason = `A/E Breakout: Price ₹${ltp.toFixed(2)} bouncing UP from Support GTT ₹${parseFloat(gtt).toFixed(2)}`;
        return;
      } else {
        item.status = "WAIT";
        item.status_badge = "🔵 WAIT";
        item.status_badge_class = "badge-purple";
        item.status_reason = `At Support GTT ₹${parseFloat(gtt).toFixed(2)} — Coiling (Awaiting 1h/Daily Green Reversal Expansion Candle)`;
        return;
      }
    }
    item.status = "WAIT";
    item.status_badge = "🔵 WAIT";
    item.status_badge_class = "badge-purple";
    item.status_reason = `Trend confirmed (${trend}) — waiting for pullback to Support GTT` + (gtt ? ` ₹${parseFloat(gtt).toFixed(2)}` : ' (GTT not set)');
    return;
  }
  item.status = "WATCHLIST";
  item.status_badge = "⬜ WATCHING";
  item.status_badge_class = "badge-gray";
  item.status_reason = `Trend not confirmed (${trend}) — monitoring only, no action expected`;
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
      item.ltp = live.ltp || item.ltp || 0;
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

  const activeList = ltWatchlist.filter(s => s.active !== false);
  const retiredList = ltWatchlist.filter(s => s.active === false);

  const buyNowCount = activeList.filter(s => s.status === 'BUY_NOW').length;
  const waitCount = activeList.filter(s => s.status === 'WAIT').length;
  const watchlistCount = activeList.filter(s => s.status === 'WATCHLIST').length;
  const totalActive = activeList.length;

  // Update Stats & Header Counts
  const el = id => document.getElementById(id);
  if (el('ltCountBuyNow')) el('ltCountBuyNow').textContent = buyNowCount;
  if (el('ltCountWait')) el('ltCountWait').textContent = waitCount;
  if (el('ltCountWatchlist')) el('ltCountWatchlist').textContent = watchlistCount;
  if (el('ltCountTotal')) el('ltCountTotal').textContent = totalActive;
  if (el('wlCount')) el('wlCount').textContent = totalActive;
  if (el('ltRetiredCount')) el('ltRetiredCount').textContent = retiredList.length;

  if (el('ltPillCountALL')) el('ltPillCountALL').textContent = totalActive;
  if (el('ltPillCountBUY_NOW')) el('ltPillCountBUY_NOW').textContent = buyNowCount;
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
  let displayList = ltWatchlist.filter(s => (ltShowRetired ? true : s.active !== false));
  if (ltFilterStatus !== 'ALL') {
    displayList = displayList.filter(s => s.status === ltFilterStatus);
  }

  // Sort
  displayList.sort((a, b) => {
    let av = a[ltSortCol];
    let bv = b[ltSortCol];
    if (ltSortCol === 'status') {
      const order = { 'BUY_NOW': 1, 'WAIT': 2, 'WATCHLIST': 3 };
      av = order[a.status] || 4;
      bv = order[b.status] || 4;
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
    const scoreVal = s.durability_score || 75;
    const scoreColor = scoreVal >= 85 ? '#10b981' : scoreVal >= 75 ? '#60a5fa' : '#fbbf24';
    const statusBadgeCls = s.status === 'BUY_NOW' ? 'badge-green' : s.status === 'WAIT' ? 'badge-purple' : 'badge-gray';
    const statusBadgeText = s.status === 'BUY_NOW' ? '🟢 BUY NOW' : s.status === 'WAIT' ? '🔵 WAIT' : '⬜ WATCHING';

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
        <span class="badge ${s.trend === 'Uptrend' || s.trend === 'Strong Uptrend' ? 'badge-green' : s.trend === 'Accumulation' ? 'badge-purple' : s.trend === 'Downtrend' ? 'badge-red' : 'badge-yellow'}" style="font-size:10px">
          ${s.trend_badge || s.trend || 'Consolidation'}
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
            <button onclick="openLtBuyModal('${s.symbol}', ${s.ltp || 0})" style="background:rgba(16,185,129,0.18);border:1px solid rgba(16,185,129,0.4);color:#34d399;font-weight:700;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Record Buy Transaction for ${s.symbol}">🛒 Buy</button>
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
  const el = id => document.getElementById(id);
  if (prefillSymbol) {
    if (el('ltFormSymbol')) el('ltFormSymbol').value = prefillSymbol;
    const screenerItem = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) ? SCREENER_DATA.find(s => s.symbol === prefillSymbol) : null;
    if (screenerItem) {
      if (el('ltFormSector')) el('ltFormSector').value = screenerItem.sector || '';
      if (el('ltFormGtt')) el('ltFormGtt').value = screenerItem.ltp ? (screenerItem.ltp * 0.95).toFixed(2) : '';
    }
  }
  const modalBg = el('ltAddModalBg');
  if (modalBg) modalBg.style.display = 'flex';
}

function closeAddLtStockModal() {
  const modalBg = document.getElementById('ltAddModalBg');
  if (modalBg) modalBg.style.display = 'none';
}

function submitAddLtStockForm(e) {
  e.preventDefault();
  const el = id => document.getElementById(id);
  const symbol = el('ltFormSymbol').value.trim().toUpperCase();
  const type = el('ltFormType').value;
  const durability_score = parseInt(el('ltFormDurability').value || 75);
  const sector = el('ltFormSector').value.trim();
  const portfolio_role = el('ltFormRole').value.trim();
  const gtt_level = el('ltFormGtt').value ? parseFloat(el('ltFormGtt').value) : null;

  const body = { symbol, type, durability_score, sector, portfolio_role, gtt_level };

  fetch('/api/lt-watchlist/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(r => r.json()).then(res => {
    let existing = ltWatchlist.find(s => s.symbol === symbol);
    if (existing) {
      Object.assign(existing, body, { active: true });
    } else {
      ltWatchlist.push({ ...body, active: true, added_date: new Date().toISOString().split('T')[0] });
    }
    closeAddLtStockModal();
    fetchLtWatchlistApi();
  }).catch(err => {
    let existing = ltWatchlist.find(s => s.symbol === symbol);
    if (existing) {
      Object.assign(existing, body, { active: true });
    } else {
      ltWatchlist.push({ ...body, active: true, added_date: new Date().toISOString().split('T')[0] });
    }
    closeAddLtStockModal();
    fetchLtWatchlistApi();
  });
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
  const freshServerWatchlist = JSON.parse(JSON.stringify(WATCHLIST_SEED));
  
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
    const live = SCREENER_DATA.find(s => s.symbol === item.symbol);
    updateWatchlistSignalsAndAlerts(item, live);
  });

  saveWatchlist();
  renderStats();
  populateSectorFilter();
  applyFilters();
  renderWatchlist();
  renderLtWatchlist();
  updateWlCount();

  renderMarketStatusHeader();
  startPolling();
  refreshLiveLTP(true);
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
          banner.style.background = 'linear-gradient(135deg,rgba(16,185,129,0.35),rgba(5,150,105,0.35))';
          banner.innerHTML = `<span>✅</span> <span>Scan complete! Reloading latest data...</span>`;
          setTimeout(() => window.location.reload(), 1000);
        } else if (wasScanning) {
          window.location.reload();
        }
        if (startupScanPoller) clearInterval(startupScanPoller);
      }
    })
    .catch(() => {});
}

// ── Auto-Add Top Suggestions ─────────────────────────────────────────────
function autoAddTopSuggestions(silent = false) {
  const available = CONFIG.max_stocks - watchlist.length;
  if (available <= 0) {
    if (!silent) alert('Watchlist is already full (20/20 slots used).');
    return;
  }
  const qualified = SCREENER_DATA.filter(s => s.qualified || s.total_score >= 55).sort((a,b) => b.total_score - a.total_score);
  const currentSyms = new Set(watchlist.map(w => w.symbol));
  let addedCount = 0;

  for (const s of qualified) {
    if (watchlist.length >= CONFIG.max_stocks) break;
    if (!currentSyms.has(s.symbol)) {
      const ltp = s.ltp || 1;
      const qty = Math.max(1, Math.floor(CONFIG.phase_budget_per_stock / ltp));
      const newItem = {
        symbol: s.symbol,
        ticker: s.ticker,
        name: s.name,
        qty: qty,
        avg_cost: ltp,
        total_invested: Math.round(ltp * qty * 100) / 100,
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
        ltp: ltp,
        sector: s.sector,
        pe: s.pe,
        roe_pct: s.roe_pct,
        de_ratio: s.de_ratio,
        npm_pct: s.npm_pct,
        rsi: s.rsi,
        wk52_return_pct: s.wk52_return_pct,
        volume_spike: s.volume_spike,
        today_volume: s.today_volume,
        avg_volume_10d: s.avg_volume_10d,
        news: s.news || [],
        alerts: [],
        auto_added: true
      };
      watchlist.push(newItem);
      currentSyms.add(s.symbol);
      addedCount++;
    }
  }

  if (addedCount > 0) {
    saveWatchlist();
    updateWlCount();
    renderTable();
    renderStats();
    renderWatchlist();
    if (!silent) alert(`⚡ Auto-added ${addedCount} top qualified stock suggestions to your watchlist!`);
  } else if (!silent) {
    alert('No new top qualified stock suggestions found to add.');
  }
}


// ── Live LTP Polling System ───────────────────────────────────────────────
function updateLtpBadgeStatus() {
  const dot = document.getElementById('ltpStatusDot');
  const txt = document.getElementById('ltpStatusText');
  if (!txt) return;

  const isOpen = (typeof MARKET_INFO !== 'undefined' && MARKET_INFO && MARKET_INFO.is_open);
  const isWeekend = (typeof MARKET_INFO !== 'undefined' && MARKET_INFO && MARKET_INFO.is_weekend);
  const isHoliday = (typeof MARKET_INFO !== 'undefined' && MARKET_INFO && MARKET_INFO.is_holiday);

  if (!isOpen) {
    if (dot) {
      dot.style.background = '#ef4444';
      dot.style.boxShadow = '0 0 6px #ef4444';
    }
    if (isWeekend) {
      txt.textContent = '🔴 Weekend — LTP Polling Stopped';
    } else if (isHoliday) {
      txt.textContent = '🔴 Exchange Holiday — LTP Polling Stopped';
    } else {
      txt.textContent = '🔴 Market Closed — LTP Polling Stopped';
    }
  } else {
    if (dot) {
      dot.style.background = '#10b981';
      dot.style.boxShadow = '0 0 6px #10b981';
    }
    if (pollIntervalMs === 0) {
      txt.textContent = 'Live LTP Polling: Off';
    } else {
      txt.textContent = `🟢 Live LTP Polling: Every ${pollIntervalMs / 1000}s`;
    }
  }
}

async function fetchLiveLTPForSymbol(ticker) {
  // 1. Try local server IF on Desktop PC
  if (isRealDesktopPC()) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2500);
      const rUrl = `http://localhost:${window.location.port}/api/ltp?ticker=${encodeURIComponent(ticker)}`;
      const res = await fetch(rUrl, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (res.ok) {
        const data = await res.json();
        if (data && data.price && data.price > 0) return data.price;
      }
    } catch (e) {}
  }

  const yUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=1m&range=1d`;
  
  // 2. Try Direct Yahoo Finance API
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(yUrl, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (res.ok) {
      const data = await res.json();
      const meta = data.chart?.result?.[0]?.meta;
      if (meta && meta.regularMarketPrice) return meta.regularMarketPrice;
    }
  } catch (e) {}

  // 3. High-availability CORS proxies for client browsers
  const proxies = [
    `https://corsproxy.io/?${encodeURIComponent(yUrl)}`,
    `https://api.codetabs.com/v1/proxy?quest=${encodeURIComponent(yUrl)}`,
    `https://api.allorigins.win/raw?url=${encodeURIComponent(yUrl)}`,
    `https://finplus-g0b5.onrender.com/api/ltp?ticker=${encodeURIComponent(ticker)}`
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
  const currentMkt = calculateCurrentMarketStatus();
  const isOpen = currentMkt.is_open || currentMkt.is_equity_open;

  if (!isOpen && !manual) {
    if (pollIntervalTimer) {
      clearInterval(pollIntervalTimer);
      pollIntervalTimer = null;
    }
    updateLtpBadgeStatus();
    return;
  }

  const dot = document.getElementById('ltpStatusDot');
  const txt = document.getElementById('ltpStatusText');
  if (dot) dot.classList.add('updating');
  if (txt && manual) txt.textContent = 'Refreshing prices...';

  let priceChanged = false;

  const symbolsToPoll = new Map();
  if (typeof TOP_PICK !== 'undefined' && TOP_PICK && TOP_PICK.symbol) {
    symbolsToPoll.set(TOP_PICK.symbol, TOP_PICK.ticker || TOP_PICK.symbol + '.NS');
  }
  if (typeof watchlist !== 'undefined' && Array.isArray(watchlist)) {
    watchlist.forEach(w => symbolsToPoll.set(w.symbol, w.ticker || w.symbol + '.NS'));
  }
  if (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist)) {
    ltWatchlist.forEach(w => symbolsToPoll.set(w.symbol, w.ticker || w.symbol + '.NS'));
  }
  if (typeof filteredData !== 'undefined' && Array.isArray(filteredData)) {
    filteredData.slice(0, 25).forEach(s => symbolsToPoll.set(s.symbol, s.ticker || s.symbol + '.NS'));
  }
  if (typeof FNO_DATA !== 'undefined' && Array.isArray(FNO_DATA)) {
    FNO_DATA.forEach(f => symbolsToPoll.set(f.symbol, f.ticker || f.symbol + '.NS'));
  }

  const fetchedPrices = new Map();
  const tickerList = Array.from(symbolsToPoll.values());

  if (isRealDesktopPC() && tickerList.length > 0) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 4000);
      const bUrl = `http://localhost:${window.location.port}/api/ltp?ticker=${encodeURIComponent(tickerList.join(','))}`;
      const res = await fetch(bUrl, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (res.ok) {
        const data = await res.json();
        const pricesObj = data.prices || {};
        for (const [sym, ticker] of symbolsToPoll.entries()) {
          const p = pricesObj[ticker] || pricesObj[sym] || pricesObj[sym + '.NS'];
          if (p && p > 0) fetchedPrices.set(sym, p);
        }
      }
    } catch (e) {}
  }

  const unpolled = Array.from(symbolsToPoll.entries()).filter(([sym, ticker]) => !fetchedPrices.has(sym));
  if (unpolled.length > 0) {
    await Promise.all(unpolled.map(async ([sym, ticker]) => {
      const p = await fetchLiveLTPForSymbol(ticker);
      if (p && p > 0) fetchedPrices.set(sym, p);
    }));
  }

  for (const [sym, newPrice] of fetchedPrices.entries()) {
    if (typeof TOP_PICK !== 'undefined' && TOP_PICK && TOP_PICK.symbol === sym) {
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

    const sc = SCREENER_DATA.find(s => s.symbol === sym);
    if (sc && Math.abs(sc.ltp - newPrice) > 0.01) {
      sc.old_ltp = sc.ltp;
      sc.ltp = newPrice;
      priceChanged = true;
    }
    const wl = watchlist.find(w => w.symbol === sym);
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
    if (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist)) {
      const lt = ltWatchlist.find(w => w.symbol === sym);
      if (lt && Math.abs((lt.ltp || 0) - newPrice) > 0.01) {
        lt.old_ltp = lt.ltp;
        lt.ltp = newPrice;
        priceChanged = true;
      }
    }
    if (typeof FNO_DATA !== 'undefined' && Array.isArray(FNO_DATA)) {
      const fn = FNO_DATA.find(f => f.symbol === sym);
      if (fn && Math.abs(fn.ltp - newPrice) > 0.01) {
        fn.old_ltp = fn.ltp;
        fn.ltp = newPrice;
        if (fn.prev_close && fn.prev_close > 0) {
          fn.day_chg_pct = Math.round(((newPrice - fn.prev_close) / fn.prev_close) * 10000) / 100;
        }
        priceChanged = true;
      }
    }
  }

  if (dot) dot.classList.remove('updating');
  updateLtpBadgeStatus();

  if (priceChanged) {
    saveWatchlist();
    renderStats();
    renderTable();
    renderWatchlist();
    if (typeof renderLtWatchlist === 'function') renderLtWatchlist();
    if (typeof renderFnoTab === 'function') renderFnoTab();
    if (typeof renderTopPick === 'function') renderTopPick();
    flashUpdatedPrices();
  }
}

function flashUpdatedPrices() {
  document.querySelectorAll('.price, .wl-ltp').forEach(el => {
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
  const currentMkt = calculateCurrentMarketStatus();
  const isOpen = currentMkt.is_open || currentMkt.is_equity_open;

  if (pollIntervalMs <= 0) {
    updateLtpBadgeStatus();
    return;
  }

  refreshLiveLTP(false);
  if (isOpen) {
    pollIntervalTimer = setInterval(() => refreshLiveLTP(false), pollIntervalMs);
  }
  updateLtpBadgeStatus();
}

function changePollInterval(val) {
  pollIntervalMs = parseInt(val);
  startPolling();
  const currentMkt = calculateCurrentMarketStatus();
  const isOpen = currentMkt.is_open || currentMkt.is_equity_open;
  if (pollIntervalMs > 0 && isOpen) {
    refreshLiveLTP(false);
  }
}

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
  const tabs = ['screener', 'swing', 'watchlist', 'fno', 'holidays'];
  document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', tabs[i] === tab));
  document.querySelectorAll('.mobile-nav-item').forEach(m => {
    m.classList.toggle('active', m.dataset.tab === tab);
  });
  document.getElementById('tab-screener').style.display  = tab === 'screener'  ? '' : 'none';
  document.getElementById('tab-swing').style.display     = tab === 'swing'     ? '' : 'none';
  document.getElementById('tab-watchlist').style.display = tab === 'watchlist' ? '' : 'none';
  document.getElementById('tab-fno').style.display       = tab === 'fno'       ? '' : 'none';
  document.getElementById('tab-holidays').style.display  = tab === 'holidays'  ? '' : 'none';
  if (tab === 'swing')      { renderSwingRadar(); renderSrBreakouts(); }
  if (tab === 'watchlist')  { renderLtWatchlist(); fetchLtPortfolioStatus(); }
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
      <span>These are <strong>underlying price signals</strong>, not option premium calls. Verify live IV, premium &amp; bid-ask from your broker's option chain before entering. Physical settlement applies on expiry — square off before expiry Thursday.</span>
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
                <div style="font-size:10px;color:var(--green);text-transform:uppercase;font-weight:700">Target 1 (1:2 R:R)</div>
                <div style="font-size:17px;font-weight:800;color:var(--green);margin-top:2px">₹${TOP_PICK.target1 != null ? TOP_PICK.target1.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--green);margin-top:2px">+${TOP_PICK.target1_pct || 0}% Upside</div>
              </div>
              <div style="background:var(--card);border:1px solid var(--purple);padding:10px;border-radius:10px">
                <div style="font-size:10px;color:var(--purple);text-transform:uppercase;font-weight:700">Target 2 (1:3 R:R)</div>
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
      if (s.trend !== 'Uptrend' && s.trend !== 'Downtrend') return false;
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
    if (th.textContent.replace(/ [↑↓]/,'').trim().toLowerCase().replace(/\s/g,'_') === col) {
      th.classList.add(sortDir === -1 ? 'sorted-desc' : 'sorted-asc');
    }
  });
  filteredData.sort((a,b) => sortDir * ((a[sortCol]??-999) - (b[sortCol]??-999)));
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
function fetchLtPortfolioStatus() {
  fetch('/api/lt-portfolio/status')
    .then(r => r.json())
    .then(res => {
      if (res && res.status === 'ok' && res.summary) {
        renderLtPortfolioSummary(res.summary);
      }
    })
    .catch(err => {
      console.log('Portfolio status API static/offline');
    });
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

function promptLtDeposit() {
  const amtStr = prompt('Enter Top-Up Capital Amount (₹) to add to LT available cash:');
  if (!amtStr) return;
  const amt = parseFloat(amtStr);
  if (isNaN(amt) || amt <= 0) {
    alert('Please enter a valid positive amount.');
    return;
  }

  fetch('/api/lt-portfolio/deposit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ amount: amt })
  }).then(r => r.json()).then(res => {
    if (res.status === 'ok') {
      alert(`✅ Successfully added ₹${amt.toFixed(2)} top-up capital!`);
      if (res.summary) renderLtPortfolioSummary(res.summary);
    } else {
      alert(`❌ Deposit failed: ${res.message}`);
    }
  }).catch(err => alert('Error connecting to backend server.'));
}

function openLtBuyModal(symbol, ltp) {
  let sym = symbol ? symbol.trim().toUpperCase() : '';
  if (!sym) {
    const symInput = prompt('Enter Stock Symbol to Record BUY (e.g. BEL, ASHOKLEY, POWERGRID):');
    if (!symInput) return;
    sym = symInput.trim().toUpperCase();
    const found = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA))
      ? SCREENER_DATA.find(s => s.symbol === sym)
      : null;
    ltp = found ? found.ltp : 0;
  }

  const defaultPrice = ltp && ltp > 0 ? ltp.toFixed(2) : '';
  const priceStr = prompt(`Record BUY Transaction for ${sym}\n\nEnter Buy Price per Share (₹):`, defaultPrice);
  if (!priceStr) return;
  const price = parseFloat(priceStr);
  if (isNaN(price) || price <= 0) {
    alert('Please enter a valid buy price.');
    return;
  }

  const qtyStr = prompt(`Record BUY Transaction for ${sym} @ ₹${price.toFixed(2)}\n\nEnter Quantity of Shares Bought:`, '1');
  if (!qtyStr) return;
  const qty = parseInt(qtyStr, 10);
  if (isNaN(qty) || qty <= 0) {
    alert('Please enter a valid quantity.');
    return;
  }

  const tradeVal = qty * price;
  const brokerage = Math.min(20.0, tradeVal * 0.0005);
  const stt = tradeVal * 0.001;
  const stamp = tradeVal * 0.00015;
  const exch = tradeVal * 0.0000297;
  const gst = (brokerage + exch) * 0.18;
  const totalFees = brokerage + stt + stamp + exch + gst;
  const netCost = tradeVal + totalFees;

  const confirmMsg = `🛒 CONFIRM BUY TRANSACTION\n\n` +
    `• Stock: ${sym}\n` +
    `• Quantity: ${qty} shares\n` +
    `• Price / Share: ₹${price.toFixed(2)}\n` +
    `• Trade Value: ₹${tradeVal.toFixed(2)}\n` +
    `• INDmoney Delivery Charges: ₹${totalFees.toFixed(2)}\n` +
    `========================================\n` +
    `• Total Cash Required: ₹${netCost.toFixed(2)}\n\n` +
    `Deduct ₹${netCost.toFixed(2)} from Available Cash & record in LT Portfolio?`;

  if (confirm(confirmMsg)) {
    fetch('/api/lt-portfolio/buy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, qty: qty, price: price })
    }).then(r => r.json()).then(res => {
      if (res.status === 'ok') {
        alert(`✅ ${res.message}`);
        fetchLtPortfolioStatus();
      } else {
        alert(`❌ Buy Order Failed: ${res.message}\n\nHint: Use "+ Top-Up Capital" button if you need more Available Cash.`);
      }
    }).catch(err => alert('Error connecting to backend server.'));
  }
}

function openLtSellModal(symbol, maxQty, avgPrice, ltp) {
  const qtyStr = prompt(`Execute SELL Order for ${symbol} (Holding: ${maxQty} shares @ ₹${avgPrice.toFixed(2)})\nLive Price: ₹${ltp.toFixed(2)}\n\nEnter Quantity to Sell:`, maxQty);
  if (!qtyStr) return;
  const qty = parseInt(qtyStr, 10);
  if (isNaN(qty) || qty <= 0 || qty > maxQty) {
    alert(`Invalid quantity. Must be between 1 and ${maxQty}.`);
    return;
  }

  if (confirm(`Confirm SELL ${qty} shares of ${symbol} @ ₹${ltp.toFixed(2)}?\n\nNet sale proceeds will be automatically credited back to your Available Cash balance for reinvestment!`)) {
    fetch('/api/lt-portfolio/sell', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: symbol, qty: qty, price: ltp })
    }).then(r => r.json()).then(res => {
      if (res.status === 'ok') {
        alert(`✅ ${res.message}`);
        fetchLtPortfolioStatus();
      } else {
        alert(`❌ Sell Order Failed: ${res.message}`);
      }
    }).catch(err => alert('Error connecting to backend server.'));
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────
init();
fetchLtPortfolioStatus();
</script>
</body>
</html>"""


def fetch_15m_history_cffi(ticker: str) -> pd.DataFrame:
    try:
        from curl_cffi import requests
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=15m&range=5d"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, impersonate="chrome120", headers=headers, timeout=8)
        if r.status_code == 200:
            res = r.json().get("chart", {}).get("result", [{}])[0]
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
def fetch_nifty_history() -> tuple[pd.DataFrame, dict]:
    """Fetches NIFTY 50 (^NSEI) historical data and calculates Market Regime."""
    log("Fetching NIFTY 50 benchmark data (^NSEI)...")
    nifty_df = pd.DataFrame()
    try:
        t = yf.Ticker("^NSEI")
        nifty_df = t.history(period="6mo")
    except Exception:
        pass

    if nifty_df.empty:
        try:
            from screener_engine import fetch_live_price_and_history_cffi
            info, nifty_df = fetch_live_price_and_history_cffi("^NSEI")
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


def build_html(screener_results: list[dict], watchlist: list[dict], lt_watchlist: list[dict], commodity_signals: dict, mkt_info: dict, fno_data: list[dict] | None = None) -> str:
    run_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    def json_serializer(o):
        if hasattr(o, 'item'):
            return o.item()
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        if isinstance(o, (bool, type(True))):
            return bool(o)
        return str(o)

    html = HTML_TEMPLATE
    html = html.replace("__PHASE_LABEL__",   cfg["phase_label"])
    html = html.replace("__PHASE_BUDGET__",  f"{cfg['phase_budget_per_stock']:,}")
    html = html.replace("__MAX_STOCKS__",    str(cfg["max_stocks"]))
    html = html.replace("__TOTAL_BUDGET__",  f"{cfg['total_budget']:,}")
    html = html.replace("__RUN_TIME__",      run_time)
    html = html.replace("__SCREENER_JSON__", json.dumps(screener_results, ensure_ascii=False, default=json_serializer))
    html = html.replace("__WATCHLIST_JSON__", json.dumps(watchlist, ensure_ascii=False, default=json_serializer))
    html = html.replace("__LT_WATCHLIST_JSON__", json.dumps(lt_watchlist, ensure_ascii=False, default=json_serializer))
    html = html.replace("__CONFIG_JSON__",   json.dumps(cfg, ensure_ascii=False, default=json_serializer))
    html = html.replace("__COMMODITIES_JSON__", json.dumps(commodity_signals, ensure_ascii=False, default=json_serializer))
    html = html.replace("__MARKET_INFO_JSON__", json.dumps(mkt_info, ensure_ascii=False, default=json_serializer))
    backtest_data = {}
    backtest_file = os.path.join(BASE_DIR, "cache", "backtest_results.json")
    if os.path.exists(backtest_file):
        try:
            with open(backtest_file) as f:
                backtest_data = json.load(f)
        except Exception:
            pass

    html = html.replace("__BACKTEST_RESULTS_JSON__", json.dumps(backtest_data, ensure_ascii=False, default=json_serializer))
    html = html.replace("__FNO_JSON__", json.dumps(fno_data or [], ensure_ascii=False, default=json_serializer))
    return html


# ─── Local HTTP Scan Server ───────────────────────────────────────────────────
class ScanRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            if os.path.exists(OUT_HTML):
                with open(OUT_HTML, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"HTML report not generated yet.")
            return
        elif parsed.path == '/api/ltp':
            query = urllib.parse.parse_qs(parsed.query)
            raw_ticker = query.get('ticker', [''])[0]
            tickers = [t.strip() for t in raw_ticker.split(',') if t.strip()]
            prices = {}
            if tickers:
                if len(tickers) == 1:
                    t = tickers[0]
                    p = fetch_live_price_only(t)
                    if p: prices[t] = p
                else:
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    with ThreadPoolExecutor(max_workers=min(len(tickers), 15)) as executor:
                        future_to_t = {executor.submit(fetch_live_price_only, t): t for t in tickers}
                        for future in as_completed(future_to_t):
                            t = future_to_t[future]
                            try:
                                p = future.result()
                                if p: prices[t] = p
                            except Exception:
                                pass

            first_price = prices.get(tickers[0]) if tickers else None
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                "ticker": raw_ticker,
                "price": first_price,
                "prices": prices
            }).encode('utf-8'))
            return
        elif parsed.path == '/api/lt-watchlist':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            data = process_lt_watchlist(LATEST_SCREENER_RESULTS)
            self.wfile.write(json.dumps(data, default=json_serializer).encode('utf-8'))
            return
        elif parsed.path in ('/health', '/api/health'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "online", "app": "Stock Screener"}).encode('utf-8'))
            return
        elif parsed.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            mkt_info = get_market_status()
            res = {
                "server": "running",
                "market_info": mkt_info,
                "out_html": OUT_HTML,
                "timestamp": datetime.datetime.now().isoformat(),
                "is_scanning": IS_INITIAL_SCANNING
            }
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/scan':
            log("\n⚡ [API Request] Received Scan Now trigger from web app...")
            try:
                nifty_df, nifty_regime = fetch_nifty_history()
                log(f"  Market Regime: {nifty_regime.get('badge')}")

                tickers = read_stock_list()
                screener_results = run_scan(tickers)
                global LATEST_SCREENER_RESULTS
                LATEST_SCREENER_RESULTS = screener_results

                log("Computing Mansfield Relative Strength (RS Rating 1-99) vs Nifty...")
                screener_results = compute_relative_strength_ratings(screener_results, nifty_df)

                log("Processing LT Watchlist stocks...")
                lt_wl_data = process_lt_watchlist(screener_results)
                wl_data = process_watchlist(screener_results)

                mkt_info = get_market_status()
                mkt_info["nifty"] = nifty_regime

                commodity_signals = fetch_commodity_signals()
                fno_data = process_fno_stocks(screener_results)
                html = build_html(screener_results, wl_data, lt_wl_data, commodity_signals, mkt_info, fno_data)
                with open(OUT_HTML, "w", encoding="utf-8") as f:
                    f.write(html)
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

        elif parsed.path == '/api/lt-portfolio/buy':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                sym = body.get("symbol")
                qty = int(body.get("qty", 0))
                price = float(body.get("price", 0.0))
                res = execute_lt_buy_order(sym, qty, price)
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        elif parsed.path == '/api/lt-portfolio/sell':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                sym = body.get("symbol")
                qty = int(body.get("qty", 0))
                price = float(body.get("price", 0.0))
                res = execute_lt_sell_order(sym, qty, price)
                self.send_response(200)
            except Exception as e:
                res = {"status": "error", "message": str(e)}
                self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(res).encode('utf-8'))
            return

        elif parsed.path == '/api/lt-portfolio/deposit':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode('utf-8'))
                amount = float(body.get("amount", 0.0))
                if amount <= 0:
                    raise ValueError("Deposit amount must be positive")
                ledger = load_lt_capital_ledger()
                ledger["extra_deposits"] = round(float(ledger.get("extra_deposits", 0.0)) + amount, 2)
                save_lt_capital_ledger(ledger)
                summary = get_lt_portfolio_summary()
                res = {"status": "ok", "message": f"Successfully deposited ₹{amount:.2f}", "summary": summary}
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


def open_in_browser(url_or_path: str) -> bool:
    try:
        import webbrowser
        if not str(url_or_path).startswith("http"):
            url_or_path = f"file:///{os.path.abspath(url_or_path).replace(os.sep, '/')}"
        return webbrowser.open(url_or_path)
    except Exception:
        return False


def run_server(port=None):
    if port is None:
        port = int(os.environ.get("PORT", 5000))
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
            if "PORT" not in os.environ:
                log(f"Opening http://localhost:{port} in default browser...")
                open_in_browser(f"http://localhost:{port}")
            while True:
                try:
                    httpd.serve_forever()
                except (KeyboardInterrupt, SystemExit):
                    break
                except Exception as e:
                    log(f"Server exception (recovering): {e}")
                    time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit):
            log("Server stopped.")
        except Exception as e:
            log(f"⚠ Server shutdown: {e}")


def background_initial_scan():
    global IS_INITIAL_SCANNING
    IS_INITIAL_SCANNING = True
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
        global LATEST_SCREENER_RESULTS
        LATEST_SCREENER_RESULTS = screener_results
        try:
            with open(OUT_JSON_FILE, "w", encoding="utf-8") as f:
                json.dump(screener_results, f, default=json_serializer)
        except Exception as e:
            log(f"  ⚠ Could not save screener_data.json: {e}")

        log("Computing Mansfield Relative Strength (RS Rating 1-99) vs Nifty...")
        screener_results = compute_relative_strength_ratings(screener_results, nifty_df)

        log("Processing LT Watchlist stocks...")
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
        with open(OUT_HTML, "w", encoding="utf-8") as f:
            f.write(html)
        try:
            os.makedirs(os.path.dirname(OUT_WWW_HTML), exist_ok=True)
            with open(OUT_WWW_HTML, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception as e:
            log(f"  ⚠ Could not copy report to www/index.html: {e}")

        log(f"\n✅ Scan complete! Report saved: {OUT_HTML}")
    except Exception as e:
        log(f"⚠ Background scan error: {e}")
    finally:
        IS_INITIAL_SCANNING = False


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log("=" * 60)
    log(f"  Quality Stock Screener — Phase 1 (Port {port})")
    log("  Source: Nifty 500 | Scoring: Strength + Value + Momentum")
    log("=" * 60)

    # Launch background scan thread so server starts instantly on port 5000
    log("⚡ Launching scan of 2413 stocks in background thread...")
    scan_t = threading.Thread(target=background_initial_scan, daemon=True)
    scan_t.start()

    # Run the HTTP server immediately in main thread
    run_server(port)



