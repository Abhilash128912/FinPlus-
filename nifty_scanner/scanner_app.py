import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
import yfinance as yf

# Import modular scanner components
from scanner_database import init_scanner_db, fetch_cached_stocks_df, clear_scanner_cache
from scanner_data_pipeline import run_nifty500_scanner_pipeline, compute_atr
from nifty_tickers import get_fno_symbols

@st.cache_data(ttl=600)
def fetch_live_stock_news(symbol: str) -> list:
    """
    Fetches latest news headlines via yfinance.
    Tries get_news() (newer API) then falls back to .news property.
    Parses both legacy dict format and nested-content format.
    Returns up to 5 items: [{title, publisher, link}].
    """
    if not symbol:
        return []

    ticker_symbol = symbol.strip().upper()
    if not ticker_symbol:
        return []

    # Append .NS for Indian stocks if not present
    if not ticker_symbol.endswith(".NS") and not ticker_symbol.endswith(".BO") and len(ticker_symbol) <= 10:
        index_keywords = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
        is_index = any(k in ticker_symbol for k in index_keywords)
        commodity_keywords = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "NATGASMINI", "NATGAS"]
        is_commodity = any(k in ticker_symbol for k in commodity_keywords)
        if not is_index and not is_commodity:
            ticker_symbol = f"{ticker_symbol}.NS"

    raw_news = []
    try:
        ticker = yf.Ticker(ticker_symbol)
        # Try newer API first (yfinance >= 0.2.37)
        try:
            raw_news = ticker.get_news() or []
        except Exception:
            pass
        # Fall back to property accessor
        if not raw_news:
            try:
                raw_news = ticker.news or []
            except Exception:
                pass
    except Exception:
        return []

    parsed_news = []
    for item in raw_news[:5]:  # Up to 5 headlines
        title = publisher = link = ""
        try:
            # Format A: {"content": {"title": ..., "provider": ..., "canonicalUrl": ...}}
            if isinstance(item, dict) and "content" in item:
                c = item["content"]
                title     = c.get("title", "") or ""
                publisher = (c.get("provider") or {}).get("displayName", "") or ""
                link      = (c.get("canonicalUrl") or {}).get("url", "") or ""
                if not link:
                    link  = (c.get("clickThroughUrl") or {}).get("url", "") or ""
            # Format B: flat dict {"title": ..., "publisher": ..., "link": ...}
            elif isinstance(item, dict):
                title     = item.get("title", "") or ""
                publisher = item.get("publisher", "") or ""
                link      = item.get("link", "") or item.get("url", "") or ""
        except Exception:
            continue
        if title:
            parsed_news.append({"title": title, "publisher": publisher, "link": link})

    return parsed_news

def get_news_sentiment(title: str) -> str:
    """
    Keyword-based sentiment classifier for a news headline.
    Returns 'positive', 'negative', or 'neutral'.
    """
    t = title.lower()
    positive_words = [
        "surge", "rally", "soar", "jump", "gain", "rise", "up", "bull", "bullish",
        "growth", "profit", "beat", "beats", "record", "high", "upgrade", "buy",
        "strong", "outperform", "positive", "recovery", "boom", "expand",
        "dividend", "buyback", "approved", "win", "award", "milestone"
    ]
    negative_words = [
        "fall", "drop", "crash", "plunge", "slump", "decline", "loss", "down",
        "bear", "bearish", "weak", "miss", "misses", "cut", "downgrade", "sell",
        "concern", "risk", "warning", "probe", "fraud", "penalty", "fine",
        "layoff", "recall", "default", "debt", "lawsuit", "investigation",
        "tumble", "sink", "disappoint", "lower", "below"
    ]
    pos = sum(1 for w in positive_words if w in t)
    neg = sum(1 for w in negative_words if w in t)
    if pos > neg:
        return "positive"
    elif neg > pos:
        return "negative"
    return "neutral"

def generate_modeled_option_chain(last_price: float, rsi: float, ticker: str):
    """
    Simulates a highly realistic derivatives option chain matching real-time market boundaries,
    open interest spikes, bid/ask spreads, and Put-Call Ratio (PCR) metrics.
    """
    if last_price < 100: interval = 2.5
    elif last_price < 250: interval = 5.0
    elif last_price < 500: interval = 10.0
    elif last_price < 1000: interval = 20.0
    elif last_price < 3000: interval = 50.0
    else: interval = 100.0
    
    # Calculate ATM Strike (nearest multiple of interval)
    atm_strike = round(last_price / interval) * interval
    
    # Expose 5 strikes above and 5 below
    strikes = [atm_strike + (i * interval) for i in range(-5, 6)]
    
    import random
    # Stable random seeding per ticker
    random.seed(hash(ticker) % 10000)
    
    records = []
    total_call_oi = 0
    total_put_oi = 0
    
    max_call_oi = 0
    max_call_strike = atm_strike
    max_put_oi = 0
    max_put_strike = atm_strike
    
    for strike in strikes:
        # Distance ratio from price
        dist = (strike - last_price) / last_price
        
        # Black-Scholes approximations
        call_price = max(0.5, last_price * 0.04 * (1 - dist * 4) + random.uniform(-0.5, 0.5))
        put_price = max(0.5, last_price * 0.04 * (1 + dist * 4) + random.uniform(-0.5, 0.5))
        
        # Base Open Interest clustering
        call_oi = int(max(100, 5000 * (1 - abs(dist - 0.05) * 5) + random.randint(-500, 500)))
        put_oi = int(max(100, 5000 * (1 - abs(dist + 0.05) * 5) + random.randint(-500, 500)))
        
        # RSI directional writing bias
        if rsi > 60:
            put_oi = int(put_oi * 1.35)
            call_oi = int(call_oi * 0.8)
        elif rsi < 40:
            call_oi = int(call_oi * 1.35)
            put_oi = int(put_oi * 0.8)
            
        total_call_oi += call_oi
        total_put_oi += put_oi
        
        if call_oi > max_call_oi:
            max_call_oi = call_oi
            max_call_strike = strike
        if put_oi > max_put_oi:
            max_put_oi = put_oi
            max_put_strike = strike
            
        records.append({
            "strike": strike,
            "call_price": round(call_price, 2),
            "call_oi": call_oi,
            "put_price": round(put_price, 2),
            "put_oi": put_oi
        })
        
    pcr = total_put_oi / total_call_oi if total_call_oi > 0 else 1.0
    
    return {
        "chain": records,
        "pcr": pcr,
        "max_call_strike": max_call_strike,
        "max_put_strike": max_put_strike
    }

# 1. Page Configurations
st.set_page_config(
    page_title="Fin+ // Nifty 500 Techno-Fundamental Scanner",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)



variables_css = """
:root {
    --bg-primary: #FFFFFF;
    --bg-secondary: #F0FDF4; /* Eye-care Soft Emerald bg */
    --card-bg: #FFFFFF;
    --border-color: #DCFCE7;
    --text-primary: #064E3B;
    --text-secondary: #166534;
    --accent-green: #10B981;
    --accent-red: #EF4444;
    --accent-blue: #059669;
    --accent-purple: #047857;
}
"""

# 2. Custom CSS Styles Injection (Harmonized Premium Light Terminal Skin)
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');
    
    {variables_css}
    
    .stApp {{
        background-color: var(--bg-secondary) !important;
        color: var(--text-primary) !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }}
    
    h1, h2, h3, h4, h5, h6 {{
        font-family: 'Outfit', sans-serif !important;
        font-weight: 700 !important;
        color: var(--text-primary) !important;
        letter-spacing: -0.02em !important;
    }}
    
    .scanner-header {{
        background: linear-gradient(135deg, #0F172A 30%, #2563EB 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
    }}
    
    .glass-card {{
        background: var(--card-bg);
        border-left: 1px solid var(--border-color);
        border-right: 1px solid var(--border-color);
        border-top: 1px solid var(--border-color);
        border-bottom: 5px solid #CBD5E1; /* Beveled bottom border for 3D extrusion */
        border-radius: 18px;
        padding: 24px;
        margin-bottom: 22px;
        box-shadow: 0 10px 18px -4px rgba(0, 0, 0, 0.04), 0 4px 6px -2px rgba(0, 0, 0, 0.02), inset 0 2px 4px rgba(255, 255, 255, 0.9);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        transform: translateY(0);
    }}
    
    .glass-card:hover {{
        border-color: #A7F3D0; /* Light emerald border highlight */
        border-bottom-color: #10B981; /* Green 3D base on hover */
        box-shadow: 0 20px 30px -8px rgba(16, 185, 129, 0.12), 0 8px 12px -4px rgba(0, 0, 0, 0.03);
        transform: translateY(-6px); /* Dynamic 3D Lift */
    }}
    
    div[data-testid="metric-container"] {{
        background: var(--card-bg) !important;
        border-left: 1px solid var(--border-color) !important;
        border-right: 1px solid var(--border-color) !important;
        border-top: 1px solid var(--border-color) !important;
        border-bottom: 4px solid #CBD5E1 !important; /* Raised bottom border */
        border-radius: 14px !important;
        padding: 18px 22px !important;
        box-shadow: 0 6px 12px -3px rgba(0, 0, 0, 0.03) !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        transform: translateY(0);
    }}
    
    div[data-testid="metric-container"]:hover {{
        border-color: #A7F3D0 !important;
        border-bottom-color: #10B981 !important;
        box-shadow: 0 14px 22px -6px rgba(16, 185, 129, 0.15) !important;
        transform: translateY(-4px) !important; /* Gentle 3D Lift */
    }}
    
    div[data-testid="stMetricValue"] {{
        font-family: 'Outfit', sans-serif !important;
        font-weight: 700 !important;
        color: var(--text-primary) !important;
    }}
    
    div[data-testid="stTabBar"] {{
        background: #F1F5F9 !important;
        border-radius: 12px !important;
        padding: 4px !important;
        margin-bottom: 24px !important;
        border: 1px solid var(--border-color) !important;
    }}
    
    button[data-testid="stTabBarTab"] {{
        font-family: 'Outfit', sans-serif !important;
        font-weight: 500 !important;
        color: var(--text-secondary) !important;
        border-radius: 8px !important;
        transition: all 0.2s ease !important;
    }}
    
    button[data-testid="stTabBarTab"][aria-selected="true"] {{
        background: #FFFFFF !important;
        color: var(--text-primary) !important;
        font-weight: 600 !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05) !important;
    }}
    
    div.stButton > button {{
        background: linear-gradient(to bottom, #FFFFFF, #F8FAFC) !important;
        color: var(--text-primary) !important;
        border-left: 1px solid var(--border-color) !important;
        border-right: 1px solid var(--border-color) !important;
        border-top: 1px solid var(--border-color) !important;
        border-bottom: 4.5px solid #CBD5E1 !important; /* Thick bottom border for realistic 3D feel */
        border-radius: 12px !important;
        font-family: 'Outfit', sans-serif !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        padding: 10px 24px !important;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.04) !important;
        transition: all 0.15s ease !important;
        transform: translateY(0);
    }}
    
    div.stButton > button:hover {{
        background: linear-gradient(to bottom, #10B981, #059669) !important; /* Dynamic Emerald Gradient */
        color: #FFFFFF !important;
        border-color: #059669 !important;
        border-bottom-color: #047857 !important;
        box-shadow: 0 6px 16px rgba(16, 185, 129, 0.35) !important;
        transform: translateY(-2px) !important; /* Elevate slightly on hover */
    }}
    
    div.stButton > button:active {{
        border-bottom-width: 1px !important; /* Flatten bottom border when pressed */
        transform: translateY(3.5px) !important; /* Dynamic 3D Press Down Effect! */
        box-shadow: 0 1px 3px rgba(16, 185, 129, 0.2) !important;
    }}
    
    /* Highlight score badges */
    .score-badge {{
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.9rem;
        display: inline-block;
    }}
    .score-badge.high {{
        background: #ECFDF5;
        color: var(--accent-green);
        border: 1px solid #A7F3D0;
    }}
    .score-badge.medium {{
        background: #FFFBEB;
        color: #D97706;
        border: 1px solid #FDE68A;
    }}
    .score-badge.low {{
        background: #FEF2F2;
        color: var(--accent-red);
        border: 1px solid #FCA5A5;
    }}
    
    /* Top Stock Cards styling */
    .top-stock-card {{
        background: linear-gradient(135deg, #FFFFFF 0%, #F8FAFC 100%);
        border: 1px solid #E2E8F0;
        border-bottom: 5px solid #CBD5E1;
        border-radius: 16px;
        padding: 16px;
        margin-bottom: 12px;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }}
    .top-stock-card:hover {{
        transform: translateY(-6px);
        border-color: #A7F3D0;
        border-bottom-color: #10B981;
        box-shadow: 0 15px 25px -5px rgba(16, 185, 129, 0.12), 0 8px 12px -4px rgba(0, 0, 0, 0.03);
    }}
    .top-stock-card .rank-badge {{
        position: absolute;
        top: 10px;
        right: 10px;
        color: #FFFFFF;
        font-family: 'Outfit', sans-serif;
        font-weight: 800;
        font-size: 0.8rem;
        padding: 2px 8px;
        border-radius: 20px;
    }}
    .top-stock-card .ticker-name {{
        font-family: 'Outfit', sans-serif;
        font-size: 1.35rem;
        font-weight: 800;
        color: #064E3B;
        margin-top: 4px;
        margin-bottom: 0px;
        line-height: 1.2;
    }}
    .top-stock-card .company-name {{
        font-size: 0.78rem;
        color: #64748B;
        margin-bottom: 12px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        font-weight: 500;
    }}
    .top-stock-card .score-wrap {{
        display: flex;
        align-items: baseline;
        margin-bottom: 10px;
    }}
    .top-stock-card .total-score {{
        font-family: 'Outfit', sans-serif;
        font-size: 1.8rem;
        font-weight: 900;
        color: #059669;
        line-height: 1;
    }}
    .top-stock-card .score-max {{
        font-size: 0.85rem;
        color: #64748B;
        font-weight: 500;
        margin-left: 1px;
    }}
    .top-stock-card .sub-scores {{
        font-size: 0.78rem;
        color: #475569;
        background: #F1F5F9;
        padding: 6px 10px;
        border-radius: 8px;
        margin-bottom: 10px;
        font-weight: 600;
        text-align: center;
        border: 1px solid #E2E8F0;
    }}
    .top-stock-card .price-row {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.82rem;
        font-weight: 700;
        color: #0F172A;
    }}
    .top-stock-card .sector-badge {{
        font-size: 0.72rem;
        background: #E0F2FE;
        color: #0369A1;
        padding: 2px 6px;
        border-radius: 4px;
        max-width: 90px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }}
    </style>
    """,
    unsafe_allow_html=True
)

# App Header
st.markdown('<h1 class="scanner-header">Fin+ // NIFTY 500 SCANNER</h1>', unsafe_allow_html=True)
st.markdown('<p style="color: var(--text-secondary); margin-top:-15px; margin-bottom: 25px;">Institutional Quantamental Screening • Fundamental Quality & Technical Momentum Scoring</p>', unsafe_allow_html=True)

# 3. Fetch Dataset
df_stocks = fetch_cached_stocks_df()

# Handle empty database welcome screen
if df_stocks.empty:
    st.markdown(
        """
        <div class="glass-card" style="text-align: center; padding: 60px 40px; margin-top: 20px;">
            <h2 style="color: var(--accent-blue); margin-bottom: 15px;">Welcome to Nifty 500 Quantamental Screener</h2>
            <p style="color: var(--text-secondary); max-width: 650px; margin: 0 auto 30px auto; font-size: 1.05rem; line-height: 1.6;">
                The local cache database is currently empty. Run the initial data pipeline scan to fetch market statistics, financial balance sheets, and momentum indicators for all Nifty 500 stocks. 
                <br><br>
                <em>Notice: The first download parses historical financial sheets for 500 stocks and takes about 4-6 minutes. Subsequent loads are instantaneous (<1s).</em>
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    c_btn1, c_btn2, c_btn3 = st.columns([1, 2, 1])
    with c_btn2:
        if st.button("⚡ Run Initial Nifty 500 Data Pipeline Scan", use_container_width=True):
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            def progress_update(current, total, ticker):
                pct = int((current / total) * 100)
                progress_bar.progress(pct)
                status_text.markdown(f"Fetching Ticker **{current}/{total}** // `{ticker}`... Please wait.")
                
            success_count = run_nifty500_scanner_pipeline(progress_callback=progress_update)
            st.success(f"Audit completed! Successfully analyzed and scored {success_count} Nifty 500 tickers out of 100.")
            st.rerun()
            
    st.stop()  # Halt execution until database is initialized

# Get global parameters
total_scored_stocks = len(df_stocks)
last_refresh_date = df_stocks["last_updated"].iloc[0] if "last_updated" in df_stocks.columns else "Unknown"

# 3.8 Automatic Background Sync Scheduler Engine
import threading
from datetime import datetime, timedelta

# Initialize auto-refresh interval in session state
if "auto_refresh_interval" not in st.session_state:
    st.session_state["auto_refresh_interval"] = "30 Minutes"

is_sync_running = any(t.name == "NiftyScannerBgSync" for t in threading.enumerate())

if st.session_state["auto_refresh_interval"] != "Manual Only" and last_refresh_date != "Unknown":
    interval_mapping = {
        "30 Minutes": 30,
        "1 Hour": 60,
        "2 Hours": 120
    }
    minutes_limit = interval_mapping.get(st.session_state["auto_refresh_interval"], 30)
    
    try:
        last_dt = datetime.strptime(last_refresh_date, "%Y-%m-%d %H:%M")
        elapsed = datetime.now() - last_dt
        if elapsed > timedelta(minutes=minutes_limit) and not is_sync_running:
            bg_thread = threading.Thread(
                target=run_nifty500_scanner_pipeline,
                args=(None,),
                name="NiftyScannerBgSync",
                daemon=True
            )
            bg_thread.start()
            is_sync_running = True
    except Exception:
        pass

# 3.5 Global Sidebar Stock Focus Selector & Callbacks
ticker_options = sorted(list(df_stocks["ticker"].unique()))

# Callback functions for centralized stock focus management
def update_focus_from_sidebar():
    if "sidebar_active_stock_focus_dropdown" in st.session_state:
        st.session_state["global_focus_ticker"] = st.session_state["sidebar_active_stock_focus_dropdown"]

def update_focus_from_sidebar_search():
    if "sidebar_search_focus" in st.session_state:
        val = st.session_state["sidebar_search_focus"].replace(" ", "").upper().strip()
        if val:
            matching = [t for t in ticker_options if t.startswith(val) or t == f"{val}.NS"]
            if matching:
                st.session_state["global_focus_ticker"] = matching[0]

def update_focus_from_tab1():
    if "tab1_select_focus" in st.session_state:
        st.session_state["global_focus_ticker"] = st.session_state["tab1_select_focus"]

def update_focus_from_tab1_search():
    if "tab1_search_focus" in st.session_state:
        val = st.session_state["tab1_search_focus"].replace(" ", "").upper().strip()
        if val:
            matching = [t for t in ticker_options if t.startswith(val) or t == f"{val}.NS"]
            if matching:
                st.session_state["global_focus_ticker"] = matching[0]
            else:
                st.session_state["global_focus_ticker"] = val

def update_focus_from_tab2():
    if "screener_quick_focus_selectbox_widget" in st.session_state:
        st.session_state["global_focus_ticker"] = st.session_state["screener_quick_focus_selectbox_widget"]

def update_focus_from_tab5():
    """Updates ONLY the F&O tab's local focus — does NOT touch global_focus_ticker."""
    if "tab_fno_active_ticker_selector" in st.session_state:
        st.session_state["fno_tab_focus_ticker"] = st.session_state["tab_fno_active_ticker_selector"]

# Check for deep-linked stock focus from URL parameters on startup
url_focus = st.query_params.get("focus_ticker", "").strip().upper()
if url_focus:
    if url_focus in ticker_options:
        st.session_state["global_focus_ticker"] = url_focus
    elif f"{url_focus}.NS" in ticker_options:
        st.session_state["global_focus_ticker"] = f"{url_focus}.NS"

if "global_focus_ticker" not in st.session_state or not st.session_state["global_focus_ticker"]:
    if ticker_options:
        default_ticker = "RELIANCE.NS" if "RELIANCE.NS" in ticker_options else ticker_options[0]
        st.session_state["global_focus_ticker"] = default_ticker
    else:
        st.session_state["global_focus_ticker"] = ""

# Synchronize widget session state keys safely on every run
current_focus = st.session_state["global_focus_ticker"]
if current_focus and current_focus in ticker_options:
    st.session_state["sidebar_active_stock_focus_dropdown"] = current_focus
    st.session_state["tab1_select_focus"] = current_focus
else:
    st.session_state["sidebar_active_stock_focus_dropdown"] = None
    st.session_state["tab1_select_focus"] = None

st.sidebar.markdown('<h3 style="margin-top:0; color: var(--text-primary);">🎯 Stock Focus</h3>', unsafe_allow_html=True)

if is_sync_running:
    st.sidebar.info("🔄 Background update in progress... You can keep browsing normally.")
elif last_refresh_date != "Unknown" and st.session_state["auto_refresh_interval"] != "Manual Only":
    st.sidebar.caption(f"🟢 Auto-Sync Enabled ({st.session_state['auto_refresh_interval']})")

st.sidebar.markdown("<p style='font-size:0.82rem; color: var(--text-secondary); margin-top:5px; margin-bottom: 15px;'>Select a stock here or click on any row in the Screener table to sync Candlestick (Tab 3) & P/E Bands (Tab 4).</p>", unsafe_allow_html=True)

# Direct Text Search Focus Box
st.sidebar.text_input(
    "🔍 Quick Search Ticker", 
    placeholder="e.g. INFY.NS or BSE", 
    key="sidebar_search_focus",
    on_change=update_focus_from_sidebar_search
)

# Dropdown list synced with session state
st.sidebar.selectbox(
    "Active Stock Focus Dropdown", 
    options=ticker_options, 
    index=None if not current_focus or current_focus not in ticker_options else ticker_options.index(current_focus),
    placeholder="Select stock to focus...",
    key="sidebar_active_stock_focus_dropdown",
    on_change=update_focus_from_sidebar
)

# Capture global focus ticker value
global_focus_ticker = st.session_state["global_focus_ticker"]

# 4. Tab Layout
tab_overview, tab_screener, tab_charting, tab_pe_valuation, tab_fno = st.tabs([
    "📊 Market Overview",
    "🔍 Quantamental Screener",
    "📈 Candlestick Analytics",
    "⚖️ P/E Valuation Bands",
    "🚀 F&O Derivatives & Heatmap"
])

# ==========================================
# TAB 1: MARKET OVERVIEW
# ==========================================
with tab_overview:
    # 3.10 On-Screen Ticker Search & Select Box (No sidebar required!)
    st.markdown("### 🎯 Quick Stock Analysis Focus")
    st.markdown("<p style='color: var(--text-secondary); margin-top:-10px; margin-bottom: 20px;'>Search and select any stock directly on-screen to view its scores, live prices, 52-week ranges, news headlines, and interactive charts.</p>", unsafe_allow_html=True)
    
    s_col1, s_col2 = st.columns([2, 3])
    with s_col1:
        # Ticker Quick Lookup
        st.text_input(
            "🔍 Quick Search Stock Symbol", 
            placeholder="e.g. INFY, HDFC BANK, BSE", 
            key="tab1_search_focus",
            on_change=update_focus_from_tab1_search
        )
    with s_col2:
        # Synced focus selectbox
        st.selectbox(
            "🎯 Select Stock from Constituency List", 
            options=ticker_options, 
            index=None if not current_focus or current_focus not in ticker_options else ticker_options.index(current_focus),
            placeholder="Select stock to focus...",
            key="tab1_select_focus",
            on_change=update_focus_from_tab1
        )
        
    st.markdown("<hr style='border-color: var(--border-color); margin: 20px 0;'>", unsafe_allow_html=True)

    # 3.9 Deep-Link Quick Analysis Panel (Optimized for Visual Accessibility)
    url_focus_active = st.query_params.get("focus_ticker", "").strip().upper()
    active_ticker = url_focus_active if url_focus_active else st.session_state.get("global_focus_ticker", "")
    
    if active_ticker:
        # Resolve exact ticker in options
        display_ticker = active_ticker if active_ticker in ticker_options else f"{active_ticker}.NS"
        is_nifty500 = display_ticker in ticker_options
        
        # Load historical price history live for quick 52-week range and chart analysis
        history_success = False
        try:
            quick_stock = yf.Ticker(display_ticker)
            df_qchart = quick_stock.history(period="1y", interval="1d")
            
            if not df_qchart.empty:
                df_qchart = df_qchart.copy()
                last_price = float(df_qchart["Close"].iloc[-1])
                fifty_two_week_high = float(df_qchart["High"].max())
                fifty_two_week_low = float(df_qchart["Low"].min())
                history_success = True
            else:
                last_price = 0.0
                fifty_two_week_high = 0.0
                fifty_two_week_low = 0.0
        except Exception:
            last_price = 0.0
            fifty_two_week_high = 0.0
            fifty_two_week_low = 0.0
            df_qchart = pd.DataFrame()
            
        # Fallback to cached metrics if network is offline and it is a Nifty 500 stock
        if not history_success and is_nifty500:
            link_stock_row = df_stocks[df_stocks["ticker"] == display_ticker]
            if not link_stock_row.empty:
                last_price = float(link_stock_row.iloc[0]["last_price"])
            
        # Render header cards
        if is_nifty500:
            link_stock_row = df_stocks[df_stocks["ticker"] == display_ticker]
            link_row = link_stock_row.iloc[0]
            link_name = link_row["company_name"]
            link_sector = link_row["sector"]
            link_rsi = link_row["rsi_14"]
            total_score = link_row["total_score"]
            fundamental_score = link_row["fundamental_score"]
            momentum_score = link_row["momentum_score"]
            
            st.markdown(
                f"""
                <div style="background-color: #EFF6FF; border: 2.5px solid #3B82F6; border-radius: 14px; padding: 26px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(59,130,246,0.1);">
                    <span style="font-size: 0.95rem; color: #1D4ED8; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em;">🔍 Deep-Link Quick Analysis Panel</span>
                    <h2 style="margin: 6px 0 4px 0; color: #1E3A8A; font-family: 'Outfit', sans-serif; font-size: 1.8rem; font-weight: 800;">
                        Active Deep-Dive: <strong style="font-size: 2.2rem; color: #0F172A;">{display_ticker.replace('.NS', '')}</strong> &bull; <span style="font-weight: 600; color: #475569;">{link_name}</span>
                    </h2>
                    <p style="font-size: 1.15rem; color: #475569; margin: 6px 0 0 0; font-weight: 600;">
                        Sector: <strong style="color: #0F172A;">{link_sector}</strong> &nbsp;&bull;&nbsp; RSI (14d): <strong style="color: #1D4ED8;">{link_rsi:.1f}</strong>
                    </p>
                </div>
                """,
                unsafe_allow_html=True
            )
        else:
            link_name = active_ticker
            link_sector = "N/A"
            try:
                link_name = quick_stock.info.get("longName", active_ticker)
            except Exception:
                pass
                
            st.markdown(
                f"""
                <div style="background-color: #FFFBEB; border: 2.5px solid #F59E0B; border-radius: 14px; padding: 26px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(245,158,11,0.05);">
                    <span style="font-size: 0.95rem; color: #B45309; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em;">⚠️ Non-Constituent Index Alert</span>
                    <h2 style="margin: 6px 0 4px 0; color: #78350F; font-family: 'Outfit', sans-serif; font-size: 1.8rem; font-weight: 800;">
                        Active Deep-Dive: <strong style="font-size: 2.2rem; color: #0F172A;">{active_ticker}</strong> &bull; <span style="font-weight: 600; color: #78350F;">{link_name}</span>
                    </h2>
                    <p style="font-size: 1.15rem; color: #78350F; margin: 6px 0 0 0; font-weight: 600; line-height: 1.4;">
                        Notice: <strong>{active_ticker}</strong> is not a constituent of the scored Nifty 500 index database. Live technical charts can still be queried, but quantamental scoring metrics are unavailable.
                    </p>
                </div>
                """,
                unsafe_allow_html=True
            )
            
        # Render Premium KPI Metric columns inside the quick analysis panel (High Readability)
        k_col1, k_col2, k_col3 = st.columns(3)
        with k_col1:
            st.metric(
                label="Last Price (LTP)", 
                value=f"₹ {last_price:,.2f}" if last_price > 0 else "N/A",
                delta="Live Stock Quote" if not df_qchart.empty else "N/A"
            )
        with k_col2:
            st.metric(
                label="52-Week High / Low", 
                value=f"₹ {fifty_two_week_high:,.1f} / ₹ {fifty_two_week_low:,.1f}" if fifty_two_week_high > 0 else "N/A",
                delta=f"Range: ₹ {fifty_two_week_high - fifty_two_week_low:,.1f}" if fifty_two_week_high > 0 else "N/A"
            )
        with k_col3:
            if is_nifty500:
                st.metric(
                    label="Quantamental Score Card", 
                    value=f"{int(total_score)}/100", 
                    delta=f"Fund: {int(fundamental_score)}/50 | Mom: {int(momentum_score)}/50",
                    delta_color="normal"
                )
            else:
                st.metric(
                    label="Quantamental Score Card", 
                    value="N/A", 
                    delta="Non-Nifty 500 constituent"
                )
                
        # ── Enhanced Trade Signal & Indicator Card (Tier 1 upgrade) ──────────
        if is_nifty500:
            def _safe(row, col, default=None):
                """Backward-safe column reader — returns default if column absent."""
                return row[col] if col in row.index else default

            def _is_valid(v):
                """Returns True only if v is a real, usable number (not None / NaN / 0)."""
                if v is None: return False
                try: return not pd.isna(v) and float(v) > 0
                except: return False

            conv_label  = _safe(link_row, "conviction_label", "Watch")
            adx_v       = _safe(link_row, "adx_14",  20.0)
            macd_sig    = _safe(link_row, "macd_signal", "Neutral")
            piot        = _safe(link_row, "piotroski_score", None)
            bk_sig      = _safe(link_row, "breakout_signal", 0)
            bb_sq       = _safe(link_row, "bb_squeeze", 0)

            # ── 15-Minute Trade Signal Cache ─────────────────────────────────
            # Priority: (1) DB scan values, (2) session cache <15 min, (3) compute fresh
            _sk  = f"tp_{display_ticker}"     # session state key for plan values
            _stk = f"tp_ts_{display_ticker}"  # session state key for timestamp

            now        = datetime.now()
            cached_ts  = st.session_state.get(_stk)
            cached_plan = st.session_state.get(_sk)
            plan_age_s  = (now - cached_ts).total_seconds() if cached_ts else 9999
            TTL_SECS    = 900   # 15 minutes

            # Try DB values first (set at scan time, only change on full rescan)
            _db_ep = _safe(link_row, "entry_price", None)
            _db_sl = _safe(link_row, "stop_loss",   None)
            _db_t1 = _safe(link_row, "target_1",    None)
            _db_t2 = _safe(link_row, "target_2",    None)
            _db_rr = _safe(link_row, "rr_ratio",    None)
            db_valid = all(_is_valid(x) for x in [_db_ep, _db_sl, _db_t1, _db_t2, _db_rr])

            if db_valid:
                # Stable DB values — only change when a new full scan is run
                entry_p, sl_p, t1_p, t2_p, rr_v = (
                    float(_db_ep), float(_db_sl), float(_db_t1),
                    float(_db_t2), float(_db_rr)
                )
                last_scan = _safe(link_row, "last_updated", "")
                signal_label = f"🗄️ Scan data · Last sync: {last_scan} · Updates on next scan"
                signal_label_color = "#16a34a"
                # Keep session cache in sync with DB values
                st.session_state[_sk]  = (entry_p, sl_p, t1_p, t2_p, rr_v)
                st.session_state[_stk] = now

            elif cached_plan and plan_age_s < TTL_SECS:
                # Serve from 15-min session cache — no recompute, no LTP drift
                entry_p, sl_p, t1_p, t2_p, rr_v = cached_plan
                remaining_s   = int(TTL_SECS - plan_age_s)
                remaining_m   = remaining_s // 60
                remaining_sec = remaining_s % 60
                set_at        = cached_ts.strftime("%H:%M:%S")
                signal_label  = f"⏳ Locked plan · Set at {set_at} · Refreshes in {remaining_m}m {remaining_sec}s"
                signal_label_color = "#b45309"

            else:
                # Compute fresh from live price + ATR, then lock for 15 min
                try:
                    _hist3m = yf.Ticker(display_ticker).history(period="3mo", interval="1d")
                    if not _hist3m.empty and len(_hist3m) >= 14:
                        _atr   = compute_atr(_hist3m)
                        _ema20 = float(_hist3m["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
                        entry_p  = round(last_price, 2)
                        sl_p     = round(max(_ema20 * 0.99, last_price * 0.93), 2)
                        t1_p     = round(last_price + 2.0 * _atr, 2)
                        t2_p     = round(last_price + 3.0 * _atr, 2)
                        _risk    = entry_p - sl_p
                        rr_v     = round((t1_p - entry_p) / _risk, 2) if _risk > 0 else 1.5
                    else:
                        raise ValueError("Insufficient history")
                except Exception:
                    entry_p = round(last_price, 2)
                    sl_p    = round(last_price * 0.93, 2)
                    t1_p    = round(last_price * 1.05, 2)
                    t2_p    = round(last_price * 1.08, 2)
                    rr_v    = 1.5

                # Lock into session state for 15 minutes
                st.session_state[_sk]  = (entry_p, sl_p, t1_p, t2_p, rr_v)
                st.session_state[_stk] = now
                signal_label  = f"✅ Plan computed at {now.strftime('%H:%M:%S')} · Locked for 15 min"
                signal_label_color = "#0369a1"

            # Refresh button — clears cache and forces recompute on next run
            if st.button("🔄 Refresh Trade Plan", key=f"refresh_tp_{display_ticker}",
                         help="Forces a fresh ATR-based trade plan recompute"):
                st.session_state.pop(_sk,  None)
                st.session_state.pop(_stk, None)
                st.rerun()

            # Conviction palette
            _conv_pal = {
                "Strong Buy": ("#052e16","#16a34a","#dcfce7","🚀"),
                "Buy":        ("#14532d","#22c55e","#f0fdf4","✅"),
                "Watch":      ("#92400e","#f59e0b","#fffbeb","👁️"),
                "Neutral":    ("#1e3a5f","#3b82f6","#eff6ff","⚖️"),
                "Avoid":      ("#7f1d1d","#ef4444","#fff1f2","🚫"),
            }
            ctext, cborder, cbg, cicon = _conv_pal.get(conv_label, _conv_pal["Watch"])

            # ADX status
            if adx_v is not None:
                if adx_v >= 25:   adx_label, adx_color = "Strong Trend",   "#16a34a"
                elif adx_v >= 20: adx_label, adx_color = "Moderate Trend", "#f59e0b"
                else:             adx_label, adx_color = "Choppy / Sideways", "#ef4444"
                adx_str = f"{adx_v:.1f} — {adx_label}"
            else:
                adx_str, adx_color = "N/A", "#94a3b8"

            # MACD palette
            _macd_pal = {
                "Bullish Crossover":  ("#15803d","#dcfce7","🟢"),
                "Bullish":            ("#166534","#f0fdf4","🟩"),
                "Neutral":            ("#475569","#f1f5f9","⬜"),
                "Bearish Crossover":  ("#991b1b","#fee2e2","🔴"),
                "Bearish":            ("#7f1d1d","#fff1f2","🟥"),
            }
            mc, mbg, micon = _macd_pal.get(macd_sig, _macd_pal["Neutral"])

            # Piotroski badge
            if piot is not None:
                if piot >= 7:   pc, pbg, plabel = "#15803d","#dcfce7", f"{piot}/9 — High Quality"
                elif piot >= 5: pc, pbg, plabel = "#b45309","#fef3c7", f"{piot}/9 — Moderate"
                else:           pc, pbg, plabel = "#991b1b","#fee2e2", f"{piot}/9 — Caution"
            else:
                pc, pbg, plabel = "#64748b","#f1f5f9", "N/A"

            # Build compact signal card HTML (no leading whitespace — avoids Markdown code-block)
            sig_html = f'<div style="background:{cbg};border:2px solid {cborder};border-radius:14px;padding:16px 20px;margin-bottom:18px;">'
            sig_html += f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap;">'
            sig_html += f'<span style="font-size:0.75rem;font-weight:800;color:#475569;text-transform:uppercase;letter-spacing:0.06em;">📊 Trade Intelligence</span>'
            sig_html += f'<span style="font-size:0.8rem;font-weight:800;color:{ctext};background:{cbg};border:1.5px solid {cborder};padding:3px 14px;border-radius:20px;">{cicon} {conv_label}</span>'
            if bk_sig: sig_html += '<span style="font-size:0.8rem;font-weight:800;color:#c2410c;background:#fff7ed;border:1.5px solid #fb923c;padding:3px 12px;border-radius:20px;">🚀 BREAKOUT SIGNAL</span>'
            if bb_sq:  sig_html += '<span style="font-size:0.8rem;font-weight:800;color:#7c3aed;background:#f5f3ff;border:1.5px solid #a78bfa;padding:3px 12px;border-radius:20px;">🔋 BB SQUEEZE</span>'
            sig_html += '</div>'

            # Row 1: ADX + MACD + Piotroski
            sig_html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">'
            sig_html += f'<div style="flex:1;min-width:150px;background:#ffffff;border-radius:10px;padding:10px 14px;border:1px solid #e2e8f0;"><div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:3px;">ADX Trend Strength</div><div style="font-size:0.9rem;font-weight:800;color:{adx_color};">{adx_str}</div></div>'
            sig_html += f'<div style="flex:1;min-width:150px;background:{mbg};border-radius:10px;padding:10px 14px;border:1px solid #e2e8f0;"><div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:3px;">MACD Signal</div><div style="font-size:0.9rem;font-weight:800;color:{mc};">{micon} {macd_sig}</div></div>'
            sig_html += f'<div style="flex:1;min-width:150px;background:{pbg};border-radius:10px;padding:10px 14px;border:1px solid #e2e8f0;"><div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:3px;">Piotroski F-Score</div><div style="font-size:0.9rem;font-weight:800;color:{pc};">{plabel}</div></div>'
            sig_html += '</div>'

            # Row 2: Entry / SL / T1 / T2 / RR
            def _fmt_price(v): return f'₹{v:,.2f}' if v is not None else 'N/A'
            sig_html += '<div style="background:#ffffff;border-radius:10px;padding:12px 16px;border:1px solid #e2e8f0;">'
            sig_html += '<div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">ATR-Based Trade Plan (Suggested — not financial advice)</div>'
            sig_html += '<div style="display:flex;gap:8px;flex-wrap:wrap;">'
            sig_html += f'<div style="text-align:center;flex:1;min-width:80px;"><div style="font-size:0.65rem;font-weight:700;color:#64748b;text-transform:uppercase;">Entry</div><div style="font-size:1rem;font-weight:800;color:#0f172a;">{_fmt_price(entry_p)}</div></div>'
            sig_html += f'<div style="text-align:center;flex:1;min-width:80px;background:#fff1f2;border-radius:8px;padding:4px;"><div style="font-size:0.65rem;font-weight:700;color:#991b1b;text-transform:uppercase;">Stop Loss</div><div style="font-size:1rem;font-weight:800;color:#dc2626;">{_fmt_price(sl_p)}</div></div>'
            sig_html += f'<div style="text-align:center;flex:1;min-width:80px;background:#f0fdf4;border-radius:8px;padding:4px;"><div style="font-size:0.65rem;font-weight:700;color:#15803d;text-transform:uppercase;">Target 1</div><div style="font-size:1rem;font-weight:800;color:#16a34a;">{_fmt_price(t1_p)}</div></div>'
            sig_html += f'<div style="text-align:center;flex:1;min-width:80px;background:#f0fdf4;border-radius:8px;padding:4px;"><div style="font-size:0.65rem;font-weight:700;color:#15803d;text-transform:uppercase;">Target 2</div><div style="font-size:1rem;font-weight:800;color:#16a34a;">{_fmt_price(t2_p)}</div></div>'
            rr_disp = f'{rr_v:.1f}:1' if rr_v is not None else 'N/A'
            rr_col  = '#16a34a' if (rr_v or 0) >= 2.0 else '#f59e0b' if (rr_v or 0) >= 1.5 else '#ef4444'
            sig_html += f'<div style="text-align:center;flex:1;min-width:80px;"><div style="font-size:0.65rem;font-weight:700;color:#64748b;text-transform:uppercase;">R:R Ratio</div><div style="font-size:1rem;font-weight:900;color:{rr_col};">{rr_disp}</div></div>'
            sig_html += f'</div><div style="margin-top:8px;font-size:0.7rem;font-weight:600;color:{signal_label_color};">{signal_label}</div></div>'
            sig_html += '</div>'
            st.markdown(sig_html, unsafe_allow_html=True)

        # Fetch live stock news with sentiment coloring
        news_items = fetch_live_stock_news(display_ticker)
        if news_items:
            # Sentiment palette lookup
            def _spal(s):
                if s == "positive":
                    return ("#22C55E","#F0FDF4","#BBF7D0","▲","#DCFCE7","#15803D","#DCFCE7","#15803D","#14532D","#166534")
                elif s == "negative":
                    return ("#EF4444","#FFF1F2","#FECACA","▼","#FEE2E2","#991B1B","#FEE2E2","#991B1B","#7F1D1D","#B91C1C")
                else:
                    return ("#94A3B8","#F8FAFC","#E2E8F0","●","#F1F5F9","#475569","#F1F5F9","#475569","#1E40AF","#64748B")

            # Legend bar (no leading spaces = no code-block trigger)
            html = '<div style="background:#FFFFFF;border:1.5px solid #E2E8F0;border-radius:14px;padding:18px 20px;margin-bottom:25px;box-shadow:0 2px 8px rgba(0,0,0,0.04);">'
            html += '<div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">'
            html += '<span style="font-size:0.78rem;font-weight:800;color:#0F172A;text-transform:uppercase;letter-spacing:0.06em;">📰 News &amp; Sentiment</span>'
            html += '<span style="font-size:0.72rem;background:#DCFCE7;color:#15803D;font-weight:800;padding:2px 10px;border-radius:20px;border:1px solid #22C55E;">▲ Positive</span>'
            html += '<span style="font-size:0.72rem;background:#FEE2E2;color:#991B1B;font-weight:800;padding:2px 10px;border-radius:20px;border:1px solid #EF4444;">▼ Negative</span>'
            html += '<span style="font-size:0.72rem;background:#F1F5F9;color:#475569;font-weight:800;padding:2px 10px;border-radius:20px;border:1px solid #94A3B8;">● Neutral</span>'
            html += '</div>'

            for item in news_items:
                s = get_news_sentiment(item["title"])
                gutter, card_bg, card_border, icon, icon_bg, icon_color, badge_bg, badge_color, link_color, pub_color = _spal(s)
                pub = item["publisher"] or "News"
                title = item["title"]
                link = item["link"] or "#"
                html += f'<div style="display:flex;align-items:stretch;margin-bottom:8px;border-radius:10px;overflow:hidden;border:1px solid {card_border};box-shadow:0 1px 4px rgba(0,0,0,0.04);">'
                html += f'<div style="width:6px;min-width:6px;background:{gutter};flex-shrink:0;"></div>'
                html += f'<div style="background:{icon_bg};padding:0 12px;display:flex;align-items:center;justify-content:center;flex-shrink:0;"><span style="font-size:1.1rem;font-weight:900;color:{icon_color};line-height:1;">{icon}</span></div>'
                html += f'<div style="background:{card_bg};padding:11px 14px;flex:1;min-width:0;">'
                html += f'<div style="margin-bottom:4px;"><span style="font-size:0.7rem;font-weight:800;color:{badge_color};background:{badge_bg};padding:1px 8px;border-radius:20px;text-transform:uppercase;letter-spacing:0.04em;margin-right:8px;">{icon} {s.capitalize()}</span>'
                html += f'<span style="font-size:0.72rem;font-weight:700;color:{pub_color};text-transform:uppercase;letter-spacing:0.04em;">{pub}</span></div>'
                html += f'<a href="{link}" target="_blank" style="color:{link_color};font-weight:700;font-size:0.97rem;text-decoration:none;line-height:1.45;display:block;">{title}</a>'
                html += '</div></div>'

            html += '</div>'
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.markdown('<div style="background:#F8FAFC;border:1.5px solid #E2E8F0;border-radius:14px;padding:18px 20px;margin-bottom:25px;box-shadow:0 2px 4px rgba(0,0,0,0.02);"><span style="font-size:0.88rem;color:#475569;font-weight:800;text-transform:uppercase;letter-spacing:0.06em;">📰 News &amp; Sentiment</span><br><span style="font-size:0.95rem;color:#94A3B8;font-style:italic;margin-top:8px;display:block;">No recent news articles found for this symbol.</span></div>', unsafe_allow_html=True)
        
        # Render Charts side-by-side
        if not df_qchart.empty:
            q_col1, q_col2 = st.columns(2)
            
            # Render Candlestick in column 1
            with q_col1:
                st.markdown("##### 📈 1-Year Candlestick Canvas (Daily)")
                try:
                    df_qchart["DateStr"] = df_qchart.index.strftime("%b %d, %Y")
                    df_qchart["20 EMA"] = df_qchart["Close"].ewm(span=20, adjust=False).mean()
                    df_qchart["50 EMA"] = df_qchart["Close"].ewm(span=50, adjust=False).mean()
                    
                    fig_qcandle = go.Figure()
                    fig_qcandle.add_trace(go.Candlestick(
                        x=df_qchart['DateStr'],
                        open=df_qchart['Open'],
                        high=df_qchart['High'],
                        low=df_qchart['Low'],
                        close=df_qchart['Close'],
                        name="Price"
                    ))
                    fig_qcandle.add_trace(go.Scatter(x=df_qchart['DateStr'], y=df_qchart["20 EMA"], name="20 EMA", line=dict(color="#3B82F6", width=1.5)))
                    fig_qcandle.add_trace(go.Scatter(x=df_qchart['DateStr'], y=df_qchart["50 EMA"], name="50 EMA", line=dict(color="#8B5CF6", width=1.5)))
                    
                    fig_qcandle.update_layout(
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        xaxis_rangeslider_visible=False,
                        xaxis=dict(type='category', gridcolor='rgba(0,0,0,0.05)', color='#475569', nticks=8),
                        yaxis=dict(gridcolor='rgba(0,0,0,0.05)', color='#475569'),
                        height=320,
                        margin=dict(l=10, r=10, t=10, b=10),
                        legend=dict(font=dict(color='#0F172A'))
                    )
                    st.plotly_chart(fig_qcandle, use_container_width=True)
                except Exception as ex:
                    st.error(f"Error drawing candlestick: {ex}")
                    
            # Render PE valuation bands in column 2
            with q_col2:
                st.markdown("##### ⚖️ Historical P/E Valuation Bands")
                try:
                    eps_val = quick_stock.info.get("trailingEps")
                    if eps_val and eps_val > 0:
                        curr_pe = quick_stock.info.get("trailingPE", 25.0)
                        multiples_q = [curr_pe * 0.85, curr_pe, curr_pe * 1.15]
                        labels_q = ["Discount PE", "Median PE", "Premium PE"]
                        colors_q = ["#3B82F6", "#8B5CF6", "#F59E0B"]
                        
                        fig_qbands = go.Figure()
                        fig_qbands.add_trace(go.Scatter(x=df_qchart["DateStr"], y=df_qchart["Close"], name="Stock Price", line=dict(color="#0F172A", width=2.5)))
                        
                        for mult, label, color in zip(multiples_q, labels_q, colors_q):
                            fig_qbands.add_trace(go.Scatter(
                                x=df_qchart["DateStr"], 
                                y=[eps_val * mult] * len(df_qchart), 
                                name=f"{label} ({mult:.1f}x)", 
                                line=dict(color=color, width=1.5, dash='dash')
                            ))
                            
                        fig_qbands.update_layout(
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            xaxis=dict(type='category', gridcolor='rgba(0,0,0,0.05)', color='#475569', nticks=8),
                            yaxis=dict(gridcolor='rgba(0,0,0,0.05)', color='#475569'),
                            height=320,
                            margin=dict(l=10, r=10, t=10, b=10),
                            legend=dict(font=dict(color='#0F172A'))
                        )
                        st.plotly_chart(fig_qbands, use_container_width=True)
                    else:
                        st.warning("EPS negative or unavailable. P/E bands cannot be calculated for loss-making or index equities.")
                except Exception as ex:
                    st.error(f"Error drawing PE bands: {ex}")
                    
            st.markdown("<hr style='border-color: var(--border-color); margin: 25px 0;'>", unsafe_allow_html=True)
        if not history_success:
            if is_nifty500:
                st.info("ℹ️ Live Spot price connection is temporarily offline. Displaying cached screener metrics.")
            else:
                st.warning(f"⚠️ Spot price connection offline for non-constituent stock '{display_ticker}'. Please check your network connection.")
            st.markdown("<hr style='border-color: var(--border-color); margin: 25px 0;'>", unsafe_allow_html=True)
    else:
        st.info("🔍 Select a stock or use Quick Search/Constituency List to activate deep-dive analysis.")
        st.markdown("<hr style='border-color: var(--border-color); margin: 25px 0;'>", unsafe_allow_html=True)

    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        st.metric("Total Scored Stocks", str(total_scored_stocks), delta="Nifty 500 Space")
    with m_col2:
        avg_score = df_stocks["total_score"].mean()
        st.metric("Average Score", f"{avg_score:.1f}/100")
    with m_col3:
        avg_roe = df_stocks["roe"].mean()
        st.metric("Average ROE (%)", f"{avg_roe:.1f}%")
    with m_col4:
        avg_rsi = df_stocks["rsi_14"].mean()
        st.metric("Average RSI (14d)", f"{avg_rsi:.1f}")
        
    # Top 5 Scored Stocks Cards Showcase
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🏆 Top 5 Quantamental Leaders")
    st.markdown("<p style='color: var(--text-secondary); margin-top:-10px; margin-bottom: 20px;'>The highest-rated equities in the Nifty 500 space based on fundamental strength and price momentum.</p>", unsafe_allow_html=True)
    
    df_top_5 = df_stocks.sort_values(
        by=["total_score", "fundamental_score", "momentum_score", "roe"],
        ascending=[False, False, False, False]
    ).head(5)
    
    top5_cols = st.columns(5)
    for idx, (index, row) in enumerate(df_top_5.iterrows()):
        rank = idx + 1
        ticker_raw = row["ticker"]
        ticker_clean = ticker_raw.replace(".NS", "")
        company = row["company_name"]
        total_sc = int(row["total_score"])
        fund_sc = int(row["fundamental_score"])
        mom_sc = int(row["momentum_score"])
        price = row["last_price"]
        sector = row["sector"]
        
        # Determine badge color based on rank
        if rank == 1:
            badge_style = "background: linear-gradient(135deg, #F59E0B 0%, #D97706 100%); box-shadow: 0 2px 4px rgba(217, 119, 6, 0.3);"
            rank_label = "🥇 #1"
        elif rank == 2:
            badge_style = "background: linear-gradient(135deg, #94A3B8 0%, #475569 100%); box-shadow: 0 2px 4px rgba(71, 85, 105, 0.3);"
            rank_label = "🥈 #2"
        elif rank == 3:
            badge_style = "background: linear-gradient(135deg, #CD7F32 0%, #B45309 100%); box-shadow: 0 2px 4px rgba(180, 83, 9, 0.3);"
            rank_label = "🥉 #3"
        else:
            badge_style = "background: linear-gradient(135deg, #10B981 0%, #059669 100%); box-shadow: 0 2px 4px rgba(5, 150, 105, 0.2);"
            rank_label = f"#{rank}"
            
        card_html = f"""
        <div class="top-stock-card">
            <span class="rank-badge" style="{badge_style}">{rank_label}</span>
            <div class="ticker-name">{ticker_clean}</div>
            <div class="company-name" title="{company}">{company}</div>
            <div class="score-wrap">
                <span class="total-score">{total_sc}</span>
                <span class="score-max">/100</span>
            </div>
            <div class="sub-scores">
                F: {fund_sc}/50 &bull; M: {mom_sc}/50
            </div>
            <div class="price-row">
                <span>₹{price:,.1f}</span>
                <span class="sector-badge" title="{sector}">{sector}</span>
            </div>
        </div>
        """
        with top5_cols[idx]:
            st.markdown(card_html, unsafe_allow_html=True)
            if st.button("🎯 Focus Ticker", key=f"focus_top5_{ticker_clean}", use_container_width=True):
                st.session_state["global_focus_ticker"] = ticker_raw
                st.rerun()
                
    st.markdown("<br><hr style='border-color: var(--border-color); margin: 15px 0;'>", unsafe_allow_html=True)
        
    g_col1, g_col2 = st.columns(2)
    
    with g_col1:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("### 🏆 Top 10 Fundamental Score Leaderboard", unsafe_allow_html=True)
        df_top_fundamentals = df_stocks.sort_values(by=["fundamental_score", "roe"], ascending=[False, False]).head(10).copy()
        df_top_fundamentals["fundamental_score"] = df_top_fundamentals["fundamental_score"].map(lambda x: f"{int(x)}/50")
        df_top_fundamentals["roe"] = df_top_fundamentals["roe"].map(lambda x: f"{x:.1f}%")
        
        # Display as clean summary table
        st.dataframe(
            df_top_fundamentals[["ticker", "company_name", "sector", "roe", "debt_to_equity", "fundamental_score"]].rename(columns={
                "ticker": "Ticker", "company_name": "Company Name", "sector": "Sector", 
                "roe": "ROE (%)", "debt_to_equity": "D/E", "fundamental_score": "Fundamental Score"
            }),
            use_container_width=True,
            hide_index=True
        )
        st.markdown('</div>', unsafe_allow_html=True)
        
    with g_col2:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("### ⚡ Top 10 Price Momentum Leaderboard", unsafe_allow_html=True)
        df_top_momentum = df_stocks.sort_values(by=["momentum_score", "rsi_14"], ascending=[False, False]).head(10).copy()
        df_top_momentum["momentum_score"] = df_top_momentum["momentum_score"].map(lambda x: f"{int(x)}/50")
        df_top_momentum["rsi_14"] = df_top_momentum["rsi_14"].map(lambda x: f"{x:.1f}")
        df_top_momentum["rel_strength_3m"] = df_top_momentum["rel_strength_3m"].map(lambda x: f"{x:.1f}%")
        
        st.dataframe(
            df_top_momentum[["ticker", "company_name", "sector", "rsi_14", "rel_strength_3m", "momentum_score"]].rename(columns={
                "ticker": "Ticker", "company_name": "Company Name", "sector": "Sector", 
                "rsi_14": "RSI (14d)", "rel_strength_3m": "RS vs Nifty 50", "momentum_score": "Momentum Score"
            }),
            use_container_width=True,
            hide_index=True
        )
        st.markdown('</div>', unsafe_allow_html=True)
        
    # ⚙️ Collapsible Scanner Database Cache & Sync Utility at bottom of Tab 1
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("⚙️ Scanner Database Diagnostics & Caching Management"):
        st.markdown(f"**Local SQLite Database Path**: `{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nifty500_scanner.db')}`")
        st.markdown(f"**Last Completed Scan Update**: `{last_refresh_date}`")
        
        st.markdown("<hr style='border-color: var(--border-color); margin: 20px 0;'>", unsafe_allow_html=True)
        
        u_col1, u_col2 = st.columns(2)
        
        with u_col1:
            st.markdown("##### Update & Synchronize Data Pipeline")
            st.markdown("<p style='color: var(--text-secondary); font-size: 0.9rem;'>Updates price feeds, technical moving averages, RSI indexes, and recent fundamental ratios for the Nifty 500 space. You can initiate a manual synchronization at any time, or enable the automatic background sync below.</p>", unsafe_allow_html=True)
            
            if st.button("🔄 Scan & Synchronize Nifty 500 Market Data", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                def progress_update(current, total, ticker):
                    pct = int((current / total) * 100)
                    progress_bar.progress(pct)
                    status_text.markdown(f"Fetching Ticker **{current}/{total}** // `{ticker}`... Please wait.")
                    
                success_count = run_nifty500_scanner_pipeline(progress_callback=progress_update)
                st.success(f"Audit successfully refreshed! Analyzed {success_count} Nifty 500 stock scores successfully!")
                st.rerun()
                
            st.markdown("<hr style='border-color: var(--border-color); margin: 15px 0;'>", unsafe_allow_html=True)
            st.markdown("##### ⚙️ Automatic Background Synchronization")
            st.markdown("<p style='color: var(--text-secondary); font-size: 0.9rem;'>Automatically fetch and update Nifty 500 data silently in the background without freezing your workspace.</p>", unsafe_allow_html=True)
            
            interval_opts = ["Manual Only", "30 Minutes", "1 Hour", "2 Hours"]
            default_interval_idx = interval_opts.index(st.session_state["auto_refresh_interval"])
            
            selected_interval = st.selectbox(
                "Background Synchronization Frequency", 
                options=interval_opts, 
                index=default_interval_idx,
                key="auto_sync_interval_selector"
            )
            if selected_interval != st.session_state["auto_refresh_interval"]:
                st.session_state["auto_refresh_interval"] = selected_interval
                st.rerun()
                
        with u_col2:
            st.markdown("##### Maintenance & Data Erasure")
            st.markdown("<p style='color: var(--accent-red); font-weight: 600; font-size: 0.9rem;'>Warning: Clearing the cache database deletes all scored Nifty 500 entries. A full pipeline audit scan will be required afterwards.</p>", unsafe_allow_html=True)
            
            confirm_wipe = st.checkbox("I verify I want to clear all cached scanner database records")
            
            if st.button("Wipe Scanner Cache Database Records", disabled=not confirm_wipe, type="secondary"):
                clear_scanner_cache()
                st.success("Scanner cache successfully cleared.")
                st.rerun()

# ==========================================
# TAB 2: QUANTAMENTAL SCREENER
# ==========================================
with tab_screener:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("### Multi-Criteria Screener Interface", unsafe_allow_html=True)
    st.markdown("<p style='color: var(--text-secondary); margin-top:-10px; margin-bottom: 20px;'>Filter the Nifty 500 space reactively using sliders based on the composite 100-point algorithm.</p>", unsafe_allow_html=True)
    
    screener_mode = st.radio(
        "Screener Mode Selection", 
        options=["Standard Scanner", "🏆 Top 5 Scoring Scrips"], 
        index=0,
        horizontal=True,
        key="screener_mode_radio_widget"
    )
    
    # Screener Controls
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns(3)
    with ctrl_col1:
        min_total_score = st.slider("Minimum Total Score (/100)", min_value=0.0, max_value=100.0, value=50.0, step=5.0)
    with ctrl_col2:
        min_quality_score = st.slider("Minimum Fundamental Score (/50)", min_value=0.0, max_value=50.0, value=20.0, step=5.0)
    with ctrl_col3:
        min_momentum_score = st.slider("Minimum Momentum Intensity (/50)", min_value=0.0, max_value=50.0, value=20.0, step=5.0)
        
    ctrl_col4, ctrl_col5, ctrl_col6, ctrl_col7, ctrl_col8 = st.columns([2, 2, 1.5, 1, 1])
    with ctrl_col4:
        all_sectors = sorted(list(df_stocks["sector"].dropna().unique()))
        selected_sectors = st.multiselect("Filter by Sector", options=all_sectors, default=[])
    with ctrl_col5:
        search_symbol = st.text_input("Search Ticker Symbol / Company Name", placeholder="e.g. INFY").upper()
    with ctrl_col6:
        min_volume_lakhs = st.slider("Min 5-Day Avg Volume (Lakh shares)", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
    with ctrl_col7:
        fno_filter = st.selectbox("F&O Segment", options=["All Stocks", "F&O Eligible", "Non-F&O"], index=0)
    with ctrl_col8:
        min_ltp_price = st.number_input("Min Price (₹)", min_value=0.0, value=0.0, step=100.0, key="screener_min_ltp_price")
        
    # Filtering Data
    df_filtered = df_stocks.copy()
    
    # Expose F&O status
    fno_symbols = get_fno_symbols()
    df_filtered["is_fno"] = df_filtered["ticker"].map(lambda t: 1 if t.replace(".NS", "") in fno_symbols else 0)
    
    # Filter by sliders
    df_filtered = df_filtered[
        (df_filtered["total_score"] >= min_total_score) & 
        (df_filtered["fundamental_score"] >= min_quality_score) &
        (df_filtered["momentum_score"] >= min_momentum_score)
    ]
    
    if selected_sectors:
        df_filtered = df_filtered[df_filtered["sector"].isin(selected_sectors)]
        
    if search_symbol.strip():
        df_filtered = df_filtered[
            (df_filtered["ticker"].str.contains(search_symbol)) |
            (df_filtered["company_name"].str.upper().str.contains(search_symbol))
        ]
        
    if fno_filter == "F&O Eligible":
        df_filtered = df_filtered[df_filtered["is_fno"] == 1]
    elif fno_filter == "Non-F&O":
        df_filtered = df_filtered[df_filtered["is_fno"] == 0]
        
    if min_ltp_price > 0:
        df_filtered = df_filtered[df_filtered["last_price"] >= min_ltp_price]
        
    # Apply 5-Day average volume parameter filter if present
    if "avg_volume_5d" in df_filtered.columns and min_volume_lakhs > 0:
        df_filtered = df_filtered[df_filtered["avg_volume_5d"] >= (min_volume_lakhs * 100000)]
        
    # Apply Top 5 Scoring Scrips filter mode if active
    if screener_mode == "🏆 Top 5 Scoring Scrips":
        df_filtered = df_filtered.sort_values(by="total_score", ascending=False).head(5)
        
    total_matches = len(df_filtered)
    st.markdown(f"<p style='color: var(--text-secondary); font-size: 0.85rem;'>Matching Stocks: <strong>{total_matches}</strong> of {total_scored_stocks} constituents</p>", unsafe_allow_html=True)
    
    # Sort options + breakout filter
    sort_col1, sort_col2 = st.columns([3, 1])
    with sort_col1:
        sort_by_col = st.selectbox(
            "Sort Results By",
            options=["Total Score", "Fundamental Score", "Momentum Score",
                     "Market Cap", "ROE (%)", "RSI (14d)", "ADX (Trend Strength)",
                     "Piotroski Score"],
            index=0
        )
    with sort_col2:
        show_breakouts_only = st.checkbox(
            "🚀 Breakouts Only",
            value=False,
            help="Show only stocks near 52-week high with a volume surge."
        )

    sort_mapping = {
        "Total Score":         "total_score",
        "Fundamental Score":   "fundamental_score",
        "Momentum Score":      "momentum_score",
        "Market Cap":          "market_cap_cr",
        "ROE (%)":             "roe",
        "RSI (14d)":           "rsi_14",
        "ADX (Trend Strength)":"adx_14",
        "Piotroski Score":     "piotroski_score",
    }

    # Breakout filter (only applies if new column exists)
    if show_breakouts_only and "breakout_signal" in df_filtered.columns:
        df_filtered = df_filtered[df_filtered["breakout_signal"] == 1]

    sort_col = sort_mapping[sort_by_col]
    if sort_col in df_filtered.columns:
        df_filtered = df_filtered.sort_values(by=sort_col, ascending=False)
    else:
        df_filtered = df_filtered.sort_values(by="total_score", ascending=False)
    
    # Render dataframe
    df_display = df_filtered.copy()
    if not df_display.empty:
        df_display["pe_ratio"]          = df_display["pe_ratio"].map(lambda x: f"{x:.1f}x" if pd.notnull(x) else "-")
        df_display["pb_ratio"]          = df_display["pb_ratio"].map(lambda x: f"{x:.1f}x" if pd.notnull(x) else "-")
        df_display["roe"]               = df_display["roe"].map(lambda x: f"{x:.1f}%")
        df_display["eps_growth_yoy"]    = df_display["eps_growth_yoy"].map(lambda x: f"{x:.1f}%" if pd.notnull(x) else "-")
        df_display["rsi_14"]            = df_display["rsi_14"].map(lambda x: f"{x:.1f}")
        df_display["market_cap_cr"]     = df_display["market_cap_cr"].map(lambda x: f"₹{x:,.0f} Cr")
        df_display["fundamental_score"] = df_display["fundamental_score"].map(lambda x: f"{int(x)}/50")
        df_display["momentum_score"]    = df_display["momentum_score"].map(lambda x: f"{int(x)}/50")
        df_display["total_score"]       = df_display["total_score"].map(lambda x: f"{int(x)}/100")
        df_display["fno_status"]        = df_display["is_fno"].map(lambda x: "🟢 F&O" if x == 1 else "➖")

        # ── New enhanced columns (backward-compatible: only add if column exists) ──
        if "conviction_label" in df_display.columns:
            _conv_icon = {"Strong Buy": "🚀", "Buy": "✅", "Watch": "👁️", "Neutral": "⚖️", "Avoid": "🚫"}
            df_display["conviction"] = df_display["conviction_label"].map(
                lambda x: f"{_conv_icon.get(x, '')} {x}" if pd.notnull(x) else "–")
        else:
            df_display["conviction"] = "–"

        if "piotroski_score" in df_display.columns:
            df_display["piotroski"] = df_display["piotroski_score"].map(
                lambda x: f"{int(x)}/9" if pd.notnull(x) else "–")
        else:
            df_display["piotroski"] = "–"

        if "macd_signal" in df_display.columns:
            _macd_icon = {"Bullish Crossover": "🟢", "Bullish": "🟩", "Bearish Crossover": "🔴",
                          "Bearish": "🟥", "Neutral": "⬜"}
            df_display["macd"] = df_display["macd_signal"].map(
                lambda x: f"{_macd_icon.get(x, '')} {x}" if pd.notnull(x) else "–")
        else:
            df_display["macd"] = "–"

        if "adx_14" in df_display.columns:
            df_display["adx_display"] = df_display["adx_14"].map(
                lambda x: f"{x:.1f}" if pd.notnull(x) else "–")
        else:
            df_display["adx_display"] = "–"

        if "breakout_signal" in df_display.columns:
            df_display["breakout"] = df_display["breakout_signal"].map(
                lambda x: "🚀 YES" if x == 1 else "–")
        else:
            df_display["breakout"] = "–"

        # Render interactive dataframe with single-row selection enabled
        display_cols = [
            "ticker", "company_name", "sector", "fno_status",
            "conviction", "piotroski", "macd", "adx_display", "breakout",
            "fundamental_score", "momentum_score", "total_score",
            "last_price", "market_cap_cr", "pe_ratio", "roe", "debt_to_equity",
            "rsi_14", "rel_strength_3m"
        ]
        rename_map = {
            "ticker": "Ticker", "company_name": "Company", "sector": "Sector",
            "fno_status": "F&O",
            "conviction": "Conviction", "piotroski": "Piotroski",
            "macd": "MACD", "adx_display": "ADX", "breakout": "Breakout 🚀",
            "fundamental_score": "Fund. Score", "momentum_score": "Mom. Score",
            "total_score": "Total Score",
            "last_price": "LTP (₹)", "market_cap_cr": "Mkt Cap",
            "pe_ratio": "P/E", "roe": "ROE", "debt_to_equity": "D/E",
            "rsi_14": "RSI", "rel_strength_3m": "RS 3M%"
        }
        selection = st.dataframe(
            df_display[display_cols].rename(columns=rename_map),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row"
        )
        
        # Capture selection events and update the active stock focus (Bulletproof compatibility check)
        selected_row_idx = None
        if selection:
            if hasattr(selection, "selection") and hasattr(selection.selection, "rows") and selection.selection.rows:
                selected_row_idx = selection.selection.rows[0]
            elif isinstance(selection, dict) and "selection" in selection and "rows" in selection["selection"] and selection["selection"]["rows"]:
                selected_row_idx = selection["selection"]["rows"][0]
                
        if selected_row_idx is not None:
            selected_ticker = df_display.iloc[selected_row_idx]["ticker"]
            if selected_ticker != st.session_state["global_focus_ticker"]:
                st.session_state["global_focus_ticker"] = selected_ticker
                st.rerun()
                
        # 3. Quick Focus Stock Selector (For Visual Accessibility & Easy Row Clicks)
        st.markdown("<hr style='border-color: var(--border-color); margin: 25px 0;'>", unsafe_allow_html=True)
        st.markdown("##### 🎯 Quick Focus Stock Selector", unsafe_allow_html=True)
        st.markdown("<p style='color: var(--text-secondary); font-size: 0.9rem;'>If clicking small checkboxes in the table is difficult, select any stock from your filtered results below to instantly focus the Candlestick Canvas & P/E Valuation Bands.</p>", unsafe_allow_html=True)
        
        matched_tickers = sorted(list(df_display["ticker"].unique()))
        if matched_tickers:
            # Safely sync the widget state inside the matched list
            current_focus = st.session_state.get("global_focus_ticker", "")
            if current_focus and current_focus in matched_tickers:
                st.session_state["screener_quick_focus_selectbox_widget"] = current_focus
            else:
                st.session_state["screener_quick_focus_selectbox_widget"] = None
                
            st.selectbox(
                "Select stock to view technicals:", 
                options=matched_tickers, 
                index=None if not current_focus or current_focus not in matched_tickers else matched_tickers.index(current_focus),
                placeholder="Select stock to focus...",
                key="screener_quick_focus_selectbox_widget",
                on_change=update_focus_from_tab2
            )
            
            # RENDER INSTANT VISUAL SCORECARD FEEDBACK
            focused_ticker = st.session_state["global_focus_ticker"]
            st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
            
            # Load details of the focused stock
            focus_row = df_stocks[df_stocks["ticker"] == focused_ticker]
            if not focus_row.empty:
                row = focus_row.iloc[0]
                name = row["company_name"]
                sector = row["sector"]
                tot_sc = row["total_score"]
                fund_sc = row["fundamental_score"]
                mom_sc = row["momentum_score"]
                price = row["last_price"]
                pe = row["pe_ratio"]
                roe = row["roe"]
                de = row["debt_to_equity"]
                rsi = row["rsi_14"]
                
                # Format pe & pb
                pe_str = f"{pe:.1f}x" if pd.notnull(pe) else "-"
                roe_str = f"{roe:.1f}%" if pd.notnull(roe) else "-"
                de_str = f"{de:.2f}" if pd.notnull(de) else "-"
                rsi_str = f"{rsi:.1f}" if pd.notnull(rsi) else "-"
                
                st.markdown(
                    f"""<div style="background-color: #f0fdf4; border: 2.5px solid #22c55e; border-radius: 12px; padding: 20px; box-shadow: 0 4px 10px rgba(34,197,94,0.08); margin-bottom: 15px;">
<div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 10px;">
<div>
<span style="font-size: 0.8rem; color: #15803d; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em; background-color: #dcfce7; padding: 3px 8px; border-radius: 4px;">🟢 Active Focus Locked</span>
<h3 style="margin: 8px 0 2px 0; color: #166534; font-size: 1.45rem; font-weight: 800; margin-bottom: 4px;">
{focused_ticker.replace('.NS', '')} &nbsp;&bull;&nbsp; <span style="font-weight: 500; font-size: 1.2rem; color: #374151;">{name}</span>
</h3>
<p style="font-size: 0.95rem; color: #4b5563; margin: 4px 0 0 0; font-weight: 600;">
Sector: <strong style="color: #111827;">{sector}</strong> &nbsp;&bull;&nbsp; Price: <strong style="color: #111827;">₹{price:,.2f}</strong>
</p>
</div>
<div style="text-align: right; min-width: 140px;">
<span style="font-size: 0.82rem; color: #4b5563; font-weight: 700;">Quantamental Rank</span>
<div style="font-size: 1.8rem; font-weight: 900; color: #15803d; font-family: 'JetBrains Mono', monospace; line-height: 1;">
{int(tot_sc)}<span style="font-size: 1rem; color: #4b5563; font-weight: 500;">/100</span>
</div>
</div>
</div>
<hr style="border-color: #bbf7d0; margin: 12px 0;">
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 10px; text-align: center;">
<div style="background-color: #ffffff; padding: 8px; border-radius: 6px; border: 1px solid #dcfce7;">
<span style="font-size: 0.75rem; color: #4b5563; font-weight: 700; text-transform: uppercase;">Fundamental</span>
<div style="font-size: 1.15rem; font-weight: 800; color: #166534; margin-top: 2px;">{int(fund_sc)}/50</div>
</div>
<div style="background-color: #ffffff; padding: 8px; border-radius: 6px; border: 1px solid #dcfce7;">
<span style="font-size: 0.75rem; color: #4b5563; font-weight: 700; text-transform: uppercase;">Momentum</span>
<div style="font-size: 1.15rem; font-weight: 800; color: #166534; margin-top: 2px;">{int(mom_sc)}/50</div>
</div>
<div style="background-color: #ffffff; padding: 8px; border-radius: 6px; border: 1px solid #dcfce7;">
<span style="font-size: 0.75rem; color: #4b5563; font-weight: 700; text-transform: uppercase;">P/E Ratio</span>
<div style="font-size: 1.15rem; font-weight: 800; color: #111827; margin-top: 2px;">{pe_str}</div>
</div>
<div style="background-color: #ffffff; padding: 8px; border-radius: 6px; border: 1px solid #dcfce7;">
<span style="font-size: 0.75rem; color: #4b5563; font-weight: 700; text-transform: uppercase;">ROE</span>
<div style="font-size: 1.15rem; font-weight: 800; color: #111827; margin-top: 2px;">{roe_str}</div>
</div>
<div style="background-color: #ffffff; padding: 8px; border-radius: 6px; border: 1px solid #dcfce7;">
<span style="font-size: 0.75rem; color: #4b5563; font-weight: 700; text-transform: uppercase;">RSI (14d)</span>
<div style="font-size: 1.15rem; font-weight: 800; color: #15803d; margin-top: 2px;">{rsi_str}</div>
</div>
</div>
<div style="margin-top: 15px; background-color: #dcfce7; border: 1px dashed #22c55e; border-radius: 6px; padding: 10px; text-align: center;">
<span style="font-size: 0.92rem; color: #14532d; font-weight: 700;">
👉 Active Stock Focus is synced! Click the <strong>📈 Candlestick Analytics</strong> or <strong>⚖️ P/E Valuation Bands</strong> tab at the top of the page to view detailed charts for {focused_ticker.replace('.NS', '')}.
</span>
</div>
</div>""",
                    unsafe_allow_html=True
                )
    else:
        st.warning("No stocks matched your active screener filter parameters. Adjust sliders to expand search.")
        
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 3: CANDLESTICK ANALYTICS
# ==========================================
with tab_charting:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("### Interactive Candlestick Canvas", unsafe_allow_html=True)
    
    # Synchronized with Global Sidebar Stock Focus Selector
    selected_chart_ticker = global_focus_ticker
    
    if not selected_chart_ticker:
        st.info("🎯 **No stock focused.** Please select a stock from the sidebar dropdown or click a row in the performance table to view its candlestick chart.")
    else:
        st.info(f"Showing Candlestick Canvas for focus stock: **`{selected_chart_ticker}`** (Sync'd with Sidebar Focus)")
        
        # Timeframe Controls (Period & Candle Timeframe Selectors)
        ch_col1, ch_col2 = st.columns(2)
        with ch_col1:
            period_label_map = {
                "5 Days (Intraday)": "5d",
                "1 Month (Short Swing)": "1mo",
                "3 Months (Swing)": "3mo",
                "6 Months (Intermediate)": "6mo",
                "1 Year (Standard)": "1y",
                "2 Years (Long-Term)": "2y",
                "5 Years (Macro)": "5y"
            }
            selected_period_label = st.selectbox(
                "Select Time Period", 
                options=list(period_label_map.keys()), 
                index=4, # Default: 1 Year (Standard)
                key="chart_selected_period"
            )
            selected_period = period_label_map[selected_period_label]
            
        with ch_col2:
            # Dynamically filter intervals to prevent yfinance API errors
            if selected_period == "5d":
                interval_options = ["15m", "30m", "1h", "1d"]
                default_int_idx = 0 # 15m
            elif selected_period in ["1mo", "3mo"]:
                interval_options = ["30m", "1h", "1d", "1wk"]
                default_int_idx = 2 # 1d
            elif selected_period == "6mo":
                interval_options = ["1h", "1d", "1wk"]
                default_int_idx = 1 # 1d
            else: # 1y, 2y, 5y
                interval_options = ["1d", "1wk", "1mo"]
                default_int_idx = 0 # 1d
                
            selected_interval = st.selectbox(
                "Select Candle Interval", 
                options=interval_options, 
                index=default_int_idx,
                key="chart_selected_interval"
            )
        
        # Retrieve technical price data
        try:
            chart_stock = yf.Ticker(selected_chart_ticker)
            df_chart = chart_stock.history(period=selected_period, interval=selected_interval)
            
            if not df_chart.empty:
                # 1. Format X-axis labels to string to force categorical clean timeframes (hiding weekends/overnight gaps)
                df_chart = df_chart.copy()
                if selected_interval in ["15m", "30m", "1h"]:
                    df_chart["DateStr"] = df_chart.index.strftime("%b %d, %H:%M")
                else:
                    df_chart["DateStr"] = df_chart.index.strftime("%b %d, %Y")
                    
                df_chart["20 EMA"] = df_chart["Close"].ewm(span=20, adjust=False).mean()
                df_chart["50 EMA"] = df_chart["Close"].ewm(span=50, adjust=False).mean()
                df_chart["200 SMA"] = df_chart["Close"].rolling(window=min(200, len(df_chart))).mean()
                
                # Plotly Candlestick Chart
                fig_candle = go.Figure()
                
                # Candles
                fig_candle.add_trace(go.Candlestick(
                    x=df_chart['DateStr'],
                    open=df_chart['Open'],
                    high=df_chart['High'],
                    low=df_chart['Low'],
                    close=df_chart['Close'],
                    name="Price"
                ))
                
                # Moving Averages
                fig_candle.add_trace(go.Scatter(x=df_chart['DateStr'], y=df_chart["20 EMA"], name="20 EMA", line=dict(color="#3B82F6", width=1.5)))
                fig_candle.add_trace(go.Scatter(x=df_chart['DateStr'], y=df_chart["50 EMA"], name="50 EMA", line=dict(color="#8B5CF6", width=1.5)))
                fig_candle.add_trace(go.Scatter(x=df_chart['DateStr'], y=df_chart["200 SMA"], name="200 SMA", line=dict(color="#EF4444", width=2)))
                
                fig_candle.update_layout(
                    title=f"{selected_chart_ticker} Candlestick Chart (Period: {selected_period_label}, Interval: {selected_interval})",
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    xaxis_rangeslider_visible=False,
                    xaxis=dict(
                        type='category',
                        gridcolor='rgba(0,0,0,0.05)', 
                        color='#475569',
                        nticks=12
                    ),
                    yaxis=dict(gridcolor='rgba(0,0,0,0.05)', color='#475569'),
                    height=450,
                    legend=dict(font=dict(color='#0F172A'))
                )
                
                st.plotly_chart(fig_candle, use_container_width=True)
                
                # Volume bar chart underneath
                fig_vol = px.bar(df_chart, x="DateStr", y="Volume", labels={"Volume": "Volume Traded"})
                fig_vol.update_traces(marker_color="#CBD5E1")
                fig_vol.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    xaxis=dict(
                        type='category',
                        gridcolor='rgba(0,0,0,0.05)', 
                        color='#475569',
                        nticks=12
                    ),
                    yaxis=dict(gridcolor='rgba(0,0,0,0.05)', color='#475569'),
                    height=150
                )
                st.plotly_chart(fig_vol, use_container_width=True)
                
            else:
                st.error("No historical candlestick data found for the selected ticker.")
        except Exception as e:
            st.error(f"Error drawing candlestick canvas: {e}")
            
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 4: P/E VALUATION BANDS
# ==========================================
with tab_pe_valuation:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("### Historical P/E Standard Deviation Valuation Bands", unsafe_allow_html=True)
    st.markdown("<p style='color: var(--text-secondary); margin-top:-10px; margin-bottom: 20px;'>Plot your stock price against historical valuation multiples to detect real-time bargains or speculative excesses.</p>", unsafe_allow_html=True)
    
    # Synchronized with Global Sidebar Stock Focus Selector
    selected_val_ticker = global_focus_ticker
    
    if not selected_val_ticker:
        st.info("🎯 **No stock focused.** Please select a stock from the sidebar dropdown or click a row in the performance table to view its P/E valuation bands.")
    else:
        st.info(f"Showing P/E Valuation Bands for focus stock: **`{selected_val_ticker}`** (Sync'd with Sidebar Focus)")
        
        try:
            val_stock = yf.Ticker(selected_val_ticker)
            
            # Load EPS info
            stock_info = val_stock.info
            eps = stock_info.get("trailingEps")
            
            hist_val = val_stock.history(period="1y", interval="1d")
            
            if eps and eps > 0 and not hist_val.empty:
                # 1. Format X-axis labels to string to force categorical clean timelines (excluding weekends)
                hist_val = hist_val.copy()
                hist_val["DateStr"] = hist_val.index.strftime("%b %d, %Y")
                
                # Generate P/E bands (Price = EPS * P/E multiple)
                # We map multiples based on the stock's current PE ratio
                current_pe = stock_info.get("trailingPE", 25.0)
                
                multiples = [current_pe * 0.7, current_pe * 0.85, current_pe, current_pe * 1.15, current_pe * 1.3]
                labels = ["Low PE Band", "Discount PE Band", "Median PE Band", "Premium PE Band", "Extreme PE Band"]
                colors = ["#10B981", "#3B82F6", "#8B5CF6", "#F59E0B", "#EF4444"]
                
                fig_bands = go.Figure()
                # Standard Stock Close Price
                fig_bands.add_trace(go.Scatter(x=hist_val["DateStr"], y=hist_val["Close"], name="Stock Price", line=dict(color="#0F172A", width=2.5)))
                
                # Draw standard multiples bands
                for mult, label, color in zip(multiples, labels, colors):
                    band_price = eps * mult
                    fig_bands.add_trace(go.Scatter(
                        x=hist_val["DateStr"], 
                        y=[band_price] * len(hist_val), 
                        name=f"{label} ({mult:.1f}x)", 
                        line=dict(color=color, width=1.5, dash='dash')
                    ))
                    
                fig_bands.update_layout(
                    title=f"{selected_val_ticker} Price Overlay on EPS-PE Valuation Bands (EPS: ₹{eps:.2f})",
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    xaxis=dict(
                        type='category',
                        gridcolor='rgba(0,0,0,0.05)', 
                        color='#475569',
                        nticks=12
                    ),
                    yaxis=dict(gridcolor='rgba(0,0,0,0.05)', color='#475569'),
                    height=450,
                    legend=dict(font=dict(color='#0F172A'))
                )
                st.plotly_chart(fig_bands, use_container_width=True)
                
                st.markdown(
                    f"""
                    > [!TIP]
                    > **Valuation Interpretation**: If the stock price trades close to the **Low PE Band** (green) or **Discount PE Band** (blue), it indicates a strong historical value buy scenario. 
                    > Trading near the **Extreme PE Band** (red) flags relative overvaluation relative to its trailing earnings.
                    """
                )
            else:
                st.warning("Trailing EPS is negative or unavailable for this stock. P/E standard deviation valuation bands cannot be modeled for loss-making corporations.")
        except Exception as e:
            st.error(f"Error modeling valuation bands: {e}")
            
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 5: F&O DERIVATIVES & HEATMAP
# ==========================================
with tab_fno:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    
    # 1. Heatmap Title and LTP filter in columns
    heat_h1, heat_h2 = st.columns([3, 1])
    with heat_h1:
        st.markdown("### 📊 F&O Sector Rotational Heatmap", unsafe_allow_html=True)
        st.markdown("<p style='color: var(--text-secondary); margin-top:-10px; margin-bottom: 25px;'>Instantly visualize the momentum structure and scale of derivative-eligible (F&O) stocks grouped by sector. Size represents Market Cap; color represents Momentum Intensity. Click any stock box in the heatmap below to instantly focus charts and option chains on that stock!</p>", unsafe_allow_html=True)
    with heat_h2:
        heat_min_price = st.number_input("Min LTP Filter (₹)", min_value=0.0, value=0.0, step=100.0, key="heatmap_min_ltp_filter_widget")
        
    # Filter only F&O stocks
    df_fno_only = df_stocks.copy()
    fno_symbols = get_fno_symbols()
    df_fno_only["is_fno"] = df_fno_only["ticker"].map(lambda t: 1 if t.replace(".NS", "") in fno_symbols else 0)
    df_fno_only = df_fno_only[df_fno_only["is_fno"] == 1]
    
    # Apply price filter to heatmap if set
    if heat_min_price > 0:
        df_fno_only = df_fno_only[df_fno_only["last_price"] >= heat_min_price]
        
    if df_fno_only.empty:
        st.info("Please run the Nifty 500 initial scan, or adjust your Min LTP Filter. Currently no stocks match the criteria.")
    else:
        # Plotly Treemap
        fig_treemap = px.treemap(
            df_fno_only,
            path=['sector', 'ticker'],
            values='market_cap_cr',
            color='momentum_score',
            color_continuous_scale='RdYlGn',
            title='F&O Market Structure Map (Sector Grouped) - CLICK BOX TO FOCUS',
            custom_data=['company_name', 'total_score', 'fundamental_score', 'momentum_score']
        )
        
        fig_treemap.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=10, r=10, t=30, b=10),
            height=500
        )
        
        fig_treemap.update_traces(
            hovertemplate="<b>%{label}</b><br>Sector: %{parent}<br>Market Cap: ₹%{value:,.0f} Cr<br>Momentum Score: %{color:.1f}/50<br><extra></extra>"
        )
        
        # Display Treemap with point selection enabled to capture clicks
        selection_event = st.plotly_chart(
            fig_treemap, 
            use_container_width=True,
            on_select="rerun",
            key="fno_treemap_click_selector"
        )
        
        # Capture clicks on Treemap boxes — updates ONLY the F&O tab focus (not global).
        # NOTE: on_select="rerun" already triggers a Streamlit rerun on click.
        # We must NOT call st.rerun() again here — a second rerun clears the Plotly
        # selection state, making the box appear to "snap back" and losing the ticker.
        if selection_event and "selection" in selection_event and selection_event["selection"]["points"]:
            points = selection_event["selection"]["points"]
            selected_point = points[0]
            selected_label = selected_point.get("label")
            # Only update if we clicked an actual ticker leaf (not a sector parent node)
            fno_ticker_options_click = sorted(list(df_fno_only["ticker"].unique()))
            if selected_label and selected_label in fno_ticker_options_click:
                # Update session state — the on_select rerun will re-render the OC below
                st.session_state["fno_tab_focus_ticker"] = selected_label
                # ← NO st.rerun() here; on_select already caused this rerun
                    
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Option Chain Visualizer Section
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("### ⛓️ Derivatives Option Chain Terminal", unsafe_allow_html=True)
        
        # Pull F&O symbols to populate the search dropdown
        fno_ticker_options = sorted(list(df_stocks["ticker"].unique()))
        # Show F&O eligible only in this search box
        fno_ticker_options = [t for t in fno_ticker_options if t.replace(".NS", "") in fno_symbols]
        
        # Initialise the F&O-local focus if not yet set
        if "fno_tab_focus_ticker" not in st.session_state or st.session_state["fno_tab_focus_ticker"] not in fno_ticker_options:
            if fno_ticker_options:
                st.session_state["fno_tab_focus_ticker"] = fno_ticker_options[0]

        # Safely sync the widget state to the F&O-local focus (independent of global)
        fno_current = st.session_state["fno_tab_focus_ticker"]
        if fno_current in fno_ticker_options:
            st.session_state["tab_fno_active_ticker_selector"] = fno_current
        else:
            if fno_ticker_options:
                st.session_state["tab_fno_active_ticker_selector"] = fno_ticker_options[0]
                
        oc_col1, oc_col2 = st.columns([3, 1])
        with oc_col1:
            st.selectbox(
                "🔍 Search & Select F&O Ticker to Focus", 
                options=fno_ticker_options, 
                key="tab_fno_active_ticker_selector",
                on_change=update_focus_from_tab5
            )
        with oc_col2:
            st.write("") 
            st.write("") 
            st.caption("ℹ️ Selecting here or clicking the heatmap updates only this F&O panel — your main chart focus is preserved.")
            
        selected_oc_ticker = st.session_state["fno_tab_focus_ticker"]
        st.info(f"Showing derivative option chain for: **`{selected_oc_ticker}`** · F&O Tab Focus (main chart focus unchanged)")
        
        # Fetch stock details from df_stocks
        stock_row = df_stocks[df_stocks["ticker"] == selected_oc_ticker]
        
        if stock_row.empty:
            st.warning("Selected stock details are not available in cache.")
        else:
            stock_row = stock_row.iloc[0]
            cached_price = stock_row["last_price"]
            rsi = stock_row["rsi_14"]
            company_name = stock_row["company_name"]
            sector_name = stock_row["sector"]
            
            # Fetch live real-time price from yfinance for active F&O underlying (takes <0.3s)
            last_price = cached_price
            try:
                live_ticker = yf.Ticker(selected_oc_ticker)
                live_hist = live_ticker.history(period="1d")
                if not live_hist.empty:
                    last_price = float(live_hist["Close"].iloc[-1])
            except Exception:
                pass  # Fallback to cached price if offline/network fails
            
            # Check if this stock is F&O eligible
            is_fno_eligible = selected_oc_ticker.replace(".NS", "") in fno_symbols
            
            if not is_fno_eligible:
                st.warning(f"⚠️ Notice: **`{selected_oc_ticker}`** is not part of the NSE F&O segment. Standard option chains are only modeled for derivatives-eligible stocks.")
            else:
                # 1. High-Readability Active Focus stock name card (Optimized for Visual Accessibility)
                st.markdown(
                    f"""
                    <div style="background-color: #F8FAFC; border: 3px solid #CBD5E1; border-radius: 14px; padding: 28px; margin-bottom: 28px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
                        <span style="font-size: 1.15rem; color: #475569; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; display: inline-block; margin-bottom: 8px;">🎯 Active Derivatives Focus</span>
                        <h1 style="font-size: 3.4rem; color: #0F172A; margin: 0; font-weight: 800; font-family: 'Outfit', sans-serif; line-height: 1.1;">
                            {selected_oc_ticker.replace('.NS', '')} &bull; <span style="font-size: 2.6rem; font-weight: 700; color: #334155;">{company_name}</span>
                        </h1>
                        <p style="font-size: 1.55rem; color: #475569; margin: 12px 0 0 0; font-weight: 600; line-height: 1.4;">
                            Sector: <strong style="color: #0F172A; text-decoration: underline; text-decoration-color: #CBD5E1;">{sector_name}</strong> &nbsp;&bull;&nbsp; Last Price: <strong style="color: #059669; font-size: 1.65rem;">₹ {last_price:,.2f}</strong> &nbsp;&bull;&nbsp; RSI (14d): <strong style="color: #1D4ED8; font-size: 1.65rem;">{rsi:.1f}</strong>
                        </p>
                        <div style="margin-top: 20px; display: flex; gap: 15px; align-items: center; border-top: 1.5px solid #E2E8F0; padding-top: 18px;">
                            <a href="http://localhost:8505/?add_ticker={selected_oc_ticker.replace('.NS', '')}&add_price={last_price:.2f}&add_segment=F%26O%20-%20Stock%20Options" target="_blank" style="background-color: #1D4ED8; color: #FFFFFF; font-weight: 700; padding: 10px 22px; border-radius: 8px; text-decoration: none; font-size: 1.1rem; display: inline-flex; align-items: center; box-shadow: 0 4px 12px rgba(29, 78, 216, 0.2); transition: all 0.2s ease;">
                                📝 Log Trade in Fin+ Trading Journal
                            </a>
                            <span style="font-size: 0.95rem; color: #64748B; font-weight: 500;">
                                Auto-populates Ticker, Live Price, and F&O Segment in your journal!
                            </span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                # ── Live News Panel with Sentiment Coloring ──────────────────────
                fno_news_items = fetch_live_stock_news(selected_oc_ticker)
                if fno_news_items:
                    fno_news_content = ""
                    for ni in fno_news_items:
                        sentiment = get_news_sentiment(ni["title"])
                        # Sentiment-driven visual tokens
                        if sentiment == "positive":
                            row_bg      = "#F0FDF4"   # soft green
                            border_col  = "#22C55E"   # green
                            dot_col     = "#16A34A"
                            badge_bg    = "#DCFCE7"
                            badge_color = "#15803D"
                            badge_label = "▲ Positive"
                            link_color  = "#14532D"
                        elif sentiment == "negative":
                            row_bg      = "#FFF1F2"   # soft red
                            border_col  = "#EF4444"   # red
                            dot_col     = "#DC2626"
                            badge_bg    = "#FEE2E2"
                            badge_color = "#991B1B"
                            badge_label = "▼ Negative"
                            link_color  = "#7F1D1D"
                        else:
                            row_bg      = "#F8FAFC"   # neutral slate
                            border_col  = "#94A3B8"
                            dot_col     = "#64748B"
                            badge_bg    = "#F1F5F9"
                            badge_color = "#475569"
                            badge_label = "● Neutral"
                            link_color  = "#1E40AF"

                        fno_news_content += f"""
                        <div style="display:flex; align-items:flex-start; gap:12px;
                                    margin-bottom:10px; padding:12px 14px;
                                    background:{row_bg}; border-radius:10px;
                                    border-left:4px solid {border_col};">
                            <div style="min-width:9px; width:9px; height:9px; border-radius:50%;
                                        background:{dot_col}; margin-top:6px; flex-shrink:0;"></div>
                            <div style="flex:1;">
                                <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px; flex-wrap:wrap;">
                                    <span style="font-size:0.72rem; color:{badge_color}; font-weight:800;
                                                 background:{badge_bg}; padding:2px 8px; border-radius:20px;
                                                 border:1px solid {border_col}; letter-spacing:0.04em;">{badge_label}</span>
                                    <span style="font-size:0.72rem; color:#64748B; font-weight:700;
                                                 text-transform:uppercase; letter-spacing:0.04em;">{ni['publisher']}</span>
                                </div>
                                <a href="{ni['link']}" target="_blank"
                                   style="color:{link_color}; font-weight:700; font-size:1.0rem;
                                          text-decoration:none; line-height:1.45;">
                                   {ni['title']}
                                </a>
                            </div>
                        </div>"""

                    st.markdown(
                        f"""
                        <div style="background:linear-gradient(135deg,#F8FAFC 0%,#EFF6FF 100%);
                                    border:1.5px solid #BFDBFE; border-left:5px solid #2563EB;
                                    border-radius:14px; padding:20px 24px; margin-bottom:24px;
                                    box-shadow:0 4px 12px rgba(37,99,235,0.06);">
                            <div style="display:flex; align-items:center; gap:8px; margin-bottom:14px;">
                                <span style="font-size:1.2rem;">📰</span>
                                <span style="font-size:0.88rem; font-weight:800; color:#1D4ED8;
                                             text-transform:uppercase; letter-spacing:0.06em;">
                                    Latest News &amp; Sentiment · {selected_oc_ticker.replace('.NS','')}
                                </span>
                                <span style="margin-left:auto; font-size:0.72rem; color:#64748B; font-weight:600;">
                                    <span style="color:#15803D; font-weight:800;">▲ Positive</span>
                                    &nbsp;/&nbsp;
                                    <span style="color:#991B1B; font-weight:800;">▼ Negative</span>
                                    &nbsp;/&nbsp;
                                    <span style="color:#475569;">● Neutral</span>
                                </span>
                            </div>
                            {fno_news_content}
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        f"""
                        <div style="background:#F8FAFC; border:1.5px solid #E2E8F0; border-left:5px solid #CBD5E1;
                                    border-radius:14px; padding:18px 24px; margin-bottom:24px;
                                    box-shadow:0 2px 6px rgba(0,0,0,0.03);">
                            <span style="font-size:0.88rem; font-weight:800; color:#64748B;
                                         text-transform:uppercase; letter-spacing:0.06em;">
                                📰 Latest News · {selected_oc_ticker.replace('.NS','')}
                            </span><br>
                            <span style="font-size:0.95rem; color:#94A3B8; font-style:italic; margin-top:6px; display:block;">
                                No recent news articles found for this symbol.
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                # ── End News Panel ─────────────────────────────────────────────────

                # Generate modeled option chain
                oc_results = generate_modeled_option_chain(last_price, rsi, selected_oc_ticker)
                
                # Render KPIs
                k_col1, k_col2, k_col3 = st.columns(3)
                with k_col1:
                    pcr_val = oc_results["pcr"]
                    pcr_status = "Bullish" if pcr_val > 1.0 else "Bearish" if pcr_val < 0.7 else "Neutral"
                    st.metric("Put-Call Ratio (PCR)", f"{pcr_val:.2f}", delta=pcr_status, delta_color="normal" if pcr_status == "Bullish" else "inverse" if pcr_status == "Bearish" else "off")
                with k_col2:
                    st.metric("Max Call OI (Major Resistance Strike)", f"₹ {oc_results['max_call_strike']:.1f}")
                with k_col3:
                    st.metric("Max Put OI (Major Support Strike)", f"₹ {oc_results['max_put_strike']:.1f}")
                    
                st.markdown("<br>", unsafe_allow_html=True)
                
                # Format into a professional two-sided option chain HTML table
                chain_data = oc_results["chain"]
                
                # Extract all OIs to identify maximums
                all_call_ois = [row["call_oi"] for row in chain_data]
                all_put_ois = [row["put_oi"] for row in chain_data]
                max_call_oi = max(all_call_ois) if all_call_ois else 0
                max_put_oi = max(all_put_ois) if all_put_ois else 0
                
                # Build HTML Option Chain (High-Readability for Visual Accessibility)
                oc_html = f"""<div style="overflow-x: auto; margin-top: 15px;">
<table style="width:100%; border-collapse: collapse; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 1.2rem; border: 2px solid #94A3B8; text-align: center;">
    <thead>
        <tr style="background-color: #0F172A; color: #FFFFFF; font-weight: 800; height: 52px; font-size: 1.25rem;">
            <th style="padding: 14px; border: 2px solid #334155; width: 22%;">Call Price (CE LTP)</th>
            <th style="padding: 14px; border: 2px solid #334155; width: 22%;">Call Open Interest (CE OI)</th>
            <th style="padding: 14px; border: 2px solid #334155; width: 12%;">Strike Price</th>
            <th style="padding: 14px; border: 2px solid #334155; width: 22%;">Put Open Interest (PE OI)</th>
            <th style="padding: 14px; border: 2px solid #334155; width: 22%;">Put Price (PE LTP)</th>
        </tr>
    </thead>
    <tbody>"""
                
                for row in chain_data:
                    strike = row["strike"]
                    is_atm = abs(strike - last_price) < (last_price * 0.015)
                    
                    # Style Strike Price Column
                    strike_style = "font-weight: 800; border: 2px solid #CBD5E1; padding: 12px; background-color: #F1F5F9; color: #0F172A; font-size: 1.2rem;"
                    strike_label = f"₹ {strike:,.1f}"
                    if is_atm:
                        strike_style = "font-weight: 900; border: 3px solid #2563EB; padding: 12px; background-color: #DBEAFE; color: #1E40AF; font-size: 1.25rem;"
                        strike_label += " ⭐ ATM"
                        
                    # Style Call OI Column: Highlight Max Call OI in vibrant high-contrast green
                    call_oi_style = "border: 2px solid #CBD5E1; padding: 12px; color: #334155; font-weight: 500; font-size: 1.2rem;"
                    call_oi_val = f"{row['call_oi']:,}"
                    if row["call_oi"] == max_call_oi and max_call_oi > 0:
                        call_oi_style = "background-color: #D1FAE5; color: #065F46; font-weight: 900; border: 3.5px solid #10B981; padding: 12px; font-size: 1.35rem; box-shadow: inset 0 0 4px rgba(16,185,129,0.2);"
                        call_oi_val = f"🔥 {call_oi_val} (MAX CE)"
                        
                    # Style Put OI Column: Highlight Max Put OI in vibrant high-contrast red
                    put_oi_style = "border: 2px solid #CBD5E1; padding: 12px; color: #334155; font-weight: 500; font-size: 1.2rem;"
                    put_oi_val = f"{row['put_oi']:,}"
                    if row["put_oi"] == max_put_oi and max_put_oi > 0:
                        put_oi_style = "background-color: #FEE2E2; color: #991B1B; font-weight: 900; border: 3.5px solid #EF4444; padding: 12px; font-size: 1.35rem; box-shadow: inset 0 0 4px rgba(239,68,68,0.2);"
                        put_oi_val = f"🔥 {put_oi_val} (MAX PE)"
                        
                    oc_html += f"""<tr style="height: 50px;">
    <td style="border: 2px solid #CBD5E1; padding: 12px; color: #0F172A; font-weight: 600; font-size: 1.2rem;">₹ {row['call_price']:.2f}</td>
    <td style="{call_oi_style}">{call_oi_val}</td>
    <td style="{strike_style}">{strike_label}</td>
    <td style="{put_oi_style}">{put_oi_val}</td>
    <td style="border: 2px solid #CBD5E1; padding: 12px; color: #0F172A; font-weight: 600; font-size: 1.2rem;">₹ {row['put_price']:.2f}</td>
</tr>"""
                    
                oc_html += """</tbody>
</table>
</div>"""
                
                st.markdown("<h3 style='font-size: 1.6rem; color: #0F172A; margin-top: 15px;'>⚖️ Two-Sided Derivative Board (Calls vs. Puts)</h3>", unsafe_allow_html=True)
                st.markdown(oc_html, unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)
                
                st.markdown(
                    """
                    > [!TIP]
                    > **Derivatives Strategy Analysis**:
                    > * **Major Resistance (Green Highlight)**: The strike price with the largest Call OI (shown under CE OI) represents heavy call writing, acting as a ceiling barrier.
                    > * **Major Support (Red Highlight)**: The strike price with the largest Put OI (shown under PE OI) represents heavy put writing, acting as a flooring cushion.
                    > * **PCR Trend**: A Put-Call Ratio above 1.0 indicates derivative writers are heavily writing puts (indexing a strongly bullish floor), whereas a PCR below 0.7 signals defensive call writing, warning of bearish limits.
                    """
                )
                
        st.markdown('</div>', unsafe_allow_html=True)


