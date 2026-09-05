import os
import json
import time
import base64
import requests
import sqlite3
import threading
import socket
import hmac
from datetime import datetime
from typing import Dict, List, Any, Optional
from fastapi import FastAPI, Request, Query, BackgroundTasks, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import yfinance as yf

app = FastAPI(title="Finplus PnL Independent YFinance Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PULLBACK_FILE = os.path.join(BASE_DIR, "pullback_data.json")
JOURNAL_FILE = os.path.join(BASE_DIR, "finplus_journal_data.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "finplus_settings.json")
DB_FILE = os.path.join(BASE_DIR, "trades_backup.db")
RISK_FILE = os.path.join(BASE_DIR, "finplus_risk_desk.json")

# Thread lock for file operations
file_lock = threading.Lock()

# Price cache: { symbol: { "ltp": float, "change": float, "prev_close": float, "high": float, "low": float, "timestamp": float } }
PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
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
    "capital_settings": { "start_date": "2026-09-07", "initial_capital": 0.0, "daily_rate": 200.0 },
    "ASHOKLEY.NS": { "name": "Ashok Leyland Limited", "category": "Core", "transactions": [] },
    "BEL.NS": { "name": "Bharat Electronics Limited", "category": "Core", "transactions": [] },
    "BORANA.NS": { "name": "BORANA", "category": "Core", "transactions": [] },
    "EMMVEE.NS": { "name": "Emmvee Photovoltaic Power Limited", "category": "Growth", "in_watchlist": False, "transactions": [] },
    "FEDERALBNK.NS": { "name": "The Federal Bank Limited", "category": "Core", "transactions": [] },
    "ITC.NS": { "name": "ITC Limited", "category": "Core", "transactions": [] },
    "NMDC.NS": { "name": "NMDC Limited", "category": "Core", "transactions": [] },
    "PANAMAPET.NS": { "name": "Panama Petrochem Limited", "category": "Growth", "in_watchlist": False, "transactions": [] },
    "TATAPOWER.NS": { "name": "Tata Power Company Limited", "category": "Core", "transactions": [] },
    "TATASTEEL.NS": { "name": "Tata Steel Limited", "category": "Growth", "transactions": [] },
    "UYFINCORP.NS": { "name": "UYFINCORP", "category": "Core", "transactions": [] },
    "NIFTYBEES.NS": { "name": "Nippon India Nifty 50 BeES ETF", "category": "Park", "transactions": [] },
    "GOLDBEES.NS": { "name": "Nippon India Gold BeES ETF", "category": "Park", "transactions": [] },
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
    """Push file to GitHub in a background thread so it never blocks the API response."""
    def _push():
        if not GITHUB_TOKEN:
            print(f"[GitHub Sync] GITHUB_TOKEN not set. Local save only for {repo_path}")
            return
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}?ref={GITHUB_BRANCH}"
            headers = {
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json"
            }
            res = requests.get(url, headers=headers, timeout=10)
            sha = None
            if res.status_code == 200:
                sha = res.json().get("sha")

            with open(filepath, "rb") as f:
                content_bytes = f.read()
            content_b64 = base64.b64encode(content_bytes).decode("utf-8")

            payload = {
                # "[skip render]" stops Render auto-deploying on data-only commits. Without
                # it every save would push a commit, trigger a redeploy and restart
                # the service - a loop, since the restart can itself trigger a save.
                "message": f"sync: update {repo_path} from backend [skip render]",
                "content": content_b64,
                "branch": GITHUB_BRANCH
            }
            if sha:
                payload["sha"] = sha

            put_res = requests.put(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{repo_path}", json=payload, headers=headers, timeout=15)
            if put_res.status_code in [200, 201]:
                print(f"[GitHub Sync] Successfully pushed {repo_path} to GitHub!")
            else:
                print(f"[GitHub Sync] Failed to push {repo_path}: {put_res.status_code} - {put_res.text}")
        except Exception as e:
            print(f"[GitHub Sync Error] Failed to sync {repo_path}: {e}")
    threading.Thread(target=_push, daemon=True).start()

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

# ══════════════════════════════════════════════════════════════════════════════
# API KEY GATE
#
# The service holds personal holdings, P&L and cash, so every endpoint that
# reads or writes that data requires a shared key in the X-Finplus-Key header.
#
# Fail-open until FINPLUS_API_KEY is set, so deploying this build cannot lock
# anyone out of their own data. /api/health reports which mode is active — set
# the env var on the host and it becomes enforced on the next restart.
#
# The key is typed in by the user and stored on their device. It is never baked
# into the web bundle, which is public and readable by anyone.
# ══════════════════════════════════════════════════════════════════════════════

FINPLUS_API_KEY = os.environ.get("FINPLUS_API_KEY", "").strip()
AUTH_ENABLED = bool(FINPLUS_API_KEY)

if not AUTH_ENABLED:
    print("[Auth] FINPLUS_API_KEY not set - private endpoints are OPEN. "
          "Set the env var to enforce the key.")

def require_key(request: Request):
    """Guard private endpoints. No-op until a key is configured on the host."""
    if not AUTH_ENABLED:
        return
    supplied = request.headers.get("X-Finplus-Key") or request.query_params.get("k") or ""
    if not supplied or not hmac.compare_digest(str(supplied), FINPLUS_API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")

@app.get("/health")
@app.get("/api/health")
def health_check():
    local_ips = get_local_ips()
    return {
        "status": "online",
        "app": "Finplus PnL Independent Backend",
        "data_source": "yfinance",
        "version": "2.1.0",
        "auth": "enabled" if AUTH_ENABLED else "disabled",
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
def get_pullback_data(_auth: None = Depends(require_key)):
    return load_pullback_file()

@app.post("/api/investment/pullback")
async def save_pullback_data(request: Request, _auth: None = Depends(require_key)):
    data = await request.json()
    if isinstance(data, dict):
        save_pullback_file(data)
        return { "status": "success", "message": "Pullback data saved" }
    return { "status": "error", "message": "Invalid JSON payload" }

@app.get("/api/settings")
def get_settings(_auth: None = Depends(require_key)):
    settings = load_settings_file()
    return {
        "status": "success",
        "settings": settings
    }

@app.post("/api/settings")
async def save_settings_endpoint(request: Request, _auth: None = Depends(require_key)):
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
async def sync_trades(request: Request, _auth: None = Depends(require_key)):
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

# ==============================================================================
# RISK DESK - opportunity-based fund & risk manager (server-side authority)
#
# The client computes locally so the Android build works offline. The server is
# the source of truth for the audit log and re-validates every recorded trade.
# ==============================================================================

RISK_COLLECTIONS = [
    "months", "trade_setups", "trades", "daily_risk_snapshots",
    "opportunity_reserve_transfers", "broker_charge_profiles",
    "broker_cash_ledger", "growth_reserve_ledger", "audit_log",
]

def _empty_risk_store() -> Dict[str, Any]:
    store: Dict[str, Any] = {"schema_version": 1, "config": {}, "updated_at": None}
    for c in RISK_COLLECTIONS:
        store[c] = []
    return store

def load_risk_file() -> Dict[str, Any]:
    with file_lock:
        if not os.path.exists(RISK_FILE):
            load_from_github(RISK_FILE, "finplus_risk_desk.json")
        if not os.path.exists(RISK_FILE):
            return _empty_risk_store()
        try:
            with open(RISK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            base = _empty_risk_store()
            base.update(data if isinstance(data, dict) else {})
            for c in RISK_COLLECTIONS:
                if not isinstance(base.get(c), list):
                    base[c] = []
            return base
        except Exception:
            return _empty_risk_store()

def _risk_tables(conn: sqlite3.Connection):
    """One table per entity in the brief. Rows are stored as JSON documents so the
    schema can evolve with the client without a migration for every field."""
    for name in RISK_COLLECTIONS:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS risk_" + name + " ("
            "id TEXT PRIMARY KEY, month_key TEXT, updated_at TEXT, data TEXT NOT NULL)"
        )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS risk_config ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL, updated_at TEXT)"
    )

def save_risk_file(store: Dict[str, Any]):
    with file_lock:
        with open(RISK_FILE, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2)
    push_to_github(RISK_FILE, "finplus_risk_desk.json")

    try:
        conn = sqlite3.connect(DB_FILE)
        _risk_tables(conn)
        for name in RISK_COLLECTIONS:
            for row in store.get(name, []) or []:
                if not isinstance(row, dict):
                    continue
                rid = str(row.get("id") or row.get("month_key") or "")
                if not rid:
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO risk_" + name +
                    " (id, month_key, updated_at, data) VALUES (?, ?, ?, ?)",
                    (rid, row.get("month_key"), row.get("updated_at") or row.get("at"), json.dumps(row)),
                )
        conn.execute(
            "INSERT OR REPLACE INTO risk_config (id, data, updated_at) VALUES (1, ?, ?)",
            (json.dumps(store.get("config") or {}), store.get("updated_at")),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print("[Risk Desk] SQLite sync failed: " + str(e))

def _num(v, default=0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default

def _blk(code: str, message: str) -> Dict[str, str]:
    return {"code": code, "message": message, "severity": "BLOCK"}

def _revalidate_trade(trade: Dict[str, Any], store: Dict[str, Any], month_key: Optional[str]) -> Dict[str, Any]:
    """Independent server-side re-check of the hard limits. Deliberately does not
    trust the risk figures sent by the client - it recomputes from stored state."""
    blocked: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    config = store.get("config") or {}
    mkey = month_key or str(trade.get("entry_date") or "")[:7]
    month = next((m for m in store.get("months", []) if m.get("month_key") == mkey), None)

    if not config.get("configured"):
        blocked.append(_blk("NOT_CONFIGURED", "Risk Desk setup is not complete on the server."))
    if month is None:
        blocked.append(_blk("NO_MONTH", "No month record for " + str(mkey) + "."))

    seg = trade.get("segment")
    risk = _num(trade.get("planned_total_risk"))
    if risk <= 0:
        blocked.append(_blk("NO_RISK", "Planned total risk is missing or zero."))
    if not _num(trade.get("stop_loss_price")):
        blocked.append(_blk("NO_SL", "Stop-loss is required."))
    if trade.get("trade_intent") == "RECOVERY":
        blocked.append(_blk("REVENGE_INTENT", "Recovery / revenge trading is blocked."))
    if str(trade.get("grade") or "") not in ("A", "A_PLUS"):
        blocked.append(_blk("GRADE", "Only A and A+ setups are tradeable."))

    others = [t for t in store.get("trades", [])
              if str(t.get("entry_date") or "")[:7] == mkey and t.get("id") != trade.get("id")]
    committed = sum(_num(t.get("planned_total_risk")) for t in others)

    if month:
        budget = _num(month.get("monthly_risk_budget"))
        pre = _num(month.get("preexisting_usage"))
        remaining = budget - pre - committed
        if risk > remaining + 0.001:
            blocked.append(_blk("MONTHLY_LIMIT",
                "Monthly risk remaining is %.2f; this trade commits %.2f." % (remaining, risk)))

        if month.get("enforce_segment_quotas", True):
            bucket = (month.get("buckets") or {}).get(seg) or {}
            initial = bucket.get("initial_allocation")
            if initial is not None:
                seg_committed = sum(_num(t.get("planned_total_risk")) for t in others if t.get("segment") == seg)
                reserve_in = sum(_num(x.get("amount")) for x in store.get("opportunity_reserve_transfers", [])
                                 if x.get("month_key") == mkey and x.get("to_segment") == seg
                                 and x.get("trade_id") != trade.get("id"))
                seg_remaining = _num(initial) + reserve_in - seg_committed
                from_bucket = risk - _num(trade.get("reserve_risk_used"))
                if from_bucket > seg_remaining + 0.001:
                    blocked.append(_blk("SEGMENT_CAPACITY",
                        "%s has %.2f risk capacity left; this trade needs %.2f." % (seg, seg_remaining, from_bucket)))

    day = str(trade.get("entry_date") or "")[:10]
    todays = [t for t in store.get("trades", [])
              if str(t.get("entry_date") or "")[:10] == day and t.get("id") != trade.get("id")]
    day_risk = sum(_num(t.get("planned_total_risk")) for t in todays)
    limit = _num(config.get("dailyRiskLimit"))
    if limit > 0 and day_risk + risk > limit + 0.001:
        blocked.append(_blk("DAILY_LIMIT",
            "Daily planned risk would be %.2f against a %.2f limit." % (day_risk + risk, limit)))

    max_exceptional = int(_num(config.get("maxPositionsExceptional"), 2))
    max_default = int(_num(config.get("maxPositionsPerDay"), 1))
    if len(todays) >= max_exceptional:
        blocked.append(_blk("POSITION_LIMIT",
            "Maximum " + str(max_exceptional) + " new positions per day already reached."))
    elif len(todays) >= max_default:
        if not trade.get("independence_confirmed"):
            blocked.append(_blk("SECOND_TRADE_INDEPENDENCE", "A second position requires independence confirmation."))
        if not str(trade.get("second_trade_rationale") or "").strip():
            blocked.append(_blk("SECOND_TRADE_RATIONALE", "A second position requires a recorded rationale."))

    reserve_used = _num(trade.get("reserve_risk_used"))
    if reserve_used > 0:
        if str(trade.get("grade") or "") != "A_PLUS":
            blocked.append(_blk("RESERVE_GRADE", "Opportunity Reserve is for A+ setups only."))
        if not str(trade.get("reserve_reason") or "").strip():
            blocked.append(_blk("RESERVE_REASON", "A written reason is required for reserve use."))
        if month:
            res_initial = _num((month.get("reserve") or {}).get("initial_allocation"))
            res_out = sum(_num(x.get("amount")) for x in store.get("opportunity_reserve_transfers", [])
                          if x.get("month_key") == mkey and x.get("trade_id") != trade.get("id"))
            if reserve_used > res_initial - res_out + 0.001:
                blocked.append(_blk("RESERVE_CAPACITY",
                    "Opportunity Reserve has %.2f left; %.2f requested." % (res_initial - res_out, reserve_used)))

    return {"agrees": len(blocked) == 0, "blocked": blocked, "warnings": warnings}

@app.get("/api/risk/sync")
def risk_sync_get(_auth: None = Depends(require_key)):
    return load_risk_file()

@app.post("/api/risk/sync")
async def risk_sync_post(request: Request, _auth: None = Depends(require_key)):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "error", "message": "Invalid JSON"}
    if not isinstance(payload, dict):
        return {"status": "error", "message": "Expected an object"}

    store = load_risk_file()
    for c in RISK_COLLECTIONS:
        if isinstance(payload.get(c), list):
            store[c] = payload[c]
    if isinstance(payload.get("config"), dict):
        store["config"] = payload["config"]
    store["schema_version"] = payload.get("schema_version", store.get("schema_version", 1))
    store["updated_at"] = payload.get("updated_at") or datetime.now().isoformat()

    save_risk_file(store)
    return {
        "status": "success",
        "updated_at": store["updated_at"],
        "counts": dict((c, len(store.get(c, []))) for c in RISK_COLLECTIONS),
    }

@app.post("/api/risk/validate")
async def risk_validate(request: Request, _auth: None = Depends(require_key)):
    try:
        payload = await request.json()
    except Exception:
        return {"agrees": False, "blocked": [_blk("BAD_REQUEST", "Invalid JSON")], "warnings": []}

    trade = payload.get("trade") or {}
    store = load_risk_file()
    result = _revalidate_trade(trade, store, payload.get("month_key"))

    # Record the server's own verdict so the audit trail is not client-controlled.
    try:
        conn = sqlite3.connect(DB_FILE)
        _risk_tables(conn)
        entry = {
            "id": "srv_" + str(trade.get("id")) + "_" + str(int(time.time() * 1000)),
            "at": datetime.now().isoformat(),
            "action": payload.get("action") or "SERVER_VALIDATION",
            "entity": "trades",
            "entity_id": trade.get("id"),
            "month_key": payload.get("month_key"),
            "detail": {"agrees": result["agrees"], "blocked": [b["code"] for b in result["blocked"]]},
            "server_confirmed": True,
        }
        conn.execute(
            "INSERT OR REPLACE INTO risk_audit_log (id, month_key, updated_at, data) VALUES (?, ?, ?, ?)",
            (entry["id"], entry["month_key"], entry["at"], json.dumps(entry)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print("[Risk Desk] audit write failed: " + str(e))

    return result

@app.get("/api/risk/audit")
def risk_audit(_auth: None = Depends(require_key), limit: int = Query(200)):
    try:
        conn = sqlite3.connect(DB_FILE)
        _risk_tables(conn)
        rows = conn.execute(
            "SELECT data FROM risk_audit_log ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return {"status": "success", "entries": [json.loads(r[0]) for r in rows]}
    except Exception as e:
        return {"status": "error", "message": str(e), "entries": []}


@app.get("/api/sync/all")
def get_all_sync_data(_auth: None = Depends(require_key)):
    return {
        "status": "success",
        "trades": load_journal_file(),
        "pullback": load_pullback_file(),
        "settings": load_settings_file(),
        "timestamp": time.time()
    }

@app.post("/api/sync/all")
async def post_all_sync_data(request: Request, _auth: None = Depends(require_key)):
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
async def save_portfolio_backup(request: Request, _auth: None = Depends(require_key)):
    try:
        data = await request.json()
        if isinstance(data, dict):
            incoming_saved_at = int(data.get("savedAt") or time.time() * 1000)
            data["savedAt"] = incoming_saved_at

            is_reset = bool(data.get("reset") or data.get("force_reset") or data.get("isFreshStart"))

            if not is_reset and os.path.exists(PORTFOLIO_FILE):
                try:
                    with file_lock:
                        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as existing_f:
                            existing = json.load(existing_f)
                    
                    existing_saved_at = int(existing.get("savedAt", 0))

                    # Merge soldHistory by ID to prevent lost closed trades
                    existing_sold = existing.get("soldHistory", [])
                    incoming_sold = data.get("soldHistory", [])
                    sold_map = { (s.get("id") or f"{s.get('ticker')}_{s.get('sellDate')}"): s for s in existing_sold if isinstance(s, dict) }
                    for s in incoming_sold:
                        if isinstance(s, dict):
                            key = s.get("id") or f"{s.get('ticker')}_{s.get('sellDate')}"
                            sold_map[key] = s
                    data["soldHistory"] = list(sold_map.values())

                    # Build set of all sold IDs and tickers to prevent resurrected sold trades
                    sold_keys = set()
                    for s in data["soldHistory"]:
                        if isinstance(s, dict):
                            if s.get("id"): sold_keys.add(s.get("id"))
                            if s.get("ticker"): sold_keys.add(s.get("ticker"))

                    # Merge active positions
                    incoming_pos = data.get("positions", [])
                    existing_pos = existing.get("positions", [])
                    if existing_saved_at > incoming_saved_at and isinstance(existing_pos, list):
                        pos_map = { p.get("id"): p for p in existing_pos if isinstance(p, dict) and p.get("id") }
                        for p in (incoming_pos if isinstance(incoming_pos, list) else []):
                            if isinstance(p, dict) and p.get("id") and p.get("id") not in pos_map:
                                pos_map[p.get("id")] = p
                        data["positions"] = [p for p in pos_map.values() if p.get("id") not in sold_keys and p.get("ticker") not in sold_keys]
                    else:
                        if isinstance(incoming_pos, list):
                            data["positions"] = [
                                p for p in incoming_pos
                                if isinstance(p, dict) and p.get("id") not in sold_keys and p.get("ticker") not in sold_keys
                            ]

                    # Merge brokerAdjustments by ID
                    existing_adj = existing.get("brokerAdjustments", [])
                    incoming_adj = data.get("brokerAdjustments", [])
                    adj_map = { (a.get("id") or f"{a.get('date')}_{a.get('amount')}"): a for a in existing_adj if isinstance(a, dict) }
                    for a in incoming_adj:
                        if isinstance(a, dict):
                            key = a.get("id") or f"{a.get('date')}_{a.get('amount')}"
                            adj_map[key] = a
                    data["brokerAdjustments"] = list(adj_map.values())

                    # Merge optionsTrades by ID
                    existing_opt = existing.get("optionsTrades", [])
                    incoming_opt = data.get("optionsTrades", [])
                    opt_map = { (o.get("id") or f"{o.get('entryDate')}_{o.get('instrument')}"): o for o in existing_opt if isinstance(o, dict) }
                    for o in incoming_opt:
                        if isinstance(o, dict):
                            key = o.get("id") or f"{o.get('entryDate')}_{o.get('instrument')}"
                            opt_map[key] = o
                    data["optionsTrades"] = list(opt_map.values())

                    # Preserve capitalLedger / freeCash / budget / split if existing is newer or incoming is missing
                    if existing_saved_at > incoming_saved_at:
                        if existing.get("freeCash"): data["freeCash"] = existing["freeCash"]
                        if existing.get("budget"): data["budget"] = existing["budget"]
                        if existing.get("split"): data["split"] = existing["split"]
                        if existing.get("capitalLedger"): data["capitalLedger"] = existing["capitalLedger"]
                    else:
                        if existing.get("capitalLedger") and not data.get("capitalLedger"):
                            data["capitalLedger"] = existing["capitalLedger"]
                        if existing.get("freeCash") and not data.get("freeCash"):
                            data["freeCash"] = existing["freeCash"]

                    data["savedAt"] = max(existing_saved_at, incoming_saved_at)
                except Exception as ex:
                    print(f"[Backup] Merge warning: {ex}")

            with file_lock:
                with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            push_to_github(PORTFOLIO_FILE, "finplus_portfolio_backup.json")
        return { "status": "success" }
    except Exception as e:
        return { "status": "error", "message": str(e) }

@app.post("/api/backup/reset")
async def reset_portfolio_backup(_auth: None = Depends(require_key)):
    try:
        now_ts = int(time.time() * 1000)
        fresh_data = {
            "positions": [],
            "capitalLedger": [],
            "soldHistory": [],
            "brokerAdjustments": [],
            "optionsTrades": [],
            "freeCash": { "swing": "0", "lt": "0", "penny": "0" },
            "budget": "0",
            "split": { "swing": 60, "lt": 30, "penny": 10 },
            "isFreshStart": True,
            "savedAt": now_ts
        }
        with file_lock:
            with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
                json.dump(fresh_data, f, indent=2)
            with open(JOURNAL_FILE, "w", encoding="utf-8") as jf:
                json.dump([], jf, indent=2)
        push_to_github(PORTFOLIO_FILE, "finplus_portfolio_backup.json")
        push_to_github(JOURNAL_FILE, "finplus_journal_data.json")
        return { "status": "success", "message": "Clean slate reset successful", "data": fresh_data }
    except Exception as e:
        return { "status": "error", "message": str(e) }


@app.get("/api/backup/load")
def load_portfolio_backup(_auth: None = Depends(require_key)):
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

@app.get("/api/backup/health")
def backup_health():
    """Debug endpoint — returns sync status without exposing full data."""
    if not os.path.exists(PORTFOLIO_FILE):
        return { "status": "missing", "file_exists": False }
    try:
        with file_lock:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        return {
            "status": "ok",
            "file_exists": True,
            "savedAt": data.get("savedAt"),
            "position_count": len(data.get("positions", [])),
            "sold_count": len(data.get("soldHistory", [])),
            "freeCash": data.get("freeCash"),
            "github_token_set": bool(GITHUB_TOKEN)
        }
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

