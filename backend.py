import os
import json
import time
import sqlite3
import threading
from typing import Dict, List, Any, Optional
from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
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
DB_FILE = os.path.join(BASE_DIR, "trades_backup.db")

# Thread lock for file operations
file_lock = threading.Lock()

# Price cache: { symbol: { "ltp": float, "change": float, "prev_close": float, "high": float, "low": float, "timestamp": float } }
PRICE_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 3.0

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
    "ASHOKLEY.NS": { "name": "Ashok Leyland Limited", "category": "Core", "transactions": [{ "date": "2026-07-13", "price": 160.53, "shares": 2 }], "local_peak": 176.25, "initial_reference_price": 160.53 },
    "BEL.NS": { "name": "Bharat Electronics Limited", "category": "Core", "transactions": [{ "date": "2026-07-29", "price": 403.52, "shares": 3 }], "local_peak": 403.52, "initial_reference_price": 403.52 },
    "EMMVEE.NS": { "name": "Emmvee Photovoltaic Power Limited", "category": "Growth", "transactions": [{ "date": "2026-08-03", "price": 330.98, "shares": 2 }], "local_peak": 330.98, "initial_reference_price": 330.98 },
    "FEDERALBNK.NS": { "name": "The Federal Bank Limited", "category": "Core", "transactions": [{ "date": "2026-08-03", "price": 359.10, "shares": 1 }], "local_peak": 359.10, "initial_reference_price": 359.10 },
    "ITC.NS": { "name": "ITC Limited", "category": "Core", "transactions": [{ "date": "2026-07-14", "price": 275.45, "shares": 1 }], "local_peak": 286.25, "initial_reference_price": 275.45 },
    "NMDC.NS": { "name": "NMDC Limited", "category": "Core", "transactions": [{ "date": "2026-08-03", "price": 84.80, "shares": 1 }], "local_peak": 84.80, "initial_reference_price": 84.80 },
    "TATAPOWER.NS": { "name": "Tata Power Company Limited", "category": "Core", "transactions": [{ "date": "2026-07-10", "price": 382.25, "shares": 1 }], "local_peak": 382.25, "initial_reference_price": 382.25 },
    "TATASTEEL.NS": { "name": "Tata Steel Limited", "category": "Growth", "transactions": [{ "date": "2026-07-27", "price": 182.82, "shares": 1 }], "local_peak": 191.53, "initial_reference_price": 182.82 },
    "mtf_trading": [
        { "id": 0, "ticker": "LODHA.NS", "buy_date": "2026-07-06", "buy_price": 1091.70, "shares": 8, "margin_used": 2183.40, "status": "Active" },
        { "id": 1, "ticker": "INDUSTOWER.NS", "buy_date": "2026-07-08", "buy_price": 394.20, "shares": 34, "margin_used": 3350.70, "status": "Active" },
        { "id": 2, "ticker": "NAUKRI.NS", "buy_date": "2026-07-08", "buy_price": 1198.00, "shares": 10, "margin_used": 2396.00, "status": "Active" }
    ]
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
    { "symbol": "GESHIP", "name": "The Great Eastern Shipping Company Limited", "aliases": ["geship", "great eastern", "shipping", "ge shipping"] }
]

def normalize_symbol(sym: str) -> str:
    cleaned = sym.strip().upper()
    if cleaned in SYMBOL_MAP:
        return SYMBOL_MAP[cleaned]
    if "NIFTY" in cleaned:
        return "^NSEI"
    if "BANKNIFTY" in cleaned:
        return "^NSEBANK"
    if "CRUDE" in cleaned:
        return "CL=F"
    if "NATGAS" in cleaned or "NATURAL" in cleaned:
        return "NG=F"
    if "GOLD" in cleaned:
        return "GC=F"
    if "SILVER" in cleaned:
        return "SI=F"
    if not cleaned.endswith(".NS") and not cleaned.endswith(".BO") and "=" not in cleaned and "^" not in cleaned:
        return f"{cleaned}.NS"
    return cleaned

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

def load_pullback_file() -> Dict[str, Any]:
    with file_lock:
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

def load_journal_file() -> List[Dict[str, Any]]:
    with file_lock:
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

@app.get("/")
@app.get("/health")
def health_check():
    return {
        "status": "online",
        "app": "Finplus PnL Independent Backend",
        "data_source": "yfinance",
        "version": "2.0.0"
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

@app.get("/api/trades")
@app.get("/api/trades/journal")
def get_trades():
    trades = load_journal_file()
    return {
        "status": "success",
        "trades": trades,
        "count": len(trades)
    }

@app.post("/api/trades")
@app.post("/api/trades/journal")
@app.post("/api/trades/sync")
@app.post("/api/journal/sync")
async def sync_trades(request: Request):
    payload = await request.json()
    trades_list = []
    if isinstance(payload, list):
        trades_list = payload
    elif isinstance(payload, dict):
        trades_list = payload.get("trades", [])
    
    if trades_list:
        save_journal_file(trades_list)
        return { "status": "success", "synced_count": len(trades_list) }
    return { "status": "success", "synced_count": 0 }
