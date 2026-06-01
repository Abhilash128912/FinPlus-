import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import calendar
import os

# Import our modular components
from config import DEFAULT_STRATEGIES, DEFAULT_MISTAKES
from database import (
    get_brokerage_rates,
    save_brokerage_rates,
    add_trade,
    update_trade,
    delete_trade,
    fetch_trades_df,
    clear_all_trades,
    get_db_settings,
    save_db_setting
)
from calculator import calculate_trade_metrics

def get_quote_mismatch_warning(symbol: str, segment: str) -> str:
    if not symbol:
        return ""
    sym = symbol.strip().upper()
    
    # Common indices in India
    index_keywords = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "NIFTY50", "CNXNIFTY", "BANKEX"]
    is_index = any(keyword in sym for keyword in index_keywords)
    
    # Check if ends with option suffix (e.g. CE, PE, or ends with number + C/P)
    import re
    # Match CE, PE at the end, or number + C or P at the end (e.g. 1500C, 22000P, etc.)
    is_option_contract = sym.endswith("CE") or sym.endswith("PE") or bool(re.search(r'\d+[CP]$', sym))
    
    # Commodities keywords
    commodity_keywords = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "COPPER", "ZINC", "ALUMINIUM", "LEAD", "MCX"]
    is_commodity = any(keyword in sym for keyword in commodity_keywords)
    
    # 1. Index Ticker mismatch
    if is_index:
        if segment in ["Equity - Delivery", "Equity - Intraday"]:
            return f"⚠️ Warning: You entered an Index ticker (**{symbol}**) but selected an Equity/Stock segment (**{segment}**). Stock indices cannot be traded directly as shares. Did you mean **F&O - Index Futures** or **F&O - Index Options**?"
        if segment == "F&O - Stock Options":
            return f"⚠️ Warning: You entered an Index ticker (**{symbol}**) but selected **F&O - Stock Options**. Index Options should be classified under **F&O - Index Options** for correct taxation."
        if segment == "Commodities":
            return f"⚠️ Warning: You entered an Index ticker (**{symbol}**) but selected the **Commodities** segment."
            
    # 2. Option Contract mismatch
    if is_option_contract:
        if segment not in ["F&O - Index Options", "F&O - Stock Options"]:
            return f"⚠️ Warning: The symbol **{symbol}** appears to be an Option contract (ends with C/P/CE/PE), but the selected segment is **{segment}**. Options should typically be classified under **F&O - Index Options** or **F&O - Stock Options**."
        
        # Check stock option vs index option classification
        if is_index and segment == "F&O - Stock Options":
            return f"⚠️ Warning: The symbol **{symbol}** contains an Index name, but the segment is **F&O - Stock Options**. Please select **F&O - Index Options** to apply the correct index tax rates."
        if not is_index and segment == "F&O - Index Options":
            return f"⚠️ Warning: The symbol **{symbol}** appears to be a Stock Option, but the segment is **F&O - Index Options**. Please select **F&O - Stock Options** to apply the correct stock tax rates."

    # 3. Commodity mismatch
    if is_commodity:
        if segment != "Commodities":
            return f"⚠️ Warning: The symbol **{symbol}** appears to be a Commodity, but the selected segment is **{segment}**. Please select **Commodities** to ensure MCX transaction charges and CTT are computed correctly."
            
    # 4. Standard stock in F&O Options mismatch
    # If it is not an index, not a commodity, and doesn't end with CE/PE/C/P, but segment is F&O - Index Options or Stock Options:
    if not is_index and not is_commodity and not is_option_contract:
        if segment in ["F&O - Index Options", "F&O - Stock Options"]:
            return f"⚠️ Warning: You selected an Option segment (**{segment}**), but the symbol **{symbol}** does not look like an option contract (typically ends with C, P, CE, or PE with strike price). Please double-check."
    return ""

def fetch_screener_scores(symbol: str) -> dict:
    """
    Checks the local Nifty 500 SQLite cache database to pull fundamental and momentum ratings
    for the given symbol to display as real-time context.
    """
    if not symbol:
        return None
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nifty_scanner", "nifty500_scanner.db")
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        sym_clean = symbol.replace(" ", "").strip().upper()
        # Query matching either exact or with .NS suffix
        cursor.execute(
            "SELECT company_name, sector, last_price, fundamental_score, momentum_score, total_score, rsi_14 FROM nifty500_cache WHERE ticker = ? OR ticker = ?", 
            (sym_clean, f"{sym_clean}.NS")
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "company_name": row[0],
                "sector": row[1],
                "last_price": row[2],
                "fundamental_score": row[3],
                "momentum_score": row[4],
                "total_score": row[5],
                "rsi_14": row[6]
            }
    except Exception:
        pass
    return None

@st.cache_data(ttl=300)
def fetch_live_market_stats(symbol: str) -> dict:
    """
    Downloads 1 year of daily price history via yfinance to calculate
    live LTP, 52-week High, and 52-week Low for any typed stock.
    """
    if not symbol:
        return None
    
    ticker_symbol = symbol.replace(" ", "").strip().upper()
    if not ticker_symbol:
        return None
        
    # Append .NS for Indian stocks if not present
    if not ticker_symbol.endswith(".NS") and not ticker_symbol.endswith(".BO") and len(ticker_symbol) <= 10:
        index_keywords = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
        is_index = any(k in ticker_symbol for k in index_keywords)
        commodity_keywords = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"]
        is_commodity = any(k in ticker_symbol for k in commodity_keywords)
        if not is_index and not is_commodity:
            ticker_symbol = f"{ticker_symbol}.NS"
            
    import yfinance as yf
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="1y", interval="1d")
        if not df.empty:
            last_price = float(df["Close"].iloc[-1])
            high_52w = float(df["High"].max())
            low_52w = float(df["Low"].min())
            return {
                "ltp": last_price,
                "high_52w": high_52w,
                "low_52w": low_52w,
                "ticker_used": ticker_symbol,
                "success": True
            }
    except Exception:
        pass
    return None

@st.cache_data(ttl=600)
def fetch_live_stock_news(symbol: str) -> list:
    """
    Downloads raw news from yfinance and parses the top 3 items.
    Returns list of dicts with title, publisher, and link.
    """
    if not symbol:
        return []
    
    ticker_symbol = symbol.replace(" ", "").strip().upper()
    if not ticker_symbol:
        return []
        
    # Append .NS for Indian stocks if not present
    if not ticker_symbol.endswith(".NS") and not ticker_symbol.endswith(".BO") and len(ticker_symbol) <= 10:
        index_keywords = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
        is_index = any(k in ticker_symbol for k in index_keywords)
        commodity_keywords = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"]
        is_commodity = any(k in ticker_symbol for k in commodity_keywords)
        if not is_index and not is_commodity:
            ticker_symbol = f"{ticker_symbol}.NS"
            
    import yfinance as yf
    try:
        ticker = yf.Ticker(ticker_symbol)
        raw_news = ticker.news
        parsed_news = []
        if raw_news:
            for item in raw_news[:3]:  # Top 3 headlines
                title = ""
                publisher = ""
                link = ""
                if "content" in item:
                    c = item["content"]
                    title = c.get("title", "")
                    publisher = c.get("provider", {}).get("displayName", "")
                    link = c.get("canonicalUrl", {}).get("url", "")
                else:
                    title = item.get("title", "")
                    publisher = item.get("publisher", "")
                    link = item.get("link", "")
                
                if title:
                    parsed_news.append({
                        "title": title,
                        "publisher": publisher,
                        "link": link
                    })
            return parsed_news
    except Exception:
        pass
    return []

def render_quantamental_health_card(symbol: str, key_suffix: str = ""):
    """
    Renders an on-screen high-contrast Quantamental Health Card or non-constituent alert box
    showing composite score, LTP, 52-week High, 52-week Low, and live news headlines.
    """
    if not symbol:
        return
        
    screener_info = fetch_screener_scores(symbol)
    live_stats = fetch_live_market_stats(symbol)
    news_items = fetch_live_stock_news(symbol)
    
    is_nifty500 = screener_info is not None
    
    ltp = 0.0
    high_52w = 0.0
    low_52w = 0.0
    
    if live_stats and live_stats.get("success"):
        ltp = live_stats["ltp"]
        high_52w = live_stats["high_52w"]
        low_52w = live_stats["low_52w"]
    elif is_nifty500:
        ltp = screener_info["last_price"]
        
    # Build News HTML block
    news_html = ""
    if news_items:
        news_html += '<hr style="border-top: 1px dashed #CBD5E1; margin: 14px 0 8px 0;">\n'
        news_html += '<div style="font-size: 0.85rem; color: #475569; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px;">📰 Latest Stock News Insights</div>\n'
        for item in news_items:
            news_html += f'<div style="font-size: 0.95rem; margin-bottom: 5px; line-height: 1.35;"><span style="color: #64748B; font-weight: 600;">[{item["publisher"]}]</span> <a href="{item["link"]}" target="_blank" style="color: #1D4ED8; font-weight: 700; text-decoration: none;">{item["title"]}</a></div>\n'
    else:
        news_html += '<hr style="border-top: 1px dashed #CBD5E1; margin: 14px 0 8px 0;">\n'
        news_html += '<div style="font-size: 0.85rem; color: #475569; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px;">📰 Latest Stock News Insights</div>\n'
        news_html += '<div style="font-size: 0.95rem; color: #64748B; font-style: italic;">No recent news found for this ticker.</div>\n'

        
    if is_nifty500:
        st.markdown(
            f"""<div style="background-color: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 10px; padding: 18px; margin-top: 15px; margin-bottom: 5px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
<span style="font-size: 0.85rem; color: #1D4ED8; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em;">📊 NIFTY 500 SCREENER QUANTAMENTAL SCORE</span>
<h5 style="margin: 6px 0 4px 0; color: #1E3A8A; font-size: 1.3rem; font-weight: 700; font-family: 'Outfit', sans-serif;">
{screener_info['company_name']} ({symbol.replace(" ", "").strip().upper()})
</h5>
<p style="font-size: 1.05rem; color: #475569; margin: 4px 0 10px 0; font-weight: 500; line-height: 1.4;">
Sector: <strong style="color: #0F172A;">{screener_info['sector']}</strong> &nbsp;&bull;&nbsp; 
RSI (14d): <strong style="color: #1D4ED8;">{screener_info['rsi_14']:.1f}</strong> &nbsp;&bull;&nbsp; 
LTP: <strong style="color: #059669;">₹ {ltp:,.2f}</strong> {"(Live)" if live_stats else "(Cached)"}
</p>
<p style="font-size: 1.05rem; color: #475569; margin: 0 0 12px 0; font-weight: 500;">
52-Week High: <strong style="color: #0F172A;">₹ {high_52w:,.2f}</strong> &nbsp;&bull;&nbsp; 
52-Week Low: <strong style="color: #0F172A;">₹ {low_52w:,.2f}</strong>
</p>
<div style="display: flex; gap: 12px; margin-top: 5px; flex-wrap: wrap;">
<span style="background-color: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0; padding: 6px 12px; border-radius: 8px; font-weight: 700; font-size: 0.9rem;">
Fundamental Score: {int(screener_info['fundamental_score'])}/50
</span>
<span style="background-color: #EEF2FF; color: #3730A3; border: 1px solid #C7D2FE; padding: 6px 12px; border-radius: 8px; font-weight: 700; font-size: 0.9rem;">
Momentum Score: {int(screener_info['momentum_score'])}/50
</span>
<span style="background-color: #F5F3FF; color: #5B21B6; border: 1px solid #DDD6FE; padding: 6px 12px; border-radius: 8px; font-weight: 700; font-size: 0.9rem;">
Total Score: {int(screener_info['total_score'])}/100
</span>
</div>
{news_html}
</div>""",
            unsafe_allow_html=True
        )
    else:
        # Stock is NOT a part of nifty 500 stocks
        clean_symbol = symbol.replace(" ", "").strip().upper()
        st.toast(f"⚠️ {clean_symbol} is not a part of Nifty 500 stocks.", icon="⚠️")
        comp_name = clean_symbol
        if live_stats:
            try:
                import yfinance as yf
                ticker = yf.Ticker(live_stats["ticker_used"])
                comp_name = ticker.info.get("longName", clean_symbol)
            except Exception:
                pass
                
        st.markdown(
            f"""<div style="background-color: #FFFBEB; border: 1.5px solid #FCD34D; border-radius: 10px; padding: 18px; margin-top: 15px; margin-bottom: 5px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
<span style="font-size: 0.85rem; color: #B45309; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em;">⚠️ Non-Constituent Index Alert</span>
<h5 style="margin: 6px 0 4px 0; color: #78350F; font-size: 1.3rem; font-weight: 700; font-family: 'Outfit', sans-serif;">
{comp_name} ({clean_symbol})
</h5>
<p style="font-size: 1.05rem; color: #78350F; margin: 4px 0 10px 0; font-weight: 600; line-height: 1.4;">
Notice: <strong>{clean_symbol}</strong> is not a part of the active Nifty 500 stocks. 
Quantamental scoring metrics are N/A.
</p>
<p style="font-size: 1.05rem; color: #475569; margin: 0 0 12px 0; font-weight: 500; line-height: 1.4;">
LTP: <strong style="color: #059669;">₹ {ltp:,.2f}</strong> {"(Live)" if live_stats else "(N/A)"} &nbsp;&bull;&nbsp;
52-Week High: <strong style="color: #0F172A;">₹ {high_52w:,.2f}</strong> &nbsp;&bull;&nbsp; 
52-Week Low: <strong style="color: #0F172A;">₹ {low_52w:,.2f}</strong>
</p>
<div style="display: flex; gap: 12px; margin-top: 5px; flex-wrap: wrap;">
<span style="background-color: #F3F4F6; color: #4B5563; border: 1px solid #E5E7EB; padding: 6px 12px; border-radius: 8px; font-weight: 700; font-size: 0.9rem;">
Fundamental Score: N/A
</span>
<span style="background-color: #F3F4F6; color: #4B5563; border: 1px solid #E5E7EB; padding: 6px 12px; border-radius: 8px; font-weight: 700; font-size: 0.9rem;">
Momentum Score: N/A
</span>
<span style="background-color: #F3F4F6; color: #4B5563; border: 1px solid #E5E7EB; padding: 6px 12px; border-radius: 8px; font-weight: 700; font-size: 0.9rem;">
Total Score: N/A
</span>
</div>
{news_html}
</div>""",
            unsafe_allow_html=True
        )

def check_and_perform_rollover() -> bool:
    # Load current values from database
    stored_opening = float(get_db_settings("capital_opening", "0.0"))
    stored_added = float(get_db_settings("capital_added", "0.0"))
    stored_withdrawn = float(get_db_settings("capital_withdrawn", "0.0"))
    stored_adjustment = float(get_db_settings("capital_adjustment", "0.0"))
    last_rollover_date = get_db_settings("capital_last_rollover_date", "")
    
    current_time = datetime.now()
    current_date_str = current_time.strftime("%Y-%m-%d")
    
    # If this is the very first run and last_rollover_date is empty, initialize it
    if not last_rollover_date:
        save_db_setting("capital_last_rollover_date", current_date_str)
        return False
        
    # Check if a new day has arrived and local time is past 6:00 AM
    if current_date_str != last_rollover_date and current_time.hour >= 6:
        # Fetch trades P&L for the last_rollover_date
        df_all = fetch_trades_df()
        if not df_all.empty:
            df_last_day_trades = df_all[df_all['trade_date'] == last_rollover_date]
            last_day_pnl = float(df_last_day_trades['net_pnl'].sum())
        else:
            last_day_pnl = 0.0
            
        # Compute closing capital for the last_rollover_date
        closing_capital = stored_opening + stored_added - stored_withdrawn + last_day_pnl + stored_adjustment
        
        # Save as the new opening capital
        save_db_setting("capital_opening", str(closing_capital))
        # Reset daily adjustments to 0.0
        save_db_setting("capital_added", "0.0")
        save_db_setting("capital_withdrawn", "0.0")
        save_db_setting("capital_adjustment", "0.0")
        # Update last rollover date to current date
        save_db_setting("capital_last_rollover_date", current_date_str)
        
        return True
        
    return False

# 1. Page Configuration and Theme Skinning
st.set_page_config(
    page_title="Fin+ // Professional Trading Journal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Sidebar Theme Customization
st.sidebar.markdown('<h3 style="margin-top:0; color: var(--text-primary);">🎨 Workstation Theme</h3>', unsafe_allow_html=True)
st.sidebar.markdown(
    """
    <div style="background-color: #ECFDF5; border: 1.5px solid #A7F3D0; border-radius: 8px; padding: 10px; margin-bottom: 20px;">
        <span style="color: #065F46; font-weight: 700; font-size: 0.9rem;">🟢 Emerald Light Active</span>
        <div style="color: #047857; font-size: 0.8rem; margin-top: 3px;">Optimized for visual health, eye comfort, and high tactile 3D contrast.</div>
    </div>
    """,
    unsafe_allow_html=True
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

# Read and inject custom CSS styles
css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles.css")
if os.path.exists(css_path):
    with open(css_path, "r") as f:
        st.markdown(f"<style>{f.read()}\n{variables_css}</style>", unsafe_allow_html=True)
else:
    st.markdown(f"<style>{variables_css}</style>", unsafe_allow_html=True)

# App Header
st.markdown('<h1 class="glowing-header">Fin+ // ANALYTICS</h1>', unsafe_allow_html=True)
st.markdown('<p style="color: var(--text-secondary); margin-top:-15px; margin-bottom: 25px;">Institutional Grade Performance Tracking & Psychology Audit</p>', unsafe_allow_html=True)

# Initialize session state for add trade form reset
if "add_form_id" not in st.session_state:
    st.session_state["add_form_id"] = 0

# Fetch latest trades from database
df_trades = fetch_trades_df()

# Check and execute automatic daily capital rollover at 6:00 AM
if check_and_perform_rollover():
    df_trades = fetch_trades_df()  # Refetch post-rollover to keep data fresh

# Compute sequential active trade numbers chronologically
if not df_trades.empty:
    df_trades = df_trades.sort_values(by=['trade_date', 'id'], ascending=[True, True])
    df_trades['s_no'] = range(1, len(df_trades) + 1)
    df_trades = df_trades.sort_values(by=['trade_date', 'id'], ascending=[False, False])
else:
    df_trades['s_no'] = pd.Series(dtype='int')

# Load regional currency settings globally
currency_sym = get_db_settings("currency_symbol", "₹")

# 2. Main Tabs Layout
tab_dash, tab_add, tab_logs, tab_psych, tab_risk, tab_capital, tab_settings = st.tabs([
    "📊 Performance Dashboard",
    "📝 Log a Trade",
    "🔍 Search & Edit Logs",
    "🧠 Psychology & Strategy",
    "🧮 Position Size Planner",
    "💳 Capital Manager",
    "⚙️ System Settings"
])

# ==========================================
# TAB 1: PERFORMANCE DASHBOARD
# ==========================================
with tab_dash:
    if df_trades.empty:
        st.markdown(
            """
            <div class="glass-card" style="text-align: center; padding: 50px 20px;">
                <h3 style="color: #3B82F6; margin-bottom: 10px;">Welcome to Fin+</h3>
                <p style="color: var(--text-secondary); margin-bottom: 20px;">Your trading journal is currently empty. Head over to the 'Log a Trade' tab or import a sample CSV in 'System Settings' to get started!</p>
            </div>
            """, 
            unsafe_allow_html=True
        )
    else:
        # Calculate Key Performance Indicators (KPIs)
        total_trades = len(df_trades)
        gross_profit = df_trades[df_trades['net_pnl'] > 0]['net_pnl'].sum()
        gross_loss = df_trades[df_trades['net_pnl'] < 0]['net_pnl'].sum()
        
        winning_trades = len(df_trades[df_trades['net_pnl'] > 0])
        losing_trades = len(df_trades[df_trades['net_pnl'] < 0])
        
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else (gross_profit if gross_profit > 0 else 1.0)
        
        net_pnl = df_trades['net_pnl'].sum()
        total_charges = df_trades['total_charges'].sum()
        
        avg_win = df_trades[df_trades['net_pnl'] > 0]['net_pnl'].mean() if winning_trades > 0 else 0.0
        avg_loss = df_trades[df_trades['net_pnl'] < 0]['net_pnl'].mean() if losing_trades > 0 else 0.0
        
        expectancy = ( (win_rate/100) * avg_win ) + ( (1 - win_rate/100) * avg_loss )
        
        # Display Metric Columns with Custom CSS
        m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
        
        with m_col1:
            pnl_color = "var(--accent-green)" if net_pnl >= 0 else "var(--accent-red)"
            st.metric(
                label="Net P&L", 
                value=f"{currency_sym} {net_pnl:,.2f}",
                delta=f"After {currency_sym}{total_charges:,.2f} Taxes",
                delta_color="off"
            )
        with m_col2:
            st.metric(
                label="Win Rate", 
                value=f"{win_rate:.1f}%",
                delta=f"{winning_trades}W - {losing_trades}L"
            )
        with m_col3:
            st.metric(
                label="Profit Factor", 
                value=f"{profit_factor:.2f}x",
                delta="Target: > 1.5x"
            )
        with m_col4:
            st.metric(
                label="Expectancy", 
                value=f"{currency_sym} {expectancy:,.2f}",
                delta="Avg net profit per trade"
            )
        with m_col5:
            st.metric(
                label="Total Trades Logged", 
                value=str(total_trades)
            )
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Row 2: Charts and Calendars
        c_col1, c_col2 = st.columns([3, 2])
        
        with c_col1:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown('<h3 style="margin-top:0;">Cumulative Net P&L (Equity Curve)</h3>', unsafe_allow_html=True)
            
            # Sort trades chronologically to compute cumulative curve
            df_chrono = df_trades.sort_values(by=['trade_date', 'id']).copy()
            df_chrono['cumulative_pnl'] = df_chrono['net_pnl'].cumsum()
            
            # Plotly Equity Curve
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_chrono['trade_date'],
                y=df_chrono['cumulative_pnl'],
                mode='lines+markers',
                name='Net P&L',
                line=dict(color='#3B82F6', width=3),
                marker=dict(size=6, color='#60A5FA'),
                fill='tozeroy',
                fillcolor='rgba(59, 130, 246, 0.05)'
            ))
            
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(
                    showgrid=True,
                    gridcolor='rgba(0,0,0,0.05)',
                    tickformat='%Y-%m-%d',
                    color='#475569'
                ),
                yaxis=dict(
                    showgrid=True,
                    gridcolor='rgba(0,0,0,0.05)',
                    color='#475569'
                ),
                height=350,
                showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        with c_col2:
            st.markdown('<div class="glass-card">', unsafe_allow_html=True)
            st.markdown('<h3 style="margin-top:0;">Daily Segment Contribution</h3>', unsafe_allow_html=True)
            
            # Segment Pie/Donut Chart
            segment_pnl = df_trades.groupby('segment')['net_pnl'].sum().reset_index()
            
            # Custom colors for segments
            colors = ['#10B981', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#EC4899']
            
            fig_pie = px.pie(
                segment_pnl, 
                values='net_pnl', 
                names='segment',
                hole=0.4,
                color_discrete_sequence=colors
            )
            fig_pie.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=10, r=10, t=10, b=10),
                legend=dict(font=dict(color='#0F172A')),
                height=350
            )
            fig_pie.update_traces(
                textposition='inside', 
                textinfo='percent+label',
                marker=dict(line=dict(color='#FFFFFF', width=2))
            )
            st.plotly_chart(fig_pie, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # Monthly Trading Calendar View
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<h3 style="margin-top:0; margin-bottom:15px;">Monthly Performance Calendar</h3>', unsafe_allow_html=True)
        
        # Select Month and Year
        today_date = date.today()
        cal_col1, cal_col2 = st.columns(2)
        with cal_col1:
            selected_year = st.selectbox("Select Year", list(range(today_date.year - 3, today_date.year + 1)), index=3)
        with cal_col2:
            selected_month = st.selectbox("Select Month", list(calendar.month_name)[1:], index=today_date.month - 1)
            
        month_idx = list(calendar.month_name).index(selected_month)
        
        # Calculate daily Net PNL for selected month/year
        df_trades['parsed_date'] = pd.to_datetime(df_trades['trade_date'])
        df_month = df_trades[
            (df_trades['parsed_date'].dt.year == selected_year) & 
            (df_trades['parsed_date'].dt.month == month_idx)
        ]
        
        daily_pnl = df_month.groupby(df_month['parsed_date'].dt.day)['net_pnl'].sum().to_dict()
        
        # Draw Calendar Grid
        cal = calendar.Calendar(firstweekday=calendar.MONDAY)
        month_days = cal.monthdayscalendar(selected_year, month_idx)
        
        # Construct the entire Calendar HTML in a single string to maintain structural DOM grid layout!
        cal_html = '<div class="calendar-container">'
        
        # Add headers
        for day_name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            cal_html += f'<div class="calendar-day-header">{day_name}</div>'
            
        # Add day boxes
        for week in month_days:
            for day in week:
                if day == 0:
                    cal_html += '<div class="calendar-day-box" style="opacity: 0.1;"></div>'
                else:
                    day_pnl = daily_pnl.get(day, 0.0)
                    day_class = ""
                    pnl_text = ""
                    pnl_class = ""
                    
                    if day_pnl > 0:
                        day_class = "green"
                        pnl_text = f"+{currency_sym}{day_pnl:,.1f}"
                        pnl_class = "green"
                    elif day_pnl < 0:
                        day_class = "red"
                        pnl_text = f"-{currency_sym}{abs(day_pnl):,.1f}"
                        pnl_class = "red"
                        
                    cal_html += f'<div class="calendar-day-box {day_class}">'
                    cal_html += f'<div class="calendar-day-number">{day}</div>'
                    cal_html += f'<div class="calendar-day-pnl {pnl_class}">{pnl_text}</div>'
                    cal_html += '</div>'
        
        cal_html += '</div>'
        
        # Render the entire calendar in a single contiguous HTML block!
        st.markdown(cal_html, unsafe_allow_html=True)
        
        # Interactive Daily Trade Inspector (Option 2.2)
        st.markdown("<hr style='border-color: var(--border-color); margin: 25px 0;'>", unsafe_allow_html=True)
        st.markdown("<h5>📅 Daily Trade Inspector</h5>", unsafe_allow_html=True)
        st.markdown("<p style='color: var(--text-secondary); margin-top:-10px; margin-bottom: 15px;'>Select any active day in this month to inspect detailed trade logs, charge calculations, and psychological emotional rules logged.</p>", unsafe_allow_html=True)
        
        # Retrieve all active days with trades in the selected month/year
        trading_days = sorted(list(df_month['parsed_date'].dt.day.unique()))
        
        if not trading_days:
            st.info("No trades executed in this month to inspect.")
        else:
            inspect_day = st.selectbox(
                "Select Trading Day to Inspect",
                options=["-- Select an Active Trading Day --"] + [f"{day:02d} {selected_month} {selected_year}" for day in trading_days],
                index=0,
                key="dashboard_calendar_inspector"
            )
            
            if inspect_day != "-- Select an Active Trading Day --":
                # Get day integer
                day_num = int(inspect_day.split()[0])
                df_day_trades = df_month[df_month['parsed_date'].dt.day == day_num].copy()
                
                st.markdown(f"###### Detailed Log Sheets for **{inspect_day}**")
                
                df_day_display = df_day_trades.copy()
                df_day_display['gross_pnl'] = df_day_display['gross_pnl'].map(lambda x: f"{currency_sym}{x:,.2f}")
                df_day_display['total_charges'] = df_day_display['total_charges'].map(lambda x: f"{currency_sym}{x:,.2f}")
                df_day_display['net_pnl'] = df_day_display['net_pnl'].map(lambda x: f"{currency_sym}{x:,.2f}")
                df_day_display = df_day_display.rename(columns={"s_no": "Trade #"})
                
                st.dataframe(
                    df_day_display[[
                        "Trade #", "symbol", "segment", "action", "quantity", 
                        "entry_price", "exit_price", "gross_pnl", "total_charges", 
                        "net_pnl", "strategy", "mistake", "notes"
                    ]],
                    use_container_width=True,
                    hide_index=True
                )
                
        st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 2: LOG A TRADE (ENTRY FORM)
# ==========================================
with tab_add:
    st.markdown('<div class="glass-card preview-card">', unsafe_allow_html=True)
    st.markdown('<h3>Record Completed Trade</h3>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Select your asset segment and parameters. The engine will auto-calculate taxes based on your configured global rates.</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Initialize form ID if not present
    if "add_form_id" not in st.session_state:
        st.session_state["add_form_id"] = 0
        
    # Check for deep-linked query parameters on app load (Pre-population)
    url_ticker = st.query_params.get("add_ticker", "").strip().upper()
    url_price = st.query_params.get("add_price", "")
    url_segment = st.query_params.get("add_segment", "").strip()
    
    # Defaults
    default_symbol = url_ticker.replace(".NS", "") if url_ticker else ""
    default_price = 0.0
    try:
        if url_price:
            default_price = float(url_price)
    except ValueError:
        pass
    
    # Load global brokerage rates to pre-fill default values
    brokerage_rates = get_brokerage_rates()
    
    default_segment_idx = 0
    if url_segment and url_segment in list(brokerage_rates.keys()):
        default_segment_idx = list(brokerage_rates.keys()).index(url_segment)
    
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        t_date = st.date_input("Trade Date", value=date.today(), key=f"add_date_{st.session_state['add_form_id']}")
        t_symbol = st.text_input("Ticker / Symbol", value=default_symbol, placeholder="e.g. INFY, RELIANCE, NIFTY26MAY20000C", key=f"add_symbol_{st.session_state['add_form_id']}").upper()
        
        t_segment = st.selectbox(
            "Asset Segment",
            options=list(brokerage_rates.keys()),
            index=default_segment_idx,
            key=f"add_segment_{st.session_state['add_form_id']}"
        )
        
        t_action = st.selectbox("Action", options=["BUY", "SELL"], format_func=lambda x: "BUY (Long)" if x == "BUY" else "SELL (Short)", key=f"add_action_{st.session_state['add_form_id']}")
    
    with f_col2:
        t_qty = st.number_input("Quantity", min_value=0.0, step=1.0, value=0.0, key=f"add_qty_{st.session_state['add_form_id']}")
        t_entry = st.number_input("Entry Price", min_value=0.0, step=0.05, value=default_price, key=f"add_entry_{st.session_state['add_form_id']}")
        t_exit = st.number_input("Exit Price", min_value=0.0, step=0.05, value=0.0, key=f"add_exit_{st.session_state['add_form_id']}")
        
        # Base Lot Size input field
        t_base_lot = st.number_input("Base Lot Size (0 for flat)", min_value=0.0, step=1.0, value=0.0, help="Set to minimum lot size (e.g. 65 or 75) to scale brokerage per lot automatically (Brokerage = Rate * Lots). Set to 0 to disable scaling.", key=f"add_base_lot_{st.session_state['add_form_id']}")
        
        # Fetch default brokerage per buy + sell for selected segment
        def_brokerage_buy = brokerage_rates[t_segment]["buy"]
        def_brokerage_sell = brokerage_rates[t_segment]["sell"]
        def_total_brokerage = def_brokerage_buy + def_brokerage_sell
        
        # Scale brokerage per lot if base lot size > 0
        import math
        lots = 1
        if t_base_lot > 0:
            lots = math.ceil(t_qty / t_base_lot)
        computed_brokerage = def_total_brokerage * lots
        
        # Brokerage input - Automatically populated and non-editable as requested!
        t_brokerage = st.number_input(
            "Total Brokerage (₹)", 
            min_value=0.0, 
            step=1.0, 
            value=float(computed_brokerage),
            disabled=True,
            help="Automated based on global settings and lot scaling. Go to System Settings to edit base rates.",
            key=f"add_brokerage_{st.session_state['add_form_id']}"
        )
        
    # Fetch Screener Context from Database Link (Visual Accessibility Integration)
    if t_symbol:
        render_quantamental_health_card(t_symbol, key_suffix="add")
    
    st.markdown("<hr style='border-color: var(--glass-border);'>", unsafe_allow_html=True)
    f_col3, f_col4 = st.columns(2)
    with f_col3:
        t_strategy = st.selectbox("Trading Strategy / Setup", options=DEFAULT_STRATEGIES, key=f"add_strategy_{st.session_state['add_form_id']}")
    with f_col4:
        t_mistake = st.selectbox("Mistake / Emotions Audit", options=DEFAULT_MISTAKES, key=f"add_mistake_{st.session_state['add_form_id']}")
        
    t_notes = st.text_area("Trade Notes / Psychological Context", placeholder="Describe entry trigger, plan validity, and exit management...", height=80, key=f"add_notes_{st.session_state['add_form_id']}")
    
    # Dynamic quote mismatch warning
    warning_msg = get_quote_mismatch_warning(t_symbol, t_segment)
    if warning_msg:
        st.warning(warning_msg)
        
    # Submit button
    submit_trade = st.button("Lock & Save Trade", type="primary", key=f"add_submit_{st.session_state['add_form_id']}")
    
    if submit_trade:
        if not t_symbol.strip():
            st.error("Please provide a valid ticker symbol.")
        elif t_qty <= 0:
            st.error("Quantity must be greater than zero.")
        elif t_entry <= 0:
            st.error("Entry Price must be greater than zero.")
        elif t_exit <= 0:
            st.error("Exit Price must be greater than zero.")
        else:
            # Calculate metrics
            metrics = calculate_trade_metrics(
                segment=t_segment,
                action=t_action,
                quantity=t_qty,
                entry_price=t_entry,
                exit_price=t_exit,
                brokerage_input=computed_brokerage
            )
            
            trade_to_save = {
                "trade_date": t_date.strftime("%Y-%m-%d"),
                "symbol": t_symbol,
                "segment": t_segment,
                "action": t_action,
                "quantity": t_qty,
                "entry_price": t_entry,
                "exit_price": t_exit,
                "brokerage": metrics["brokerage"],
                "stt": metrics["stt"],
                "exchange_charges": metrics["exchange_charges"],
                "sebi_charges": metrics["sebi_charges"],
                "stamp_duty": metrics["stamp_duty"],
                "gst": metrics["gst"],
                "total_charges": metrics["total_charges"],
                "gross_pnl": metrics["gross_pnl"],
                "net_pnl": metrics["net_pnl"],
                "strategy": t_strategy,
                "mistake": t_mistake,
                "notes": t_notes
            }
            
            add_trade(trade_to_save)
            st.session_state["add_form_id"] += 1
            st.success(f"Trade for {t_symbol} successfully saved to journal database!")
            st.rerun()

# ==========================================
# TAB 3: SEARCH & EDIT LOGS (TABLE VIEW)
# ==========================================
with tab_logs:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0;">Searchable Trading Journal Logs</h3>', unsafe_allow_html=True)
    
    # Define segments and strategies safely even if empty
    db_segments = list(df_trades['segment'].unique()) if not df_trades.empty else []
    db_strategies = list(df_trades['strategy'].unique()) if not df_trades.empty else []
    
    # Search Filters
    l_col1, l_col2, l_col3 = st.columns(3)
    with l_col1:
        search_ticker = st.text_input("Filter by Symbol", placeholder="e.g. RELIANCE").upper()
    with l_col2:
        filter_segment = st.multiselect("Filter by Segment", options=db_segments)
    with l_col3:
        filter_strategy = st.multiselect("Filter by Strategy", options=db_strategies)
        
    # Apply Filters to DataFrame
    df_filtered = df_trades.copy() if not df_trades.empty else pd.DataFrame(columns=[
        "id", "trade_date", "symbol", "segment", "action", "quantity", 
        "entry_price", "exit_price", "brokerage", "stt", "exchange_charges", 
        "sebi_charges", "stamp_duty", "gst", "total_charges", "gross_pnl", "net_pnl", 
        "strategy", "mistake", "notes"
    ])
    
    if not df_trades.empty:
        if search_ticker.strip():
            df_filtered = df_filtered[df_filtered['symbol'].str.contains(search_ticker)]
        if filter_segment:
            df_filtered = df_filtered[df_filtered['segment'].isin(filter_segment)]
        if filter_strategy:
            df_filtered = df_filtered[df_filtered['strategy'].isin(filter_strategy)]
        
    total_db_count = len(df_trades)
    filtered_count = len(df_filtered)
    st.markdown(f"<p style='color: var(--text-secondary); font-size: 0.85rem;'>Showing {filtered_count} of {total_db_count} logs</p>", unsafe_allow_html=True)
    
    # Display styled table
    df_display = df_filtered.copy()
    if not df_display.empty:
        df_display['gross_pnl'] = df_display['gross_pnl'].map(lambda x: f"{currency_sym}{x:,.2f}")
        df_display['total_charges'] = df_display['total_charges'].map(lambda x: f"{currency_sym}{x:,.2f}")
        df_display['net_pnl'] = df_display['net_pnl'].map(lambda x: f"{currency_sym}{x:,.2f}")
        df_display = df_display.rename(columns={"s_no": "Trade #"})
        
        st.dataframe(
            df_display[[
                "Trade #", "trade_date", "symbol", "segment", "action", 
                "quantity", "entry_price", "exit_price", 
                "gross_pnl", "total_charges", "net_pnl", "strategy", "mistake", "notes"
            ]],
            use_container_width=True,
            hide_index=True
        )
    else:
        # Create an empty dataframe with correct columns to display nicely
        empty_cols = [
            "Trade #", "trade_date", "symbol", "segment", "action", 
            "quantity", "entry_price", "exit_price", 
            "gross_pnl", "total_charges", "net_pnl", "strategy", "mistake", "notes"
        ]
        st.dataframe(pd.DataFrame(columns=empty_cols), use_container_width=True, hide_index=True)
    
    # Edit and Delete Operations
    st.markdown("<hr style='border-color: var(--border-color);'>", unsafe_allow_html=True)
    st.markdown("<h5>Manage / Edit Trade Log Entries</h5>", unsafe_allow_html=True)
    
    if df_filtered.empty:
        st.info("No trades matched the filters or database is empty. Add trades to edit/delete.")
    else:
        # User selected brokerage defaults
        brokerage_rates = get_brokerage_rates()
        
        # Create user-friendly display labels that show chronological S.No., Symbol, and Date!
        selectbox_options = ["-- Select a Trade to Edit / Manage --"]
        id_map = {}
        # Make sure options are sorted by sequential Trade # ascending
        df_filtered_sorted = df_filtered.sort_values(by=['s_no'], ascending=True)
        for index, row in df_filtered_sorted.iterrows():
            label = f"Trade #{row['s_no']} // {row['symbol']} on {row['trade_date']}"
            selectbox_options.append(label)
            id_map[label] = row['id']
            
        selected_label = st.selectbox("Select Trade to Manage", options=selectbox_options, index=0)
        
        if selected_label == "-- Select a Trade to Edit / Manage --":
            st.info("Select a trade from the dropdown above to view, edit, or delete its details.")
        else:
            selected_trade_id = int(id_map[selected_label])
            
            # Fetch the selected trade data
            trade_row = df_filtered[df_filtered['id'] == selected_trade_id].iloc[0]
            
            # Pre-filled edit form (Formless reactive layout)
            st.markdown(f"**Editing Trade #{trade_row['s_no']} ({trade_row['symbol']})**")
            e_col1, e_col2 = st.columns(2)
            
            with e_col1:
                e_date = st.date_input("Trade Date", value=datetime.strptime(trade_row['trade_date'], "%Y-%m-%d").date(), key=f"edit_date_{selected_trade_id}")
                e_symbol = st.text_input("Ticker / Symbol", value=trade_row['symbol'], key=f"edit_symbol_{selected_trade_id}").upper()
                e_segment = st.selectbox(
                    "Asset Segment", 
                    options=list(brokerage_rates.keys()), 
                    index=list(brokerage_rates.keys()).index(trade_row['segment']) if trade_row['segment'] in brokerage_rates else 0,
                    key=f"edit_segment_{selected_trade_id}"
                )
                e_action = st.selectbox(
                    "Action", 
                    options=["BUY", "SELL"], 
                    index=0 if trade_row['action'] == "BUY" else 1, 
                    format_func=lambda x: "BUY (Long)" if x == "BUY" else "SELL (Short)",
                    key=f"edit_action_{selected_trade_id}"
                )
                
            with e_col2:
                e_qty = st.number_input("Quantity", min_value=0.01, step=1.0, value=float(trade_row['quantity']), key=f"edit_qty_{selected_trade_id}")
                e_entry = st.number_input("Entry Price", min_value=0.01, step=0.05, value=float(trade_row['entry_price']), key=f"edit_entry_{selected_trade_id}")
                e_exit = st.number_input("Exit Price", min_value=0.01, step=0.05, value=float(trade_row['exit_price']), key=f"edit_exit_{selected_trade_id}")
                
                # Base Lot Size input field for scaling brokerage during edits
                e_base_lot = st.number_input(
                    "Base Lot Size (0 for flat)", 
                    min_value=0.0, 
                    step=1.0, 
                    value=0.0, 
                    help="Set to minimum lot size (e.g. 65 or 75) to scale brokerage per lot automatically (Brokerage = Rate * Lots). Set to 0 to disable scaling.", 
                    key=f"edit_base_lot_{selected_trade_id}"
                )
                
                # Compute default brokerage from rates for selected segment (pre-filled, read-only)
                e_def_brokerage_buy = brokerage_rates[e_segment]["buy"]
                e_def_brokerage_sell = brokerage_rates[e_segment]["sell"]
                e_def_total_brokerage = e_def_brokerage_buy + e_def_brokerage_sell
                
                import math
                e_lots = 1
                if e_base_lot > 0:
                    e_lots = math.ceil(e_qty / e_base_lot)
                    e_computed_brokerage = e_def_total_brokerage * e_lots
                else:
                    # If e_base_lot is 0, we can use the saved brokerage if no changes were made to segment and qty
                    if e_segment == trade_row['segment'] and e_qty == trade_row['quantity']:
                        e_computed_brokerage = float(trade_row['brokerage'])
                    else:
                        e_computed_brokerage = e_def_total_brokerage
                
                e_brokerage = st.number_input(
                    "Total Brokerage (₹)", 
                    min_value=0.0, 
                    step=1.0, 
                    value=float(e_computed_brokerage), 
                    disabled=True, 
                    key=f"edit_brokerage_display_{selected_trade_id}",
                    help="Automatically loaded based on segment settings and lot scaling."
                )
            # Fetch Screener Context from Database Link (Visual Accessibility Integration)
            if e_symbol:
                render_quantamental_health_card(e_symbol, key_suffix=f"edit_{selected_trade_id}")
            
            st.markdown("<hr style='border-color: var(--border-color);'>", unsafe_allow_html=True)
            e_col3, e_col4 = st.columns(2)
            with e_col3:
                e_strategy = st.selectbox(
                    "Trading Strategy / Setup", 
                    options=DEFAULT_STRATEGIES, 
                    index=DEFAULT_STRATEGIES.index(trade_row['strategy']) if trade_row['strategy'] in DEFAULT_STRATEGIES else 0,
                    key=f"edit_strategy_{selected_trade_id}"
                )
            with e_col4:
                e_mistake = st.selectbox(
                    "Mistake / Emotions Audit", 
                    options=DEFAULT_MISTAKES, 
                    index=DEFAULT_MISTAKES.index(trade_row['mistake']) if trade_row['mistake'] in DEFAULT_MISTAKES else 0,
                    key=f"edit_mistake_{selected_trade_id}"
                )
                
            e_notes = st.text_area("Trade Notes / Psychological Context", value=trade_row['notes'] if trade_row['notes'] else "", height=80, key=f"edit_notes_{selected_trade_id}")
            
            # Dynamic quote mismatch warning
            warning_msg = get_quote_mismatch_warning(e_symbol, e_segment)
            if warning_msg:
                st.warning(warning_msg)
                
            # Submit Button
            submit_update = st.button("Save & Update Trade", type="primary", key=f"edit_update_btn_{selected_trade_id}")
            
            # Delete action button outside form (to avoid form submission collisions)
            del_col1, del_col2 = st.columns([1, 2])
            with del_col1:
                if st.button("❌ Delete Selected Trade Entry", key=f"del_btn_{selected_trade_id}", type="secondary"):
                    delete_trade(selected_trade_id)
                    st.success(f"Trade Entry #{selected_trade_id} successfully removed.")
                    st.rerun()
                
            with del_col2:
                st.markdown(
                    """
                    <p style="color: var(--text-secondary); font-size: 0.85rem; margin-top:10px;">
                        Warning: Deleting a trade entry is permanent. Click 'Save & Update Trade' above to write updates.
                    </p>
                    """, 
                    unsafe_allow_html=True
                )
                
            if submit_update:
                if not e_symbol.strip():
                    st.error("Please provide a valid ticker symbol.")
                else:
                    # Recalculate metrics
                    metrics = calculate_trade_metrics(
                        segment=e_segment,
                        action=e_action,
                        quantity=e_qty,
                        entry_price=e_entry,
                        exit_price=e_exit,
                        brokerage_input=e_computed_brokerage
                    )
                    
                    updated_trade_to_save = {
                        "trade_date": e_date.strftime("%Y-%m-%d"),
                        "symbol": e_symbol,
                        "segment": e_segment,
                        "action": e_action,
                        "quantity": e_qty,
                        "entry_price": e_entry,
                        "exit_price": e_exit,
                        "brokerage": metrics["brokerage"],
                        "stt": metrics["stt"],
                        "exchange_charges": metrics["exchange_charges"],
                        "sebi_charges": metrics["sebi_charges"],
                        "stamp_duty": metrics["stamp_duty"],
                        "gst": metrics["gst"],
                        "total_charges": metrics["total_charges"],
                        "gross_pnl": metrics["gross_pnl"],
                        "net_pnl": metrics["net_pnl"],
                        "strategy": e_strategy,
                        "mistake": e_mistake,
                        "notes": e_notes
                    }
                    
                    update_trade(selected_trade_id, updated_trade_to_save)
                    st.success(f"Trade Entry #{selected_trade_id} successfully updated!")
                    st.rerun()
                    
    # Ticker Quick Lookup in Nifty 500 Screener (Interactive Visual Accessibility Integration)
    st.markdown("<hr style='border-color: var(--border-color); margin: 25px 0;'>", unsafe_allow_html=True)
    st.markdown("<h5>🔍 Screener Quantitative Jump Analysis</h5>", unsafe_allow_html=True)
    st.markdown("<p style='color: var(--text-secondary); font-size: 0.9rem;'>Type any stock ticker from your journal to instantly cross-navigate to its charts, P/E bands, and option chains in the Screener terminal.</p>", unsafe_allow_html=True)
    
    j_col1, j_col2 = st.columns([2, 3])
    with j_col1:
        jump_ticker = st.text_input("Enter Ticker to Analyze", placeholder="e.g. BSE, INFY", key="logs_quick_jump_ticker").upper().strip()
    with j_col2:
        st.write("")
        st.write("")
        if jump_ticker:
            st.markdown(
                f"""
                <a href="http://localhost:8506/?focus_ticker={jump_ticker}" target="_blank" style="background-color: #1D4ED8; color: #FFFFFF; font-weight: 700; padding: 10px 22px; border-radius: 8px; text-decoration: none; font-size: 1.05rem; display: inline-flex; align-items: center; box-shadow: 0 4px 12px rgba(29, 78, 216, 0.2); transition: all 0.2s ease;">
                    📊 Deep Analyze `{jump_ticker}` in Screener Tab
                </a>
                """,
                unsafe_allow_html=True
            )
        else:
            st.info("Enter a symbol on the left to activate deep-linking analysis.")
            
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 4: PSYCHOLOGY & STRATEGY
# ==========================================
with tab_psych:
    if df_trades.empty:
        st.info("Log a few trades to begin tracking setup win rates and psychological leakage.")
    else:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<h3 style="margin-top:0;">1. Psychological Leak Calculator (Cost of Mistakes)</h3>', unsafe_allow_html=True)
        st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Institutional traders track visual leaks: money lost solely due to rule violations or emotional impulses.</p>', unsafe_allow_html=True)
        
        # Calculate loss per mistake type
        mistake_analysis = df_trades.groupby('mistake')['net_pnl'].agg(['sum', 'count']).reset_index()
        # Filter for negative P&L mistakes or simply sum up P&L
        # In professional psychology audit, we sum the actual net P&L of trades grouped by mistake.
        # Highlighting the negative sums shows how much that mistake drained from the equity curve.
        mistake_analysis = mistake_analysis.sort_values(by='sum')
        
        # Draw a beautiful bar chart of PNL by Mistake
        fig_mistake = px.bar(
            mistake_analysis,
            x='sum',
            y='mistake',
            orientation='h',
            title='Net Profit/Loss Impact by Emotional State / Mistake (Taxes Adjusted)',
            color='sum',
            color_continuous_scale=px.colors.sequential.Reds_r,
            labels={'sum': 'Cumulative Net Impact', 'mistake': 'Psychological Audit / Mistake'}
        )
        fig_mistake.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', color='#475569'),
            yaxis=dict(showgrid=False, color='#475569'),
            title_font=dict(color='#0F172A', size=14),
            height=300,
            coloraxis_showscale=False
        )
        st.plotly_chart(fig_mistake, use_container_width=True)
        
        # Summary of psychological leaks
        fomo_total = df_trades[df_trades['mistake'] != 'None']['net_pnl'].sum()
        fomo_color = "red" if fomo_total < 0 else "green"
        st.markdown(
            f"""
            > [!CAUTION]
            > **Rule Violation Capital Leak**: Your total financial loss associated with emotional mistakes is **{currency_sym}{abs(fomo_total):,.2f}**. 
            > Eliminating these errors would increase your overall trading capital by that exact amount.
            """
        )
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<h3 style="margin-top:0;">2. Strategy Efficiency Analysis</h3>', unsafe_allow_html=True)
        st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Evaluate which trading setups are high expectancy and which ones are underperforming.</p>', unsafe_allow_html=True)
        
        # Group by strategy
        strategy_analysis = df_trades.groupby('strategy').agg(
            total_trades=('net_pnl', 'count'),
            win_rate=('net_pnl', lambda x: (sum(x > 0) / len(x)) * 100),
            total_pnl=('net_pnl', 'sum'),
            avg_pnl=('net_pnl', 'mean')
        ).reset_index()
        
        strat_col1, strat_col2 = st.columns(2)
        
        with strat_col1:
            fig_strat_pnl = px.bar(
                strategy_analysis,
                x='strategy',
                y='total_pnl',
                title='Total Cumulative P&L by Strategy Setup',
                color='total_pnl',
                color_continuous_scale=px.colors.diverging.RdYlGn,
                labels={'total_pnl': 'Net Profit/Loss', 'strategy': 'Strategy Setup'}
            )
            fig_strat_pnl.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, color='#475569'),
                yaxis=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', color='#475569'),
                title_font=dict(color='#0F172A', size=14),
                height=300,
                coloraxis_showscale=False
            )
            st.plotly_chart(fig_strat_pnl, use_container_width=True)
            
        with strat_col2:
            fig_strat_wr = px.bar(
                strategy_analysis,
                x='strategy',
                y='win_rate',
                title='Win Rate (%) by Strategy Setup',
                labels={'win_rate': 'Win Rate %', 'strategy': 'Strategy Setup'}
            )
            fig_strat_wr.update_traces(marker_color='#8B5CF6')
            fig_strat_wr.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, color='#475569'),
                yaxis=dict(showgrid=True, gridcolor='rgba(0,0,0,0.05)', color='#475569'),
                title_font=dict(color='#0F172A', size=14),
                height=300
            )
            st.plotly_chart(fig_strat_wr, use_container_width=True)
            
        # Tabular breakdown for Strategy Setup
        st.markdown("<hr style='border-color: var(--border-color);'>", unsafe_allow_html=True)
        st.markdown("<h5>Detailed Strategy Breakdown</h5>", unsafe_allow_html=True)
        
        strategy_display = strategy_analysis.copy()
        
        # Rename columns for high readability
        strategy_display.columns = [
            "Strategy Setup", 
            "Total Trades", 
            "Win Rate (%)", 
            "Cumulative Net P&L", 
            "Average Net P&L per Trade"
        ]
        
        # Format numerical fields
        strategy_display["Win Rate (%)"] = strategy_display["Win Rate (%)"].map(lambda x: f"{x:.1f}%")
        strategy_display["Cumulative Net P&L"] = strategy_display["Cumulative Net P&L"].map(lambda x: f"{currency_sym}{x:,.2f}")
        strategy_display["Average Net P&L per Trade"] = strategy_display["Average Net P&L per Trade"].map(lambda x: f"{currency_sym}{x:,.2f}")
        
        st.dataframe(
            strategy_display,
            use_container_width=True,
            hide_index=True
        )
            
        st.markdown('</div>', unsafe_allow_html=True)
        
        # 3. Cognitive Behavioral Leak Heatmap (Option 2.3)
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown('<h3 style="margin-top:0;">3. Cognitive Behavioral Leak Heatmap</h3>', unsafe_allow_html=True)
        st.markdown('<p style="color: var(--text-secondary); margin-top:-10px; margin-bottom: 20px;">Cross-reference emotional mistakes and discipline violations against your trading setups to locate high-cost behavioral leaks.</p>', unsafe_allow_html=True)
        
        # Filter for actual mistakes (exclude None)
        df_leak = df_trades[df_trades['mistake'] != 'None'].copy()
        
        if df_leak.empty:
            st.info("💡 No emotional mistakes or rule violations logged yet! Keep logging your discipline metrics in Log a Trade to compile the Cognitive Behavioral Leak Heatmap.")
        else:
            # Pivot table to sum Net P&L per Mistake type per Strategy Setup
            leak_pivot = df_leak.pivot_table(
                index='mistake',
                columns='strategy',
                values='net_pnl',
                aggfunc='sum'
            ).fillna(0)
            
            # Plotly Heatmap
            fig_heatmap = px.imshow(
                leak_pivot,
                text_auto=".0f",
                color_continuous_scale="Reds_r",
                labels=dict(x="Strategy Setup / Trading System", y="Psychological Leak / Violation", color=f"Net P&L ({currency_sym})"),
                title="Cumulative Capital Drain by Mistake vs Setup Setup"
            )
            
            fig_heatmap.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, color='#475569'),
                yaxis=dict(showgrid=False, color='#475569'),
                title_font=dict(color='#0F172A', size=14),
                height=350,
                coloraxis_colorbar=dict(title=f"Net P&L ({currency_sym})")
            )
            
            st.plotly_chart(fig_heatmap, use_container_width=True)
            
            st.markdown(
                f"""
                > [!WARNING]
                > **Leak Analysis Interpretation**: Deep red zones highlight critical structural leaks where psychological mistakes drain strategy performance. 
                > For example, if you see high losses for **FOMO** on **Breakout**, it highlights that trading discipline (and not the strategy itself) is the primary source of loss. Use this breakdown to establish hard stop rules for specific setups.
                """
            )
            
        st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 5: POSITION SIZE PLANNER
# ==========================================
with tab_risk:
    st.markdown('<div class="glass-card preview-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0; color: var(--text-primary);">Institutional Capital Allocation & Leverage Planner</h3>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Plan your capital deployment, risk tolerance, and broker leverage (MTF/Intraday) to auto-calculate Stop Loss, Target, and quantities.</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    brokerage_rates = get_brokerage_rates()
    rc_col1, rc_col2 = st.columns([3, 2])
    
    with rc_col1:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("<h5>Planned Sizing Parameters</h5>", unsafe_allow_html=True)
        
        r_col1, r_col2 = st.columns(2)
        with r_col1:
            planned_segment = st.selectbox("Asset Segment", options=list(brokerage_rates.keys()), key="planner_segment_sel")
            capital_deployed = st.number_input("Capital Deployed (₹)", min_value=0.0, step=100.0, value=0.0, help="The actual money you wish to deploy for this specific trade.", key="calc_cap_deployed")
            risk_pct = st.number_input("Risk Tolerance (%)", min_value=0.0, max_value=100.0, step=0.1, value=2.0, help="Your maximum risk percentage on the deployed capital.", key="calc_risk_tolerance")
            
        with r_col2:
            trade_action = st.selectbox("Direction", options=["BUY", "SELL"], format_func=lambda x: "BUY (Long)" if x == "BUY" else "SELL (Short)", key="planner_direction_sel")
            calc_entry = st.number_input("Planned Entry Price (₹)", min_value=0.0, step=1.0, value=0.0, help="The price at which you will enter the stock.", key="calc_entry_val")
            leverage = st.number_input("Leverage Applied (x)", min_value=0.0, max_value=5.0, step=1.0, value=0.0, help="Broker leverage (0 for no leverage, 4 for 4x additional leverage MTF/Intraday). Cap set at 5x.", key="calc_leverage_val")
            
        # 1. Total available buying power = Capital Deployed * (1 + Leverage)
        total_exposure = capital_deployed * (1 + leverage)
        
        is_valid = capital_deployed > 0 and calc_entry > 0
        is_over_budget = is_valid and calc_entry > total_exposure
        
        # 2. Calculate values dynamically on every rerun if within budget
        if is_valid and not is_over_budget:
            # Total Risk in Rupees on Total Exposure (Buying Power)
            risk_rupees = total_exposure * (risk_pct / 100)
            
            # Optimal Quantity = Total Buying Power / Entry Price (rounded down to whole shares)
            optimal_qty = int(total_exposure / calc_entry)
            
            if optimal_qty > 0:
                # Risk per share
                risk_per_share = risk_rupees / optimal_qty
                
                # Auto-Calculated Stop Loss Price
                sl_price = calc_entry - risk_per_share
                
                # Auto-Calculated Target Price (Professional 1:2 Risk-to-Reward Ratio)
                target_price = calc_entry + (2 * risk_per_share)
                
                estimated_reward = optimal_qty * (2 * risk_per_share)
                
                # Retrieve default brokerage rates
                def_brokerage_buy = brokerage_rates[planned_segment]["buy"]
                def_brokerage_sell = brokerage_rates[planned_segment]["sell"]
                def_total_brokerage = def_brokerage_buy + def_brokerage_sell
                
                # Compute charges at Stop Loss
                metrics_sl = calculate_trade_metrics(
                    segment=planned_segment,
                    action=trade_action,
                    quantity=optimal_qty,
                    entry_price=calc_entry,
                    exit_price=sl_price,
                    brokerage_input=def_total_brokerage
                )
                charges_sl = metrics_sl["total_charges"]
                total_risk_with_charges = risk_rupees + charges_sl
                
                # Compute charges at Target
                metrics_tgt = calculate_trade_metrics(
                    segment=planned_segment,
                    action=trade_action,
                    quantity=optimal_qty,
                    entry_price=calc_entry,
                    exit_price=target_price,
                    brokerage_input=def_total_brokerage
                )
                charges_tgt = metrics_tgt["total_charges"]
                net_reward_with_charges = estimated_reward - charges_tgt
            else:
                risk_rupees = 0.0
                optimal_qty = 0
                risk_per_share = 0.0
                sl_price = 0.0
                target_price = 0.0
                estimated_reward = 0.0
                charges_sl = 0.0
                total_risk_with_charges = 0.0
                charges_tgt = 0.0
                net_reward_with_charges = 0.0
        else:
            risk_rupees = 0.0
            optimal_qty = 0
            risk_per_share = 0.0
            sl_price = 0.0
            target_price = 0.0
            estimated_reward = 0.0
            charges_sl = 0.0
            total_risk_with_charges = 0.0
            charges_tgt = 0.0
            net_reward_with_charges = 0.0

        st.markdown("<hr style='border-color: var(--glass-border); margin: 15px 0;'>", unsafe_allow_html=True)
        st.markdown("##### Automatically Computed Thresholds", unsafe_allow_html=True)
        
        sl_col, tgt_col = st.columns(2)
        with sl_col:
            st.number_input("Stop Loss Price (₹)", value=float(sl_price), disabled=True, format="%.2f", help="Auto-calculated stop loss adjusted for risk tolerance and leverage.")
        with tgt_col:
            st.number_input("Target Price (₹)", value=float(target_price), disabled=True, format="%.2f", help="Auto-calculated target price (1:2 Risk-to-Reward ratio).")
            
        if is_over_budget:
            st.warning(f"⚠️ Planned Entry Price ({currency_sym}{calc_entry:,.2f}) exceeds your total available Buying Power ({currency_sym}{total_exposure:,.2f}). Please increase capital or leverage to trade this asset.")
        elif is_valid and optimal_qty == 0:
            st.warning(f"⚠️ Your available Buying Power ({currency_sym}{total_exposure:,.2f}) is insufficient to purchase even 1 share of this asset at {currency_sym}{calc_entry:,.2f}.")
            
        st.markdown('</div>', unsafe_allow_html=True)
        
    with rc_col2:
        st.markdown('<div class="glass-card" style="height: 100%;">', unsafe_allow_html=True)
        st.markdown('<h3 style="margin-top:0; color: var(--accent-blue);">Optimal Position Allocation</h3>', unsafe_allow_html=True)
        
        # Only run calculations if user entered valid parameters within budget and has at least 1 share
        if is_valid and not is_over_budget and optimal_qty > 0:
            st.markdown(
                f"""
                <table style="width:100%; border-collapse: collapse; font-size: 0.95rem;">
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                        <td style="color: var(--text-secondary);">Capital Deployed</td>
                        <td style="text-align: right; font-weight: 700; color: var(--text-primary);">{currency_sym}{capital_deployed:,.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                        <td style="color: var(--text-secondary);">Leverage Multiplier</td>
                        <td style="text-align: right; font-weight: 700; color: #3B82F6;">+{leverage:.0f}x (additional)</td>
                    </tr>
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                        <td style="color: var(--text-secondary);">Total Exposure (Buying Power)</td>
                        <td style="text-align: right; font-weight: 700; color: var(--text-primary);">{currency_sym}{total_exposure:,.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px; font-size: 1.05rem;">
                        <td style="color: var(--text-primary); font-weight: 600;">Optimal Share Quantity</td>
                        <td style="text-align: right; font-weight: 800; color: var(--accent-green);">{optimal_qty:,} shares / units</td>
                    </tr>
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px; font-size: 1.05rem;">
                        <td style="color: var(--text-primary); font-weight: 600;">Auto-Calculated Stop Loss</td>
                        <td style="text-align: right; font-weight: 800; color: var(--accent-red);">{currency_sym}{sl_price:,.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px; font-size: 1.05rem;">
                        <td style="color: var(--text-primary); font-weight: 600;">Auto-Calculated Target</td>
                        <td style="text-align: right; font-weight: 800; color: var(--accent-green);">{currency_sym}{target_price:,.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                        <td style="color: var(--text-secondary);">Absolute Capital at Risk ({risk_pct}%)</td>
                        <td style="text-align: right; font-weight: 700; color: var(--accent-red);">{currency_sym}{risk_rupees:,.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                        <td style="color: var(--text-secondary);">Absolute Potential Reward (1:2)</td>
                        <td style="text-align: right; font-weight: 700; color: var(--accent-green);">{currency_sym}{estimated_reward:,.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px; font-weight: 600;">
                        <td style="color: var(--accent-red);">Stop Loss Risk + Charges</td>
                        <td style="text-align: right; font-weight: 800; color: var(--accent-red);">{currency_sym}{total_risk_with_charges:,.2f}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid rgba(0,0,0,0.1); height: 40px; font-weight: 600;">
                        <td style="color: var(--accent-green);">Target Net Profit (After Charges)</td>
                        <td style="text-align: right; font-weight: 800; color: var(--accent-green);">{currency_sym}{net_reward_with_charges:,.2f}</td>
                    </tr>
                </table>
                """, 
                unsafe_allow_html=True
            )
            
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(
                """
                > [!TIP]
                > **Leverage Position Re-Sizing**: Applied stop loss and target bounds are mathematically adjusted for leverage to preserve absolute risk exposure. 
                """
            )
        else:
            # High-readability empty instructions card (No default losses or profits!)
            st.markdown(
                """
                <div style="text-align: center; padding: 40px 10px; color: var(--text-secondary); font-size: 0.9rem;">
                    <p style="font-weight: 600; margin-bottom: 10px; color: var(--text-primary);">Awaiting Sizing Inputs</p>
                    <p>Enter your Capital Deployed, Planned Entry Price, Risk %, and Leverage on the left. The entry price must be less than or equal to your total buying power to compute optimal allocation.</p>
                </div>
                """, 
                unsafe_allow_html=True
            )
            
        st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 6: CAPITAL MANAGER
# ==========================================
with tab_capital:
    st.markdown('<div class="glass-card preview-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0; color: var(--text-primary);">💳 Capital Manager & Daily Rollover</h3>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Track your daily opening capital, capital additions/withdrawals, net P&L, adjustments, and roll over to tomorrow.</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Load capital settings from database
    try:
        stored_opening = float(get_db_settings("capital_opening", "0.0"))
        stored_added = float(get_db_settings("capital_added", "0.0"))
        stored_withdrawn = float(get_db_settings("capital_withdrawn", "0.0"))
        stored_adjustment = float(get_db_settings("capital_adjustment", "0.0"))
    except Exception:
        stored_opening = 0.0
        stored_added = 0.0
        stored_withdrawn = 0.0
        stored_adjustment = 0.0
        
    # Get today's net P&L from logged trades
    today_str = date.today().strftime("%Y-%m-%d")
    if not df_trades.empty:
        df_today_trades = df_trades[df_trades['trade_date'] == today_str]
        auto_pnl = float(df_today_trades['net_pnl'].sum())
    else:
        auto_pnl = 0.0
        
    # Callback to handle discrepancy calculations and update widget states before instantiation
    def apply_adjustment_callback():
        c_open = float(st.session_state.get("cap_open_input", stored_opening))
        c_add = float(st.session_state.get("cap_add_input", stored_added))
        c_with = float(st.session_state.get("cap_with_input", stored_withdrawn))
        c_pnl_val = float(st.session_state.get("cap_pnl_input", auto_pnl))
        broker_val = float(st.session_state.get("calc_broker_input", 0.0))
        
        if broker_val > 0:
            system_before_adj = c_open + c_add - c_with + c_pnl_val
            diff_val = broker_val - system_before_adj
            st.session_state["cap_adj_input"] = float(diff_val)
        
    cap_col1, cap_col2 = st.columns([3, 2])
    
    with cap_col1:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("<h5>Daily Capital Adjustments</h5>", unsafe_allow_html=True)
        
        c_opening = st.number_input("Opening Capital (₹)", min_value=0.0, step=100.0, value=stored_opening, key="cap_open_input")
        c_added = st.number_input("Add Capital (₹) - Deposit", min_value=0.0, step=100.0, value=stored_added, key="cap_add_input")
        c_withdrawn = st.number_input("Withdraw Capital (₹)", min_value=0.0, step=100.0, value=stored_withdrawn, key="cap_with_input")
        c_pnl = st.number_input("Today's Net Profit / Loss (₹)", step=50.0, value=auto_pnl, help="Pre-populated from today's logged trades but fully editable.", key="cap_pnl_input")
        c_adjust = st.number_input("Manual Adjustment (₹)", step=10.0, value=stored_adjustment, help="Use positive/negative values to match broker discrepancy.", key="cap_adj_input")
        
        # Discrepancy Helper Expandable Calculator
        with st.expander("⚖️ Broker Discrepancy Calculator"):
            st.markdown("<p style='font-size:0.85rem; color: var(--text-secondary); margin-top:0; margin-bottom: 12px;'>Enter the actual capital balance shown on your broker's terminal. The system will auto-compute and fill the difference as the manual adjustment.</p>", unsafe_allow_html=True)
            
            c_calc_broker = st.number_input(
                "Actual Broker Terminal Capital (₹)", 
                min_value=0.0, 
                step=100.0, 
                value=0.0, 
                key="calc_broker_input",
                help="Type the final cash/ledger balance from your broker's account page."
            )
            
            # System closing capital before manual adjustment
            system_before_adj = c_opening + c_added - c_withdrawn + c_pnl
            
            diff = c_calc_broker - system_before_adj if c_calc_broker > 0 else 0.0
            
            st.markdown(
                f"""
                <div style="font-size: 0.9rem; margin-bottom: 15px; padding: 10px; background-color: var(--bg-secondary); border-radius: 8px; border: 1px solid var(--border-color);">
                    <span style="color: var(--text-secondary);">Computed System Capital:</span> 
                    <strong>{currency_sym}{system_before_adj:,.2f}</strong><br>
                    <span style="color: var(--text-secondary);">Required Adjustment:</span> 
                    <strong style="color: {'var(--accent-green)' if diff >= 0 else 'var(--accent-red)'};">
                        {'+' if diff >= 0 else ''}{diff:,.2f}
                    </strong>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            if st.button("Apply Computed Adjustment", key="apply_adj_btn", on_click=apply_adjustment_callback):
                if c_calc_broker > 0:
                    st.success(f"Applied adjustment of {currency_sym}{diff:,.2f} successfully! Click 'Save Capital States' below to save changes.")
                    st.rerun()
                else:
                    st.error("Please enter a valid broker capital value.")
        
        # Save Capital State
        if st.button("Save Capital States", key="save_cap_btn"):
            save_db_setting("capital_opening", str(c_opening))
            save_db_setting("capital_added", str(c_added))
            save_db_setting("capital_withdrawn", str(c_withdrawn))
            save_db_setting("capital_adjustment", str(c_adjust))
            st.success("Capital manager states saved successfully!")
            st.rerun()
            
        st.markdown('</div>', unsafe_allow_html=True)
        
    with cap_col2:
        st.markdown('<div class="glass-card" style="height: 100%;">', unsafe_allow_html=True)
        st.markdown('<h3 style="margin-top:0; color: var(--accent-blue);">Capital Allocation Summary</h3>', unsafe_allow_html=True)
        
        # Calculations
        total_available = c_opening + c_added
        closing_capital = total_available - c_withdrawn + c_pnl + c_adjust
        
        pnl_color_class = "green" if c_pnl >= 0 else "red"
        adj_color_class = "green" if c_adjust >= 0 else ("red" if c_adjust < 0 else "")
        
        st.markdown(
            f"""
            <table style="width:100%; border-collapse: collapse; font-size: 0.95rem;">
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Opening Capital</td>
                    <td style="text-align: right; font-weight: 700; color: var(--text-primary);">{currency_sym}{c_opening:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Capital Added (Deposit)</td>
                    <td style="text-align: right; font-weight: 700; color: var(--accent-green);">+{currency_sym}{c_added:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px; font-weight: 600;">
                    <td style="color: var(--text-primary);">Total Capital Available Today</td>
                    <td style="text-align: right; font-weight: 800; color: var(--text-primary);">{currency_sym}{total_available:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Capital Withdrawn</td>
                    <td style="text-align: right; font-weight: 700; color: var(--accent-red);">-{currency_sym}{c_withdrawn:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Today's Net P&L</td>
                    <td style="text-align: right; font-weight: 700;" class="{pnl_color_class}">{currency_sym}{c_pnl:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Manual Adjustment</td>
                    <td style="text-align: right; font-weight: 700;" class="{adj_color_class}">{currency_sym}{c_adjust:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.1); height: 45px; font-size: 1.1rem; font-weight: 700; background-color: rgba(59, 130, 246, 0.03);">
                    <td style="color: var(--accent-blue); padding-left: 5px;">Closing Capital (COB)</td>
                    <td style="text-align: right; color: var(--accent-blue); padding-right: 5px;">{currency_sym}{closing_capital:,.2f}</td>
                </tr>
            </table>
            """, 
            unsafe_allow_html=True
        )
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Automated Rollover Message
        st.markdown(
            f"""
            > [!NOTE]
            > **Automated 6:00 AM Rollover Active**: The system automatically rolls over your closing capital to become the next day's opening capital every day at **6:00 AM**. Daily deposits, withdrawals, and adjustments are reset to 0.0 at rollover. No manual action is required.
            """
        )
            
        st.markdown('</div>', unsafe_allow_html=True)

# TAB 7: SYSTEM SETTINGS
# ==========================================
with tab_settings:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0;">Global Brokerage Configurations</h3>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Adjust the default flat brokerage rates. These default parameters will auto-fill the trade entry page but are always editable per trade.</p>', unsafe_allow_html=True)
    
    # Load current settings from DB
    current_rates = get_brokerage_rates()
    
    with st.form("settings_brokerage_form"):
        set_cols = st.columns(2)
        
        updated_rates = {}
        
        idx = 0
        for seg_name, rates in current_rates.items():
            col_target = set_cols[idx % 2]
            with col_target:
                st.markdown(f"**{seg_name}**")
                sub_col1, sub_col2 = st.columns(2)
                with sub_col1:
                    b_buy = st.number_input(f"Buy Rate (₹)", min_value=0.0, step=1.0, value=float(rates["buy"]), key=f"set_b_buy_{idx}")
                with sub_col2:
                    b_sell = st.number_input(f"Sell Rate (₹)", min_value=0.0, step=1.0, value=float(rates["sell"]), key=f"set_b_sell_{idx}")
                
                updated_rates[seg_name] = {"buy": b_buy, "sell": b_sell}
                st.markdown("<br>", unsafe_allow_html=True)
            idx += 1
            
        save_set = st.form_submit_button("Save & Update Brokerage Defaults")
        
        if save_set:
            save_brokerage_rates(updated_rates)
            st.success("Global default brokerage rates updated successfully!")
            st.rerun()
            
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Currency Settings
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0;">Regional Customization</h3>', unsafe_allow_html=True)
    
    curr_col1, curr_col2 = st.columns(2)
    with curr_col1:
        selected_curr = st.selectbox("Preferred Currency Symbol", options=["₹", "$", "€", "£", "¥"], index=["₹", "$", "€", "£", "¥"].index(get_db_settings("currency_symbol", "₹")))
    
    if st.button("Save Regional Settings"):
        save_db_setting("currency_symbol", selected_curr)
        st.success("Regional currency setting updated!")
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # Data Operations / Backup
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0;">Data Utility & Maintenance</h3>', unsafe_allow_html=True)
    
    op_col1, op_col2 = st.columns(2)
    
    with op_col1:
        st.markdown("##### CSV Backup Operations")
        # Export CSV Button
        if not df_trades.empty:
            csv_data = df_trades.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📤 Export All Trades to CSV File",
                data=csv_data,
                file_name=f"trading_journal_export_{datetime.now().strftime('%Y%m%d')}.csv",
                mime='text/csv'
            )
        else:
            st.warning("No trades available in database to export.")

            
    with op_col2:
        st.markdown("##### Maintenance")
        st.markdown("<p style='color: var(--accent-red); font-weight:600;'>Warning: Wipe Operations are irreversible.</p>", unsafe_allow_html=True)
        
        confirm_clear = st.checkbox("I verify I want to clear all data in the database")
        
        if st.button("Wipe All Trading Database Records", disabled=not confirm_clear):
            clear_all_trades()
            st.success("Database fully wiped. All logs cleared.")
            st.rerun()
        
    st.markdown('</div>', unsafe_allow_html=True)
