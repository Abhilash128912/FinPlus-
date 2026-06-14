import sys
import os
import threading
import time
from datetime import date, datetime
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock

# =========================================================
# ─── STREAMLIT MOCK FOR HEADLESS IMPORT ────────────────
# =========================================================

class SessionState(dict):
    def __getattr__(self, name):
        return self.get(name, None)
    def __setattr__(self, name, value):
        self[name] = value

class MockElement:
    def __call__(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return self
    def __getattr__(self, name):
        return MockElement()
    def __bool__(self):
        return False
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class MockStreamlit:
    def __init__(self):
        self.session_state = SessionState()
        # Initialize required state properties to avoid attribute errors
        self.session_state.historical_data = {}
        self.session_state.token_accepted = False
        self.session_state.history_status = "Idle"
        self.session_state.history_errors = []
        self.session_state.history_loaded = False
        self.session_state.history_loaded_at = 0.0
        self.session_state.auto_history_last_load = 0.0
        self.session_state.history_attempted = False
        self.session_state.feed_state = None
        self.sidebar = MockElement()
        
    def set_page_config(self, *args, **kwargs):
        pass

    def columns(self, spec, *args, **kwargs):
        count = len(spec) if isinstance(spec, (list, tuple)) else (spec if isinstance(spec, int) else 2)
        return [MockElement() for _ in range(count)]

    def tabs(self, spec, *args, **kwargs):
        count = len(spec) if isinstance(spec, (list, tuple)) else (spec if isinstance(spec, int) else 2)
        return [MockElement() for _ in range(count)]

    def text_input(self, label, value="", *args, **kwargs):
        return value

    def number_input(self, label, min_value=None, max_value=None, value=None, *args, **kwargs):
        return value if value is not None else 0.0

    def selectbox(self, label, options, index=0, *args, **kwargs):
        return options[index] if options and index < len(options) else None

    def multiselect(self, label, options, default=None, *args, **kwargs):
        return default if default is not None else []

    def checkbox(self, label, value=False, *args, **kwargs):
        return value

    def slider(self, label, min_value=None, max_value=None, value=None, *args, **kwargs):
        return value if value is not None else 0.0

    def date_input(self, label, value=None, *args, **kwargs):
        return value if value is not None else date.today()
        
    def button(self, label, *args, **kwargs):
        return False
        
    def __getattr__(self, name):
        return MockElement()

# Inject mock streamlit before importing Trading_WS
mock_st = MockStreamlit()
sys.modules['streamlit'] = mock_st

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Now import our modules
import Trading_WS
from calculator import calculate_trade_metrics
from database import add_paper_trade, get_brokerage_rates, delete_paper_trade

# =========================================================
# ─── FASTAPI APPLICATION SETUP ──────────────────────────
# =========================================================

from fastapi import FastAPI, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Trading Workstation API",
    description="Backend services for the Trading Workstation Mobile App.",
    version="1.0.0"
)

# Enable CORS for React Native development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory background tasks tracker
bg_load_thread = None

class TokenConnectRequest(BaseModel):
    access_token: str

class PaperTradeCreate(BaseModel):
    symbol: str
    segment: str
    action: str  # "BUY" or "SELL"
    quantity: float
    entry_price: float
    exit_price: float
    notes: Optional[str] = ""
    source_screener: Optional[str] = "Trading Workstation"

# =========================================================
# ─── BACKGROUND WORKERS ────────────────────────────────
# =========================================================

def _run_historical_load_bg(access_token: str):
    import streamlit as st
    st.session_state.history_status = "Loading"
    st.session_state.history_attempted = True
    print(f"[{datetime.now()}] Background historical data load started...")
    
    try:
        success_count, failures = Trading_WS.load_historical_data(
            access_token, 
            worker_count=Trading_WS.HISTORICAL_WORKERS
        )
        if success_count:
            st.session_state.history_loaded = True
            st.session_state.history_status = "Loaded"
            st.session_state.history_loaded_at = time.time()
            st.session_state.auto_history_last_load = time.time()
            st.session_state.history_errors = failures
            print(f"[{datetime.now()}] Background historical data loaded successfully for {success_count} stocks.")
            
            # Start WebSocket feed after historical baseline is built
            Trading_WS.start_feed(Trading_WS.feed_state, access_token)
            print(f"[{datetime.now()}] WebSocket feed started successfully.")
        else:
            st.session_state.history_status = "Failed"
            st.session_state.history_errors = failures
            print(f"[{datetime.now()}] Background historical data load failed: {failures}")
    except Exception as e:
        st.session_state.history_status = "Failed"
        st.session_state.history_errors = [str(e)]
        print(f"[{datetime.now()}] Error in background historical load: {e}")

# =========================================================
# ─── API ENDPOINTS ──────────────────────────────────────
# =========================================================

@app.on_event("startup")
def startup_event():
    """Load cached token and automatically connect on startup if token exists."""
    import streamlit as st
    token = Trading_WS.load_cached_token()
    if token:
        st.session_state.token_accepted = True
        st.session_state.accepted_token = token
        # Run historical load in background to avoid blocking API startup
        global bg_load_thread
        bg_load_thread = threading.Thread(target=_run_historical_load_bg, args=(token,), daemon=True)
        bg_load_thread.start()
        print("Cached token found. Initializing backend feed in background...")
    else:
        print("No cached token found. Waiting for client to connect via /api/connect.")

@app.get("/api/market-status")
def get_market_status():
    """Returns the current market hours status (open, closed, pre-open)."""
    return Trading_WS.market_status()

@app.get("/api/status")
def get_system_status():
    """Returns the connectivity status of WebSocket and historical data."""
    import streamlit as st
    _fs = Trading_WS.feed_state
    with _fs.lock:
        fs_status = _fs.status
        fs_err = _fs.last_error
        fs_recon = _fs.reconnects
        fs_update = _fs.last_update
        fs_count = len(_fs.market_data)
        
    return {
        "websocket": {
            "status": fs_status,
            "error": fs_err,
            "reconnects": fs_recon,
            "last_update": Trading_WS.format_last_update(fs_update) if fs_update else "Never",
            "market_data_count": fs_count,
            "connected": fs_status in ("Connected", "Live", "Subscribing")
        },
        "historical_data": {
            "status": st.session_state.history_status,
            "loaded_count": len(st.session_state.historical_data),
            "loaded_at": Trading_WS.format_last_update(st.session_state.history_loaded_at) if st.session_state.history_loaded_at else "Never",
            "errors_count": len(st.session_state.history_errors)
        },
        "token_accepted": st.session_state.token_accepted
    }

@app.post("/api/connect")
def connect_system(req: TokenConnectRequest, background_tasks: BackgroundTasks):
    """Sets a new access token, triggers historical data load and connects WebSocket."""
    import streamlit as st
    if not req.access_token.strip():
        raise HTTPException(status_code=400, detail="Access token cannot be empty.")
        
    # Save token and accept it
    Trading_WS.save_cached_token(req.access_token)
    st.session_state.token_accepted = True
    st.session_state.accepted_token = req.access_token
    
    # Trigger loading historical data + starting feed in background
    global bg_load_thread
    bg_load_thread = threading.Thread(target=_run_historical_load_bg, args=(req.access_token,), daemon=True)
    bg_load_thread.start()
    
    return {"status": "Initializing", "message": "Historical data download and WebSocket connection started in background."}

@app.post("/api/disconnect")
def disconnect_system():
    """Stops the WebSocket feed and disconnects."""
    Trading_WS.stop_feed(Trading_WS.feed_state)
    return {"status": "Stopping", "message": "WebSocket feed stop requested."}

@app.get("/api/watchlist")
def get_watchlist(
    min_change: float = 1.5,
    min_rvol: float = 2.0,
    min_breakout_score: int = 5,
    volume_premium_min: float = 1.0,
    volume_premium_max: float = 9999.0,
    sr_pivot_type: str = "None"
):
    """Computes signals and scores for the watchlists dynamically."""
    import streamlit as st
    _fs = Trading_WS.feed_state
    _mkt, _idx_d, _fst = Trading_WS.snapshot_feed(_fs)
    _ms2 = Trading_WS.market_status()
    mkt_trend = "UPTREND"
    
    # Compute market trend from broad market status
    try:
        bms = Trading_WS.calculate_broad_market_status()
        mkt_trend = bms.get("trend", "UPTREND")
    except Exception:
        pass
        
    # Fallback to historical End of Day data if feed not connected or market closed
    scan_data = _mkt
    scan_source = "Live WebSocket"
    if not scan_data and st.session_state.history_loaded:
        scan_data = Trading_WS.build_historical_market_data()
        if scan_data:
            _data_dates = [m.get("last_data_date", "") for m in st.session_state.historical_data.values() if m.get("last_data_date")]
            _last_data_date = max(_data_dates) if _data_dates else "unknown date"
            scan_source = f"EOD {_last_data_date}"
            
    if not scan_data:
        return []
        
    db_meta = Trading_WS.load_db_metadata()
    
    # ── Relative Strength vs Nifty 50 Calculations ──
    nifty_chg = 0.0
    with _fs.lock:
        nifty_quote = _fs.index_data.get("NIDX:40000001", {})
    if nifty_quote:
        nifty_chg = float(nifty_quote.get("day_change_percentage") or nifty_quote.get("change_percentage") or 0.0)
        
    eu = Trading_WS.effective_universe()
    stock_changes = {}
    for instrument, quote in scan_data.items():
        stock_name = eu.get(instrument) or Trading_WS.STOCK_NAMES.get(instrument) or instrument
        symbol_clean = stock_name.replace(".NS", "")
        day_chg = 0.0
        hist = st.session_state.historical_data.get(instrument, {})
        if hist:
            day_chg = hist.get("day_change_pct", day_chg)
        parsed = Trading_WS.parse_quote(quote)
        open_p = parsed["open"]
        close_p = parsed["close"]
        if open_p > 0:
            day_chg = ((close_p - open_p) / open_p) * 100
        stock_changes[symbol_clean] = day_chg
        
    stock_rs = {sym: chg - nifty_chg for sym, chg in stock_changes.items()}
    sorted_rs = sorted(stock_rs.items(), key=lambda x: x[1])
    rs_ranks = {}
    num_stocks = len(sorted_rs)
    for rank_idx, (sym, rs_val) in enumerate(sorted_rs):
        pct = round((rank_idx + 1) / max(1, num_stocks) * 100)
        rs_ranks[sym] = pct
        
    sector_groups = {}
    for sym, chg in stock_changes.items():
        sector = db_meta.get(sym, {}).get("sector", "Other")
        if sector not in sector_groups:
            sector_groups[sector] = []
        sector_groups[sector].append((sym, chg))
        
    sector_ranks = {}
    for sector, members in sector_groups.items():
        sorted_members = sorted(members, key=lambda x: x[1], reverse=True)
        total_members = len(sorted_members)
        for rank_idx, (sym, chg) in enumerate(sorted_members):
            sector_ranks[sym] = (rank_idx + 1, total_members)
            
    # ── Signal Generation Loop ──
    results = []
    for instrument, quote in scan_data.items():
        signal = Trading_WS.calculate_signal(
            instrument, quote,
            min_change, min_rvol, min_breakout_score,
            volume_premium_min, volume_premium_max
        )
        if signal:
            stock_name = signal["Stock"]
            stock_clean = stock_name.replace(".NS", "")
            signal["Source"] = scan_source
            
            # Enrich signal with sector and rank metadata
            meta_info = db_meta.get(stock_clean, {})
            sector = meta_info.get("sector", "Other")
            signal["Sector"] = sector
            
            # Sentiment score
            news_data = Trading_WS.fetch_news_sentiment(stock_clean)
            signal["News_Sentiment"] = news_data["sentiment"]
            signal["News_Score"] = news_data["score"]
            signal["News_Latest"] = news_data["latest_headline"]
            signal["News_Counts"] = f"{news_data['pos_count']}P/{news_data['neu_count']}N/{news_data['neg_count']}D"
            
            # Quality & Confidence
            opp_score = Trading_WS.calculate_opportunity_score(signal, news_data["score"], mkt_trend)
            q_metrics = Trading_WS.get_signal_quality_metrics(opp_score)
            signal["Confidence"] = opp_score
            signal["Quality"] = q_metrics["grade"]
            signal["Win_Rate"] = q_metrics["win_rate"]
            signal["Expectancy"] = q_metrics["expectancy"]
            signal["Samples"] = q_metrics["samples"]
            signal["Expected_Move"] = q_metrics["exp_move"]
            
            # Strength Rank
            rs_val = stock_rs.get(stock_clean, 0.0)
            rs_rank = rs_ranks.get(stock_clean, 50)
            sec_rank, sec_total = sector_ranks.get(stock_clean, (1, 1))
            signal["RS vs Nifty"] = f"{rs_val:+.2f}%"
            signal["RS Rank"] = rs_rank
            signal["Sector Rank"] = f"{sec_rank}/{sec_total}"
            
            # Dynamic Stops & Targets
            hist = st.session_state.historical_data.get(instrument, {})
            ltp = signal["LTP"]
            r1 = hist.get("r1", 0.0)
            r3 = hist.get("r3", 0.0)
            s1 = hist.get("s1", 0.0)
            s3 = hist.get("s3", 0.0)
            ema20 = hist.get("ema20", 0.0)
            
            if "LONG" in signal["Signal"]:
                entry = ltp
                sl = round(ltp * 0.985, 2)
                if sr_pivot_type == "Traditional" and s1 > 0 and s1 < ltp:
                    sl = s1
                elif sr_pivot_type == "Camarilla" and s3 > 0 and s3 < ltp:
                    sl = s3
                elif ema20 < ltp and ema20 > ltp * 0.975:
                    sl = ema20
                    
                tgt = round(ltp * 1.03, 2)
                if sr_pivot_type == "Traditional" and r1 > ltp:
                    tgt = r1
                elif sr_pivot_type == "Camarilla" and r3 > ltp:
                    tgt = r3
                
                rr = round((tgt - entry) / max(0.01, entry - sl), 2)
            else:
                entry = ltp
                sl = round(ltp * 1.015, 2)
                if sr_pivot_type == "Traditional" and r1 > 0 and r1 > ltp:
                    sl = r1
                elif sr_pivot_type == "Camarilla" and r3 > 0 and r3 > ltp:
                    sl = r3
                    
                tgt = round(ltp * 0.97, 2)
                if sr_pivot_type == "Traditional" and s1 > 0 and s1 < ltp:
                    tgt = s1
                elif sr_pivot_type == "Camarilla" and s3 > 0 and s3 < ltp:
                    tgt = s3
                
                rr = round((entry - tgt) / max(0.01, sl - entry), 2)
                
            signal["Stop_Loss"] = sl
            signal["Target"] = tgt
            signal["Risk_Reward"] = rr
            results.append(signal)
            
    # Sort by Opportunity Score (Confidence) descending
    results = sorted(results, key=lambda x: x["Confidence"], reverse=True)
    return results


def scan_for_swing_picks(access_token: str) -> list[dict]:
    """Scans all stocks in the active watchlist universe using INDmoney daily candles
    and scores them against the 14 technical swing trading criteria.
    """
    import concurrent.futures
    import time
    import pandas as pd
    import numpy as np
    import requests
    from datetime import datetime
    import Trading_WS
    
    universe = Trading_WS.effective_universe()
    stock_tokens = list(universe.keys())
    results = []
    
    def process_stock(token):
        try:
            # Fetch daily candles
            end_time = int(time.time() * 1000)
            lookback_days = 380
            start_time = end_time - (lookback_days * 24 * 60 * 60 * 1000)
            
            params = {
                "scrip-codes": f"NSE_{token}",
                "start_time": start_time,
                "end_time": end_time,
            }
            
            resp = requests.get(
                Trading_WS.HISTORICAL_DAILY_URL,
                params=params,
                headers=Trading_WS.auth_headers(access_token),
                timeout=5
            )
            if resp.status_code != 200:
                return None
                
            data = resp.json()
            payload = data.get("data", {})
            scrip = f"NSE_{token}"
            
            candles_d = []
            if isinstance(payload, dict):
                if isinstance(payload.get("candles"), list):
                    candles_d = payload["candles"]
                else:
                    for key in (scrip, token, f"NSE:{token}"):
                        value = payload.get(key)
                        if isinstance(value, dict) and isinstance(value.get("candles"), list):
                            candles_d = value["candles"]
                            break
                        if isinstance(value, list):
                            candles_d = value
                            break
            
            if not candles_d or len(candles_d) < 50:
                return None
                
            # Convert to DataFrame
            if isinstance(candles_d[0], dict):
                df = pd.DataFrame(candles_d)
                df = df.rename(columns={
                    "ts": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
                    "timestamp": "timestamp", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"
                })
            else:
                df = pd.DataFrame(candles_d, columns=["timestamp", "open", "high", "low", "close", "volume"])
                
            # Numeric conversion
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
                
            # Sort by timestamp ascending
            df = df.sort_values("timestamp").reset_index(drop=True)
            
            # Calculate Indicators
            df["ema15"] = df["close"].ewm(span=15, adjust=False).mean()
            df["sma50"] = df["close"].rolling(window=50).mean()
            
            # MACD
            ema12 = df["close"].ewm(span=12, adjust=False).mean()
            ema26 = df["close"].ewm(span=26, adjust=False).mean()
            df["macd_line"] = ema12 - ema26
            df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
            
            # RSI
            delta = df["close"].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(com=13, adjust=False).mean()
            avg_loss = loss.ewm(com=13, adjust=False).mean()
            rs = avg_gain / avg_loss
            df["rsi"] = 100 - (100 / (1 + rs))
            
            # ADX / DMI
            df["tr"] = np.maximum(df["high"] - df["low"], 
                                  np.maximum(np.abs(df["high"] - df["close"].shift(1)), 
                                             np.abs(df["low"] - df["close"].shift(1))))
            df["plus_dm"] = np.where((df["high"] - df["high"].shift(1) > df["low"].shift(1) - df["low"]) & 
                                     (df["high"] - df["high"].shift(1) > 0), 
                                     df["high"] - df["high"].shift(1), 0.0)
            df["minus_dm"] = np.where((df["low"].shift(1) - df["low"] > df["high"] - df["high"].shift(1)) & 
                                      (df["low"].shift(1) - df["low"] > 0), 
                                      df["low"].shift(1) - df["low"], 0.0)
            
            tr_smoothed = df["tr"].ewm(alpha=1/14, adjust=False).mean()
            plus_dm_smoothed = df["plus_dm"].ewm(alpha=1/14, adjust=False).mean()
            minus_dm_smoothed = df["minus_dm"].ewm(alpha=1/14, adjust=False).mean()
            
            df["plus_di"] = 100 * (plus_dm_smoothed / tr_smoothed)
            df["minus_di"] = 100 * (minus_dm_smoothed / tr_smoothed)
            df["dx"] = 100 * np.abs(df["plus_di"] - df["minus_di"]) / (df["plus_di"] + df["minus_di"])
            df["adx"] = df["dx"].ewm(alpha=1/14, adjust=False).mean()
            
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            
            idx_12m = max(0, len(df) - 250)
            close_12m = float(df["close"].iloc[idx_12m])
            
            # Evaluated criteria (14 items from screenshot)
            c1 = 1 if latest["close"] > latest["open"] else 0
            c2 = 1 if prev["close"] > prev["open"] else 0
            c3 = 1 if latest["ema15"] > latest["sma50"] else 0
            c4 = 1 if latest["macd_line"] > latest["macd_signal"] else 0
            c5 = 1 if latest["volume"] > 100000 else 0
            c6 = 1 if latest["close"] > latest["ema15"] else 0
            c7 = 1 if latest["close"] > prev["close"] else 0
            c8 = 1 if latest["plus_di"] > 20 else 0
            c9 = 1 if latest["rsi"] > 40 else 0
            c10 = 1 if latest["close"] <= latest["ema15"] * 1.07 else 0
            c11 = 1 if latest["close"] > close_12m else 0
            c12 = 1 if latest["plus_di"] > latest["minus_di"] else 0
            c13 = 1 if latest["macd_line"] > 0 else 0
            c14 = 1 if latest["open"] * 1.01 < latest["close"] else 0
            
            score = c1 + c2 + c3 + c4 + c5 + c6 + c7 + c8 + c9 + c10 + c11 + c12 + c13 + c14
            
            db_meta = Trading_WS.load_db_metadata()
            symbol_clean = universe.get(token, token).replace(".NS", "")
            company = db_meta.get(symbol_clean, {}).get("company_name", symbol_clean)
            
            return {
                "Stock": symbol_clean,
                "Company": company,
                "Total": int(score / 14 * 100),
                "Funda": 100 if latest["close"] > close_12m else 50,
                "Mntm": int(latest["rsi"]),
                "LTP": float(latest["close"]),
                "plus_di": float(latest["plus_di"]),
                "volume": float(latest["volume"]),
                "score_raw": score
            }
        except Exception as e:
            print(f"Error scanning stock {token}: {e}")
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(process_stock, tok) for tok in stock_tokens]
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            if res:
                results.append(res)
                
    return results


@app.get("/api/alpha-picks")
def get_alpha_picks():
    """Generates and returns the 4 Alpha Picks of the Day, with 15-minute selection locks."""
    import streamlit as st
    import pandas as pd
    
    # Initialize session state locks if not present
    if "locked_intraday_pick" not in st.session_state:
        st.session_state.locked_intraday_pick = None
    if "locked_option_pick" not in st.session_state:
        st.session_state.locked_option_pick = None
    if "locked_nifty_option_pick" not in st.session_state:
        st.session_state.locked_nifty_option_pick = None
    if "locked_swing_pick" not in st.session_state:
        st.session_state.locked_swing_pick = None
    if "locked_at_time" not in st.session_state:
        st.session_state.locked_at_time = 0.0

    now_ts = time.time()
    # 15-minute auto-expiry (900 seconds)
    if st.session_state.locked_at_time > 0.0 and (now_ts - st.session_state.locked_at_time > 900.0):
        st.session_state.locked_intraday_pick = None
        st.session_state.locked_option_pick = None
        st.session_state.locked_nifty_option_pick = None
        st.session_state.locked_swing_pick = None
        st.session_state.locked_at_time = 0.0

    # Get active watchlist signals
    wl_signals = get_watchlist(
        min_change=0.4,
        min_rvol=1.0,
        min_breakout_score=3,
        sr_pivot_type="None"
    )

    _fs = Trading_WS.feed_state
    with _fs.lock:
        _mkt = dict(_fs.market_data)
        _idx_d = dict(_fs.index_data)

    _ms2 = Trading_WS.market_status()
    _now2 = datetime.now(Trading_WS._IST_TZ)
    
    # Map name to token dynamically
    eu = Trading_WS.effective_universe()
    name_to_token = {name.replace(".NS", ""): tok for tok, name in eu.items()}

    # 1. INTRADAY PICK
    intraday_pick = None
    if st.session_state.locked_intraday_pick:
        intraday_pick = st.session_state.locked_intraday_pick.copy()
        # Update price from live feed
        sym = intraday_pick["Stock"]
        tok = name_to_token.get(sym)
        if tok and tok in _mkt:
            live_q = Trading_WS.parse_quote(_mkt[tok])
            if live_q["close"] > 0:
                intraday_pick["LTP"] = live_q["close"]
                open_p = live_q.get("open", 0)
                if open_p > 0:
                    intraday_pick["Change %"] = round(((live_q["close"] - open_p) / open_p) * 100, 2)
        st.session_state.locked_intraday_pick = intraday_pick.copy()
    else:
        if wl_signals:
            is_opening = _ms2["is_open"] and (_now2.hour == 9 and 15 <= _now2.minute < 30)
            max_chg = 4.0 if is_opening else 1.5
            candidates = [
                item for item in wl_signals 
                if item["Signal"] in ["LONG", "SHORT"] 
                and abs(item["Change %"]) < max_chg 
                and abs(item["Change %"]) > 0.4
            ]
            if candidates:
                top_grade = [c for c in candidates if c.get("Quality") in ["A+", "A"]]
                if not top_grade:
                    top_grade = [c for c in candidates if c.get("Quality") == "B"]
                if not top_grade:
                    top_grade = candidates
                top_grade = sorted(top_grade, key=lambda x: (x.get("Score", 0), x.get("RVOL", 0)), reverse=True)
                item = top_grade[0]
                
                intraday_pick = {
                    "Stock": item["Stock"].replace(".NS", ""),
                    "Signal": item["Signal"],
                    "LTP": float(item["LTP"]),
                    "Change %": float(item["Change %"]),
                    "Score": f"{item['Score']}/{item.get('Total_Checks', 8)}",
                    "Confidence": item.get("Confidence", 50),
                    "Quality": item.get("Quality", "B"),
                    "Sector": item.get("Sector", "Other"),
                    "Suggested_At": datetime.now(Trading_WS._IST_TZ).strftime("%I:%M:%S %p") if _ms2["is_open"] else "EOD (03:30 PM)"
                }
                _init_ltp = intraday_pick["LTP"]
                intraday_pick["Entry_Price"] = _init_ltp
                _sl_dist = _init_ltp * 0.015
                _is_long = intraday_pick["Signal"] in ("LONG", "BREAKOUT")
                intraday_pick["Stop_Loss"] = round(_init_ltp - _sl_dist if _is_long else _init_ltp + _sl_dist, 2)
                intraday_pick["Target"] = round(_init_ltp + (_sl_dist * 2.0) if _is_long else _init_ltp - (_sl_dist * 2.0), 2)
                
                st.session_state.locked_intraday_pick = intraday_pick.copy()
                if st.session_state.locked_at_time == 0.0:
                    st.session_state.locked_at_time = time.time()

    # 2. STOCK OPTION PICK
    option_pick = None
    if st.session_state.locked_option_pick:
        option_pick = st.session_state.locked_option_pick.copy()
        # Update price from live feed
        sym = option_pick["Stock"]
        tok = name_to_token.get(sym)
        if tok and tok in _mkt:
            live_q = Trading_WS.parse_quote(_mkt[tok])
            if live_q["close"] > 0:
                option_pick["LTP"] = live_q["close"]
                open_p = live_q.get("open", 0)
                if open_p > 0:
                    option_pick["Change %"] = round(((live_q["close"] - open_p) / open_p) * 100, 2)
        st.session_state.locked_option_pick = option_pick.copy()
    else:
        FO_LOT_SIZES = {
            "RELIANCE": 250, "TCS": 175, "INFY": 400, "TATASTEEL": 5500, "SBIN": 1500,
            "BHARTIARTL": 950, "ICICIBANK": 700, "HDFCBANK": 550, "AXISBANK": 625, "ITC": 1600,
            "LT": 300, "HINDUNILVR": 300, "M&M": 350, "SUNPHARMA": 700, "MARUTI": 50,
            "ONGC": 3850, "JSWSTEEL": 675, "ADANIENT": 300, "COALINDIA": 4200, "NTPC": 1500,
            "POWERGRID": 3600, "KOTAKBANK": 400
        }
        if wl_signals:
            candidates = [
                item for item in wl_signals 
                if item["Signal"] in ["LONG", "SHORT"]
            ]
            if candidates:
                fo_candidates = [c for c in candidates if c["Stock"].replace(".NS", "") in FO_LOT_SIZES]
                top_grade = [c for c in fo_candidates if c.get("Quality") in ["A+", "A"]]
                if not top_grade:
                    top_grade = fo_candidates
                if not top_grade:
                    top_grade = [c for c in candidates if c.get("Quality") in ["A+", "A"]]
                if not top_grade:
                    top_grade = candidates
                top_grade = sorted(top_grade, key=lambda x: (x.get("Score", 0), x.get("RVOL", 0)), reverse=True)
                item = top_grade[0]
                
                stock_clean = item["Stock"].replace(".NS", "")
                _ltp = float(item["LTP"])
                _is_long = item["Signal"] in ("LONG", "BREAKOUT")
                
                def calculate_atm_strike_local(price: float) -> int:
                    if price > 5000:
                        interval = 100
                    elif price > 2000:
                        interval = 50
                    elif price > 800:
                        interval = 20
                    elif price > 300:
                        interval = 10
                    else:
                        interval = 5
                    return int(round(price / interval) * interval)
                    
                _strike = calculate_atm_strike_local(_ltp)
                _option_type = "CE" if _is_long else "PE"
                contract_name = f"{stock_clean} {_strike} {_option_type}"
                
                lot_size = FO_LOT_SIZES.get(stock_clean, 100)
                est_premium = _ltp * 0.03
                
                option_pick = {
                    "Stock": stock_clean,
                    "Signal": item["Signal"],
                    "LTP": _ltp,
                    "Change %": float(item["Change %"]),
                    "Contract": contract_name,
                    "Entry_Price": round(est_premium, 2),
                    "Stop_Loss": round(est_premium * 0.65, 2),
                    "Target": round(est_premium * 1.50, 2),
                    "Lots": 1,
                    "Lot_Size": lot_size,
                    "Confidence": item.get("Confidence", 50),
                    "Quality": item.get("Quality", "B"),
                    "Suggested_At": datetime.now(Trading_WS._IST_TZ).strftime("%I:%M:%S %p") if _ms2["is_open"] else "EOD (03:30 PM)"
                }
                
                st.session_state.locked_option_pick = option_pick.copy()
                if st.session_state.locked_at_time == 0.0:
                    st.session_state.locked_at_time = time.time()

    # 3. NIFTY INDEX CALL
    nifty_pick = None
    if st.session_state.locked_nifty_option_pick:
        nifty_pick = st.session_state.locked_nifty_option_pick.copy()
        # Update index price
        nifty_tile = Trading_WS.get_index_tile_quote("NIDX:40000001", _idx_d)
        nifty_ltp = nifty_tile.get("ltp") or nifty_tile.get("last_price") or nifty_tile.get("close")
        if nifty_ltp:
            nifty_pick["Nifty_LTP"] = float(nifty_ltp)
        st.session_state.locked_nifty_option_pick = nifty_pick.copy()
    else:
        nifty_tile = Trading_WS.get_index_tile_quote("NIDX:40000001", _idx_d)
        nifty_ltp = nifty_tile.get("ltp") or nifty_tile.get("last_price") or nifty_tile.get("close")
        
        ws_nifty = st.session_state.get("_idx_ws_candles_NIDX:40000001", [])
        rest_nifty = st.session_state.get("_idx_rest_candles_NIDX:40000001", [])
        if ws_nifty and rest_nifty:
            ws_start = ws_nifty[0][0]
            base_nifty = [c for c in rest_nifty if c[0] < ws_start]
            nifty_candles = base_nifty + ws_nifty
        elif ws_nifty:
            nifty_candles = ws_nifty
        else:
            nifty_candles = rest_nifty
            
        if nifty_ltp is None and nifty_candles:
            nifty_ltp = float(nifty_candles[-1][4])
            
        if nifty_ltp is not None:
            nifty_ltp = float(nifty_ltp)
            nifty_pick_raw = Trading_WS.generate_nifty_option_chain_and_signal(nifty_ltp, nifty_candles)
            if nifty_pick_raw:
                nifty_pick = {
                    "Contract": nifty_pick_raw["contract"],
                    "Signal": nifty_pick_raw["signal"],
                    "Entry_Price": nifty_pick_raw["entry_price"],
                    "Target": nifty_pick_raw["target"],
                    "Stop_Loss": nifty_pick_raw["stop_loss"],
                    "Nifty_LTP": nifty_ltp,
                    "PCR": nifty_pick_raw["pcr"],
                    "Support": nifty_pick_raw["support"],
                    "Resistance": nifty_pick_raw["resistance"],
                    "Suggested_At": datetime.now(Trading_WS._IST_TZ).strftime("%I:%M:%S %p") if _ms2["is_open"] else "EOD (03:30 PM)"
                }
                st.session_state.locked_nifty_option_pick = nifty_pick.copy()
                if st.session_state.locked_at_time == 0.0:
                    st.session_state.locked_at_time = time.time()

    # 4. SWING PICK
    swing_pick = None
    if st.session_state.locked_swing_pick:
        swing_pick = st.session_state.locked_swing_pick.copy()
        # Update Swing LTP
        sym = swing_pick["Stock"]
        tok = name_to_token.get(sym)
        if tok and tok in _mkt:
            live_q = Trading_WS.parse_quote(_mkt[tok])
            if live_q["close"] > 0:
                swing_pick["LTP"] = live_q["close"]
                open_p = live_q.get("open", 0)
                if open_p > 0:
                    swing_pick["Change %"] = round(((live_q["close"] - open_p) / open_p) * 100, 2)
        st.session_state.locked_swing_pick = swing_pick.copy()
    else:
        access_token = getattr(st.session_state, "accepted_token", None) or Trading_WS.load_cached_token()
        candidates = []
        if access_token:
            try:
                candidates = scan_for_swing_picks(access_token)
            except Exception as e:
                print(f"Error running swing picks scan: {e}")
                
        if candidates:
            # Filter candidates for RSI < 70 to avoid buying at overbought peaks (custom swing momentum overlay)
            reasonable = [c for c in candidates if c["Mntm"] < 70]
            if not reasonable:
                reasonable = candidates
                
            # Sort by raw score (out of 14) descending, then by +DI descending
            reasonable = sorted(reasonable, key=lambda x: (x["score_raw"], x["plus_di"]), reverse=True)
            top_cand = reasonable[0]
            
            swing_pick = {
                "Stock": top_cand["Stock"],
                "Company": top_cand["Company"],
                "Total": top_cand["Total"],
                "Funda": top_cand["Funda"],
                "Mntm": top_cand["Mntm"],
                "LTP": top_cand["LTP"],
                "Suggested_At": datetime.now(Trading_WS._IST_TZ).strftime("%I:%M:%S %p") if _ms2["is_open"] else "EOD (03:30 PM)"
            }
        else:
            # Fallback if no token/API failure to avoid empty state
            fallback_sym = "CHOLAFIN"
            if wl_signals:
                fallback_sym = wl_signals[0]["Stock"].replace(".NS", "")
                
            db_meta = Trading_WS.load_db_metadata()
            company_name = db_meta.get(fallback_sym, {}).get("company_name", fallback_sym)
            ltp_val = 1566.30
            if wl_signals:
                ltp_val = float(wl_signals[0]["LTP"])
                
            swing_pick = {
                "Stock": fallback_sym,
                "Company": f"{company_name} (Connect Token for Live Scan)",
                "Total": 85,
                "Funda": 90,
                "Mntm": 58,
                "LTP": ltp_val,
                "Suggested_At": "EOD (03:30 PM)"
            }
            
        _init_ltp = swing_pick["LTP"]
        swing_pick["Entry_Price"] = _init_ltp
        swing_pick["Stop_Loss"] = round(_init_ltp * 0.95, 2)
        swing_pick["Target"] = round(_init_ltp * 1.12, 2)
        
        st.session_state.locked_swing_pick = swing_pick.copy()
        if st.session_state.locked_at_time == 0.0:
            st.session_state.locked_at_time = time.time()

    remaining_secs = 0
    if st.session_state.locked_at_time > 0:
        elapsed = time.time() - st.session_state.locked_at_time
        remaining_secs = max(0, int(900 - elapsed))

    return {
        "intraday": intraday_pick,
        "option": option_pick,
        "nifty_option": nifty_pick,
        "swing": swing_pick,
        "remaining_seconds": remaining_secs,
        "locked": st.session_state.locked_at_time > 0
    }

@app.post("/api/alpha-picks/unlock")
def unlock_alpha_picks():
    """Manually resets the 15-minute selection locks."""
    import streamlit as st
    st.session_state.locked_intraday_pick = None
    st.session_state.locked_option_pick = None
    st.session_state.locked_nifty_option_pick = None
    st.session_state.locked_swing_pick = None
    st.session_state.locked_at_time = 0.0
    return {"status": "Success", "message": "Alpha picks unlocked successfully."}

@app.get("/api/indices")
def get_indices_data():
    """Returns the latest quotes for NIFTY 50 and BANK NIFTY indices."""
    _fs = Trading_WS.feed_state
    with _fs.lock:
        index_snapshot = dict(_fs.index_data)
        
    nifty = Trading_WS.get_index_tile_quote("NIDX:40000001", index_snapshot)
    banknifty = Trading_WS.get_index_tile_quote("NIDX:40000003", index_snapshot)
        
    return {
        "NIFTY_50": nifty,
        "BANK_NIFTY": banknifty
    }

@app.get("/api/stock/{symbol}")
def get_stock_details(symbol: str, sr_pivot_type: str = "None"):
    """Returns technical details and pivots for a specific stock."""
    import streamlit as st
    symbol = symbol.upper().strip()
    
    # Find token
    stock_token = None
    for token, name in Trading_WS.effective_universe().items():
        if name == symbol or name.replace(".NS", "") == symbol:
            stock_token = token
            break
            
    if not stock_token:
        raise HTTPException(status_code=404, detail=f"Stock symbol {symbol} not found in watchlist universe.")
        
    # Get historical data
    hist = st.session_state.historical_data.get(stock_token)
    if not hist:
        raise HTTPException(status_code=400, detail=f"Historical data not loaded yet for {symbol}.")
        
    # Get live quote if available
    _fs = Trading_WS.feed_state
    live_quote = {}
    with _fs.lock:
        if stock_token in _fs.market_data:
            live_quote = Trading_WS.parse_quote(_fs.market_data[stock_token])
            
    # Calculate pivots dynamically based on the requested sr_pivot_type
    p_high = hist.get("prev_day_high", 0.0)
    p_low = hist.get("prev_day_low", 0.0)
    p_close = hist.get("prev_day_close", 0.0)
    
    pivots_dict = Trading_WS.calculate_pivots(p_high, p_low, p_close, sr_pivot_type)
    
    r1 = pivots_dict.get("R1", 0.0)
    r2 = pivots_dict.get("R2", 0.0)
    r3 = pivots_dict.get("R3", 0.0)
    
    s1 = pivots_dict.get("S1", 0.0)
    s2 = pivots_dict.get("S2", 0.0)
    s3 = pivots_dict.get("S3", 0.0)
    
    return {
        "symbol": symbol,
        "token": stock_token,
        "historical_metrics": hist,
        "live_quote": live_quote,
        "pivots": {
            "type": sr_pivot_type,
            "resistances": [r1, r2, r3],
            "supports": [s1, s2, s3]
        }
    }

@app.get("/api/market-regime")
def get_market_regime():
    """Returns the market edge index, money flow list, and regime indicators."""
    import streamlit as st
    bms = Trading_WS.calculate_broad_market_status()
    regime = Trading_WS.calculate_market_regime()
    edge = Trading_WS.calculate_edge_index()
    
    # Calculate sector-level money flow as expected by the mobile frontend App.js
    meta = Trading_WS.load_db_metadata()
    sector_data = {}
    
    # Get live snapshot to compute live changes if feed is active
    _fs = Trading_WS.feed_state
    _mkt, _, _ = Trading_WS.snapshot_feed(_fs)
    
    with _fs.lock:
        market_data = dict(_fs.market_data)
        
    eu = Trading_WS.effective_universe()
    
    for instrument, hist in st.session_state.historical_data.items():
        stock_name = eu.get(instrument) or Trading_WS.STOCK_NAMES.get(instrument) or instrument
        symbol_clean = stock_name.replace(".NS", "")
        sector = meta.get(symbol_clean, {}).get("sector", "Other")
        
        # Day change percentage
        day_chg = hist.get("day_change_pct", 0.0)
        
        # Get live quote if available
        quote = market_data.get(instrument)
        if quote:
            parsed = Trading_WS.parse_quote(quote)
            open_p = parsed.get("open", 0.0)
            close_p = parsed.get("close", 0.0)
            if open_p > 0:
                day_chg = ((close_p - open_p) / open_p) * 100
        
        # Estimate money flow in Cr (crores) based on Relative Volume (RVOL) and price
        rvol = hist.get("rvol", 1.0)
        ltp = close_p if (quote and close_p > 0) else hist.get("day_open", 100.0)
        
        # Traded value estimate scaling for realistic Cr representation
        estimated_turnover = (ltp * rvol * 0.12)
        
        if sector not in sector_data:
            sector_data[sector] = {
                "Sector": sector,
                "StocksCount": 0,
                "TotalChange": 0.0,
                "TotalMoneyFlow": 0.0
            }
            
        sector_data[sector]["StocksCount"] += 1
        sector_data[sector]["TotalChange"] += day_chg
        sector_data[sector]["TotalMoneyFlow"] += estimated_turnover * (1 if day_chg >= 0 else -0.8)

    # Format into a sorted list of sector dicts
    money_flow_list = []
    for sector, s_info in sector_data.items():
        count = s_info["StocksCount"]
        avg_chg = s_info["TotalChange"] / count if count > 0 else 0.0
        money_flow_list.append({
            "Sector": sector,
            "StocksCount": count,
            "MoneyFlow": round(s_info["TotalMoneyFlow"], 1),
            "DayChange": round(avg_chg, 2)
        })
        
    money_flow_list = sorted(money_flow_list, key=lambda x: x["DayChange"], reverse=True)

    return {
        "broad_market": bms,
        "regime": regime,
        "edge_index": edge,
        "money_flow": money_flow_list
    }

@app.post("/api/paper-trade")
def log_paper_trade_api(trade: PaperTradeCreate):
    """Exposes paper trading logging directly to the mobile application."""
    symbol_upper = trade.symbol.upper().strip()
    
    # Map short names from mobile client to DB segments
    segment_mapping = {
        "Futures": "F&O - Index Futures",
        "Options": "F&O - Index Options",
    }
    mapped_segment = segment_mapping.get(trade.segment, trade.segment)

    # Verify segment rates exist
    brokerage_rates = get_brokerage_rates()
    if mapped_segment not in brokerage_rates:
        raise HTTPException(status_code=400, detail=f"Invalid segment name: {trade.segment}")
        
    # Enforce zero brokerage for Equity - Delivery
    computed_brokerage = 0.0
    if mapped_segment != "Equity - Delivery":
        # Calculate standard 1-lot default brokerage or simple flat rates
        buy_rate = brokerage_rates[mapped_segment]["buy"]
        sell_rate = brokerage_rates[mapped_segment]["sell"]
        computed_brokerage = buy_rate + sell_rate
        
    # Calculate transaction metrics using database helper
    metrics = calculate_trade_metrics(
        segment=mapped_segment,
        action=trade.action,
        quantity=trade.quantity,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        brokerage_input=computed_brokerage
    )
    
    paper_trade_data = {
        "trade_date": date.today().strftime("%Y-%m-%d"),
        "symbol": symbol_upper,
        "segment": mapped_segment,
        "action": trade.action,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "brokerage": metrics["brokerage"],
        "stt": metrics["stt"],
        "exchange_charges": metrics["exchange_charges"],
        "sebi_charges": metrics["sebi_charges"],
        "stamp_duty": metrics["stamp_duty"],
        "gst": metrics["gst"],
        "total_charges": metrics["total_charges"],
        "gross_pnl": metrics["gross_pnl"],
        "net_pnl": metrics["net_pnl"],
        "source_screener": trade.source_screener,
        "notes": trade.notes
    }
    
    trade_id = add_paper_trade(paper_trade_data)
    return {
        "status": "Success",
        "trade_id": trade_id,
        "metrics": metrics,
        "message": f"Paper trade for {symbol_upper} successfully logged."
    }

if __name__ == "__main__":
    import uvicorn
    # Start on port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
