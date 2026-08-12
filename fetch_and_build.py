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

from screener_engine import score_stock, check_quality_alerts, compute_signal, check_top_pick_status, compute_trend_classification, compute_fno_signal

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CACHE_DIR  = os.path.join(BASE_DIR, "cache")
WL_SEED    = os.path.join(BASE_DIR, "watchlist_seed.json")
WL_FILE    = os.path.join(BASE_DIR, "watchlist_data.json")
OUT_HTML   = os.path.join(BASE_DIR, "index.html")
OUT_WWW_HTML = os.path.join(BASE_DIR, "www", "index.html")

os.makedirs(CACHE_DIR, exist_ok=True)

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

# ─── Live-market LTP cache TTL (minutes) ─────────────────────────────────────
# During equity market hours, prices are re-fetched if cached data is older
# than this many minutes.  Fundamentals still use the full 24-h cache.
LIVE_PRICE_TTL_MINS = 15


def is_equity_market_open() -> bool:
    """Return True when NSE equity session is currently live (09:15–15:30 IST)."""
    import datetime as _dt
    ist_offset = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    now = _dt.datetime.now(ist_offset)
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    t = now.time()
    return _dt.time(9, 15) <= t <= _dt.time(15, 30)


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


def load_cache(ticker, price_stale_check=False):
    """Load cached ticker data.

    Args:
        price_stale_check: When True and the equity market is currently open,
            return None if the cached LTP is older than LIVE_PRICE_TTL_MINS.
            This forces a fresh price fetch while still reusing fundamental
            data from within the same cache file.
    """
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
        if age_hrs >= CACHE_TTL_HRS:
            return None   # fundamentals stale — full re-fetch
        # Invalidate cache entries missing fundamental metrics
        has_fund = any(info.get(k) is not None for k in ["returnOnEquity", "debtToEquity", "trailingPE", "profitMargins"])
        if not has_fund:
            return None   # cache file missing fundamentals — force re-fetch
        # During live market hours, invalidate if price is older than LIVE_PRICE_TTL_MINS
        if price_stale_check and is_equity_market_open():
            age_mins = age_hrs * 60
            if age_mins >= LIVE_PRICE_TTL_MINS:
                return None   # trigger a fresh fetch for live LTP
        return data
    except Exception:
        pass
    return None



def save_cache(ticker, data):
    data["cached_at"] = datetime.datetime.now().isoformat()
    try:
        with open(cache_path(ticker), "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


# ─── Step 1: Read Excel ───────────────────────────────────────────────────────
def read_stock_list() -> list[str]:
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
        log(f"ERROR: Stock list file not found: {target_excel}")
        sys.exit(1)

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
    # During live market hours use a short price TTL so LTP is always fresh.
    market_live = is_equity_market_open()
    cached = load_cache(ticker, price_stale_check=market_live)
    if cached:
        if market_live:
            live_price = fetch_live_price_only(ticker)
            if live_price and live_price > 0:
                old_price = (cached.get("info", {}).get("currentPrice")
                             or cached.get("info", {}).get("regularMarketPrice") or 0)
                if abs(old_price - live_price) > 0.01:
                    cached["info"]["currentPrice"] = live_price
                    cached["info"]["regularMarketPrice"] = live_price
                    cached["cached_at"] = datetime.datetime.now().isoformat()
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
        has_fundamentals = (scored.get("roe_pct") is not None or scored.get("pe") is not None or scored.get("de_ratio") is not None)
        if has_fundamentals:
            qualified = (
                scored["total_score"] >= MIN_TOTAL and
                scored["strength"] >= MIN_STRENGTH
            )
        else:
            qualified = (scored["total_score"] >= MIN_TOTAL)
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



    # Pre-Breakout Score Calculation Pass
    try:
        from pre_breakout_engine import (
            compute_vcp_score, compute_stealth_accumulation,
            compute_sector_rs, compute_tight_consolidation,
            compute_pre_breakout_score, compute_exclusion_thresholds,
            apply_exclusion_filter
        )
        from nse_delivery_fetcher import fetch_delivery_data
        from news_context_fetcher import classify_news_context

        excl_thresholds = compute_exclusion_thresholds(results, min_universe=50)

        for r in results:
            history_df = r.get("history_df")
            if history_df is None or len(history_df) < 55:
                r["pre_breakout_score"] = None
                continue

            is_excl, pen, reasons = apply_exclusion_filter(r, excl_thresholds)
            r["is_pre_breakout_excluded"] = is_excl
            r["exclusion_reasons"] = reasons

            vcp, vcp_brk = compute_vcp_score(history_df)
            stealth, stealth_brk = compute_stealth_accumulation(history_df, r.get("cmf_history"))

            info = {"fiftyTwoWeekHigh": r.get("week_high_52")}
            cons, cons_brk = compute_tight_consolidation(history_df, info)

            stk_ret = r.get("wk52_return_pct")
            sec_ret = 0.0
            sec_rs, sec_brk = compute_sector_rs(stk_ret, sec_ret)

            sym = r.get("symbol", "")
            current_del_pct = fetch_delivery_data(sym)
            del_score = current_del_pct  # raw delivery % used as score input (0–100 natural range)

            is_fno = sym in ["MARUTI", "RELIANCE", "BAJAJ-AUTO", "ULTRACEMCO", "APOLLOHOSP", "TCS"]
            fno_oi_score = None

            pb_score, pb_brk = compute_pre_breakout_score(
                vcp_score=vcp,
                stealth_score=stealth,
                delivery_score=del_score,
                fno_oi_score=fno_oi_score,
                sector_rs_score=sec_rs,
                consolidation_score=cons,
                is_fno=is_fno,
                exclusion_penalty=pen
            )

            r["pre_breakout_score"] = pb_score
            r["atr_ratio"] = vcp_brk.get("atr_ratio")
            r["del_5d_vs_20d"] = f"{current_del_pct:.0f}% / —" if current_del_pct is not None else "—"
            r["rs_vs_sector"] = sec_brk.get("rs_diff")
            r["days_consolidation"] = cons_brk.get("days_in_consolidation")  # fixed key
            r["oi_buildup"] = "🟢 Long Buildup" if is_fno else "—"

            news_ctx = classify_news_context(r.get("name", ""), sym)
            r["news_context"] = news_ctx

    except Exception as e:
        log(f"  ⚠ Pre-Breakout scoring pass skipped/failed: {e}")

    results.sort(key=lambda x: x["total_score"], reverse=True)
    log(f"\nScan complete: {len(results)} priced < ₹{MAX_PRICE}, "
        f"{sum(1 for r in results if r['qualified'])} qualified, "
        f"{skipped_price} excluded by price, {skipped_nodata} no-data\n")
    return results



# ─── Step 3b: Process F&O stocks (bypass price cap, compute options signal) ────────
def process_fno_stocks(screener_results: list[dict]) -> list[dict]:
    """Fetch/score the 6 designated F&O stocks and compute their weekly
    OTM options signal.  F&O stocks bypass the ₹5000 price filter."""
    fno_cfgs = cfg.get("fno_stocks", [])
    if not fno_cfgs:
        return []

    result_map = {r["symbol"]: r for r in screener_results}
    fno_data = []

    for fc in fno_cfgs:
        sym    = fc["symbol"]
        ticker = fc["ticker"]
        scored = result_map.get(sym)

        if scored is None:
            # Not in the main scan (price > ₹5000 cap) — fetch individually
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
            signal = compute_fno_signal(scored, fc)
            fno_data.append(signal)
        else:
            log(f"  ⚠ F&O: could not fetch data for {sym}")

    return fno_data


# ─── Step 4: Score watchlist stocks & fill entry metrics ─────────────────────
def process_watchlist(screener_results: list[dict]) -> list[dict]:
    # Load or initialise watchlist from seed
    if os.path.exists(WL_FILE):
        with open(WL_FILE) as f:
            watchlist = json.load(f)
    else:
        with open(WL_SEED) as f:
            watchlist = json.load(f)

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

    # ─── Auto-add top stock suggestions to fill empty watchlist slots ──────
    existing_symbols = {w["symbol"] for w in watchlist}
    slots_available = MAX_STOCKS - len(watchlist)

    if slots_available > 0:
        log(f"\nChecking top stock suggestions to auto-add into watchlist ({slots_available} slots open)...")
        for scored in screener_results:
            if len(watchlist) >= MAX_STOCKS:
                break
            sym = scored["symbol"]
            if sym in existing_symbols:
                continue

            if scored.get("qualified") or (scored["total_score"] >= MIN_TOTAL and scored["strength"] >= MIN_STRENGTH):
                ltp = scored["ltp"]
                if ltp <= 0:
                    continue
                qty = max(1, int(PHASE_BUDGET / ltp))
                avg_cost = ltp
                tot_inv = round(ltp * qty, 2)
                sig = compute_signal(scored, {})

                new_item = {
                    "symbol": sym,
                    "ticker": scored["ticker"],
                    "name": scored.get("name") or sym,
                    "sector": scored.get("sector", ""),
                    "qty": qty,
                    "avg_cost": avg_cost,
                    "total_invested": tot_inv,
                    "added_at": datetime.date.today().isoformat(),
                    "auto_added": True,
                    "score_at_entry": scored["total_score"],
                    "strength_at_entry": scored["strength"],
                    "value_at_entry": scored["value"],
                    "momentum_at_entry": scored["momentum"],
                    "roe_at_entry": scored.get("roe_pct"),
                    "de_at_entry": scored.get("de_ratio"),
                    "npm_at_entry": scored.get("npm_pct"),
                    "current_score": scored["total_score"],
                    "current_strength": scored["strength"],
                    "current_value": scored["value"],
                    "current_momentum": scored["momentum"],
                    "ltp": ltp,
                    "pe": scored.get("pe"),
                    "roe_pct": scored.get("roe_pct"),
                    "de_ratio": scored.get("de_ratio"),
                    "npm_pct": scored.get("npm_pct"),
                    "rsi": scored.get("rsi"),
                    "ma200": scored.get("ma200"),
                    "wk52_return_pct": scored.get("wk52_return_pct"),
                    "volume_spike": scored.get("volume_spike", 0.0),
                    "today_volume": scored.get("today_volume", 0),
                    "avg_volume_10d": scored.get("avg_volume_10d", 0),
                    "news": scored.get("news", []),
                    "alerts": check_quality_alerts(scored, {}),
                    "signal": sig["signal"],
                    "signal_badge": sig["badge"],
                    "signal_reason": sig["reason"],
                    "unrealised_pnl": 0.0,
                    "unrealised_pct": 0.0,
                }
                watchlist.append(new_item)
                existing_symbols.add(sym)
                log(f"  ⚡ Auto-added top suggestion: {sym:<12} (Score: {scored['total_score']:>4.1f}, Signal: {sig['badge']}, LTP: ₹{ltp:>7.2f}, Qty: {qty:>2})")

    # Save updated watchlist
    with open(WL_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)

    return watchlist


# ─── Step 4b: Market Timezone Awareness & Daily Top Pick Processing ────────────
DAILY_PICKS_FILE = os.path.join(BASE_DIR, "daily_picks_history.json")

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
    # If today's pick has already been locked in history, check if it remains ACTIVE & is Large/Mid cap with LTP >= 100
    if history and history[0].get("date") == today_str and not history[0].get("is_pre_market"):
        top_pick = dict(history[0])
        sym = top_pick.get("symbol")
        res = result_map.get(sym)
        if res and is_eligible_for_stock_of_the_day(top_pick) and is_eligible_for_stock_of_the_day(res):
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
        
        # If history[0] was invalid (penny stock, ORTEL, smallcap), remove it
        history.pop(0)

    # STRICT SELECTION: Stock of the Day MUST BE Large Cap or Mid Cap ONLY, with LTP >= Rs 100
    eligible_screener_results = [r for r in screener_results if is_eligible_for_stock_of_the_day(r)]
    
    qualified_eligible = [
        r for r in eligible_screener_results
        if (
            r.get("qualified") and
            (
                r.get("market_structure") == "HH / HL Uptrend" or
                r.get("tech_class") == "badge-green" or
                (r.get("ltp", 0) > r.get("ma50", 0) and r.get("ltp", 0) > r.get("ma200", 0))
            )
        )
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

    dist_ma50 = round(((ltp - ma50) / ma50) * 100, 1) if (ma50 and ltp) else None
    dist_ma200 = round(((ltp - ma200) / ma200) * 100, 1) if (ma200 and ltp) else None
    dist_52h = round(((ltp - w52_h) / w52_h) * 100, 1) if (w52_h and ltp) else None
    dist_52l = round(((ltp - w52_l) / w52_l) * 100, 1) if (w52_l and ltp) else None

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

    is_pre_mkt = mkt_info["is_pre_market"]

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

  <!-- Desktop Top Tabs (Hidden on mobile where bottom nav is active) -->
  <div class="tabs">
    <button class="tab active" onclick="switchTab('screener')">🔍 Screener Results</button>
    <button class="tab" onclick="switchTab('prebreakout')">🔥 Pre-Breakout Watchlist</button>
    <button class="tab" onclick="switchTab('watchlist')">⭐ My Watchlist (<span id="wlCount">0</span>)</button>
    <button class="tab" onclick="switchTab('top-pick')">🏆 Stock of the Day</button>
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
    <div class="table-wrap">
      <table id="screenerTable">
        <thead>
          <tr>
            <th onclick="sortTable('symbol')" title="Click to sort by Symbol">Symbol <span id="sort_symbol">↕</span></th>
            <th onclick="sortTable('ltp')" title="Click to sort by Price">Price <span id="sort_ltp">↕</span></th>
            <th onclick="sortTable('total_score')" title="Click to sort by Total Score">Total Score <span id="sort_total_score">↕</span></th>
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

  <!-- WATCHLIST TAB -->
  <div id="tab-watchlist" style="display:none">
    <!-- Sleek Glassmorphic Summary Banner -->
    <div style="background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px;margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,0.2)">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;text-align:center;align-items:center">
        <div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">Slots Used</div>
          <div style="font-size:22px;font-weight:700;margin-top:2px"><span id="slotsUsed">0</span> / __MAX_STOCKS__</div>
          <div class="slot-bar" style="margin-top:6px;height:4px"><div class="slot-fill" id="slotFill" style="width:0%"></div></div>
        </div>
        <div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">Total Invested</div>
          <div style="font-size:22px;font-weight:700;color:var(--accent2);margin-top:2px">₹<span id="totalInvested">0</span></div>
          <div style="font-size:11px;color:var(--muted);margin-top:2px">Cap: ₹__TOTAL_BUDGET__</div>
        </div>
        <div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">Portfolio P&L</div>
          <div style="font-size:22px;font-weight:700;margin-top:2px" id="wlPortfolioPnl">—</div>
          <div style="font-size:11px;color:var(--muted);margin-top:2px" id="wlPortfolioPnlPct">0.00%</div>
        </div>
        <div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">Signal Breakdown</div>
          <div style="font-size:12px;font-weight:700;margin-top:6px;display:flex;justify-content:center;gap:10px" id="wlSignalCounts">
            <span style="color:var(--green)">🟢 0 BUY</span>
            <span style="color:var(--warn)">🟡 0 HOLD</span>
            <span style="color:var(--danger)">🔴 0 SELL</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Toolbar: Filter Pills & View Toggles & Auto-Add button -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:12px">
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <span style="font-size:12px;color:var(--muted);font-weight:600;margin-right:4px">Signal:</span>
        <button class="filter-reset" onclick="filterWlSignal('ALL')" id="wlSigBtnALL" style="border-color:var(--accent);color:var(--accent);font-weight:700">All</button>
        <button class="filter-reset" onclick="filterWlSignal('BUY')" id="wlSigBtnBUY" style="color:var(--green)">🟢 BUY</button>
        <button class="filter-reset" onclick="filterWlSignal('HOLD')" id="wlSigBtnHOLD" style="color:var(--warn)">🟡 HOLD</button>
        <button class="filter-reset" onclick="filterWlSignal('SELL')" id="wlSigBtnSELL" style="color:var(--danger)">🔴 SELL</button>
      </div>

      <div style="display:flex;gap:10px;align-items:center">
        <!-- View Toggle Pills -->
        <div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:3px;display:flex;gap:2px">
          <button id="wlViewCardsBtn" onclick="setWlViewMode('cards')" style="background:var(--accent);color:#fff;border:none;padding:5px 12px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer">📱 Cards</button>
          <button id="wlViewTableBtn" onclick="setWlViewMode('table')" style="background:none;color:var(--muted);border:none;padding:5px 12px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer">📊 Table</button>
        </div>

        <button class="btn-add" style="background:var(--card2);border:1px solid var(--border);color:var(--text);font-weight:600;padding:6px 14px;border-radius:8px;cursor:pointer;font-size:12px" onclick="openBseModal()">
          ➕ Add BSE / Custom Stock
        </button>
        <button class="btn-add" style="background:linear-gradient(135deg,#00d4aa,#10b981);color:#06060f;font-weight:700;padding:6px 14px;border-radius:8px;cursor:pointer;font-size:12px" onclick="autoAddTopSuggestions()">
          ⚡ Auto-Add Suggestions
        </button>
      </div>
    </div>

    <!-- Cards View Container -->
    <div class="wl-grid" id="watchlistGrid"></div>

    <!-- Datatable View Container -->
    <div class="table-wrap" id="watchlistTableWrap" style="display:none">
      <table>
        <thead>
          <tr>
            <th onclick="sortWlTable('symbol')" style="cursor:pointer;user-select:none" title="Click to sort by Symbol">SYMBOL <span id="wlSort_symbol">↕</span></th>
            <th onclick="sortWlTable('signal')" style="cursor:pointer;user-select:none" title="Click to sort by Signal">SIGNAL <span id="wlSort_signal">↕</span></th>
            <th onclick="sortWlTable('ltp')" style="cursor:pointer;user-select:none" title="Click to sort by Price">PRICE <span id="wlSort_ltp">↕</span></th>
            <th onclick="sortWlTable('unrealised_pnl')" style="cursor:pointer;user-select:none" title="Click to sort by Unrealised P&L">UNREALISED P&L <span id="wlSort_unrealised_pnl">↕</span></th>
            <th onclick="sortWlTable('current_score')" style="cursor:pointer;user-select:none" title="Click to sort by Quality Score">SCORE <span id="wlSort_current_score">↕</span></th>
            <th onclick="sortWlTable('current_strength')" style="cursor:pointer;user-select:none" title="Click to sort by Strength">STRENGTH <span id="wlSort_current_strength">↕</span></th>
            <th onclick="sortWlTable('roe_pct')" style="cursor:pointer;user-select:none" title="Click to sort by ROE%">ROE% <span id="wlSort_roe_pct">↕</span></th>
            <th onclick="sortWlTable('de_ratio')" style="cursor:pointer;user-select:none" title="Click to sort by Debt/Equity">D/E <span id="wlSort_de_ratio">↕</span></th>
            <th onclick="sortWlTable('rsi')" style="cursor:pointer;user-select:none" title="Click to sort by RSI">RSI <span id="wlSort_rsi">↕</span></th>
            <th>ACTION</th>
          </tr>
        </thead>
        <tbody id="watchlistTableBody"></tbody>
      </table>
    </div>

    <div id="wlEmpty" style="display:none;text-align:center;padding:40px;color:var(--muted)">
      No stocks in watchlist match the selected signal filter. Add from the Screener tab or click ⚡ Auto-Add Suggestions!
    </div>
  </div>

  <!-- PRE-BREAKOUT WATCHLIST TAB -->
  <div id="tab-prebreakout" style="display:none">
    <!-- Backtest Statistical Validation Card -->
    <div style="background:linear-gradient(135deg,#0a0a1a,#13132e);border:1px solid #6c63ff44;border-radius:16px;padding:20px;margin-bottom:20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px">
      <div>
        <div style="font-size:16px;font-weight:700;color:#a5b4fc;margin-bottom:4px;display:flex;align-items:center;gap:8px">
          <span>📊 Section 7A Statistical Validation Backtest</span>
          <span style="font-size:11px;background:rgba(16,185,129,0.2);border:1px solid #10b981;color:#34d399;padding:2px 8px;border-radius:12px;font-weight:700">✅ GATE PASSED (1.55x Ratio)</span>
        </div>
        <div style="font-size:12px;color:var(--muted)">
          Evaluated 19,823 daily instances across 180 stocks over 6 months. Top-decile PreBreakoutScore hit rate: <strong>39.23%</strong> vs <strong>25.23%</strong> base rate (+5.0% move in 10 days).
        </div>
      </div>
      <div style="display:flex;gap:16px">
        <div style="text-align:center">
          <div style="font-size:22px;font-weight:800;color:#00d4aa">1.55x</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Hit-Rate Ratio</div>
        </div>
        <div style="text-align:center">
          <div style="font-size:22px;font-weight:800;color:#a5b4fc">2,238</div>
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Top-Decile Scans</div>
        </div>
      </div>
    </div>

    <!-- Pre-Breakout Table -->
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th onclick="sortPbTable('symbol')" style="cursor:pointer" title="Sort by Symbol">SYMBOL <span id="pbSort_symbol">↕</span></th>
            <th onclick="sortPbTable('ltp')" style="cursor:pointer" title="Sort by Price">PRICE <span id="pbSort_ltp">↕</span></th>
            <th onclick="sortPbTable('pre_breakout_score')" style="cursor:pointer" title="Sort by PreBreakoutScore">PRE-BREAKOUT SCORE <span id="pbSort_pre_breakout_score">↕</span></th>
            <th title="ATR(14)/ATR(50) Contraction Ratio">ATR RATIO (VCP)</th>
            <th title="5-Day vs 20-Day Rolling Delivery %">DELIVERY TREND (5D/20D)</th>
            <th title="Relative Strength vs Sector Average">RS VS SECTOR</th>
            <th title="Days Price Stayed in Tight Range">CONSOLIDATION</th>
            <th title="F&O Futures Long Buildup Flag">OI BUILDUP</th>
            <th title="Recent News Context Classification">NEWS CONTEXT</th>
          </tr>
        </thead>
        <tbody id="prebreakoutTableBody"></tbody>
      </table>
    </div>
  </div>

  <!-- STOCK OF THE DAY & DASHBOARD OVERVIEW TAB -->
  <div id="tab-top-pick" style="display:none">

    <!-- 6-Card Stats Summary Grid -->
    <div class="stats-grid" id="statsGrid" style="margin-bottom:20px"></div>

    <!-- Commodities Intraday Signals Bar -->
    <div class="commodity-bar" id="commodityBar" style="margin-bottom:20px">
      <div class="commodity-bar-title">
        <span style="font-size:16px">⛽</span>
        <span style="font-weight:600;font-size:13px;color:var(--text)">Commodities Intraday Signals</span>
        <span style="font-size:10px;background:rgba(255,255,255,0.06);padding:2px 8px;border-radius:10px;color:var(--muted)">15m timeframe (15/20 EMA Crossover)</span>
      </div>
      <div class="commodity-cards" id="commodityCards"></div>
    </div>

    <!-- Inner Spotlight Content -->
    <div id="topPickInnerContent"></div>
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

<!-- Fixed Mobile Bottom Navigation Bar -->
<div class="mobile-nav-bar">
  <button class="mobile-nav-item active" data-tab="screener" onclick="switchTab('screener')">
    <span class="mobile-nav-icon">🔍</span>
    <span>Screener</span>
  </button>
  <button class="mobile-nav-item" data-tab="watchlist" onclick="switchTab('watchlist')">
    <span class="mobile-nav-icon">⭐</span>
    <span>Watchlist</span>
  </button>
  <button class="mobile-nav-item" data-tab="top-pick" onclick="switchTab('top-pick')">
    <span class="mobile-nav-icon">🏆</span>
    <span>Top Pick</span>
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
const CONFIG = __CONFIG_JSON__;
const TOP_PICK = __TOP_PICK_JSON__;
const DAILY_PICKS_HISTORY = __DAILY_PICKS_HISTORY_JSON__;
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
  if (!container) return;
  
  const currentMkt = calculateCurrentMarketStatus();
  if (typeof MARKET_INFO !== 'undefined' && MARKET_INFO) {
    MARKET_INFO.is_open = currentMkt.is_open;
    MARKET_INFO.is_equity_open = currentMkt.is_equity_open;
    MARKET_INFO.is_pre_market = currentMkt.is_pre_market;
  }
  container.innerHTML = `<span class="badge ${currentMkt.badge_class || 'badge-green'}" style="font-size:12px;padding:6px 14px;font-weight:700" title="${currentMkt.message}">${currentMkt.badge}</span>`;
  updateLtpBadgeStatus();
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

// ── Init ──────────────────────────────────────────────────────────────────
function init() {
  renderMarketStatusHeader();
  updateLtpBadgeStatus();
  renderCommodityBar();
  // Load watchlist from localStorage, merge with seed
  const stored = localStorage.getItem('quality_watchlist_v1');
  if (stored) {
    try { watchlist = JSON.parse(stored); }
    catch { watchlist = []; }
  }
  // Always ensure seed stocks are present (first run)
  WATCHLIST_SEED.forEach(seed => {
    const exists = watchlist.find(w => w.symbol === seed.symbol);
    if (!exists) watchlist.push(seed);
    else {
      // Update live data from scan
      const live = SCREENER_DATA.find(s => s.symbol === seed.symbol);
      if (live) {
        exists.ltp = live.ltp;
        exists.current_score = live.total_score;
        exists.current_strength = live.strength;
        exists.current_value = live.value;
        exists.current_momentum = live.momentum;
        exists.roe_pct = live.roe_pct;
        exists.de_ratio = live.de_ratio;
        exists.npm_pct = live.npm_pct;
        exists.rsi = live.rsi;
        exists.wk52_return_pct = live.wk52_return_pct;
        exists.alerts = seed.alerts || [];
        exists.news = live.news || [];
        if (exists.score_at_entry == null) {
          exists.score_at_entry = seed.score_at_entry;
          exists.strength_at_entry = seed.strength_at_entry;
          exists.roe_at_entry = seed.roe_at_entry;
          exists.de_at_entry = seed.de_at_entry;
          exists.npm_at_entry = seed.npm_at_entry;
        }
      }
    }
  });

  // Auto-add top suggestions on boot if empty slots exist
  autoAddTopSuggestions(true);

  saveWatchlist();
  renderStats();
  populateSectorFilter();
  applyFilters();
  renderWatchlist();
  updateWlCount();

  renderMarketStatusHeader();
  startPolling();
  refreshLiveLTP(true);
  setInterval(renderMarketStatusHeader, 30000);
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

  // Automatically stop background polling if market is closed (allow manual click if forced)
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

  const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  let priceChanged = false;

  const symbolsToPoll = new Map();
  if (typeof TOP_PICK !== 'undefined' && TOP_PICK && TOP_PICK.symbol) {
    symbolsToPoll.set(TOP_PICK.symbol, TOP_PICK.ticker || TOP_PICK.symbol + '.NS');
  }
  watchlist.forEach(w => symbolsToPoll.set(w.symbol, w.ticker || w.symbol + '.NS'));
  filteredData.slice(0, 20).forEach(s => symbolsToPoll.set(s.symbol, s.ticker || s.symbol + '.NS'));
  if (typeof FNO_DATA !== 'undefined' && Array.isArray(FNO_DATA)) {
    FNO_DATA.forEach(f => symbolsToPoll.set(f.symbol, f.ticker || f.symbol + '.NS'));
  }

  for (const [sym, ticker] of symbolsToPoll.entries()) {
    const newPrice = await fetchLiveLTPForSymbol(ticker);
    if (newPrice && newPrice > 0) {
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
  }

  if (dot) dot.classList.remove('updating');
  updateLtpBadgeStatus();

  if (priceChanged) {
    saveWatchlist();
    renderStats();
    renderTable();
    renderWatchlist();
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

  // Stop background polling automatically if market is closed
  if (!isOpen || pollIntervalMs <= 0) {
    updateLtpBadgeStatus();
    return;
  }

  pollIntervalTimer = setInterval(() => refreshLiveLTP(false), pollIntervalMs);
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
  localStorage.setItem('quality_watchlist_v1', JSON.stringify(watchlist));
}

// ── Stats ─────────────────────────────────────────────────────────────────
function renderStats() {
  const qualified = SCREENER_DATA.filter(s => s.qualified).length;
  const total = SCREENER_DATA.length;
  const avgScore = total > 0 ? (SCREENER_DATA.reduce((a,b)=>a+b.total_score,0)/total).toFixed(1) : 0;
  const alerts = watchlist.filter(w => w.alerts && w.alerts.length > 0).length;
  const totalInvested = watchlist.reduce((a,w)=>a+(w.total_invested||0),0);

  document.getElementById('statsGrid').innerHTML = `
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
  const tabs = ['screener', 'prebreakout', 'watchlist', 'top-pick', 'fno', 'holidays'];
  document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', tabs[i] === tab));
  document.querySelectorAll('.mobile-nav-item').forEach(m => {
    m.classList.toggle('active', m.dataset.tab === tab);
  });
  document.getElementById('tab-screener').style.display  = tab === 'screener'  ? '' : 'none';
  document.getElementById('tab-prebreakout').style.display = tab === 'prebreakout' ? '' : 'none';
  document.getElementById('tab-watchlist').style.display = tab === 'watchlist' ? '' : 'none';
  document.getElementById('tab-top-pick').style.display  = tab === 'top-pick'  ? '' : 'none';
  document.getElementById('tab-fno').style.display       = tab === 'fno'       ? '' : 'none';
  document.getElementById('tab-holidays').style.display  = tab === 'holidays'  ? '' : 'none';
  if (tab === 'prebreakout') renderPreBreakoutTab();
  if (tab === 'watchlist')  renderWatchlist();
  if (tab === 'top-pick')   renderTopPick();
  if (tab === 'fno')        renderFnoTab();
  if (tab === 'holidays')   renderHolidaysTab();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

let pbSortCol = 'pre_breakout_score';
let pbSortDir = -1;

function sortPbTable(col) {
  if (pbSortCol === col) {
    pbSortDir *= -1;
  } else {
    pbSortCol = col;
    pbSortDir = -1;
  }
  renderPreBreakoutTab();
}

function renderPreBreakoutTab() {
  const tbody = document.getElementById('prebreakoutTableBody');
  if (!tbody) return;

  const pbData = (SCREENER_DATA || []).filter(s => s.pre_breakout_score != null || s.symbol);
  if (!pbData.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:40px;color:var(--muted)">No pre-breakout score calculated yet. Run a scan.</td></tr>';
    return;
  }

  pbData.sort((a, b) => {
    let va = a[pbSortCol];
    let vb = b[pbSortCol];
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'string') return va.localeCompare(vb) * pbSortDir;
    return (va - vb) * pbSortDir;
  });

  tbody.innerHTML = pbData.map(s => {
    const score = s.pre_breakout_score != null ? s.pre_breakout_score : '—';
    const scoreCls = typeof score === 'number' ? (score >= 70 ? 'badge-green' : score >= 50 ? 'badge-yellow' : 'badge-gray') : 'badge-gray';
    const atrRatio = s.atr_ratio != null ? s.atr_ratio.toFixed(2) : '—';
    const delTrend = s.del_5d_vs_20d ? s.del_5d_vs_20d : '—';
    const rsSector = s.rs_vs_sector != null ? (s.rs_vs_sector >= 0 ? '+' : '') + s.rs_vs_sector.toFixed(1) + '%' : '—';
    const daysCons = s.days_consolidation != null ? s.days_consolidation + 'd' : '—';
    const oiBuild = s.oi_buildup || '—';

    const newsCtx = s.news_context || { badge: '⚪ Neutral', badge_class: 'badge-gray', headlines: [] };
    const newsTitle = (newsCtx.headlines || []).join('\n') || 'No recent news';
    const exclBadge = s.is_pre_breakout_excluded ? ` <span title="${(s.exclusion_reasons || []).join(', ')}" style="color:var(--danger);font-size:10px;cursor:help">⛔ Excluded</span>` : '';

    return `
      <tr>
        <td style="font-weight:700;color:var(--white)">${s.symbol}${exclBadge} <div style="font-size:10px;color:var(--muted)">${s.sector || ''}</div></td>
        <td style="font-family:monospace;font-weight:600">₹${s.ltp ? s.ltp.toFixed(2) : '—'}</td>
        <td><span class="badge ${scoreCls}" style="font-size:13px;font-weight:800">${score}</span></td>
        <td style="font-family:monospace">${atrRatio}</td>
        <td style="font-family:monospace">${delTrend}</td>
        <td style="font-family:monospace;color:${s.rs_vs_sector >= 0 ? 'var(--green)' : 'var(--danger)'}">${rsSector}</td>
        <td>${daysCons}</td>
        <td>${oiBuild}</td>
        <td><span class="badge ${newsCtx.badge_class}" title="${newsTitle.replace(/"/g, '&quot;')}">${newsCtx.badge}</span></td>
      </tr>
    `;
  }).join('');
}


// ── F&O Options Tab ──────────────────────────────────────────────
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

  const cards = FNO_DATA.map(s => {
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
            <span>Conviction</span>
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
    <div class="fno-grid">${cards}</div>
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
            ✨ ${TOP_PICK.is_pre_market ? "Today's #1 Candidate" : "Today's #1 Highest-Scoring Stock"}
          </span>`}
          <span class="badge ${TOP_PICK.is_pre_market ? 'badge-yellow' : (TOP_PICK.status === 'INVALIDATED' ? 'badge-yellow' : TOP_PICK.status === 'INACTIVE' ? 'badge-red' : 'badge-green')}" style="font-weight:700;font-size:12px;padding:6px 12px">
            ${TOP_PICK.status_badge || '🟢 ACTIVE'}
          </span>
        </div>
        <div class="badge ${TOP_PICK.tech_class || 'badge-green'}" style="font-size:14px;font-weight:800;padding:8px 18px;border-radius:20px;box-shadow:0 4px 14px rgba(0,0,0,0.3);letter-spacing:0.02em">
          ${TOP_PICK.tech_rating || '🟢 Strong Uptrend'}
        </div>
      </div>

      ${TOP_PICK.status && TOP_PICK.status !== 'ACTIVE' ? `
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

function applyFilters() {
  const search   = document.getElementById('fSearch').value.trim().toLowerCase();
  const qual     = document.getElementById('fQual').value;
  const sector   = document.getElementById('fSector') ? document.getElementById('fSector').value : 'all';
  const mcap     = document.getElementById('fMcap') ? document.getElementById('fMcap').value : 'all';
  const trend    = document.getElementById('fTrend').value;

  filteredData = SCREENER_DATA.filter(s => {
    if (qual === 'qualified' && !s.qualified) return false;
    if (qual === 'watch' && s.total_score < 45) return false;

    if (search && !s.symbol.toLowerCase().includes(search) && !(s.name||'').toLowerCase().includes(search) && !(s.sector||'').toLowerCase().includes(search)) return false;

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

  const match = SCREENER_DATA.find(s => s.symbol.toLowerCase() === search) ||
                SCREENER_DATA.find(s => s.symbol.toLowerCase().startsWith(search)) ||
                SCREENER_DATA.find(s => (s.name||'').toLowerCase().includes(search));

  if (!match) {
    container.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px 16px;font-size:13px;color:var(--muted);display:flex;align-items:center;gap:8px">
        <span>🔍</span> No stock matching "<strong>${search}</strong>" found in Nifty 500 scan results.
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
  const body = filteredData.map(s => {
    const inWlSet = inWl.has(s.symbol);
    const full = watchlist.length >= maxSlots && !inWlSet;
    const badge = s.qualified
      ? `<span class="badge badge-green">🟢 Qualified</span>`
      : s.total_score >= 45
        ? `<span class="badge badge-yellow">🟡 Watch</span>`
        : `<span class="badge badge-red">🔴 Avoid</span>`;

    return `<tr>
      <td>
        <div class="stock-name">${s.symbol}</div>
        <div class="stock-sym">${s.name||''}</div>
        <div class="stock-sector">${s.sector||''}</div>
      </td>
      <td><span class="price">₹${s.ltp.toFixed(2)}</span></td>
      <td>${scoreBar(s.total_score)}</td>
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
      <td><span class="badge ${s.tech_class || 'badge-yellow'}" style="font-size:11px;white-space:nowrap">${s.tech_rating || '🟡 Consolidation'}</span></td>
      <td>${badge}</td>
      <td>
        <button class="btn-add" onclick="openModal('${s.symbol}')" style="margin-bottom:4px">Detail</button><br>
        <button class="btn-add" onclick="addToWl('${s.symbol}')"
          ${inWlSet?'disabled':''}
          ${full&&!inWlSet?'disabled title="20 slots full"':''}
        >${inWlSet?'✓ In WL':'+ Watchlist'}</button>
      </td>
    </tr>`;
  }).join('');

  document.getElementById('screenerBody').innerHTML = body || `<tr><td colspan="17" class="no-data">No stocks match the current filters.</td></tr>`;
}

// ── Watchlist ─────────────────────────────────────────────────────────────
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

// ── Boot ──────────────────────────────────────────────────────────────────
init();
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
    return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])


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


def build_html(screener_results: list[dict], watchlist: list[dict], top_pick: dict, daily_history: list[dict], commodity_signals: dict, mkt_info: dict, fno_data: list[dict] | None = None) -> str:
    run_time = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")

    html = HTML_TEMPLATE
    html = html.replace("__PHASE_LABEL__",   cfg["phase_label"])
    html = html.replace("__PHASE_BUDGET__",  f"{cfg['phase_budget_per_stock']:,}")
    html = html.replace("__MAX_STOCKS__",    str(cfg["max_stocks"]))
    html = html.replace("__TOTAL_BUDGET__",  f"{cfg['total_budget']:,}")
    html = html.replace("__RUN_TIME__",      run_time)
    html = html.replace("__SCREENER_JSON__", json.dumps(screener_results, ensure_ascii=False))
    html = html.replace("__WATCHLIST_JSON__", json.dumps(watchlist, ensure_ascii=False))
    html = html.replace("__CONFIG_JSON__",   json.dumps(cfg, ensure_ascii=False))
    html = html.replace("__TOP_PICK_JSON__", json.dumps(top_pick, ensure_ascii=False))
    html = html.replace("__DAILY_PICKS_HISTORY_JSON__", json.dumps(daily_history, ensure_ascii=False))
    html = html.replace("__COMMODITIES_JSON__", json.dumps(commodity_signals, ensure_ascii=False))
    html = html.replace("__MARKET_INFO_JSON__", json.dumps(mkt_info, ensure_ascii=False))
    backtest_data = {}
    backtest_file = os.path.join(BASE_DIR, "cache", "backtest_results.json")
    if os.path.exists(backtest_file):
        try:
            with open(backtest_file) as f:
                backtest_data = json.load(f)
        except Exception:
            pass

    html = html.replace("__BACKTEST_RESULTS_JSON__", json.dumps(backtest_data, ensure_ascii=False))
    html = html.replace("__FNO_JSON__", json.dumps(fno_data or [], ensure_ascii=False))
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
                "timestamp": datetime.datetime.now().isoformat()
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
                tickers = read_stock_list()
                screener_results = run_scan(tickers)
                wl_data = process_watchlist(screener_results)
                top_pick, daily_history, mkt_info = process_daily_top_pick(screener_results)
                commodity_signals = fetch_commodity_signals()
                fno_data = process_fno_stocks(screener_results)
                html = build_html(screener_results, wl_data, top_pick, daily_history, commodity_signals, mkt_info, fno_data)
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

    def log_message(self, format, *args):
        pass


def run_server(port=None):
    if port is None:
        port = int(os.environ.get("PORT", 5000))
    log("=" * 60)
    log(f"⚡ Stock Screener Server running at port {port}")
    log("=" * 60)
    
    server_address = ('0.0.0.0', port)
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        def handle_error(self, request, client_address):
            exctype, value, tb = sys.exc_info()
            if exctype and issubclass(exctype, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError)):
                return
            super().handle_error(request, client_address)

    try:
        httpd = ThreadedHTTPServer(server_address, ScanRequestHandler)
        if "PORT" not in os.environ:
            log(f"Opening http://localhost:{port} in default browser...")
            open_in_browser(f"http://localhost:{port}")
        httpd.serve_forever()
    except Exception as e:
        log(f"⚠ Could not start server on port {port}: {e}")
        log(f"Falling back to opening static file: {OUT_HTML}")
        open_in_browser(OUT_HTML)


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import threading
    log("=" * 60)
    log("  Quality Stock Screener — Phase 1")
    log("  Source: Nifty 500 | Scoring: Strength + Value + Momentum")
    log("=" * 60)

    # Launch web server immediately in background thread so Render detects port binding in <1s
    log("⚡ Starting Web Server for cloud port binding...")
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Automatically check and download Nifty index list updates first
    log("Checking for Nifty stock list updates from NSE...")
    try:
        import download_nse_indices
        download_nse_indices.main()
    except Exception as e:
        log(f"  ⚠ Stock list auto-update skipped: {e}")

    tickers = read_stock_list()
    screener_results = run_scan(tickers)

    log("Processing watchlist stocks...")
    wl_data = process_watchlist(screener_results)

    log("Processing Stock of the Day & history...")
    top_pick, daily_history, mkt_info = process_daily_top_pick(screener_results)

    log("Fetching Commodity Intraday Signals (Crude Oil & Natural Gas)...")
    commodity_signals = fetch_commodity_signals()

    log("Processing F&O Options Signals (MARUTI, RELIANCE, BAJAJ-AUTO, ULTRACEMCO, APOLLOHOSP, TCS)...")
    fno_data = process_fno_stocks(screener_results)

    log("Building HTML report...")
    html = build_html(screener_results, wl_data, top_pick, daily_history, commodity_signals, mkt_info, fno_data)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    try:
        os.makedirs(os.path.dirname(OUT_WWW_HTML), exist_ok=True)
        with open(OUT_WWW_HTML, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        log(f"  ⚠ Could not copy report to www/index.html: {e}")

    log(f"\n✅ Scan complete! Report saved: {OUT_HTML}")
    port = int(os.environ.get("PORT", 5000))
    if "PORT" not in os.environ:
        log(f"Opening http://localhost:{port} in default browser...")
        if not open_in_browser(f"http://localhost:{port}"):
            open_in_browser(OUT_HTML)
    server_thread.join()


