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

@app.get("/api/indices")
def get_indices_data():
    """Returns the latest quotes for NIFTY 50 and BANK NIFTY indices."""
    _fs = Trading_WS.feed_state
    with _fs.lock:
        nifty = dict(_fs.index_data.get("NIDX:40000001", {}))
        banknifty = dict(_fs.index_data.get("NIDX:40000003", {}))
        
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
            
    # Compute stops and targets
    ltp = live_quote.get("close", hist.get("day_open", 0.0))
    r1, r2, r3 = hist.get("r1", 0.0), hist.get("r2", 0.0), hist.get("r3", 0.0)
    s1, s2, s3 = hist.get("s1", 0.0), hist.get("s2", 0.0), hist.get("s3", 0.0)
    
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
    """Returns the market edge index, money flow, and regime indicators."""
    bms = Trading_WS.calculate_broad_market_status()
    regime = Trading_WS.calculate_market_regime()
    edge = Trading_WS.calculate_edge_index()
    money_flow = Trading_WS.calculate_money_flow_universe()
    
    return {
        "broad_market": bms,
        "regime": regime,
        "edge_index": edge,
        "money_flow": money_flow
    }

@app.post("/api/paper-trade")
def log_paper_trade_api(trade: PaperTradeCreate):
    """Exposes paper trading logging directly to the mobile application."""
    symbol_upper = trade.symbol.upper().strip()
    
    # Verify segment rates exist
    brokerage_rates = get_brokerage_rates()
    if trade.segment not in brokerage_rates:
        raise HTTPException(status_code=400, detail=f"Invalid segment name: {trade.segment}")
        
    # Enforce zero brokerage for Equity - Delivery
    computed_brokerage = 0.0
    if trade.segment != "Equity - Delivery":
        # Calculate standard 1-lot default brokerage or simple flat rates
        buy_rate = brokerage_rates[trade.segment]["buy"]
        sell_rate = brokerage_rates[trade.segment]["sell"]
        computed_brokerage = buy_rate + sell_rate
        
    # Calculate transaction metrics using database helper
    metrics = calculate_trade_metrics(
        segment=trade.segment,
        action=trade.action,
        quantity=trade.quantity,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        brokerage_input=computed_brokerage
    )
    
    paper_trade_data = {
        "trade_date": date.today().strftime("%Y-%m-%d"),
        "symbol": symbol_upper,
        "segment": trade.segment,
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
