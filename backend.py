import os
import json
import time
import base64
import requests
import sqlite3
import threading
import socket
from typing import Dict, List, Any, Optional
from fastapi import FastAPI, Request, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yfinance as yf

app = FastAPI(title="Finplus PnL Independent YFinance Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PULLBACK_FILE = os.path.join(BASE_DIR, "pullback_data.json")
JOURNAL_FILE = os.path.join(BASE_DIR, "finplus_journal_data.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "finplus_settings.json")
DB_FILE = os.path.join(BASE_DIR, "trades_backup.db")

# Thread lock for file operations
file_lock = threading.Lock()

# Price cache: { symbol: { "ltp": float, "change": float, "prev_close": float, "high": float, "low": float, "timestamp": float } }
PRICE_CACHE: Dict[str, Dict[str, Any]] = {
    "ASHOKLEY.NS": { "ltp": 177.54, "change": 0.48, "change_percent": 0.27, "prev_close": 177.06, "high": 178.00, "low": 176.50, "timestamp": time.time() },
    "BEL.NS": { "ltp": 410.40, "change": 1.16, "change_percent": 0.28, "prev_close": 409.24, "high": 412.00, "low": 408.00, "timestamp": time.time() },
    "BORANA.NS": { "ltp": 324.40, "change": -1.83, "change_percent": -0.56, "prev_close": 326.23, "high": 330.00, "low": 322.00, "timestamp": time.time() },
    "EMMVEE.NS": { "ltp": 314.15, "change": -4.55, "change_percent": -1.43, "prev_close": 318.70, "high": 322.00, "low": 312.00, "timestamp": time.time() },
    "FEDERALBNK.NS": { "ltp": 352.65, "change": -1.18, "change_percent": -0.33, "prev_close": 353.83, "high": 356.00, "low": 351.00, "timestamp": time.time() },
    "ITC.NS": { "ltp": 277.50, "change": 0.29, "change_percent": 0.10, "prev_close": 277.21, "high": 279.00, "low": 276.00, "timestamp": time.time() },
    "NMDC.NS": { "ltp": 84.77, "change": -1.32, "change_percent": -1.53, "prev_close": 86.09, "high": 86.50, "low": 84.50, "timestamp": time.time() },
    "PANAMAPET.NS": { "ltp": 507.25, "change": -38.25, "change_percent": -7.01, "prev_close": 545.50, "high": 548.00, "low": 505.00, "timestamp": time.time() },
    "TATAPOWER.NS": { "ltp": 381.30, "change": 0.49, "change_percent": 0.13, "prev_close": 380.81, "high": 384.00, "low": 379.00, "timestamp": time.time() },
    "TATASTEEL.NS": { "ltp": 184.24, "change": -1.05, "change_percent": -0.57, "prev_close": 185.29, "high": 186.00, "low": 183.00, "timestamp": time.time() },
    "UYFINCORP.NS": { "ltp": 20.17, "change": 5.00, "change_percent": 5.00, "prev_close": 19.17, "high": 20.17, "low": 19.10, "timestamp": time.time() },
    "GOLDBEES.NS": { "ltp": 124.98, "change": -0.68, "change_percent": -0.54, "prev_close": 125.66, "high": 126.50, "low": 124.80, "timestamp": time.time() },
    "NIFTYBEES.NS": { "ltp": 278.40, "change": 0.13, "change_percent": 0.05, "prev_close": 278.27, "high": 279.50, "low": 277.50, "timestamp": time.time() },
    "MIDHANI.NS": { "ltp": 423.95, "change": 3.45, "change_percent": 0.82, "prev_close": 420.50, "high": 426.00, "low": 418.00, "timestamp": time.time() },
    "CUPID.NS": { "ltp": 284.65, "change": 2.15, "change_percent": 0.76, "prev_close": 282.50, "high": 286.00, "low": 280.00, "timestamp": time.time() },
    "KIRIINDUS.NS": { "ltp": 477.90, "change": 16.60, "change_percent": 3.60, "prev_close": 461.30, "high": 482.00, "low": 460.00, "timestamp": time.time() },
    "RVNL.NS": { "ltp": 225.30, "change": -2.10, "change_percent": -0.92, "prev_close": 227.40, "high": 230.00, "low": 224.00, "timestamp": time.time() }
}
CACHE_TTL_SECONDS = 20.0

SYMBOL_MAP = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTY BANK": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "CRUDEOIL": "CL=F",
    "CRUDE": "CL=F",
    "NATGAS": "NG=F",
    "NATURALGAS": "NG=F",
    "NATGASMINI": "NG=F",
    "GOLD": "GC=F",
    "SILVER": "SI=F"
}

DEFAULT_PULLBACK_DATA = {
    "capital_settings": { "start_date": "2026-07-03", "initial_capital": 3477.97, "daily_rate": 200.0 },
    "ASHOKLEY.NS": { "name": "Ashok Leyland Limited", "category": "Core", "transactions": [{ "date": "2026-07-13", "price": 160.53, "shares": 2 }], "local_peak": 177.85, "date_added": "2026-07-03", "initial_reference_price": 160.53 },
    "BEL.NS": { "name": "Bharat Electronics Limited", "category": "Core", "transactions": [{ "date": "2026-07-29", "price": 403.52, "shares": 3 }], "local_peak": 410.45, "date_added": "2026-07-03", "initial_reference_price": 403.52 },
    "BORANA.NS": { "name": "BORANA", "category": "Core", "transactions": [{ "date": "2026-08-06", "price": 342.0, "shares": 1 }], "local_peak": 353.95, "date_added": "2026-08-06", "initial_reference_price": 342.00 },
    "EMMVEE.NS": { "name": "Emmvee Photovoltaic Power Limited", "category": "Growth", "in_watchlist": False, "transactions": [{ "date": "2026-08-03", "price": 330.98, "shares": 2 }, { "date": "2026-08-12", "price": 314.10, "shares": -2, "type": "SELL" }], "local_peak": 330.98, "date_added": "2026-07-03", "initial_reference_price": 314.10 },
    "FEDERALBNK.NS": { "name": "The Federal Bank Limited", "category": "Core", "transactions": [{ "date": "2026-08-03", "price": 359.10, "shares": 1 }, { "date": "2026-08-11", "price": 353.10, "shares": 1 }], "local_peak": 359.10, "date_added": "2026-07-03", "initial_reference_price": 355.75 },
    "ITC.NS": { "name": "ITC Limited", "category": "Core", "transactions": [{ "date": "2026-07-14", "price": 275.45, "shares": 1 }], "local_peak": 286.25, "date_added": "2026-07-03", "initial_reference_price": 275.45 },
    "NMDC.NS": { "name": "NMDC Limited", "category": "Core", "transactions": [{ "date": "2026-08-03", "price": 84.80, "shares": 1 }, { "date": "2026-08-11", "price": 85.29, "shares": 5 }], "local_peak": 85.49, "date_added": "2026-07-03", "initial_reference_price": 84.80 },
    "PANAMAPET.NS": { "name": "Panama Petrochem Limited", "category": "Growth", "in_watchlist": False, "transactions": [{ "date": "2026-08-11", "price": 544.95, "shares": 3 }, { "date": "2026-08-12", "price": 567.65, "shares": -3, "type": "SELL" }], "local_peak": 598.70, "date_added": "2026-08-11", "initial_reference_price": 506.15 },
    "TATAPOWER.NS": { "name": "Tata Power Company Limited", "category": "Core", "transactions": [{ "date": "2026-07-10", "price": 382.25, "shares": 1 }], "local_peak": 382.25, "date_added": "2026-07-03", "initial_reference_price": 382.25 },
    "TATASTEEL.NS": { "name": "Tata Steel Limited", "category": "Growth", "transactions": [{ "date": "2026-07-27", "price": 182.82, "shares": 1 }], "local_peak": 191.53, "date_added": "2026-07-05", "initial_reference_price": 182.82 },
    "UYFINCORP.NS": { "name": "UYFINCORP", "category": "Core", "transactions": [{ "date": "2026-08-06", "price": 19.33, "shares": 12 }], "local_peak": 22.34, "date_added": "2026-08-06", "initial_reference_price": 19.33 },
    "NIFTYBEES.NS": { "name": "Nippon India Nifty 50 BeES ETF", "category": "Park", "transactions": [{ "date": "2026-08-12", "price": 277.40, "shares": 3 }, { "date": "2026-08-13", "price": 278.05, "shares": 3 }], "local_peak": 286.50, "date_added": "2026-08-11", "initial_reference_price": 277.40 },
    "GOLDBEES.NS": { "name": "Nippon India Gold BeES ETF", "category": "Park", "transactions": [{ "date": "2026-08-12", "price": 126.25, "shares": 6 }, { "date": "2026-08-13", "price": 125.84, "shares": 4 }], "local_peak": 126.39, "date_added": "2026-08-11", "initial_reference_price": 126.25 },
    "mtf_trading": []
}

NIFTY500_STOCKS = [
    { "symbol": "SBIN", "name": "State Bank of India", "aliases": ["sbi", "sbin", "state bank"] },
    { "symbol": "TMPV", "name": "Tata Motors Passenger Vehicles Limited", "aliases": ["tmpv", "tata motors pv"] },
    { "symbol": "TMCV", "name": "Tata Motors Commercial Vehicles Limited", "aliases": ["tmcv", "tata motors cv"] },
    { "symbol": "TATASTEEL", "name": "Tata Steel Limited", "aliases": ["tata steel", "tatasteel"] },
    { "symbol": "TATAPOWER", "name": "Tata Power Company Limited", "aliases": ["tata power", "tatapower"] },
    { "symbol": "TCS", "name": "Tata Consultancy Services Limited", "aliases": ["tcs", "tata consultancy"] },
    { "symbol": "INFY", "name": "Infosys Limited", "aliases": ["infosys", "infy"] },
    { "symbol": "RELIANCE", "name": "Reliance Industries Limited", "aliases": ["reliance", "ril"] },
    { "symbol": "HDFCBANK", "name": "HDFC Bank Limited", "aliases": ["hdfc bank", "hdfc", "hdfcbank"] },
    { "symbol": "ICICIBANK", "name": "ICICI Bank Limited", "aliases": ["icici bank", "icici", "icicibank"] },
    { "symbol": "AXISBANK", "name": "Axis Bank Limited", "aliases": ["axis bank", "axis"] },
    { "symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Limited", "aliases": ["kotak bank", "kotak"] },
    { "symbol": "LT", "name": "Larsen & Toubro Limited", "aliases": ["lt", "l&t", "larsen"] },
    { "symbol": "M&M", "name": "Mahindra & Mahindra Limited", "aliases": ["m&m", "mahindra"] },
    { "symbol": "MARUTI", "name": "Maruti Suzuki India Limited", "aliases": ["maruti"] },
    { "symbol": "BAJFINANCE", "name": "Bajaj Finance Limited", "aliases": ["bajaj finance"] },
    { "symbol": "BAJAJFINSV", "name": "Bajaj Finserv Limited", "aliases": ["bajaj finserv"] },
    { "symbol": "BHARTIARTL", "name": "Bharti Airtel Limited", "aliases": ["airtel", "bharti"] },
    { "symbol": "ITC", "name": "ITC Limited", "aliases": ["itc"] },
    { "symbol": "HINDUNILVR", "name": "Hindustan Unilever Limited", "aliases": ["hul"] },
    { "symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Limited", "aliases": ["sun pharma"] },
    { "symbol": "TITAN", "name": "Titan Company Limited", "aliases": ["titan"] },
    { "symbol": "ULTRACEMCO", "name": "UltraTech Cement Limited", "aliases": ["ultratech"] },
    { "symbol": "ADANIENT", "name": "Adani Enterprises Limited", "aliases": ["adani ent"] },
    { "symbol": "ADANIPORTS", "name": "Adani Ports and Special Economic Zone Limited", "aliases": ["adani ports"] },
    { "symbol": "ASIANPAINT", "name": "Asian Paints Limited", "aliases": ["asian paints"] },
    { "symbol": "POWERGRID", "name": "Power Grid Corporation of India Limited", "aliases": ["power grid"] },
    { "symbol": "NTPC", "name": "NTPC Limited", "aliases": ["ntpc"] },
    { "symbol": "ONGC", "name": "Oil & Natural Gas Corporation Limited", "aliases": ["ongc"] },
    { "symbol": "COALINDIA", "name": "Coal India Limited", "aliases": ["coal india"] },
    { "symbol": "BEL", "name": "Bharat Electronics Limited", "aliases": ["bel"] },
    { "symbol": "HAL", "name": "Hindustan Aeronautics Limited", "aliases": ["hal"] },
    { "symbol": "IOC", "name": "Indian Oil Corporation Limited", "aliases": ["ioc"] },
    { "symbol": "BPCL", "name": "Bharat Petroleum Corporation Limited", "aliases": ["bpcl"] },
    { "symbol": "GAIL", "name": "GAIL (India) Limited", "aliases": ["gail"] },
    { "symbol": "WIPRO", "name": "Wipro Limited", "aliases": ["wipro"] },
    { "symbol": "HCLTECH", "name": "HCL Technologies Limited", "aliases": ["hcl"] },
    { "symbol": "TECHM", "name": "Tech Mahindra Limited", "aliases": ["techm"] },
    { "symbol": "ZOMATO", "name": "Zomato Limited", "aliases": ["zomato"] },
    { "symbol": "JIOFIN", "name": "Jio Financial Services Limited", "aliases": ["jiofin"] },
    { "symbol": "GESHIP", "name": "The Great Eastern Shipping Company Limited", "aliases": ["geship", "great eastern", "shipping", "ge shipping"] },
    { "symbol": "GOLDBEES", "name": "Nippon India ETF Gold BeES", "aliases": ["gold", "goldb", "goldbees", "gold bees", "gold etf", "nippon gold", "gold be"] },
    { "symbol": "NIFTYBEES", "name": "Nippon India ETF Nifty 50 BeES", "aliases": ["nifty", "niftyb", "niftybees", "nifty bees", "nifty 50", "nifty etf", "nippon nifty"] },
    { "symbol": "BANKBEES", "name": "Nippon India ETF Nifty Bank BeES", "aliases": ["bank", "bankbees", "bank bees", "bank etf", "nifty bank", "banknifty etf"] },
    { "symbol": "LIQUIDBEES", "name": "Nippon India ETF Liquid BeES", "aliases": ["liquid", "liquidbees", "liquid bees", "liquid etf", "cash", "park cash"] },
    { "symbol": "SILVERBEES", "name": "Nippon India ETF Silver BeES", "aliases": ["silver", "silverbees", "silver bees", "silver etf", "nippon silver"] },
    { "symbol": "ITBEES", "name": "Nippon India ETF Nifty IT", "aliases": ["it", "itbees", "it bees", "it etf", "tech etf", "nifty it"] },
    { "symbol": "JUNIORBEES", "name": "Nippon India ETF Nifty Next 50", "aliases": ["junior", "juniorbees", "junior bees", "next 50", "nifty next 50"] },
    { "symbol": "CPSEETF", "name": "CPSE ETF", "aliases": ["cpse", "cpse etf", "psu etf", "cpseetf"] },
    { "symbol": "MON100", "name": "Motilal Oswal Nasdaq 100 ETF", "aliases": ["nasdaq", "mon100", "nasdaq 100", "us tech", "motilal nasdaq"] }
]

def normalize_symbol(sym: str) -> str:
    cleaned = sym.strip().upper()
    if cleaned in SYMBOL_MAP:
        return SYMBOL_MAP[cleaned]
    
    # Specific ETF checks - preserve NSE ETF ticker
    if "BEES" in cleaned or "ETF" in cleaned:
        if not cleaned.endswith(".NS") and not cleaned.endswith(".BO"):
            return f"{cleaned}.NS"
        return cleaned

    # Futures / Indices (exact words or commodity trade names)
    if cleaned in ["NIFTY", "NIFTY 50", "NIFTY50", "INDEX"]:
        return "^NSEI"
    if cleaned in ["BANKNIFTY", "BANK NIFTY", "NIFTY BANK"]:
        return "^NSEBANK"
    if cleaned in ["CRUDE", "CRUDEOIL", "CRUDE OIL"]:
        return "CL=F"
    if cleaned in ["NATGAS", "NATURALGAS", "NATURAL GAS", "NATGASMINI"]:
        return "NG=F"
    if cleaned in ["GOLD", "MCX GOLD", "GOLDM"]:
        return "GC=F"
    if cleaned in ["SILVER", "MCX SILVER", "SILVERM"]:
        return "SI=F"

    if not cleaned.endswith(".NS") and not cleaned.endswith(".BO") and "=" not in cleaned and "^" not in cleaned:
        return f"{cleaned}.NS"
    return cleaned

def fetch_direct_yahoo(y_sym: str) -> Optional[Dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{y_sym}?interval=1m&range=1d"
    try:
        res = requests.get(url, headers=headers, timeout=4)
        if res.status_code == 200:
            data = res.json()
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            ltp = meta.get("regularMarketPrice")
            prev_close = meta.get("chartPreviousClose") or meta.get("previousClose") or ltp
            high = meta.get("dayHigh") or ltp
            low = meta.get("dayLow") or ltp
            if ltp and ltp > 0:
                ltp = round(float(ltp), 2)
                prev_c = round(float(prev_close), 2) if prev_close else ltp
                chg = round(ltp - prev_c, 2)
                chg_pct = round((chg / prev_c) * 100, 2) if prev_c else 0.0
                return {
                    "ltp": ltp,
                    "change": chg,
                    "change_percent": chg_pct,
                    "prev_close": prev_c,
                    "high": round(float(high), 2) if high else ltp,
                    "low": round(float(low), 2) if low else ltp,
                    "timestamp": time.time()
                }
    except Exception as e:
        print(f"[Direct Yahoo Fetch Error for {y_sym}]: {e}")
    return None

def fetch_yfinance_batch(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    now = time.time()
    results = {}
    needed_y_symbols = set()
    raw_to_y_map = {}

    for raw in symbols:
        if not raw:
            continue
        clean_raw = raw.strip().upper()
        y_sym = normalize_symbol(clean_raw)
        raw_to_y_map[clean_raw] = y_sym

        # Check cache
        if y_sym in PRICE_CACHE and (now - PRICE_CACHE[y_sym]["timestamp"]) < CACHE_TTL_SECONDS:
            results[clean_raw] = PRICE_CACHE[y_sym]
            results[y_sym] = PRICE_CACHE[y_sym]
        else:
            needed_y_symbols.add(y_sym)

    if needed_y_symbols:
        try:
            tickers_obj = yf.Tickers(" ".join(list(needed_y_symbols)))
            for y_sym in needed_y_symbols:
                try:
                    t = tickers_obj.tickers[y_sym]
                    fast = getattr(t, "fast_info", None)
                    ltp = None
                    prev_close = None
                    high = None
                    low = None
                    
                    if fast:
                        ltp = getattr(fast, "last_price", None)
                        prev_close = getattr(fast, "previous_close", None)
                        high = getattr(fast, "day_high", None)
                        low = getattr(fast, "day_low", None)
                    
                    if ltp is None or ltp == 0:
                        # Fallback to info dict if fast_info is missing
                        info = getattr(t, "info", {})
                        ltp = info.get("regularMarketPrice") or info.get("currentPrice")
                        prev_close = prev_close or info.get("previousClose")
                        high = high or info.get("dayHigh")
                        low = low or info.get("dayLow")

                    if ltp and ltp > 0:
                        ltp = round(float(ltp), 2)
                        prev_c = round(float(prev_close), 2) if prev_close else ltp
                        chg = round(ltp - prev_c, 2)
                        chg_pct = round((chg / prev_c) * 100, 2) if prev_c else 0.0
                        
                        price_data = {
                            "ltp": ltp,
                            "change": chg,
                            "change_percent": chg_pct,
                            "prev_close": prev_c,
                            "high": round(float(high), 2) if high else ltp,
                            "low": round(float(low), 2) if low else ltp,
                            "timestamp": now
                        }
                        PRICE_CACHE[y_sym] = price_data
                        results[y_sym] = price_data
                except Exception as ex:
                    print(f"[YFinance Fetch Error for {y_sym}]: {ex}")
        except Exception as e:
            print(f"[YFinance Batch Error]: {e}")

        # Direct HTTP chart fallback for any symbols that failed or hit rate limits
        for y_sym in needed_y_symbols:
            if y_sym not in results or not results[y_sym].get("ltp"):
                direct_data = fetch_direct_yahoo(y_sym)
                if direct_data:
                    PRICE_CACHE[y_sym] = direct_data
                    results[y_sym] = direct_data

    # Map results back to raw symbols requested
    final_output = {}
    for raw in symbols:
        clean_raw = raw.strip().upper()
        y_sym = raw_to_y_map.get(clean_raw, clean_raw)
        data = results.get(y_sym) or PRICE_CACHE.get(y_sym) or results.get(clean_raw)
        if data:
            final_output[raw] = data
            final_output[clean_raw] = data
            final_output[y_sym] = data

    return final_output

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = "Abhilash128912/FinPlus-"
GITHUB_BRANCH = "main"

def push_to_github(filepath: str, repo_path: str):
    if not GITHUB_TOKEN:
        print(f"[GitHub Sync] GITHUB_TOKEN not set. Local save only for {repo_path}")
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}?ref={GITHUB_BRANCH}"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
        res = requests.get(url, headers=headers)
        sha = None
        if res.status_code == 200:
            sha = res.json().get("sha")

        with open(filepath, "rb") as f:
            content_bytes = f.read()
        content_b64 = base64.b64encode(content_bytes).decode("utf-8")

        payload = {
            "message": f"sync: update {repo_path} from backend",
            "content": content_b64,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha

        put_res = requests.put(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}", json=payload, headers=headers)
        if put_res.status_code in [200, 201]:
            print(f"[GitHub Sync] Successfully pushed {repo_path} to GitHub!")
        else:
            print(f"[GitHub Sync] Failed to push {repo_path}: {put_res.status_code} - {put_res.text}")
    except Exception as e:
        print(f"[GitHub Sync Error] Failed to sync {repo_path}: {e}")

def load_from_github(filepath: str, repo_path: str) -> bool:
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{repo_path}"
    try:
        res = requests.get(raw_url, timeout=5)
        if res.status_code == 200:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(res.text)
            return True
    except Exception as e:
        print(f"[GitHub Load Error] Failed to fetch {repo_path}: {e}")
    return False

def load_pullback_file() -> Dict[str, Any]:
    with file_lock:
        if not os.path.exists(PULLBACK_FILE):
            load_from_github(PULLBACK_FILE, "pullback_data.json")
        if not os.path.exists(PULLBACK_FILE):
            with open(PULLBACK_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_PULLBACK_DATA, f, indent=2)
            return DEFAULT_PULLBACK_DATA
        try:
            with open(PULLBACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_PULLBACK_DATA

def save_pullback_file(data: Dict[str, Any]):
    with file_lock:
        with open(PULLBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    push_to_github(PULLBACK_FILE, "pullback_data.json")

def load_journal_file() -> List[Dict[str, Any]]:
    with file_lock:
        if not os.path.exists(JOURNAL_FILE):
            load_from_github(JOURNAL_FILE, "finplus_journal_data.json")
        if not os.path.exists(JOURNAL_FILE):
            return []
        try:
            with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

def save_journal_file(trades: List[Dict[str, Any]]):
    with file_lock:
        with open(JOURNAL_FILE, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2)
            
    push_to_github(JOURNAL_FILE, "finplus_journal_data.json")
            
    # Sync SQLite
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT,
                symbol TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity INTEGER NOT NULL,
                stop_loss REAL,
                target_price REAL,
                exit_price REAL,
                instrument_type TEXT,
                status TEXT,
                created_at TEXT
            )
        """)
        for t in trades:
            uuid_val = t.get("uuid") or f"fp_{t.get('id', '')}"
            sym = t.get("symbol", "")
            entry_p = t.get("entry_price", 0)
            qty = t.get("quantity", 0)
            exit_p = t.get("exit_price")
            inst = t.get("instrument_type", "Intraday")
            st = t.get("status", "ACTIVE")
            ca = t.get("created_at", "")
            
            existing = conn.execute("SELECT id FROM trades WHERE uuid = ? OR (symbol = ? AND created_at = ?)", (uuid_val, sym, ca)).fetchone()
            if not existing:
                conn.execute("""
                    INSERT INTO trades (uuid, symbol, entry_price, quantity, exit_price, instrument_type, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (uuid_val, sym, entry_p, qty, exit_p, inst, st, ca))
            else:
                conn.execute("""
                    UPDATE trades SET exit_price = ?, status = ? WHERE id = ?
                """, (exit_p, st, existing[0]))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SQLite Sync Error]: {e}")
def get_local_ips() -> List[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip and primary_ip not in ips and not primary_ip.startswith("127."):
            ips.append(primary_ip)
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip not in ips and not ip.startswith("127.") and not ip.startswith("169.254"):
                ips.append(ip)
    except Exception:
        pass
    return ips

def load_settings_file() -> Dict[str, Any]:
    with file_lock:
        if not os.path.exists(SETTINGS_FILE):
            load_from_github(SETTINGS_FILE, "finplus_settings.json")
        if not os.path.exists(SETTINGS_FILE):
            return {}
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

def save_settings_file(settings: Dict[str, Any]):
    with file_lock:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    push_to_github(SETTINGS_FILE, "finplus_settings.json")

@app.get("/health")
@app.get("/api/health")
def health_check():
    local_ips = get_local_ips()
    return {
        "status": "online",
        "app": "Finplus PnL Independent Backend",
        "data_source": "yfinance",
        "version": "2.0.0",
        "local_ips": local_ips,
        "recommended_server_urls": [f"http://{ip}:8000" for ip in local_ips]
    }

@app.get("/api/ltp")
def get_ltp(symbols: str = Query("")):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return { "status": "success", "ltps": {} }
    
    price_data = fetch_yfinance_batch(symbol_list)
    ltps = {}
    for sym, info in price_data.items():
        if info and "ltp" in info:
            ltps[sym] = info["ltp"]

    return {
        "status": "success",
        "ltps": ltps
    }

@app.get("/api/investment/yfinance-prices")
def get_yfinance_prices(tickers: Optional[str] = None, symbols: Optional[str] = None):
    raw_query = tickers or symbols or ""
    symbol_list = [s.strip() for s in raw_query.split(",") if s.strip()]
    if not symbol_list:
        return { "status": "success", "prices": {}, "updated_peaks": False }

    price_map = fetch_yfinance_batch(symbol_list)
    
    # Check if local peaks in pullback_data.json need to be updated
    updated_peaks = False
    pullback = load_pullback_file()
    
    for sym, info in price_map.items():
        if not info or "ltp" not in info:
            continue
        ltp = info["ltp"]
        # Match symbol in pullback dict (e.g. SBIN.NS or SBIN)
        target_keys = [sym, f"{sym}.NS", sym.replace(".NS", "")]
        for k in target_keys:
            if k in pullback and isinstance(pullback[k], dict) and "local_peak" in pullback[k]:
                curr_peak = float(pullback[k].get("local_peak", 0))
                if ltp > curr_peak:
                    pullback[k]["local_peak"] = ltp
                    updated_peaks = True

    if updated_peaks:
        save_pullback_file(pullback)

    return {
        "status": "success",
        "prices": price_map,
        "updated_peaks": updated_peaks
    }

@app.get("/api/investment/nifty500")
def get_nifty500():
    return {
        "status": "success",
        "stocks": NIFTY500_STOCKS,
        "count": len(NIFTY500_STOCKS)
    }

@app.get("/api/investment/pullback")
def get_pullback_data():
    return load_pullback_file()

@app.post("/api/investment/pullback")
async def save_pullback_data(request: Request):
    data = await request.json()
    if isinstance(data, dict):
        save_pullback_file(data)
        return { "status": "success", "message": "Pullback data saved" }
    return { "status": "error", "message": "Invalid JSON payload" }

@app.get("/api/settings")
def get_settings():
    settings = load_settings_file()
    return {
        "status": "success",
        "settings": settings
    }

@app.post("/api/settings")
async def save_settings_endpoint(request: Request):
    payload = await request.json()
    if isinstance(payload, dict):
        save_settings_file(payload)
        return { "status": "success", "message": "Settings saved", "settings": payload }
    return { "status": "error", "message": "Invalid JSON payload" }

@app.get("/api/trades")
@app.get("/api/trades/journal")
def get_trades():
    trades = load_journal_file()
    settings = load_settings_file()
    return {
        "status": "success",
        "trades": trades,
        "settings": settings,
        "count": len(trades)
    }

@app.post("/api/trades")
@app.post("/api/trades/journal")
@app.post("/api/trades/sync")
@app.post("/api/journal/sync")
async def sync_trades(request: Request):
    payload = await request.json()
    trades_list = []
    settings_data = None
    if isinstance(payload, list):
        trades_list = payload
    elif isinstance(payload, dict):
        trades_list = payload.get("trades", [])
        settings_data = payload.get("settings")
    
    if trades_list:
        save_journal_file(trades_list)
    if settings_data and isinstance(settings_data, dict):
        save_settings_file(settings_data)
        
    return { 
        "status": "success", 
        "synced_count": len(trades_list),
        "settings_saved": bool(settings_data)
    }

@app.get("/api/sync/all")
def get_all_sync_data():
    return {
        "status": "success",
        "trades": load_journal_file(),
        "pullback": load_pullback_file(),
        "settings": load_settings_file(),
        "timestamp": time.time()
    }

@app.post("/api/sync/all")
async def post_all_sync_data(request: Request):
    payload = await request.json()
    if isinstance(payload, dict):
        trades = payload.get("trades")
        pullback = payload.get("pullback")
        settings = payload.get("settings")
        if isinstance(trades, list) and len(trades) > 0:
            save_journal_file(trades)
        if isinstance(pullback, dict) and len(pullback) > 0:
            save_pullback_file(pullback)
        if isinstance(settings, dict) and len(settings) > 0:
            save_settings_file(settings)
        return {
            "status": "success",
            "message": "Full dataset synchronized successfully",
            "trades_count": len(trades) if isinstance(trades, list) else 0,
            "pullback_keys": len(pullback) if isinstance(pullback, dict) else 0,
            "settings_saved": bool(settings)
        }
PORTFOLIO_FILE = os.path.join(BASE_DIR, "finplus_portfolio_backup.json")

@app.post("/api/backup/save")
async def save_portfolio_backup(request: Request):
    try:
        data = await request.json()
        if isinstance(data, dict):
            incoming_pos = data.get("positions", [])
            # Protect existing data: keep the larger/more complete dataset
            if os.path.exists(PORTFOLIO_FILE):
                try:
                    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as existing_f:
                        existing = json.load(existing_f)
                        existing_pos = existing.get("positions", [])
                        if len(existing_pos) > len(incoming_pos):
                            data["positions"] = existing_pos
                        if existing.get("capitalLedger") and not data.get("capitalLedger"):
                            data["capitalLedger"] = existing["capitalLedger"]
                        if existing.get("freeCash") and not data.get("freeCash"):
                            data["freeCash"] = existing["freeCash"]
                except Exception:
                    pass

            with file_lock:
                with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            push_to_github(PORTFOLIO_FILE, "finplus_portfolio_backup.json")
        return { "status": "success" }
    except Exception as e:
        return { "status": "error", "message": str(e) }

@app.get("/api/backup/load")
def load_portfolio_backup():
    with file_lock:
        if not os.path.exists(PORTFOLIO_FILE):
            load_from_github(PORTFOLIO_FILE, "finplus_portfolio_backup.json")
        if not os.path.exists(PORTFOLIO_FILE):
            return { "status": "empty", "data": None }
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return { "status": "success", "data": data }
        except Exception as e:
            return { "status": "error", "message": str(e) }

DIST_DIR = os.path.join(BASE_DIR, "dist")
if os.path.exists(DIST_DIR):
    ASSETS_DIR = os.path.join(DIST_DIR, "assets")
    if os.path.exists(ASSETS_DIR):
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

    @app.get("/")
    def serve_root():
        index_file = os.path.join(DIST_DIR, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"status": "online", "app": "Finplus PnL Independent Backend"}

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path in ["health", "api/health", "docs", "openapi.json"]:
            return {"error": "Not Found"}
        target = os.path.join(DIST_DIR, full_path)
        if os.path.exists(target) and os.path.isfile(target):
            return FileResponse(target)
        index_file = os.path.join(DIST_DIR, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"status": "online"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend:app", host="0.0.0.0", port=port, reload=False)

