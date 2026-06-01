import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import os
import time
import math
from datetime import datetime

# Import database settings from local database file
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

# Custom Styling (Dark Glassmorphic Premium Theme)
st.markdown("""
<style>
    :root {
        --primary-color: #ff9f43;
        --secondary-color: #00d2d3;
        --bg-color: #0f1115;
        --card-bg: rgba(22, 27, 34, 0.7);
        --border-color: rgba(255, 255, 255, 0.1);
        --text-color: #f0f6fc;
        --success-color: #2ecc71;
        --error-color: #ea2027;
    }
    
    .stApp {
        background-color: var(--bg-color);
        color: var(--text-color);
        font-family: 'Outfit', sans-serif;
    }
    
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, var(--primary-color), var(--secondary-color));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    
    .sub-title {
        font-size: 1rem;
        color: #8b949e;
        margin-bottom: 2rem;
    }
    
    .premium-card {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        backdrop-filter: blur(10px);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }
    
    .price-value {
        font-size: 2.5rem;
        font-weight: 800;
        margin: 0.5rem 0;
    }
    
    .metric-label {
        font-size: 0.85rem;
        color: #8b949e;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    .status-bullish {
        color: var(--success-color);
        font-weight: 600;
    }
    
    .status-bearish {
        color: var(--error-color);
        font-weight: 600;
    }
    
    .status-neutral {
        color: #ffc107;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------
# Data & Master CSV Sync Functions
# ----------------------------------------------------
CACHE_FILE = "api-scrip-master.csv"

@st.cache_data(ttl=86400)
def download_dhan_scrip_master():
    """Downloads Dhan instrument master and caches it for 24 hours."""
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        # Fast streaming download
        r = requests.get(url, stream=True)
        if r.status_code == 200:
            with open(CACHE_FILE, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            return True
    except Exception as e:
        st.sidebar.error(f"Scrip download failed: {str(e)}")
    return False

def get_mcx_active_contracts():
    """Parses Dhan script master to find the near-month Crude Oil and Natural Gas futures contracts."""
    if not os.path.exists(CACHE_FILE):
        success = download_dhan_scrip_master()
        if not success:
            return None
            
    try:
        # Load columns we need to save memory
        cols = ['SEM_EXM_EXCH_ID', 'SEM_SMST_SECURITY_ID', 'SEM_INSTRUMENT_NAME', 
                'SEM_TRADING_SYMBOL', 'SEM_LOT_UNITS', 'SEM_EXPIRY_DATE', 'SM_SYMBOL_NAME']
        df = pd.read_csv(CACHE_FILE, usecols=cols)
        
        # Filter for active MCX Futures
        mcx_df = df[(df['SEM_EXM_EXCH_ID'] == 'MCX') & (df['SEM_INSTRUMENT_NAME'] == 'FUTCOM')]
        
        contracts = {}
        for symbol in ['CRUDEOIL', 'NATURALGAS']:
            sym_df = mcx_df[mcx_df['SM_SYMBOL_NAME'] == symbol].copy()
            if not sym_df.empty:
                # Filter out expired or invalid contracts (expiry >= today)
                today_str = datetime.today().strftime('%Y-%m-%d')
                sym_df = sym_df[sym_df['SEM_EXPIRY_DATE'] >= today_str]
                if not sym_df.empty:
                    # Sort by expiry date to get near-month
                    sym_df = sym_df.sort_values(by='SEM_EXPIRY_DATE')
                    near_month = sym_df.iloc[0]
                    contracts[symbol] = {
                        "security_id": str(near_month['SEM_SMST_SECURITY_ID']),
                        "trading_symbol": near_month['SEM_TRADING_SYMBOL'],
                        "lot_size": float(near_month['SEM_LOT_UNITS']),
                        "expiry": near_month['SEM_EXPIRY_DATE']
                    }
        return contracts
    except Exception as e:
        st.sidebar.error(f"Error parsing scrip master: {str(e)}")
        return None

def fetch_dhan_ltp(client_id, access_token, security_ids):
    """Fetches real-time LTP from Dhan's POST endpoint."""
    url = "https://api.dhan.co/v2/marketfeed/ltp"
    headers = {
        "access-token": access_token,
        "client-id": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # Map exchange segment correctly
    body = {
        "instruments": [
            {"exchange_segment": "MCX_COMM", "security_id": sec_id} for sec_id in security_ids
        ]
    }
    
    try:
        r = requests.post(url, headers=headers, json=body, timeout=5)
        if r.status_code == 200:
            res_data = r.json()
            # Standardize output: dictionary of security_id -> LTP
            prices = {}
            for item in res_data.get("data", []):
                sec_id = str(item.get("security_id"))
                prices[sec_id] = float(item.get("last_traded_price", 0.0))
            return prices
    except Exception as e:
        pass
    return None

# ----------------------------------------------------
# Technical Analysis Helpers (NYMEX)
# ----------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_nymex_trends(ticker, usdinr):
    """Fetches daily NYMEX prices, converts to INR, and calculates technical momentum indicators."""
    try:
        df = yf.download(ticker, period="60d", interval="1d", progress=False)
        if df.empty:
            return None
        
        # Convert prices from USD to INR using conversion multiplier
        # WTI is quoted in USD/bbl, Henry Hub in USD/MMBtu.
        df['Close_INR'] = df['Close'] * usdinr
        df['High_INR'] = df['High'] * usdinr
        df['Low_INR'] = df['Low'] * usdinr
        df['Open_INR'] = df['Open'] * usdinr
        
        # 1. EMAs
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
        
        return df
    except Exception:
        return None

# ----------------------------------------------------
# Core Application Flow
# ----------------------------------------------------
# 1. Main Title
st.markdown("<h1 class='main-title'>🛢️ FinPlus MCX Energy Workstation</h1>", unsafe_allow_html=True)
st.markdown("<p class='sub-title'>Free, tokenless NYMEX Proxy + Dhan Hybrid Swing Workstation for Crude Oil & Natural Gas</p>", unsafe_allow_html=True)

# 2. Fetch Saved Settings / Dhan Credentials
dhan_creds = {}
if database:
    dhan_creds = database.get_db_settings("dhan_credentials", {})

# 3. Sidebar Configuration
st.sidebar.markdown("### ⚙️ Dhan API Settings")
d_client_id = st.sidebar.text_input("Dhan Client ID", value=dhan_creds.get("client_id", ""), type="password")
d_access_token = st.sidebar.text_input("Dhan Access Token", value=dhan_creds.get("access_token", ""), type="password")

if st.sidebar.button("💾 Save Credentials", type="primary"):
    if database:
        database.save_db_setting("dhan_credentials", {"client_id": d_client_id, "access_token": d_access_token})
        st.sidebar.success("Credentials saved securely in Database!")
        time.sleep(1)
        st.rerun()

# Download / Sync master script manual trigger
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Scrip Master Database")
if st.sidebar.button("🔄 Force Sync Dhan Master CSV"):
    with st.spinner("Downloading master CSV..."):
        if download_dhan_scrip_master():
            st.sidebar.success("CSV synced successfully!")
        else:
            st.sidebar.error("Sync failed.")

# Load active contracts
mcx_contracts = get_mcx_active_contracts()

# Fallback values if master CSV or API fails
if not mcx_contracts:
    mcx_contracts = {
        "CRUDEOIL": {"security_id": "0", "trading_symbol": "CRUDEOIL FUT", "lot_size": 100.0, "expiry": "N/A"},
        "NATURALGAS": {"security_id": "0", "trading_symbol": "NATURALGAS FUT", "lot_size": 1250.0, "expiry": "N/A"}
    }

# 4. Fetch USDINR & NYMEX Live data
try:
    usdinr_ticker = yf.Ticker("USDINR=X")
    usdinr = float(usdinr_ticker.history(period="1d")['Close'].iloc[-1])
except Exception:
    usdinr = 83.50 # Robust fallback

# Fetch NYMEX Spot Estimates
nymex_symbols = {"CRUDEOIL": "CL=F", "NATURALGAS": "NG=F"}
spot_prices = {}
for key, tick in nymex_symbols.items():
    try:
        ticker_obj = yf.Ticker(tick)
        spot_prices[key] = float(ticker_obj.history(period="1d")['Close'].iloc[-1])
    except Exception:
        spot_prices[key] = 75.0 if key == "CRUDEOIL" else 2.50

# Live Price Fetching (Dhan or NYMEX Correlation proxy)
live_prices = {}
pricing_source = "NYMEX Proxy (Correlation converted)"

if d_client_id and d_access_token and mcx_contracts:
    sec_ids = [val["security_id"] for val in mcx_contracts.values() if val["security_id"] != "0"]
    if sec_ids:
        dhan_prices = fetch_dhan_ltp(d_client_id, d_access_token, sec_ids)
        if dhan_prices:
            for symbol, details in mcx_contracts.items():
                sec_id = details["security_id"]
                if sec_id in dhan_prices:
                    live_prices[symbol] = dhan_prices[sec_id]
            pricing_source = "Live Dhan MCX API ✅"

# Apply fallback proxy pricing if Dhan didn't return
for symbol in ["CRUDEOIL", "NATURALGAS"]:
    if symbol not in live_prices:
        live_prices[symbol] = round(spot_prices[symbol] * usdinr, 2)

# Calculate percentage changes (NYMEX fallback or estimated)
pct_changes = {}
for symbol in ["CRUDEOIL", "NATURALGAS"]:
    try:
        t_obj = yf.Ticker(nymex_symbols[symbol])
        hist = t_obj.history(period="2d")
        prev = hist['Close'].iloc[0]
        curr = hist['Close'].iloc[1]
        pct_changes[symbol] = ((curr - prev) / prev) * 100
    except Exception:
        pct_changes[symbol] = 0.0

# ----------------------------------------------------
# Tab 1: Swing Dashboard
# ----------------------------------------------------
tab_dash, tab_calc = st.tabs(["📊 Commodity Swing Dashboard", "🧮 Swing Trade Planner & Charges"])

with tab_dash:
    # Display Active Pricing Source
    st.info(f"🔌 **Pricing Feed Source:** {pricing_source} | **Live USDINR:** ₹{usdinr:.2f}")
    
    col1, col2 = st.columns(2)
    
    # 🛢️ CRUDE OIL COLUMN
    with col1:
        st.markdown("""
        <div class='premium-card'>
            <div class='metric-label'>🛢️ CRUDE OIL (MCX Futures)</div>
        """, unsafe_allow_html=True)
        
        # Price and Change
        price = live_prices["CRUDEOIL"]
        change = pct_changes["CRUDEOIL"]
        change_class = "status-bullish" if change >= 0 else "status-bearish"
        change_sign = "+" if change >= 0 else ""
        
        st.markdown(f"<div class='price-value'>₹{price:,.2f}</div>", unsafe_allow_html=True)
        st.markdown(f"<p class='{change_class}'>{change_sign}{change:.2f}% (NYMEX Global Today)</p>", unsafe_allow_html=True)
        
        # Load Technical Indicators from NYMEX data
        df_crude = fetch_nymex_trends("CL=F", usdinr)
        if df_crude is not None:
            last_row = df_crude.iloc[-1]
            ema9 = last_row['EMA9']
            ema21 = last_row['EMA21']
            rsi = last_row['RSI']
            atr = last_row['ATR']
            
            # Determine momentum
            if ema9 > ema21:
                trend_desc = "Bullish Momentum ✅"
                trend_class = "status-bullish"
            else:
                trend_desc = "Bearish / Sideways Crossover ⚠️"
                trend_class = "status-bearish"
                
            # Support & Resistance (Pivot points from daily)
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
                    <td style='color:#8b949e; padding:5px 0;'>Trend State:</td>
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
                <tr style='border-top: 1px solid var(--border-color);'>
                    <td style='color:#8b949e; padding:8px 0 4px 0;'>Pivot Level:</td>
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
            
            # Simple Chart
            st.markdown("<p class='metric-label' style='margin-top:1.5rem;'>30-Day Swing Trend</p>", unsafe_allow_html=True)
            chart_df = df_crude.tail(30)[['Close_INR', 'EMA9', 'EMA21']]
            st.line_chart(chart_df)
            
        st.markdown("</div>", unsafe_allow_html=True)

    # 🔥 NATURAL GAS COLUMN
    with col2:
        st.markdown("""
        <div class='premium-card'>
            <div class='metric-label'>🔥 NATURAL GAS (MCX Futures)</div>
        """, unsafe_allow_html=True)
        
        # Price and Change
        price_ng = live_prices["NATURALGAS"]
        change_ng = pct_changes["NATURALGAS"]
        change_class_ng = "status-bullish" if change_ng >= 0 else "status-bearish"
        change_sign_ng = "+" if change_ng >= 0 else ""
        
        st.markdown(f"<div class='price-value'>₹{price_ng:,.2f}</div>", unsafe_allow_html=True)
        st.markdown(f"<p class='{change_class_ng}'>{change_sign_ng}{change_ng:.2f}% (NYMEX Global Today)</p>", unsafe_allow_html=True)
        
        # Load Technical Indicators from NYMEX data
        df_ng = fetch_nymex_trends("NG=F", usdinr)
        if df_ng is not None:
            last_row_ng = df_ng.iloc[-1]
            ema9_ng = last_row_ng['EMA9']
            ema21_ng = last_row_ng['EMA21']
            rsi_ng = last_row_ng['RSI']
            atr_ng = last_row_ng['ATR']
            
            # Determine momentum
            if ema9_ng > ema21_ng:
                trend_desc_ng = "Bullish Momentum ✅"
                trend_class_ng = "status-bullish"
            else:
                trend_desc_ng = "Bearish / Sideways Crossover ⚠️"
                trend_class_ng = "status-bearish"
                
            # Support & Resistance
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
                    <td style='color:#8b949e; padding:5px 0;'>Trend State:</td>
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
                <tr style='border-top: 1px solid var(--border-color);'>
                    <td style='color:#8b949e; padding:8px 0 4px 0;'>Pivot Level:</td>
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
            
            # Simple Chart
            st.markdown("<p class='metric-label' style='margin-top:1.5rem;'>30-Day Swing Trend</p>", unsafe_allow_html=True)
            chart_df_ng = df_ng.tail(30)[['Close_INR', 'EMA9', 'EMA21']]
            st.line_chart(chart_df_ng)
            
        st.markdown("</div>", unsafe_allow_html=True)

# ----------------------------------------------------
# Tab 2: Position Planner & Charges Calculator
# ----------------------------------------------------
with tab_calc:
    st.markdown("### 🧮 Swing Trade Position Sizer & MCX Option Charge Estimator")
    
    cc1, cc2 = st.columns([1, 1.2])
    
    with cc1:
        st.markdown("<div class='premium-card'>", unsafe_allow_html=True)
        st.markdown("<p class='metric-label'>Position Planner Inputs</p>", unsafe_allow_html=True)
        
        # User selection
        planned_symbol = st.selectbox("Asset Commodity", options=["CRUDEOIL", "NATURALGAS"], key="mcx_calc_symbol")
        
        # Set dynamic default prices based on selected commodity
        planned_ltp = live_prices[planned_symbol]
        
        # Default ATR values for default Stop Loss
        default_sl_distance = 150.0 if planned_symbol == "CRUDEOIL" else 15.0
        if planned_symbol == "CRUDEOIL" and df_crude is not None:
            default_sl_distance = round(float(df_crude.iloc[-1]['ATR']) * 1.5, 1)
        elif planned_symbol == "NATURALGAS" and df_ng is not None:
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
        contract_lot = mcx_contracts[planned_symbol]["lot_size"]
        
        # Calculate Risk and Sizing
        max_risk_rupees = c_capital * (c_risk_pct / 100.0)
        
        # Sizing in barrels/MMBtu = Max Risk / SL Distance
        sizing_units = max_risk_rupees / c_sl_dist
        
        # Sizing in Lots
        sizing_lots = math.floor(sizing_units / contract_lot)
        if sizing_lots < 1:
            sizing_lots = 1 # Trade at least 1 lot
            
        actual_qty = sizing_lots * contract_lot
        actual_risk_rupees = actual_qty * c_sl_dist
        
        # Calculate Option PNL
        option_gross_pnl = (c_exit_premium - c_premium) * actual_qty
        
        # Calculate Option premium total cost
        total_premium_cost = c_premium * actual_qty
        
        # Calculate MCX Option Taxes
        # STT is charged on Sell Side premium = 0.05%
        # Exchange transaction charges = 0.05% on premium (Buy + Sell)
        # Stamp Duty is on Buy Side premium = 0.003%
        # SEBI Fee = 0.0001% of premium turnover
        # GST = 18% of (Exchange + SEBI + flat brokerage)
        # Brokerage = Flat ₹40.0
        
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
