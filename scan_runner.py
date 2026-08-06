import json
import os
import sys
import time
import datetime
import pandas as pd
import yfinance as yf
from screener_engine import score_stock, compute_trend_classification

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
OUT_JSON = os.path.join(BASE_DIR, "screener_data.json")

os.makedirs(CACHE_DIR, exist_ok=True)

# Load config
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
else:
    cfg = {}

EXCEL_PATH = cfg.get("excel_path", "D:\\Nifty 500 stocks.xlsx")
MAX_PRICE = cfg.get("max_price_per_share", 5000)
MIN_TOTAL = cfg.get("min_total_score", 55)
MIN_STRENGTH = cfg.get("min_strength_score", 50)
CACHE_TTL_HRS = cfg.get("cache_ttl_hours", 24)
LIVE_PRICE_TTL_MINS = 15

FORCE_REFRESH = "--refresh" in sys.argv or "--force-refresh" in sys.argv

def is_equity_market_open() -> bool:
    """Return True when NSE equity session is currently live (09:15–15:30 IST)."""
    ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now = datetime.datetime.now(ist_offset)
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    t = now.time()
    return datetime.time(9, 15) <= t <= datetime.time(15, 30)

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or 'ascii'
        safe_msg = str(msg).encode(enc, errors='replace').decode(enc)
        print(f"[{ts}] {safe_msg}", flush=True)

def cache_path(ticker):
    return os.path.join(CACHE_DIR, f"{ticker.replace('.', '_')}.json")

def load_cache(ticker, price_stale_check=False):
    if FORCE_REFRESH:
        return None
    path = cache_path(ticker)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        cached_at = datetime.datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
        age_hrs = (datetime.datetime.now() - cached_at).total_seconds() / 3600
        if age_hrs >= CACHE_TTL_HRS:
            return None
        if price_stale_check and is_equity_market_open():
            age_mins = age_hrs * 60
            if age_mins >= LIVE_PRICE_TTL_MINS:
                return None
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

def fetch_live_price_only(ticker: str) -> float | None:
    try:
        from curl_cffi import requests as cffi_req
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = cffi_req.get(url, impersonate="chrome120", headers=headers, timeout=6)
        if r.status_code == 200:
            meta = (r.json().get("chart", {}).get("result") or [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
            if price and float(price) > 0:
                return float(price)
    except Exception:
        pass
    try:
        t = yf.Ticker(ticker)
        p = t.fast_info.get("lastPrice") or t.fast_info.get("regularMarketPrice")
        if p and float(p) > 0:
            return float(p)
    except Exception:
        pass
    return None

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

def fetch_ticker_data(ticker: str) -> dict | None:
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

            data = {
                "ticker": ticker,
                "info": {k: v for k, v in info.items()
                         if isinstance(v, (int, float, str, bool, type(None)))},
                "history_close": hist_records,
                "news": [],
            }
            save_cache(ticker, data)
            return data
    except Exception:
        pass

    return fetch_via_curl_cffi(ticker)

def history_from_records(records: list) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame(records)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col.capitalize()] = pd.to_numeric(df[col], errors="coerce")
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    return df[cols].dropna(subset=["Close"])

def read_stock_list() -> list[str]:
    auto_json = os.path.join(BASE_DIR, "nifty_stocks_auto.json")
    if os.path.exists(auto_json):
        log(f"Reading stock list from JSON: {auto_json}")
        with open(auto_json) as f:
            syms = json.load(f)
        tickers = [f"{s}.NS" if not s.endswith(".NS") and not s.endswith(".BO") else s for s in syms]
        return tickers

    # Fallback default list if no file exists
    return ["ASHOKLEY.NS", "BEL.NS", "EMMVEE.NS", "FEDERALBNK.NS", "ITC.NS", "NMDC.NS", "TATAPOWER.NS", "TATASTEEL.NS"]

def process_single_ticker(args):
    i, ticker = args
    clean = ticker.replace(".NS", "").replace(".BO", "")
    data = fetch_ticker_data(ticker)
    if data is None:
        return None
    info = data.get("info", {})
    history = history_from_records(data.get("history_close", []))
    price = (info.get("currentPrice") or info.get("regularMarketPrice")
             or info.get("previousClose") or 0)
    
    # Run scoring
    try:
        scored = score_stock(info, history)
    except Exception as e:
        log(f"Error scoring {ticker}: {e}")
        return None
        
    scored["symbol"] = clean
    scored["ticker"] = ticker
    scored["name"] = info.get("longName") or info.get("shortName") or clean
    
    qualified = (
        scored["total_score"] >= MIN_TOTAL and
        scored["strength"] >= MIN_STRENGTH
    )
    scored["qualified"] = qualified
    
    trend_info = compute_trend_classification(scored)
    scored["trend"] = trend_info["trend"]
    scored["tech_rating"] = trend_info["badge"]
    scored["tech_class"] = trend_info["class"]
    
    return scored

def run_scan(tickers: list[str]) -> list[dict]:
    total = len(tickers)
    results = []
    log(f"Multithreaded scanning {total} stocks (6 parallel workers)...")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as executor:
        scan_items = list(enumerate(tickers, 1))
        futures = [executor.submit(process_single_ticker, item) for item in scan_items]
        for idx, f in enumerate(futures):
            try:
                res = f.result()
                if res:
                    results.append(res)
            except Exception as e:
                log(f"Future error: {e}")
            if (idx + 1) % 100 == 0 or (idx + 1) == total:
                log(f"Progress: {idx + 1}/{total} processed...")

    results.sort(key=lambda x: x["total_score"], reverse=True)
    log(f"Scan complete: {len(results)} processed successfully.")
    return results

def main():
    # Attempt to update stock list from NSE
    try:
        import download_nse_indices
        download_nse_indices.main()
    except Exception as e:
        log(f"Failed to auto-update NSE stock list: {e}")

    tickers = read_stock_list()
    log(f"Loaded {len(tickers)} stocks for scan.")
    results = run_scan(tickers)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    log(f"Successfully saved scan results database to {OUT_JSON}")

if __name__ == "__main__":
    main()
