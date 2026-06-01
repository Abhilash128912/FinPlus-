import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import xml.etree.ElementTree as ET
import math
from datetime import datetime, timedelta

# Import database settings from local database file if exists
try:
    import database
except ImportError:
    database = None

# Set Streamlit Page Configuration
st.set_page_config(
    page_title="FinPlus MCX Energy Workstation",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling (Light Institutional Neumorphic Theme matching styles.css)
st.markdown("""
<style>
    :root {
        --primary-color: #4F46E5;
        --secondary-color: #10B981;
        --bg-color: #F8FAFC;
        --card-bg: #FFFFFF;
        --border-color: #E2E8F0;
        --text-color: #0F172A;
        --text-secondary: #475569;
        --success-color: #059669;
        --error-color: #DC2626;
    }
    
    .stApp {
        background-color: var(--bg-color) !important;
        color: var(--text-color) !important;
        font-family: 'Plus Jakarta Sans', 'Outfit', sans-serif !important;
    }
    
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #0F172A 30%, #334155 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
        letter-spacing: -0.02em;
    }
    
    .sub-title {
        font-size: 1rem;
        color: var(--text-secondary);
        margin-bottom: 1.5rem;
    }
    
    .premium-card {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-bottom: 5px solid #CBD5E1; /* Raised neomorphic bevel */
        border-radius: 16px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 10px 18px -4px rgba(0, 0, 0, 0.04), 0 4px 6px -2px rgba(0, 0, 0, 0.02);
        color: var(--text-color) !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    .premium-card:hover {
        border-color: #A7F3D0;
        border-bottom-color: #10B981;
        transform: translateY(-4px);
    }
    
    .price-value {
        font-size: 2.5rem;
        font-weight: 800;
        color: var(--text-color);
        margin: 0.5rem 0;
    }
    
    .metric-label {
        font-size: 0.85rem;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
    }
    
    .status-bullish {
        color: var(--success-color);
        font-weight: 700;
    }
    
    .status-bearish {
        color: var(--error-color);
        font-weight: 700;
    }
    
    .status-neutral {
        color: #d97706;
        font-weight: 700;
    }
    
    .news-item {
        border-bottom: 1px solid var(--border-color);
        padding: 0.8rem 0;
    }
    
    .news-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: var(--text-color) !important;
        text-decoration: none;
        transition: color 0.2s;
    }
    
    .news-title:hover {
        color: var(--primary-color) !important;
    }
    
    .news-meta {
        font-size: 0.75rem;
        color: var(--text-secondary);
        margin-top: 0.3rem;
    }
    
    /* Sidebar high contrast matching main styles.css */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid var(--border-color) !important;
    }
    
    /* Neumorphic Metric containers */
    div[data-testid="metric-container"] {
        background: var(--card-bg) !important;
        border: 1px solid var(--border-color) !important;
        border-bottom: 4px solid #CBD5E1 !important;
        border-radius: 14px !important;
        padding: 14px 18px !important;
        box-shadow: 0 6px 12px -3px rgba(0, 0, 0, 0.03) !important;
    }
    
    div[data-testid="stMetricValue"] {
        font-family: 'Outfit', sans-serif !important;
        font-size: 1.6rem !important;
        font-weight: 700 !important;
        color: var(--text-color) !important;
    }
    
    /* Neumorphic Tab bar matching main styles.css */
    div[data-testid="stTabBar"] {
        background: #F1F5F9 !important;
        border-radius: 12px !important;
        padding: 4px !important;
        margin-bottom: 24px !important;
        border: 1px solid var(--border-color) !important;
    }
    
    button[data-testid="stTabBarTab"] {
        font-family: 'Outfit', sans-serif !important;
        font-weight: 500 !important;
        color: var(--text-secondary) !important;
        border-radius: 8px !important;
        transition: all 0.2s ease !important;
    }
    
    button[data-testid="stTabBarTab"][aria-selected="true"] {
        background: #FFFFFF !important;
        color: var(--text-color) !important;
        font-weight: 600 !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05) !important;
    }
    
    /* Inputs background fix for readability */
    div[data-baseweb="input"], div[data-baseweb="select"], div[data-baseweb="textarea"] {
        background-color: #FFFFFF !important;
        border: 1px solid #CBD5E1 !important;
        color: var(--text-color) !important;
    }
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------
# News & Inventory Feed Functions (Free/Tokenless)
# ----------------------------------------------------
@st.cache_data(ttl=900) # Cache news for 15 minutes
def fetch_energy_news():
    """Fetches real-time energy commodity news from OilPrice.com free RSS feed."""
    try:
        url = "https://oilprice.com/rss/main"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            news_items = []
            for item in root.findall(".//item")[:6]: # Get top 6 energy news
                title = item.find("title").text
                link = item.find("link").text
                pub_date = item.find("pubDate").text
                
                # Standardize date output
                try:
                    dt = datetime.strptime(pub_date[:-6], "%a, %d %b %Y %H:%M:%S")
                    dt_ist = dt + timedelta(hours=5, minutes=30)
                    date_str = dt_ist.strftime("%d %b, %I:%M %p IST")
                except Exception:
                    date_str = pub_date
                    
                news_items.append({"title": title, "link": link, "date": date_str})
            return news_items
    except Exception:
        pass
    return []

def get_eia_countdown():
    """Calculates active countdown to the next weekly EIA Crude Oil & Natural Gas Reports (Wed/Thu 8:00 PM IST)."""
    now = datetime.now()
    
    # Standard U.S. EIA Release is 10:30 AM Eastern = 8:00 PM IST
    # 1. Crude Oil (Wednesdays 8:00 PM IST)
    wed = now.replace(hour=20, minute=0, second=0, microsecond=0)
    while wed.weekday() != 2 or wed < now:
        wed += timedelta(days=1)
    
    # 2. Natural Gas (Thursdays 8:00 PM IST)
    thu = now.replace(hour=20, minute=0, second=0, microsecond=0)
    while thu.weekday() != 3 or thu < now:
        thu += timedelta(days=1)
        
    crude_diff = wed - now
    ng_diff = thu - now
    
    def format_diff(diff):
        days = diff.days
        hours = diff.seconds // 3600
        mins = (diff.seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h left"
        elif hours > 0:
            return f"{hours}h {mins}m left"
        else:
            return f"{mins}m left (RELEASE IMMINENT ⚠️)"
            
    return format_diff(crude_diff), format_diff(ng_diff)

# ----------------------------------------------------
# Technical Analysis Helpers (NYMEX Proxy)
# ----------------------------------------------------
def clean_yf_df(df):
    """Robust helper to flatten MultiIndex columns returned by newer yfinance versions."""
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def calculate_mfi(df, period=14):
    """Calculates Money Flow Index (MFI) to track institutional buying vs selling volume imbalance."""
    try:
        tp = (df['High_INR'] + df['Low_INR'] + df['Close_INR']) / 3.0
        rmf = tp * df['Volume']
        
        pos_flow = pd.Series(0.0, index=df.index)
        neg_flow = pd.Series(0.0, index=df.index)
        
        tp_prev = tp.shift(1)
        
        pos_mask = tp > tp_prev
        neg_mask = tp < tp_prev
        
        pos_flow[pos_mask] = rmf[pos_mask]
        neg_flow[neg_mask] = rmf[neg_mask]
        
        pos_sum = pos_flow.rolling(window=period).sum()
        neg_sum = neg_flow.rolling(window=period).sum()
        
        mfr = pos_sum / (neg_sum + 1e-9)
        mfi = 100 - (100 / (1.0 + mfr))
        return mfi
    except Exception:
        return pd.Series(50.0, index=df.index)

@st.cache_data(ttl=1800)
def fetch_nymex_trends(ticker, usdinr):
    """Fetches daily NYMEX prices, converts to INR, and calculates technical indicators for swing trading."""
    try:
        df = yf.download(ticker, period="60d", interval="1d", progress=False)
        df = clean_yf_df(df)
        if df is None or df.empty:
            return None
        
        # Convert prices from USD to INR
        df['Close_INR'] = df['Close'] * usdinr
        df['High_INR'] = df['High'] * usdinr
        df['Low_INR'] = df['Low'] * usdinr
        df['Open_INR'] = df['Open'] * usdinr
        
        # 1. EMAs for 3-5 days momentum
        df['EMA9'] = df['Close_INR'].ewm(span=9, adjust=False).mean()
        df['EMA21'] = df['Close_INR'].ewm(span=21, adjust=False).mean()
        df['SMA50'] = df['Close_INR'].rolling(window=50).mean()
        
        # 2. RSI (14)
        delta = df['Close_INR'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 3. ATR (14) for stop-loss distance calculation
        high_low = df['High_INR'] - df['Low_INR']
        high_cp = np.abs(df['High_INR'] - df['Close_INR'].shift())
        low_cp = np.abs(df['Low_INR'] - df['Close_INR'].shift())
        tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(14).mean()
        
        # 4. Money Flow Index (14)
        df['MFI'] = calculate_mfi(df)
        
        return df
    except Exception:
        return None

# ----------------------------------------------------
# Main Application Flow
# ----------------------------------------------------
# Title Header
st.markdown("<h1 class='main-title'>🛢️ FinPlus MCX Energy Workstation</h1>", unsafe_allow_html=True)
st.markdown("<p class='sub-title'>Highly optimized, tokenless energy swing dashboard powered strictly by NYMEX global benchmarks</p>", unsafe_allow_html=True)

# 1. Fetch USDINR & NYMEX Live spot pricing
try:
    usdinr_ticker = yf.Ticker("USDINR=X")
    usdinr_hist = usdinr_ticker.history(period="1d")
    usdinr_hist = clean_yf_df(usdinr_hist)
    usdinr = float(usdinr_hist['Close'].iloc[-1])
except Exception:
    usdinr = 83.50 # Standard fallback

# Fetch NYMEX Spot Estimates
nymex_symbols = {"CRUDEOIL": "CL=F", "NATURALGAS": "NG=F"}
spot_prices = {}
for key, tick in nymex_symbols.items():
    try:
        ticker_obj = yf.Ticker(tick)
        hist = ticker_obj.history(period="1d")
        hist = clean_yf_df(hist)
        spot_prices[key] = float(hist['Close'].iloc[-1])
    except Exception:
        spot_prices[key] = 75.0 if key == "CRUDEOIL" else 2.50

# Apply NYMEX proxy pricing directly
live_prices = {}
for symbol in ["CRUDEOIL", "NATURALGAS"]:
    live_prices[symbol] = round(spot_prices[symbol] * usdinr, 2)
# Map NATGASMINI to use identical spot conversion
live_prices["NATGASMINI"] = live_prices["NATURALGAS"]

# Calculate percentage changes
pct_changes = {}
for symbol in ["CRUDEOIL", "NATURALGAS"]:
    try:
        t_obj = yf.Ticker(nymex_symbols[symbol])
        hist = t_obj.history(period="2d")
        hist = clean_yf_df(hist)
        prev = hist['Close'].iloc[0]
        curr = hist['Close'].iloc[1]
        pct_changes[symbol] = ((curr - prev) / prev) * 100
    except Exception:
        pct_changes[symbol] = 0.0

# ----------------------------------------------------
# Price Feed Customizer & Manual Overrides
# ----------------------------------------------------
st.sidebar.markdown("### ⚡ Price Feed Customizer")
enable_override = st.sidebar.checkbox(
    "Manual MCX Price Override", 
    help="Enable to manually input active MCX prices when NYMEX global feeds are closed or static."
)
if enable_override:
    override_crude = st.sidebar.number_input("Crude Oil MCX Price (₹)", min_value=100.0, value=float(live_prices["CRUDEOIL"]), step=10.0)
    override_ng = st.sidebar.number_input("Natural Gas MCX Price (₹)", min_value=1.0, value=float(live_prices["NATURALGAS"]), step=1.0)
    
    # Overwrite the feed prices
    live_prices["CRUDEOIL"] = round(override_crude, 2)
    live_prices["NATURALGAS"] = round(override_ng, 2)
    live_prices["NATGASMINI"] = round(override_ng, 2)

# ----------------------------------------------------
# Sidebar Information Panel
# ----------------------------------------------------
st.sidebar.markdown("### 📊 MCX Contract Specs")
st.sidebar.info("""
**🛢️ Crude Oil (1 Lot):**
*   Lot Size: 100 Barrels
*   Futures Symbol: CRUDEOIL
*   Option Symbol: CRUDEOIL Strike

**🔥 Natural Gas Mega (1 Lot):**
*   Lot Size: 1250 MMBtu
*   Futures Symbol: NATURALGAS
*   Option Symbol: NATURALGAS Strike

**🔥 Natural Gas Mini (1 Lot):**
*   Lot Size: 250 MMBtu
*   Futures Symbol: NATGASMINI
""")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📈 Live USDINR Exchange Rate")
st.sidebar.metric("USD to INR Conversion", f"₹{usdinr:.2f}", help="Used to dynamically convert NYMEX WTI/Henry Hub prices to MCX INR equivalent prices in real-time.")

# ----------------------------------------------------
# Main Layout Tabs
# ----------------------------------------------------
tab_dash, tab_news, tab_calc = st.tabs(["📊 Energy Swing Dashboard", "📰 Live Energy News & Reports", "🧮 Swing Trade Planner"])

# Tab 1: Dashboard
with tab_dash:
    st.info(f"⚡ **Pricing Mode:** NYMEX Global Correlation Conversion (Token-Free) | **Live Spot Conversion Active**")
    
    col1, col2 = st.columns(2)
    
    # Crude Oil Column
    with col1:
        st.markdown("""
        <div class='premium-card'>
            <div class='metric-label'>🛢️ CRUDE OIL (MCX Indicative)</div>
        """, unsafe_allow_html=True)
        
        price = live_prices["CRUDEOIL"]
        change = pct_changes["CRUDEOIL"]
        change_class = "status-bullish" if change >= 0 else "status-bearish"
        change_sign = "+" if change >= 0 else ""
        
        st.markdown(f"<div class='price-value'>₹{price:,.2f}</div>", unsafe_allow_html=True)
        st.markdown(f"<p class='{change_class}'>{change_sign}{change:.2f}% (NYMEX Global Today)</p>", unsafe_allow_html=True)
        
        # Load Indicators
        df_crude = fetch_nymex_trends("CL=F", usdinr)
        if df_crude is not None:
            last_row = df_crude.iloc[-1]
            ema9 = last_row['EMA9']
            ema21 = last_row['EMA21']
            rsi = last_row['RSI']
            atr = last_row['ATR']
            mfi = last_row['MFI']
            
            if ema9 > ema21:
                trend_desc = "Bullish Momentum ✅"
                trend_class = "status-bullish"
            else:
                trend_desc = "Bearish / Sideways Crossover ⚠️"
                trend_class = "status-bearish"
                
            # Determine Money Flow Index State
            if mfi > 80:
                mfi_desc = "Hyper-Accumulation"
                mfi_class = "status-bullish"
                mfi_color = "var(--success-color)"
            elif mfi > 60:
                mfi_desc = "Buying Pressure"
                mfi_class = "status-bullish"
                mfi_color = "#10B981"
            elif mfi > 40:
                mfi_desc = "Neutral Money Flow"
                mfi_class = "status-neutral"
                mfi_color = "#d97706"
            elif mfi > 20:
                mfi_desc = "Selling Pressure"
                mfi_class = "status-bearish"
                mfi_color = "#EF4444"
            else:
                mfi_desc = "Selling Exhaustion"
                mfi_class = "status-bearish"
                mfi_color = "var(--error-color)"
                
            prev_row = df_crude.iloc[-2]
            p_high = prev_row['High_INR']
            p_low = prev_row['Low_INR']
            p_close = prev_row['Close_INR']
            
            pivot = (p_high + p_low + p_close) / 3
            r1 = (2 * pivot) - p_low
            s1 = (2 * pivot) - p_high
            
            st.markdown(f"""
            <table style='width:100%; border-collapse:collapse; margin-top:1rem;'>
                <tr>
                    <td style='color:#8b949e; padding:5px 0;'>EMA Crossover (9/21):</td>
                    <td class='{trend_class}' style='text-align:right;'>{trend_desc}</td>
                </tr>
                <tr>
                    <td style='color:#8b949e; padding:5px 0;'>Daily RSI (14):</td>
                    <td style='text-align:right; font-weight:600;'>{rsi:.1f}</td>
                </tr>
                <tr>
                    <td style='color:#8b949e; padding:5px 0;'>Daily ATR (14):</td>
                    <td style='text-align:right; font-weight:600;'>{atr:.2f} pts</td>
                </tr>
                <tr style='border-top:1px solid var(--border-color);'>
                    <td style='color:#8b949e; padding:8px 0 4px 0;'>Money Flow Index (14):</td>
                    <td class='{mfi_class}' style='text-align:right; font-weight:700; padding:8px 0 4px 0;'>{mfi:.1f}% ({mfi_desc})</td>
                </tr>
                <tr>
                    <td colspan='2' style='padding-bottom:10px;'>
                        <div style='background-color:#E2E8F0; border-radius:10px; width:100%; height:8px;'>
                            <div style='background-color:{mfi_color}; width:{mfi}%; height:8px; border-radius:10px;'></div>
                        </div>
                    </td>
                </tr>
                <tr style='border-top: 1px solid var(--border-color);'>
                    <td style='color:#8b949e; padding:8px 0 4px 0;'>Daily Pivot Level:</td>
                    <td style='text-align:right; font-weight:600; padding:8px 0 4px 0;'>₹{pivot:,.2f}</td>
                </tr>
                <tr>
                    <td style='color:var(--success-color); padding:4px 0;'>Swing Target (R1):</td>
                    <td style='text-align:right; font-weight:600; color:var(--success-color);'>₹{r1:,.2f}</td>
                </tr>
                <tr>
                    <td style='color:var(--error-color); padding:4px 0;'>Swing Stop (S1):</td>
                    <td style='text-align:right; font-weight:600; color:var(--error-color);'>₹{s1:,.2f}</td>
                </tr>
            </table>
            """, unsafe_allow_html=True)
            
            st.markdown("<p class='metric-label' style='margin-top:1.5rem;'>30-Day Daily Chart</p>", unsafe_allow_html=True)
            st.line_chart(df_crude.tail(30)[['Close_INR', 'EMA9', 'EMA21']])
            
        st.markdown("</div>", unsafe_allow_html=True)
        
    # Natural Gas Column
    with col2:
        st.markdown("""
        <div class='premium-card'>
            <div class='metric-label'>🔥 NATURAL GAS / NG MINI (MCX Indicative)</div>
        """, unsafe_allow_html=True)
        
        price_ng = live_prices["NATURALGAS"]
        change_ng = pct_changes["NATURALGAS"]
        change_class_ng = "status-bullish" if change_ng >= 0 else "status-bearish"
        change_sign_ng = "+" if change_ng >= 0 else ""
        
        st.markdown(f"<div class='price-value'>₹{price_ng:,.2f}</div>", unsafe_allow_html=True)
        st.markdown(f"<p class='{change_class_ng}'>{change_sign_ng}{change_ng:.2f}% (NYMEX Global Today)</p>", unsafe_allow_html=True)
        
        # Load Indicators
        df_ng = fetch_nymex_trends("NG=F", usdinr)
        if df_ng is not None:
            last_row_ng = df_ng.iloc[-1]
            ema9_ng = last_row_ng['EMA9']
            ema21_ng = last_row_ng['EMA21']
            rsi_ng = last_row_ng['RSI']
            atr_ng = last_row_ng['ATR']
            mfi_ng = last_row_ng['MFI']
            
            if ema9_ng > ema21_ng:
                trend_desc_ng = "Bullish Momentum ✅"
                trend_class_ng = "status-bullish"
            else:
                trend_desc_ng = "Bearish / Sideways Crossover ⚠️"
                trend_class_ng = "status-bearish"
                
            # Determine Money Flow Index State
            if mfi_ng > 80:
                mfi_desc_ng = "Hyper-Accumulation"
                mfi_class_ng = "status-bullish"
                mfi_color_ng = "var(--success-color)"
            elif mfi_ng > 60:
                mfi_desc_ng = "Buying Pressure"
                mfi_class_ng = "status-bullish"
                mfi_color_ng = "#10B981"
            elif mfi_ng > 40:
                mfi_desc_ng = "Neutral Money Flow"
                mfi_class_ng = "status-neutral"
                mfi_color_ng = "#d97706"
            elif mfi_ng > 20:
                mfi_desc_ng = "Selling Pressure"
                mfi_class_ng = "status-bearish"
                mfi_color_ng = "#EF4444"
            else:
                mfi_desc_ng = "Selling Exhaustion"
                mfi_class_ng = "status-bearish"
                mfi_color_ng = "var(--error-color)"
                
            prev_row_ng = df_ng.iloc[-2]
            p_high_ng = prev_row_ng['High_INR']
            p_low_ng = prev_row_ng['Low_INR']
            p_close_ng = prev_row_ng['Close_INR']
            
            pivot_ng = (p_high_ng + p_low_ng + p_close_ng) / 3
            r1_ng = (2 * pivot_ng) - p_low_ng
            s1_ng = (2 * pivot_ng) - p_high_ng
            
            st.markdown(f"""
            <table style='width:100%; border-collapse:collapse; margin-top:1rem;'>
                <tr>
                    <td style='color:#8b949e; padding:5px 0;'>EMA Crossover (9/21):</td>
                    <td class='{trend_class_ng}' style='text-align:right;'>{trend_desc_ng}</td>
                </tr>
                <tr>
                    <td style='color:#8b949e; padding:5px 0;'>Daily RSI (14):</td>
                    <td style='text-align:right; font-weight:600;'>{rsi_ng:.1f}</td>
                </tr>
                <tr>
                    <td style='color:#8b949e; padding:5px 0;'>Daily ATR (14):</td>
                    <td style='text-align:right; font-weight:600;'>{atr_ng:.2f} pts</td>
                </tr>
                <tr style='border-top:1px solid var(--border-color);'>
                    <td style='color:#8b949e; padding:8px 0 4px 0;'>Money Flow Index (14):</td>
                    <td class='{mfi_class_ng}' style='text-align:right; font-weight:700; padding:8px 0 4px 0;'>{mfi_ng:.1f}% ({mfi_desc_ng})</td>
                </tr>
                <tr>
                    <td colspan='2' style='padding-bottom:10px;'>
                        <div style='background-color:#E2E8F0; border-radius:10px; width:100%; height:8px;'>
                            <div style='background-color:{mfi_color_ng}; width:{mfi_ng}%; height:8px; border-radius:10px;'></div>
                        </div>
                    </td>
                </tr>
                <tr style='border-top: 1px solid var(--border-color);'>
                    <td style='color:#8b949e; padding:8px 0 4px 0;'>Daily Pivot Level:</td>
                    <td style='text-align:right; font-weight:600; padding:8px 0 4px 0;'>₹{pivot_ng:,.2f}</td>
                </tr>
                <tr>
                    <td style='color:var(--success-color); padding:4px 0;'>Swing Target (R1):</td>
                    <td style='text-align:right; font-weight:600; color:var(--success-color);'>₹{r1_ng:,.2f}</td>
                </tr>
                <tr>
                    <td style='color:var(--error-color); padding:4px 0;'>Swing Stop (S1):</td>
                    <td style='text-align:right; font-weight:600; color:var(--error-color);'>₹{s1_ng:,.2f}</td>
                </tr>
            </table>
            """, unsafe_allow_html=True)
            
            st.markdown("<p class='metric-label' style='margin-top:1.5rem;'>30-Day Daily Chart</p>", unsafe_allow_html=True)
            st.line_chart(df_ng.tail(30)[['Close_INR', 'EMA9', 'EMA21']])
            
        st.markdown("</div>", unsafe_allow_html=True)

# Tab 2: Energy News & Reports
with tab_news:
    st.markdown("### 📰 Energy News & High-Impact EIA Reports Tracker")
    
    n_col1, n_col2 = st.columns([1.2, 1])
    
    with n_col1:
        st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
        st.markdown("<p class='metric-label'>🔥 Fresh Energy Market News (OilPrice.com)</p>", unsafe_allow_html=True)
        
        # Fetch RSS News
        news_items = fetch_energy_news()
        
        if news_items:
            for item in news_items:
                st.markdown(f"""
                <div class='news-item'>
                    <a href='{item["link"]}' target='_blank' class='news-title'>{item["title"]}</a>
                    <div class='news-meta'>⏰ {item["date"]} | Source: OilPrice.com</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.warning("⚠️ Could not load news headlines. Check your internet connection.")
            
        st.markdown("</div>", unsafe_allow_html=True)
        
    with n_col2:
        st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
        st.markdown("<p class='metric-label'>⚡ Weekly EIA Inventory Radar (High Volatility Events)</p>", unsafe_allow_html=True)
        
        # Calculate Countdowns
        crude_cnt, ng_cnt = get_eia_countdown()
        
        st.markdown(f"""
        <table style='width:100%; border-collapse:collapse; margin-bottom:1.5rem;'>
            <tr style='border-bottom:1px solid var(--border-color);'>
                <td style='padding:10px 0; font-weight:700;'>🛢️ EIA Weekly Crude Oil Stock:</td>
                <td style='padding:10px 0; text-align:right; font-weight:700; color:var(--primary-color);'>{crude_cnt}</td>
            </tr>
            <tr style='font-size:0.8rem; color:#8b949e;'>
                <td colspan='2' style='padding-bottom:10px;'>Standard schedule: Wednesdays at 8:00 PM IST. High-impact volatility event for Crude.</td>
            </tr>
            <tr style='border-bottom:1px solid var(--border-color);'>
                <td style='padding:10px 0; font-weight:700;'>🔥 EIA Weekly Natural Gas Storage:</td>
                <td style='padding:10px 0; text-align:right; font-weight:700; color:var(--primary-color);'>{ng_cnt}</td>
            </tr>
            <tr style='font-size:0.8rem; color:#8b949e;'>
                <td colspan='2' style='padding-bottom:10px;'>Standard schedule: Thursdays at 8:00 PM IST. High-impact volatility event for Gas.</td>
            </tr>
        </table>
        """, unsafe_allow_html=True)
        
        st.markdown("<p class='metric-label'>💡 Swing Options Inventory Strategy Cheat Sheet</p>", unsafe_allow_html=True)
        st.info("""
**🛢️ CRUDE OIL INVENTORY PLAY:**
*   **DRAW (Inventory Decr.):** Bullish 🟢 (Option: BUY Call/SELL Put)
*   **BUILD (Inventory Incr.):** Bearish 🔴 (Option: BUY Put/SELL Call)

**🔥 NATURAL GAS STORAGE PLAY:**
*   **DRAW (High Winter/AC Demand):** Bullish 🟢
*   **BUILD (Low Weather Demand):** Bearish 🔴

*⚠️ **Swing Trading Note:** As an MCX swing trader holding options for 3 to 5 days, it is highly recommended to **avoid entering new options trades 1 hour before the EIA report**. Enter 1 hour after the release once the initial high-implied-volatility (IV) spike collapses and clear structural momentum asserts itself.*
""")
        st.markdown("</div>", unsafe_allow_html=True)

# Tab 3: Planner
with tab_calc:
    st.markdown("### 🧮 Swing Trade Position Sizer & MCX Option Charge Estimator")
    
    cc1, cc2 = st.columns([1, 1.2])
    
    with cc1:
        st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
        st.markdown("<p class='metric-label'>Position Planner Inputs</p>", unsafe_allow_html=True)
        
        planned_symbol = st.selectbox("Asset Commodity", options=["CRUDEOIL", "NATURALGAS", "NATGASMINI"], key="mcx_calc_symbol")
        planned_ltp = live_prices[planned_symbol]
        
        # Default ATR values for default Stop Loss
        default_sl_distance = 150.0 if planned_symbol == "CRUDEOIL" else 15.0
        if planned_symbol == "CRUDEOIL" and df_crude is not None:
            default_sl_distance = round(float(df_crude.iloc[-1]['ATR']) * 1.5, 1)
        elif planned_symbol in ["NATURALGAS", "NATGASMINI"] and df_ng is not None:
            default_sl_distance = round(float(df_ng.iloc[-1]['ATR']) * 1.5, 1)
            
        c_capital = st.number_input("Account Capital (₹)", min_value=1000.0, step=10000.0, value=200000.0)
        c_risk_pct = st.slider("Risk Per Trade (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
        
        c_entry = st.number_input("Futures Entry Price (₹)", min_value=0.1, value=float(planned_ltp), step=5.0)
        c_sl_dist = st.number_input("Stop Loss Distance (Points)", min_value=0.1, value=float(default_sl_distance), step=1.0, help="Sizing is based strictly on stop-loss distance in futures points.")
        
        st.markdown("---")
        st.markdown("<p class='metric-label'>Option Premium Planning (Held 3-5 Days)</p>", unsafe_allow_html=True)
        
        c_strike = st.number_input("Option Strike Price (₹)", min_value=10, value=int(round(planned_ltp, -2)), step=100 if planned_symbol == "CRUDEOIL" else 5)
        c_premium = st.number_input("Option Entry Premium (₹)", min_value=0.1, value=150.0 if planned_symbol == "CRUDEOIL" else 12.0, step=1.0)
        c_exit_premium = st.number_input("Option Exit Target Premium (₹)", min_value=0.1, value=250.0 if planned_symbol == "CRUDEOIL" else 20.0, step=1.0)
        
        st.markdown("</div>", unsafe_allow_html=True)
        
    with cc2:
        # Load contract lot sizes
        if planned_symbol == "CRUDEOIL":
            contract_lot = 100.0
        elif planned_symbol == "NATURALGAS":
            contract_lot = 1250.0
        else:
            contract_lot = 250.0
        
        # Calculate Risk and Sizing
        max_risk_rupees = c_capital * (c_risk_pct / 100.0)
        sizing_units = max_risk_rupees / c_sl_dist
        
        # Sizing in Lots
        sizing_lots = math.floor(sizing_units / contract_lot)
        if sizing_lots < 1:
            sizing_lots = 1
            
        actual_qty = sizing_lots * contract_lot
        actual_risk_rupees = actual_qty * c_sl_dist
        
        # Calculate Option PNL
        option_gross_pnl = (c_exit_premium - c_premium) * actual_qty
        total_premium_cost = c_premium * actual_qty
        
        # Calculate MCX Option Taxes
        c_flat_brokerage = 40.0
        opt_buy_turnover = actual_qty * c_premium
        opt_sell_turnover = actual_qty * c_exit_premium
        opt_total_turnover = opt_buy_turnover + opt_sell_turnover
        
        opt_stt = opt_sell_turnover * 0.05 / 100.0
        opt_exc = opt_total_turnover * 0.05 / 100.0
        opt_sebi = opt_total_turnover * 0.0001 / 100.0
        opt_stamp = opt_buy_turnover * 0.003 / 100.0
        
        opt_gst = (c_flat_brokerage + opt_exc + opt_sebi) * 18.0 / 100.0
        opt_total_charges = c_flat_brokerage + opt_stt + opt_exc + opt_sebi + opt_stamp + opt_gst
        option_net_pnl = option_gross_pnl - opt_total_charges
        
        # UI Outputs
        st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
        st.markdown("<p class='metric-label'>Position Sizing Results & Risk Management</p>", unsafe_allow_html=True)
        
        st.markdown(f"""
        <table style='width:100%; border-collapse:collapse; margin-bottom:1.5rem;'>
            <tr style='font-size:1.1rem; border-bottom:1px solid var(--border-color);'>
                <td style='padding:8px 0; color:#8b949e;'>Planned Stop Loss Risk:</td>
                <td style='padding:8px 0; text-align:right; font-weight:700;'>₹{max_risk_rupees:,.2f} ({c_risk_pct}%)</td>
            </tr>
            <tr style='font-size:1.2rem; background-color:rgba(0, 210, 211, 0.1);'>
                <td style='padding:10px; color:var(--secondary-color); font-weight:700;'>Recommended Position:</td>
                <td style='padding:10px; text-align:right; font-weight:800; color:var(--secondary-color);'>{sizing_lots} Lot(s) ({int(actual_qty)} units)</td>
            </tr>
            <tr>
                <td style='padding:6px 0; color:#8b949e;'>Actual Futures SL Risk:</td>
                <td style='padding:6px 0; text-align:right; font-weight:600;'>₹{actual_risk_rupees:,.2f}</td>
            </tr>
            <tr>
                <td style='padding:6px 0; color:#8b949e;'>Total Premium Deployment:</td>
                <td style='padding:6px 0; text-align:right; font-weight:600;'>₹{total_premium_cost:,.2f}</td>
            </tr>
        </table>
        """, unsafe_allow_html=True)
        
        st.markdown("<p class='metric-label'>MCX Option Swing Trade Profit/Loss & Charges</p>", unsafe_allow_html=True)
        
        net_pnl_class = "status-bullish" if option_net_pnl >= 0 else "status-bearish"
        
        st.markdown(f"""
        <table style='width:100%; border-collapse:collapse;'>
            <tr style='font-size:1.1rem; border-bottom:1px solid var(--border-color);'>
                <td style='padding:8px 0; color:#8b949e;'>Estimated Gross P&L:</td>
                <td style='padding:8px 0; text-align:right; font-weight:700;'>₹{option_gross_pnl:,.2f}</td>
            </tr>
            <tr>
                <td style='padding:4px 0; color:#8b949e;'>Flat Brokerage (Buy + Sell):</td>
                <td style='padding:4px 0; text-align:right;'>₹{c_flat_brokerage:.2f}</td>
            </tr>
            <tr>
                <td style='padding:4px 0; color:#8b949e;'>Commodity Transaction Tax (CTT):</td>
                <td style='padding:4px 0; text-align:right;'>₹{opt_stt:.2f}</td>
            </tr>
            <tr>
                <td style='padding:4px 0; color:#8b949e;'>Exchange Transaction Charges:</td>
                <td style='padding:4px 0; text-align:right;'>₹{opt_exc:.2f}</td>
            </tr>
            <tr>
                <td style='padding:4px 0; color:#8b949e;'>Stamp Duty (Buy Side only):</td>
                <td style='padding:4px 0; text-align:right;'>₹{opt_stamp:.2f}</td>
            </tr>
            <tr>
                <td style='padding:4px 0; color:#8b949e;'>SEBI Turnover Charge & GST (18%):</td>
                <td style='padding:4px 0; text-align:right;'>₹{(opt_sebi + opt_gst):.2f}</td>
            </tr>
            <tr style='font-size:1.1rem; border-top:1px solid var(--border-color); font-weight:700;'>
                <td style='padding:8px 0; color:#8b949e;'>Total Estimated Charges:</td>
                <td style='padding:8px 0; text-align:right; color:#ffc107;'>₹{opt_total_charges:.2f}</td>
            </tr>
            <tr style='font-size:1.3rem; background-color:rgba(46, 204, 113, 0.1); border-top:2px solid var(--border-color);'>
                <td style='padding:12px; color:#2ecc71; font-weight:700;'>Expected Net P&L:</td>
                <td class='{net_pnl_class}' style='padding:12px; text-align:right; font-weight:800;'>₹{option_net_pnl:,.2f}</td>
            </tr>
        </table>
        """, unsafe_allow_html=True)
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # Add a helpful premium swing note
        st.warning("💡 **Swing Trade Tip (3-5 Days):** When holding options over several days, keep stop-losses strictly in the underlying futures chart rather than tracking the premium, as options premium decays (Theta) by roughly 2-5% per day during sideways consolidation.")
