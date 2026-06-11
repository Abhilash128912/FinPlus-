import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import calendar
import os
import base64

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
    save_db_setting,
    add_capital_movement,
    fetch_capital_movements_df,
    delete_capital_movement,
    clear_all_capital_movements,
    add_pair_trade,
    update_pair_trade,
    delete_pair_trade,
    fetch_pair_trades_df,
    clear_all_pair_trades,
    add_paper_trade,
    update_paper_trade,
    delete_paper_trade,
    fetch_paper_trades_df,
    clear_all_paper_trades
)
from calculator import calculate_trade_metrics

def style_dataframe_pnl(df_to_style, gross_col="gross_pnl", net_col="net_pnl", other_cols_currency=[]):
    """
    Styles gross_pnl and net_pnl columns using custom colors:
    - Positive: Green (#16A34A)
    - Negative: Orange (#EA580C)
    """
    def color_pnl(val):
        try:
            val_float = float(val)
            if val_float > 0:
                return 'color: #16A34A; font-weight: bold;'
            elif val_float < 0:
                return 'color: #EA580C; font-weight: bold;'
        except (ValueError, TypeError):
            pass
        return ''

    styler = df_to_style.style
    
    # Try mapping styling
    try:
        styler = styler.map(color_pnl, subset=[gross_col, net_col])
    except AttributeError:
        styler = styler.applymap(color_pnl, subset=[gross_col, net_col])
        
    # Apply format mappings
    format_rules = {}
    for col in [gross_col, net_col] + other_cols_currency:
        if col in df_to_style.columns:
            format_rules[col] = lambda x: f"{currency_sym}{x:,.2f}" if pd.notnull(x) and isinstance(x, (int, float)) else ""
            
    # Format standard price columns
    for price_col in ["entry_price", "exit_price", "L1 Entry", "L1 Exit", "L2 Entry", "L2 Exit", "leg1_entry", "leg1_exit", "leg2_entry", "leg2_exit"]:
        if price_col in df_to_style.columns:
            format_rules[price_col] = lambda x: f"{x:,.2f}" if pd.notnull(x) and isinstance(x, (int, float)) else ""
            
    # Format quantity columns
    for qty_col in ["quantity", "L1 Qty", "L2 Qty", "leg1_qty", "leg2_qty"]:
        if qty_col in df_to_style.columns:
            format_rules[qty_col] = lambda x: f"{x:,.0f}" if pd.notnull(x) and isinstance(x, (int, float)) else ""
            
    styler = styler.format(format_rules)
    return styler

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
    commodity_keywords = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "NATGASMINI", "NATGAS", "COPPER", "ZINC", "ALUMINIUM", "LEAD", "MCX"]
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
        if is_commodity:
            if segment != "Commodities":
                return f"⚠️ Warning: The symbol **{symbol}** appears to be a Commodity Option contract, but the selected segment is **{segment}**. Please select **Commodities** to ensure MCX transaction charges are computed correctly."
        else:
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

def get_monthly_segment_pnl() -> dict:
    """
    Computes the net P&L for each segment in the current calendar month dynamically.
    """
    df = fetch_trades_df()
    if df.empty:
        return {}
    now = datetime.now()
    df['parsed_date'] = pd.to_datetime(df['trade_date'])
    df_current_month = df[
        (df['parsed_date'].dt.year == now.year) & 
        (df['parsed_date'].dt.month == now.month)
    ]
    segment_pnl = df_current_month.groupby('segment')['net_pnl'].sum().to_dict()
    return segment_pnl

DEFAULT_SEGMENT_RULES = {
    "base_daily_risk": 250.0,
    "enable_step_up": True,
    "enforcement_mode": "Hard Lock", # "Hard Lock" or "Soft Warning"
    "rules": {
        "Commodities": {
            "allocation_pct": 15.0,
            "min_savings": 6000.0,
            "manual_adjustment": 0.0
        },
        "Equity - Delivery": {
            "allocation_pct": 40.0,
            "min_savings": 3000.0,
            "manual_adjustment": 0.0
        },
        "F&O - Stock Options": {
            "allocation_pct": 15.0,
            "min_savings": 4500.0,
            "manual_adjustment": 0.0
        },
        "F&O - Index Options": {
            "allocation_pct": 15.0,
            "min_savings": 4500.0,
            "manual_adjustment": 0.0
        },
        "Equity - Intraday": {
            "allocation_pct": 15.0,
            "min_savings": 3000.0,
            "manual_adjustment": 0.0
        }
    }
}

def get_segment_rules() -> dict:
    """
    Fetches the segment rules from settings table or returns the default structure.
    """
    rules = get_db_settings("segment_rules", None)
    if rules is None:
        rules = dict(DEFAULT_SEGMENT_RULES)
    else:
        # Check that all default segments exist (for schema evolution/backwards compatibility)
        if "rules" not in rules:
            rules["rules"] = {}
        for seg_name, defaults in DEFAULT_SEGMENT_RULES["rules"].items():
            if seg_name not in rules["rules"]:
                rules["rules"][seg_name] = dict(defaults)
            else:
                # Fill missing keys in segments
                for k, v in defaults.items():
                    if k not in rules["rules"][seg_name]:
                        if k == "manual_adjustment" and "current_savings" in rules["rules"][seg_name]:
                            rules["rules"][seg_name]["manual_adjustment"] = float(rules["rules"][seg_name]["current_savings"])
                        else:
                            rules["rules"][seg_name][k] = v
        # Ensure top level keys exist
        for k in ["base_daily_risk", "enable_step_up", "enforcement_mode"]:
            if k not in rules:
                rules[k] = DEFAULT_SEGMENT_RULES[k]
    return rules

def save_segment_rules(rules: dict):
    """
    Saves segment rules to DB.
    """
    save_db_setting("segment_rules", rules)

def get_segment_savings(rules: dict, seg_key: str, active_daily_risk: float) -> dict:
    """
    Calculates the dynamic savings, progress, and status for a segment.
    """
    seg_rule_data = rules.get("rules", {}).get(seg_key, {})
    alloc_pct = float(seg_rule_data.get("allocation_pct", 15.0))
    min_savings = float(seg_rule_data.get("min_savings", 3000.0))
    manual_adj = float(seg_rule_data.get("manual_adjustment", 0.0))
    
    # Calculate daily risk allocation for this segment
    seg_risk_allocation = active_daily_risk * (alloc_pct / 100.0)
    
    # Calculate days passed since start date
    start_date_str = get_db_settings("segment_rules_start_date", "2026-06-07")
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except Exception:
        start_date = date.today()
        
    days_passed = max(1, (date.today() - start_date).days + 1)
    
    # Calculate sum of P&L for this segment since start date
    df_t = fetch_trades_df()
    seg_pnl = 0.0
    if not df_t.empty:
        # Filter trades in this segment executed on or after start_date
        df_t['parsed_date'] = pd.to_datetime(df_t['trade_date'])
        start_dt = datetime.combine(start_date, datetime.min.time())
        df_filtered = df_t[
            (df_t['segment'] == seg_key) & 
            (df_t['parsed_date'] >= start_dt)
        ]
        seg_pnl = float(df_filtered['net_pnl'].sum())
        
    # Total dynamic savings
    current_savings = (days_passed * seg_risk_allocation) + seg_pnl + manual_adj
    
    # Status
    is_ready = current_savings >= min_savings
    
    # Calculate unlock date if locked
    days_needed = 0
    unlock_date = None
    if not is_ready:
        import math
        from datetime import timedelta
        diff = min_savings - current_savings
        days_needed = math.ceil(diff / seg_risk_allocation) if seg_risk_allocation > 0 else 0
        unlock_date = date.today() + timedelta(days=days_needed)
    
    return {
        "current_savings": current_savings,
        "days_passed": days_passed,
        "seg_risk_allocation": seg_risk_allocation,
        "seg_pnl": seg_pnl,
        "is_ready": is_ready,
        "progress_pct": (current_savings / min_savings * 100.0) if min_savings > 0 else 0.0,
        "days_needed": days_needed,
        "unlock_date": unlock_date
    }

def get_monthly_total_pnl() -> float:
    """
    Computes the total net P&L for the current calendar month across both
    standard trades and pair trades.
    """
    df_t = fetch_trades_df()
    df_p = fetch_pair_trades_df()
    
    now = datetime.now()
    
    m_pnl = 0.0
    
    if not df_t.empty:
        df_t['parsed_date'] = pd.to_datetime(df_t['trade_date'])
        df_t_month = df_t[
            (df_t['parsed_date'].dt.year == now.year) & 
            (df_t['parsed_date'].dt.month == now.month)
        ]
        m_pnl += float(df_t_month['net_pnl'].sum())
        
    if not df_p.empty:
        df_p['parsed_date'] = pd.to_datetime(df_p['trade_date'])
        df_p_month = df_p[
            (df_p['parsed_date'].dt.year == now.year) & 
            (df_p['parsed_date'].dt.month == now.month)
        ]
        m_pnl += float(df_p_month['net_pnl'].sum())
        
    return m_pnl


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
        commodity_keywords = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "NATGASMINI", "NATGAS"]
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
        commodity_keywords = ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS", "NATGASMINI", "NATGAS"]
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
        add_capital_movement(current_date_str, "Opening", stored_opening, "Initial startup capital state")
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
        
        # Log rollover history
        add_capital_movement(
            last_rollover_date, 
            "Rollover", 
            closing_capital, 
            f"Daily Rollover. Prev Opening: {stored_opening}, Added: {stored_added}, Withdrawn: {stored_withdrawn}, P&L: {last_day_pnl}, Adj: {stored_adjustment}"
        )
        
        return True
        
    return False

# 1. Page Configuration and Theme Skinning
st.set_page_config(
    page_title="FinPlus // Professional Trading Workstation",
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

# App Header with Brand Logo
brand_img_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finplus_brand_image.png")
brand_img_base64 = ""
if os.path.exists(brand_img_path):
    try:
        with open(brand_img_path, "rb") as f:
            brand_img_base64 = base64.b64encode(f.read()).decode()
    except Exception:
        pass

if brand_img_base64:
    brand_logo_html = f"""
    <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-color); padding-bottom: 20px; margin-bottom: 25px; gap: 20px;">
      <div style="display: flex; align-items: center; gap: 24px;">
        <div class="brand-container" style="margin-bottom: 0;">
          <img src="data:image/png;base64,{brand_img_base64}" class="brand-image" alt="FinPlus Illustration" />
          <div class="brand-text-group">
            <div class="brand-logo">
              <span class="brand-logo-text">FinPlus</span><span class="brand-logo-plus"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="4.5" stroke-linecap="round"><line x1="12" y1="3" x2="12" y2="21"></line><line x1="3" y1="12" x2="21" y2="12"></line></svg></span>
            </div>
            <p class="header-subtitle">Institutional Grade Performance Tracking & Psychology Audit</p>
          </div>
        </div>
        <div class="header-divider"></div>
        <div>
          <span style="font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 0.08em; display: block;">Active View</span>
          <h1 class="glowing-header" style="font-size: 24px; margin: 0; line-height: 1.2;">ANALYTICS</h1>
        </div>
      </div>
    </div>
    """
    st.markdown(brand_logo_html, unsafe_allow_html=True)
else:
    st.markdown('<h1 class="glowing-header">FinPlus // ANALYTICS</h1>', unsafe_allow_html=True)
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

# --- GLOBAL CIRCUIT BREAKER LOGIC ---
df_pair_trades_kpi = fetch_pair_trades_df()

def check_system_lock(df_t, df_p):
    # Daily penalty box and monthly hard stops are deactivated as of today.
    # Trading locks are now governed strictly by segment savings levels.
    return False, ""

is_system_locked, lock_reason = check_system_lock(df_trades, df_pair_trades_kpi)

# 2. Main Tabs Layout
tab_dash, tab_add, tab_logs, tab_psych, tab_risk, tab_capital, tab_settings, tab_pair, tab_rules, tab_paper = st.tabs([
    "📊 Performance Dashboard",
    "📝 Log a Trade",
    "🔍 Search & Edit Logs",
    "🧠 Psychology & Strategy",
    "🧮 Position Size Planner",
    "💳 Capital Manager",
    "⚙️ System Settings",
    "🔀 Nifty Pair Trading",
    "🛡️ Segment Rules",
    "🧪 Paper Trading"
])

# ==========================================
# TAB 1: PERFORMANCE DASHBOARD
# ==========================================
with tab_dash:
    if df_trades.empty:
        st.markdown(
            """
            <div class="glass-card" style="text-align: center; padding: 50px 20px;">
                <h3 style="color: #3B82F6; margin-bottom: 10px;">Welcome to FinPlus</h3>
                <p style="color: var(--text-secondary); margin-bottom: 20px;">Your trading journal is currently empty. Head over to the 'Log a Trade' tab or import a sample CSV in 'System Settings' to get started!</p>
            </div>
            """, 
            unsafe_allow_html=True
        )
    else:
        # Calculate Key Performance Indicators (KPIs)
        df_pair_trades_kpi = fetch_pair_trades_df()
        
        total_trades = len(df_trades) + len(df_pair_trades_kpi)
        
        gross_profit = df_trades[df_trades['net_pnl'] > 0]['net_pnl'].sum()
        gross_loss = df_trades[df_trades['net_pnl'] < 0]['net_pnl'].sum()
        winning_trades = len(df_trades[df_trades['net_pnl'] > 0])
        losing_trades = len(df_trades[df_trades['net_pnl'] < 0])
        
        if not df_pair_trades_kpi.empty:
            gross_profit += df_pair_trades_kpi[df_pair_trades_kpi['net_pnl'] > 0]['net_pnl'].sum()
            gross_loss += df_pair_trades_kpi[df_pair_trades_kpi['net_pnl'] < 0]['net_pnl'].sum()
            winning_trades += len(df_pair_trades_kpi[df_pair_trades_kpi['net_pnl'] > 0])
            losing_trades += len(df_pair_trades_kpi[df_pair_trades_kpi['net_pnl'] < 0])
        
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        profit_factor = abs(gross_profit / gross_loss) if gross_loss != 0 else (gross_profit if gross_profit > 0 else 1.0)
        
        net_pnl = df_trades['net_pnl'].sum() + (df_pair_trades_kpi['net_pnl'].sum() if not df_pair_trades_kpi.empty else 0.0)
        total_charges = df_trades['total_charges'].sum() + (df_pair_trades_kpi['total_charges'].sum() if not df_pair_trades_kpi.empty else 0.0)
        
        avg_win = gross_profit / winning_trades if winning_trades > 0 else 0.0
        avg_loss = gross_loss / losing_trades if losing_trades > 0 else 0.0
        
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
            
        # Monthly Capital Preservation Circuit Breaker Status
        st.markdown("<hr style='border-color: var(--border-color); margin: 15px 0;'>", unsafe_allow_html=True)
        st.markdown("<h3 style='margin-top:0;'>🛡️ Capital Preservation & Risk Circuit Breakers</h3>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <p style="color: var(--text-secondary); margin-top:-10px; margin-bottom: 20px;">
                Segment limits and trade eligibility are now governed by the **🛡️ Segment Rules & Risk Allocator** tab based on savings targets. Historical monthly performance circuit breaker locks are deactivated.
            </p>
            """,
            unsafe_allow_html=True
        )
        
        # Calculate monthly PNL for key segments
        monthly_pnls = get_monthly_segment_pnl()
        risk_limit = float(get_db_settings("monthly_risk_limit", 3000.0))
        
        target_segments = [
            "Commodities",
            "F&O - Index Options",
            "Equity - Intraday",
            "F&O - Stock Options",
            "Nifty Pair Trading"
        ]
        
        df_pair_trades = fetch_pair_trades_df()
        pair_total_pnl = float(df_pair_trades["net_pnl"].sum()) if not df_pair_trades.empty else 0.0

        card_cols = st.columns(5)
        for idx, seg in enumerate(target_segments):
            with card_cols[idx]:
                if seg == "Nifty Pair Trading":
                    seg_pnl = pair_total_pnl
                else:
                    seg_pnl = monthly_pnls.get(seg, 0.0)
                
                # Check status (locking deactivated)
                if seg_pnl < 0:
                    status_text = "🟡 ACTIVE (Net Loss)"
                    card_border = "border: 1.5px solid #FCD34D;"
                    card_bg = "background-color: #FFFBEB;"
                    text_color = "#92400E"
                    progress_val = min(1.0, abs(seg_pnl) / risk_limit)
                else:
                    status_text = "🟢 SAFE (In Profit / Inactive)"
                    card_border = "border: 1.5px solid #A7F3D0;"
                    card_bg = "background-color: #ECFDF5;"
                    text_color = "#065F46"
                    progress_val = 0.0
                
                # Render beautiful custom card
                pnl_formatted = f"+{currency_sym}{seg_pnl:,.2f}" if seg_pnl >= 0 else f"-{currency_sym}{abs(seg_pnl):,.2f}"
                st.markdown(
                    f"""
                    <div style="{card_bg} {card_border} border-radius: 8px; padding: 15px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.05); height: 100%;">
                        <div style="font-weight: 700; font-size: 0.95rem; color: #0F172A; margin-bottom: 5px;">{seg}</div>
                        <div style="font-weight: 800; font-size: 1.4rem; color: {text_color}; margin-bottom: 5px;">{pnl_formatted}</div>
                        <div style="font-weight: 700; font-size: 0.75rem; color: {text_color}; text-transform: uppercase; letter-spacing: 0.03em;">{status_text}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                # We can also add a progress bar for losses
                if seg_pnl < 0:
                    st.progress(min(progress_val, 1.0))
                else:
                    st.progress(0.0)
                    
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

        if not df_pair_trades_kpi.empty:
            df_pair_trades_kpi['parsed_date'] = pd.to_datetime(df_pair_trades_kpi['trade_date'])
            df_pair_month = df_pair_trades_kpi[
                (df_pair_trades_kpi['parsed_date'].dt.year == selected_year) & 
                (df_pair_trades_kpi['parsed_date'].dt.month == month_idx)
            ]
            pair_daily_pnl = df_pair_month.groupby(df_pair_month['parsed_date'].dt.day)['net_pnl'].sum().to_dict()
            for day, pnl in pair_daily_pnl.items():
                daily_pnl[day] = daily_pnl.get(day, 0.0) + pnl
        
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
                df_day_display = df_day_display.rename(columns={"s_no": "Trade #"})
                
                styled_df = style_dataframe_pnl(
                    df_day_display[[
                        "Trade #", "symbol", "segment", "action", "quantity", 
                        "entry_price", "exit_price", "gross_pnl", "total_charges", 
                        "net_pnl", "strategy", "mistake", "notes"
                    ]],
                    other_cols_currency=["total_charges"]
                )
                
                st.dataframe(
                    styled_df,
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

    if is_system_locked:
        clean_reason = lock_reason.replace('🔴 **', '').replace('**: ', ': ')
        st.markdown(
            f"""
            <div style="background-color: rgba(239, 68, 68, 0.15); border: 2px solid rgba(239, 68, 68, 0.6); border-radius: 12px; padding: 25px; margin-bottom: 20px; text-align: center;">
                <h2 style="color: #ef4444; margin-top: 0; margin-bottom: 10px;">🔒 SYSTEM LOCKED</h2>
                <p style="font-size: 1.15rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0;">{clean_reason}</p>
            </div>
            """, 
            unsafe_allow_html=True
        )
    
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
        
        # Determine default base lot size dynamically based on segment and symbol to automate lot calculation
        default_base_lot = 0.0
        if t_segment in ["F&O - Index Options", "F&O - Stock Options", "F&O - Index Futures"]:
            sym_upper = t_symbol.upper().strip()
            if "NIFTY" in sym_upper:
                if "BANK" in sym_upper:
                    default_base_lot = 30.0  # NSE updated lot size as of 2026
                elif "FIN" in sym_upper:
                    default_base_lot = 60.0  # NSE updated lot size as of 2026
                elif "MIDCP" in sym_upper or "MID CAP" in sym_upper:
                    default_base_lot = 120.0 # NSE updated lot size as of 2026
                else:
                    default_base_lot = 65.0  # Nifty 50 lot size
            else:
                default_base_lot = 65.0  # Default fallback for options to represent 1 lot

        # Base Lot Size input field
        t_base_lot = st.number_input("Base Lot Size (0 for flat)", min_value=0.0, step=1.0, value=float(default_base_lot), help="Set to minimum lot size (e.g. 65 or 75) to scale brokerage per lot automatically (Brokerage = Rate * Lots). Set to 0 to disable scaling.", key=f"add_base_lot_{st.session_state['add_form_id']}")
        
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
        
        if t_base_lot > 0 and t_base_lot < 5.0 and t_qty > 10.0:
            st.warning("⚠️ **Warning: Brokerage scaling is active with a small lot size.** This multiplies your brokerage (currently scaled by the number of lots). If you want standard flat brokerage, set **Base Lot Size** to **0**.")
        
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
    
    # Circuit Breaker Validation (Deactivated - locks are now governed by Segment Rules)
    is_blocked = False

    # Segment Rules / Savings Guard Validation
    seg_rules = get_segment_rules()
    enforcement_mode = seg_rules.get("enforcement_mode", "Hard Lock")
    
    if t_segment in seg_rules.get("rules", {}):
        # Calculate active daily risk for dynamic checking
        base_risk = float(seg_rules.get("base_daily_risk", 250.0))
        enable_step_up = seg_rules.get("enable_step_up", True)
        monthly_pnl_val = get_monthly_total_pnl()
        step_up_bonus = 0.0
        if enable_step_up and monthly_pnl_val > 0:
            step_up_bonus = monthly_pnl_val * 0.10
        active_daily_risk = base_risk + step_up_bonus
        
        # Calculate dynamic savings
        savings_info = get_segment_savings(seg_rules, t_segment, active_daily_risk)
        curr_savings = savings_info["current_savings"]
        min_savings = float(seg_rules["rules"][t_segment].get("min_savings", 3000.0))
        
        if curr_savings < min_savings:
            unlock_date_str = savings_info["unlock_date"].strftime("%d %b %Y") if savings_info.get("unlock_date") else "N/A"
            days_needed = savings_info.get("days_needed", 0)
            if enforcement_mode == "Hard Lock":
                is_blocked = True
                st.error(
                    f"🛑 **Segment Guard Active for {t_segment}!** "
                    f"Your current savings allocated for this segment (**{currency_sym} {curr_savings:,.2f}**) is below the required "
                    f"minimum target of **{currency_sym} {min_savings:,.2f}**. "
                    f"Trade logging is strictly locked to preserve capital. "
                    f"*(Estimated Unlock: {unlock_date_str} / in {days_needed} days)*"
                )
            else:
                st.warning(
                    f"⚠️ **Segment Guard Warning for {t_segment}!** "
                    f"Your current savings allocated for this segment (**{currency_sym} {curr_savings:,.2f}**) is below the required "
                    f"minimum target of **{currency_sym} {min_savings:,.2f}**. "
                    f"Please increase your savings to meet the rules. "
                    f"*(Estimated Unlock: {unlock_date_str} / in {days_needed} days)*"
                )

    # Dynamic quote mismatch warning
    warning_msg = get_quote_mismatch_warning(t_symbol, t_segment)
    if warning_msg:
        st.warning(warning_msg)
        
    # Submit button
    submit_trade = st.button(
        "Log Trade & Update Capital", 
        type="primary", 
        use_container_width=True,
        disabled=is_system_locked or is_blocked,
        key=f"add_submit_{st.session_state['add_form_id']}"
    )
    
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
        df_display = df_display.rename(columns={"s_no": "Trade #"})
        
        styled_df = style_dataframe_pnl(
            df_display[[
                "Trade #", "trade_date", "symbol", "segment", "action", 
                "quantity", "entry_price", "exit_price", 
                "gross_pnl", "total_charges", "net_pnl", "strategy", "mistake", "notes"
            ]],
            other_cols_currency=["total_charges"]
        )
        
        st.dataframe(
            styled_df,
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
                
                # Determine default edit base lot size dynamically based on segment and symbol to automate lot calculation
                default_edit_base_lot = 0.0
                if e_segment in ["F&O - Index Options", "F&O - Stock Options", "F&O - Index Futures"]:
                    sym_upper = e_symbol.upper().strip()
                    if "NIFTY" in sym_upper:
                        if "BANK" in sym_upper:
                            default_edit_base_lot = 30.0  # NSE updated lot size as of 2026
                        elif "FIN" in sym_upper:
                            default_edit_base_lot = 60.0  # NSE updated lot size as of 2026
                        elif "MIDCP" in sym_upper or "MID CAP" in sym_upper:
                            default_edit_base_lot = 120.0 # NSE updated lot size as of 2026
                        else:
                            default_edit_base_lot = 65.0  # Nifty 50 lot size
                    else:
                        default_edit_base_lot = 65.0  # Default fallback for options to represent 1 lot

                # Base Lot Size input field for scaling brokerage during edits
                e_base_lot = st.number_input(
                    "Base Lot Size (0 for flat)", 
                    min_value=0.0, 
                    step=1.0, 
                    value=float(default_edit_base_lot), 
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
                
                if e_base_lot > 0 and e_base_lot < 5.0 and e_qty > 10.0:
                    st.warning("⚠️ **Warning: Brokerage scaling is active with a small lot size.** This multiplies your brokerage (currently scaled by the number of lots). If you want standard flat brokerage, set **Base Lot Size** to **0**.")
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
            
            # Circuit Breaker Warning for Editing
            e_monthly_pnls = get_monthly_segment_pnl()
            e_risk_limit = float(get_db_settings("monthly_risk_limit", 3000.0))
            if e_segment in ["Commodities", "F&O - Index Options", "Equity - Intraday", "F&O - Stock Options"]:
                e_seg_pnl = e_monthly_pnls.get(e_segment, 0.0)
                if e_seg_pnl <= -e_risk_limit:
                    st.error(
                        f"⚠️ **Circuit Breaker Active for {e_segment}!** "
                        f"This segment's monthly net P&L is **{currency_sym} {e_seg_pnl:,.2f}** (exceeding **{currency_sym} {e_risk_limit:,.2f}** limit). "
                        f"You can still save edits to existing trades, but logging *new* trades in this segment is blocked."
                    )

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
        
    # Get total net P&L from all logged trades
    if not df_trades.empty:
        lifetime_pnl = float(df_trades['net_pnl'].sum())
    else:
        lifetime_pnl = 0.0
        
    df_pair_trades_cap = fetch_pair_trades_df()
    if not df_pair_trades_cap.empty:
        lifetime_pair_pnl = float(df_pair_trades_cap['net_pnl'].sum())
    else:
        lifetime_pair_pnl = 0.0

    # Callback to handle discrepancy calculations and update widget states before instantiation
    def apply_adjustment_callback():
        c_open = float(st.session_state.get("cap_open_input", stored_opening))
        c_add = float(st.session_state.get("cap_add_input", stored_added))
        c_with = float(st.session_state.get("cap_with_input", stored_withdrawn))
        broker_val = float(st.session_state.get("calc_broker_input", 0.0))
        
        if broker_val > 0:
            system_before_adj = c_open + c_add - c_with + lifetime_pnl + lifetime_pair_pnl
            diff_val = broker_val - system_before_adj
            st.session_state["cap_adj_input"] = float(diff_val)
        
    cap_col1, cap_col2 = st.columns([3, 2])
    
    with cap_col1:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("<h5>Lifetime Capital Ledger</h5>", unsafe_allow_html=True)
        
        c_opening = st.number_input("Initial Capital Day One (₹)", min_value=0.0, step=100.0, value=stored_opening, key="cap_open_input")
        c_added = st.number_input("Lifetime Capital Added (₹)", min_value=0.0, step=100.0, value=stored_added, key="cap_add_input")
        c_withdrawn = st.number_input("Lifetime Capital Withdrawn (₹)", min_value=0.0, step=100.0, value=stored_withdrawn, key="cap_with_input")
        
        st.markdown(
            f"""
            <div style="margin-top: 15px; padding: 12px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--bg-secondary);">
                <div style="display:flex; justify-content:space-between; gap:12px; margin-bottom: 8px;">
                    <span style="color:var(--text-secondary);">Lifetime Trade P&L</span>
                    <strong style="color:{'var(--accent-green)' if lifetime_pnl >= 0 else 'var(--accent-red)'};">{currency_sym}{lifetime_pnl:,.2f}</strong>
                </div>
                <div style="display:flex; justify-content:space-between; gap:12px; margin-bottom: 8px;">
                    <span style="color:var(--text-secondary);">Lifetime Pair P&L</span>
                    <strong style="color:{'var(--accent-green)' if lifetime_pair_pnl >= 0 else 'var(--accent-red)'};">{currency_sym}{lifetime_pair_pnl:,.2f}</strong>
                </div>
                <div style="display:flex; justify-content:space-between; gap:12px; font-size:1.05rem; margin-top:6px; border-top: 1px solid rgba(0,0,0,0.1); padding-top: 8px;">
                    <span>Total Lifetime P&L</span>
                    <strong style="color:{'var(--accent-green)' if (lifetime_pnl + lifetime_pair_pnl) >= 0 else 'var(--accent-red)'};">{currency_sym}{(lifetime_pnl + lifetime_pair_pnl):,.2f}</strong>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
        c_adjust = st.number_input("Lifetime Manual Adjustments (₹)", step=10.0, value=stored_adjustment, help="Use positive/negative values to match broker discrepancy.", key="cap_adj_input")
        
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
            system_before_adj = c_opening + c_added - c_withdrawn + lifetime_pnl + lifetime_pair_pnl
            
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
        # 3. Capital Allocation Summary Table
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("<h5>Capital Ledger Summary</h5>", unsafe_allow_html=True)
        
        total_available = c_opening + c_added
        closing_capital = total_available - c_withdrawn + lifetime_pnl + lifetime_pair_pnl + c_adjust
        pnl_color_class = "green" if (lifetime_pnl + lifetime_pair_pnl) >= 0 else "red"
        adj_color_class = "green" if c_adjust >= 0 else ("red" if c_adjust < 0 else "")
        
        st.markdown(
            f"""
            <table style="width:100%; border-collapse: collapse; font-size: 0.95rem;">
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Initial Capital Day One</td>
                    <td style="text-align: right; font-weight: 700; color: var(--text-primary);">{currency_sym}{c_opening:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Lifetime Capital Added</td>
                    <td style="text-align: right; font-weight: 700; color: var(--accent-green);">+{currency_sym}{c_added:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Lifetime Capital Withdrawn</td>
                    <td style="text-align: right; font-weight: 700; color: var(--accent-red);">-{currency_sym}{c_withdrawn:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Lifetime Net P&L</td>
                    <td style="text-align: right; font-weight: 700;" class="{pnl_color_class}">{currency_sym}{(lifetime_pnl + lifetime_pair_pnl):,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 40px;">
                    <td style="color: var(--text-secondary);">Lifetime Adjustments</td>
                    <td style="text-align: right; font-weight: 700;" class="{adj_color_class}">{'+' if c_adjust > 0 else ''}{currency_sym}{c_adjust:,.2f}</td>
                </tr>
                <tr style="height: 48px; background-color: var(--bg-secondary);">
                    <td style="color: var(--text-primary); font-weight: 800; font-size: 1.05rem; padding-left: 8px; border-radius: 6px 0 0 6px;">Current Total Capital</td>
                    <td style="text-align: right; font-weight: 800; font-size: 1.05rem; color: var(--text-primary); padding-right: 8px; border-radius: 0 6px 6px 0;">{currency_sym}{closing_capital:,.2f}</td>
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

    # Monthly Risk Tolerance Settings
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0;">Monthly Segment Risk Limits</h3>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Configure the maximum acceptable net loss per segment for a calendar month. If a segment\'s monthly net loss exceeds this limit, trading on that segment will be blocked for capital preservation.</p>', unsafe_allow_html=True)
    
    current_limit = float(get_db_settings("monthly_risk_limit", 3000.0))
    
    lim_col1, lim_col2 = st.columns(2)
    with lim_col1:
        new_limit = st.number_input(f"Monthly Risk Limit per Segment ({currency_sym})", min_value=1.0, step=100.0, value=current_limit, help="Default is ₹ 3,000.00.")
        
    if st.button("Save Risk Limit Configuration"):
        save_db_setting("monthly_risk_limit", new_limit)
        st.success("Risk limit configuration updated successfully!")
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
            clear_all_capital_movements()
            clear_all_pair_trades()
            clear_all_paper_trades()
            st.success("Database fully wiped. All logs cleared.")
            st.rerun()
        
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 8: NIFTY INDEX OPTION PAIR TRADING
# ==========================================
with tab_pair:
    st.markdown('<div class="glass-card preview-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0; color: var(--text-primary);">Nifty Index Option Pair Trading</h3>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Track two-leg Nifty index option pair trades with a dedicated capital book. These trades stay separate from the main journal, dashboard totals, and capital manager.</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    if is_system_locked:
        clean_reason = lock_reason.replace('🔴 **', '').replace('**: ', ': ')
        st.markdown(
            f"""
            <div style="background-color: rgba(239, 68, 68, 0.15); border: 2px solid rgba(239, 68, 68, 0.6); border-radius: 12px; padding: 25px; margin-bottom: 20px; text-align: center;">
                <h2 style="color: #ef4444; margin-top: 0; margin-bottom: 10px;">🔒 SYSTEM LOCKED</h2>
                <p style="font-size: 1.15rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0;">{clean_reason}</p>
            </div>
            """, 
            unsafe_allow_html=True
        )

    df_pair_trades = fetch_pair_trades_df()
    today_str = date.today().strftime("%Y-%m-%d")
    if not df_pair_trades.empty:
        df_pair_today = df_pair_trades[df_pair_trades["trade_date"] == today_str]
        pair_today_pnl = float(df_pair_today["net_pnl"].sum())
        pair_total_pnl = float(df_pair_trades["net_pnl"].sum())
        pair_total_charges = float(df_pair_trades["total_charges"].sum())
        pair_trade_count = len(df_pair_trades)
    else:
        pair_today_pnl = 0.0
        pair_total_pnl = 0.0
        pair_total_charges = 0.0
        pair_trade_count = 0

    try:
        pair_opening = float(get_db_settings("nifty_pair_capital_opening", "0.0"))
        pair_added = float(get_db_settings("nifty_pair_capital_added", "0.0"))
        pair_withdrawn = float(get_db_settings("nifty_pair_capital_withdrawn", "0.0"))
        pair_adjustment = float(get_db_settings("nifty_pair_capital_adjustment", "0.0"))
    except Exception:
        pair_opening = 0.0
        pair_added = 0.0
        pair_withdrawn = 0.0
        pair_adjustment = 0.0

    pair_closing_capital = pair_opening + pair_added - pair_withdrawn + pair_total_pnl + pair_adjustment

    pm1, pm2, pm3, pm4 = st.columns(4)
    with pm1:
        st.metric("Pair Book Net P&L", f"{currency_sym} {pair_total_pnl:,.2f}", delta=f"After {currency_sym}{pair_total_charges:,.2f} charges", delta_color="off")
    with pm2:
        st.metric("Today's Pair P&L", f"{currency_sym} {pair_today_pnl:,.2f}")
    with pm3:
        st.metric("Pair Trades Logged", str(pair_trade_count))
    with pm4:
        st.metric("Pair Closing Capital", f"{currency_sym} {pair_closing_capital:,.2f}", delta="Separate from main capital", delta_color="off")

    pair_cap_col, pair_log_col = st.columns([2, 3])

    with pair_cap_col:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("<h5>Dedicated Pair Capital</h5>", unsafe_allow_html=True)

        p_opening = st.number_input("Pair Initial Capital Day One (₹)", min_value=0.0, step=100.0, value=pair_opening, key="pair_cap_open_input")
        p_added = st.number_input("Pair Lifetime Added (₹)", min_value=0.0, step=100.0, value=pair_added, key="pair_cap_add_input")
        p_withdrawn = st.number_input("Pair Lifetime Withdrawn (₹)", min_value=0.0, step=100.0, value=pair_withdrawn, key="pair_cap_with_input")
        p_adjust = st.number_input("Pair Lifetime Manual Adjustment (₹)", step=10.0, value=pair_adjustment, key="pair_cap_adj_input")

        if st.button("Save Pair Capital State", key="save_pair_cap_btn"):
            save_db_setting("nifty_pair_capital_opening", str(p_opening))
            save_db_setting("nifty_pair_capital_added", str(p_added))
            save_db_setting("nifty_pair_capital_withdrawn", str(p_withdrawn))
            save_db_setting("nifty_pair_capital_adjustment", str(p_adjust))
            st.success("Nifty pair capital state saved separately.")
            st.rerun()

        p_total_available = p_opening + p_added
        p_closing = p_total_available - p_withdrawn + pair_total_pnl + p_adjust
        p_pnl_class = "green" if pair_total_pnl >= 0 else "red"
        p_adj_class = "green" if p_adjust >= 0 else ("red" if p_adjust < 0 else "")

        st.markdown(
            f"""
            <table style="width:100%; border-collapse: collapse; font-size: 0.95rem; margin-top: 18px;">
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 38px;">
                    <td style="color: var(--text-secondary);">Initial Capital Day One</td>
                    <td style="text-align: right; font-weight: 700; color: var(--text-primary);">{currency_sym}{p_opening:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 38px;">
                    <td style="color: var(--text-secondary);">Lifetime Capital Added</td>
                    <td style="text-align: right; font-weight: 700; color: var(--accent-green);">+{currency_sym}{p_added:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 38px;">
                    <td style="color: var(--text-secondary);">Lifetime Capital Withdrawn</td>
                    <td style="text-align: right; font-weight: 700; color: var(--accent-red);">-{currency_sym}{p_withdrawn:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 38px;">
                    <td style="color: var(--text-secondary);">Lifetime Pair P&L</td>
                    <td style="text-align: right; font-weight: 700;" class="{p_pnl_class}">{currency_sym}{pair_total_pnl:,.2f}</td>
                </tr>
                <tr style="border-bottom: 1px solid rgba(0,0,0,0.05); height: 38px;">
                    <td style="color: var(--text-secondary);">Lifetime Manual Adjustment</td>
                    <td style="text-align: right; font-weight: 700;" class="{p_adj_class}">{currency_sym}{p_adjust:,.2f}</td>
                </tr>
                <tr style="height: 44px; font-size: 1.05rem; font-weight: 800; background-color: rgba(16, 185, 129, 0.06);">
                    <td style="color: var(--accent-blue); padding-left: 5px;">Pair Closing Capital</td>
                    <td style="text-align: right; color: var(--accent-blue); padding-right: 5px;">{currency_sym}{p_closing:,.2f}</td>
                </tr>
            </table>
            """,
            unsafe_allow_html=True
        )
        st.markdown('</div>', unsafe_allow_html=True)

    with pair_log_col:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("<h5>Log Completed Option Pair</h5>", unsafe_allow_html=True)

        index_option_rates = brokerage_rates.get("F&O - Index Options", {"buy": 20.0, "sell": 20.0})
        index_option_buy_brokerage = float(index_option_rates.get("buy", 20.0))
        index_option_sell_brokerage = float(index_option_rates.get("sell", 20.0))
        nifty_lot_size = 65.0

        def is_nifty_lot_multiple(quantity: float) -> bool:
            if quantity <= 0:
                return False
            return abs((quantity / nifty_lot_size) - round(quantity / nifty_lot_size)) < 1e-9

        with st.form("nifty_pair_trade_form", clear_on_submit=True):
            pair_date = st.date_input("Trade Date", value=date.today(), key="pair_trade_date")
            pair_name = st.text_input("Pair Name", value="NIFTY CE/PE Pair", placeholder="e.g. NIFTY Weekly Straddle", key="pair_name")

            leg_header_cols = st.columns([1.4, 0.8, 0.8, 0.8, 0.8])
            leg_header_cols[0].markdown("**Leg Symbol**")
            leg_header_cols[1].markdown("**Action**")
            leg_header_cols[2].markdown("**Qty**")
            leg_header_cols[3].markdown("**Entry**")
            leg_header_cols[4].markdown("**Exit**")

            l1c1, l1c2, l1c3, l1c4, l1c5 = st.columns([1.4, 0.8, 0.8, 0.8, 0.8])
            with l1c1:
                leg1_symbol = st.text_input("Leg 1 Symbol", placeholder="NIFTY26JUN23000CE", label_visibility="collapsed", key="pair_leg1_symbol").upper()
            with l1c2:
                leg1_action = st.selectbox("Leg 1 Action", ["BUY", "SELL"], label_visibility="collapsed", key="pair_leg1_action")
            with l1c3:
                leg1_qty = st.number_input("Leg 1 Qty", min_value=nifty_lot_size, step=nifty_lot_size, value=nifty_lot_size, label_visibility="collapsed", key="pair_leg1_qty")
            with l1c4:
                leg1_entry = st.number_input("Leg 1 Entry", min_value=0.0, step=0.05, value=0.0, format="%.2f", label_visibility="collapsed", key="pair_leg1_entry")
            with l1c5:
                leg1_exit = st.number_input("Leg 1 Exit", min_value=0.0, step=0.05, value=0.0, format="%.2f", label_visibility="collapsed", key="pair_leg1_exit")

            l2c1, l2c2, l2c3, l2c4, l2c5 = st.columns([1.4, 0.8, 0.8, 0.8, 0.8])
            with l2c1:
                leg2_symbol = st.text_input("Leg 2 Symbol", placeholder="NIFTY26JUN23000PE", label_visibility="collapsed", key="pair_leg2_symbol").upper()
            with l2c2:
                leg2_action = st.selectbox("Leg 2 Action", ["BUY", "SELL"], label_visibility="collapsed", key="pair_leg2_action")
            with l2c3:
                leg2_qty = st.number_input("Leg 2 Qty", min_value=nifty_lot_size, step=nifty_lot_size, value=nifty_lot_size, label_visibility="collapsed", key="pair_leg2_qty")
            with l2c4:
                leg2_entry = st.number_input("Leg 2 Entry", min_value=0.0, step=0.05, value=0.0, format="%.2f", label_visibility="collapsed", key="pair_leg2_entry")
            with l2c5:
                leg2_exit = st.number_input("Leg 2 Exit", min_value=0.0, step=0.05, value=0.0, format="%.2f", label_visibility="collapsed", key="pair_leg2_exit")

            brokerage_cols = st.columns([1, 1, 1])
            with brokerage_cols[0]:
                st.number_input(
                    "Index Option Buy Brokerage (₹)",
                    min_value=0.0,
                    step=1.0,
                    value=float(index_option_buy_brokerage),
                    disabled=True,
                    key="pair_index_option_buy_brokerage",
                    help="Saved F&O - Index Options buy-side brokerage from System Settings."
                )
            with brokerage_cols[1]:
                st.number_input(
                    "Index Option Sell Brokerage (₹)",
                    min_value=0.0,
                    step=1.0,
                    value=float(index_option_sell_brokerage),
                    disabled=True,
                    key="pair_index_option_sell_brokerage",
                    help="Saved F&O - Index Options sell-side brokerage from System Settings."
                )

            leg1_brokerage = index_option_buy_brokerage if leg1_action == "BUY" else index_option_sell_brokerage
            leg2_brokerage = index_option_buy_brokerage if leg2_action == "BUY" else index_option_sell_brokerage
            pair_brokerage = leg1_brokerage + leg2_brokerage

            with brokerage_cols[2]:
                st.number_input(
                    "Pair Brokerage (₹)",
                    min_value=0.0,
                    step=1.0,
                    value=float(pair_brokerage),
                    disabled=True,
                    key="pair_total_brokerage",
                    help="Uses the saved F&O - Index Options buy brokerage for BUY legs and sell brokerage for SELL legs."
                )

            pair_other_charges = 0.0
            st.number_input(
                "Manual Extra Charges (₹)",
                min_value=0.0,
                step=1.0,
                value=0.0,
                disabled=True,
                help="Charges are calculated automatically. This is locked to prevent manual overrides.",
                key="pair_other_charges_locked"
            )

            leg1_metrics = calculate_trade_metrics(
                segment="F&O - Index Options",
                action=leg1_action,
                quantity=leg1_qty,
                entry_price=leg1_entry,
                exit_price=leg1_exit,
                brokerage_input=leg1_brokerage
            )
            leg2_metrics = calculate_trade_metrics(
                segment="F&O - Index Options",
                action=leg2_action,
                quantity=leg2_qty,
                entry_price=leg2_entry,
                exit_price=leg2_exit,
                brokerage_input=leg2_brokerage
            )

            pair_gross_pnl = leg1_metrics["gross_pnl"] + leg2_metrics["gross_pnl"]
            pair_statutory_charges = leg1_metrics["total_charges"] + leg2_metrics["total_charges"]
            pair_total_trade_charges = pair_statutory_charges + pair_other_charges
            pair_net_trade_pnl = pair_gross_pnl - pair_total_trade_charges

            pair_charge_breakdown = {
                "Brokerage": leg1_metrics["brokerage"] + leg2_metrics["brokerage"],
                "STT": leg1_metrics["stt"] + leg2_metrics["stt"],
                "Exchange Charges": leg1_metrics["exchange_charges"] + leg2_metrics["exchange_charges"],
                "SEBI Charges": leg1_metrics["sebi_charges"] + leg2_metrics["sebi_charges"],
                "Stamp Duty": leg1_metrics["stamp_duty"] + leg2_metrics["stamp_duty"],
                "GST": leg1_metrics["gst"] + leg2_metrics["gst"],
                "Manual Extra Charges": pair_other_charges
            }

            st.markdown(
                f"""
                <div style="margin-top: 12px; padding: 12px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--bg-secondary);">
                    <div style="font-weight: 800; color: var(--text-primary); margin-bottom: 8px;">Charges & Taxes Preview</div>
                    <div style="display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; font-size: 0.86rem;">
                        <div><span style="color:var(--text-secondary);">Brokerage</span><br><strong>{currency_sym}{pair_charge_breakdown["Brokerage"]:,.2f}</strong></div>
                        <div><span style="color:var(--text-secondary);">STT</span><br><strong>{currency_sym}{pair_charge_breakdown["STT"]:,.2f}</strong></div>
                        <div><span style="color:var(--text-secondary);">Exchange</span><br><strong>{currency_sym}{pair_charge_breakdown["Exchange Charges"]:,.2f}</strong></div>
                        <div><span style="color:var(--text-secondary);">SEBI</span><br><strong>{currency_sym}{pair_charge_breakdown["SEBI Charges"]:,.2f}</strong></div>
                        <div><span style="color:var(--text-secondary);">Stamp Duty</span><br><strong>{currency_sym}{pair_charge_breakdown["Stamp Duty"]:,.2f}</strong></div>
                        <div><span style="color:var(--text-secondary);">GST</span><br><strong>{currency_sym}{pair_charge_breakdown["GST"]:,.2f}</strong></div>
                        <div><span style="color:var(--text-secondary);">Manual Extra</span><br><strong>{currency_sym}{pair_charge_breakdown["Manual Extra Charges"]:,.2f}</strong></div>
                        <div><span style="color:var(--text-secondary);">Total Charges</span><br><strong style="color:var(--accent-red);">{currency_sym}{pair_total_trade_charges:,.2f}</strong></div>
                    </div>
                    <div style="display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(0,0,0,0.06);">
                        <div><span style="color:var(--text-secondary);">Leg 1 Gross</span><br><strong>{currency_sym}{leg1_metrics["gross_pnl"]:,.2f}</strong></div>
                        <div><span style="color:var(--text-secondary);">Leg 2 Gross</span><br><strong>{currency_sym}{leg2_metrics["gross_pnl"]:,.2f}</strong></div>
                        <div><span style="color:var(--text-secondary);">Pair Net P&L</span><br><strong style="color:{'var(--accent-green)' if pair_net_trade_pnl >= 0 else 'var(--accent-red)'};">{currency_sym}{pair_net_trade_pnl:,.2f}</strong></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

            pair_notes = st.text_area("Notes", placeholder="Setup, expiry, hedge reason, execution notes", key="pair_notes")
            save_pair_trade = st.form_submit_button("Save Nifty Pair Trade", disabled=is_system_locked)

            if save_pair_trade:
                if not leg1_symbol or not leg2_symbol:
                    st.error("Please enter both option leg symbols.")
                elif leg1_qty <= 0 or leg2_qty <= 0:
                    st.error("Please enter a valid quantity for both legs.")
                elif not is_nifty_lot_multiple(leg1_qty) or not is_nifty_lot_multiple(leg2_qty):
                    st.error("Nifty quantities must be 65 or multiples of 65, such as 65, 130, 195, 260.")
                else:
                    add_pair_trade({
                        "trade_date": pair_date.strftime("%Y-%m-%d"),
                        "pair_name": pair_name.strip() or "NIFTY Option Pair",
                        "leg1_symbol": leg1_symbol,
                        "leg1_action": leg1_action,
                        "leg1_qty": leg1_qty,
                        "leg1_entry": leg1_entry,
                        "leg1_exit": leg1_exit,
                        "leg2_symbol": leg2_symbol,
                        "leg2_action": leg2_action,
                        "leg2_qty": leg2_qty,
                        "leg2_entry": leg2_entry,
                        "leg2_exit": leg2_exit,
                        "brokerage": pair_brokerage,
                        "other_charges": pair_other_charges,
                        "total_charges": pair_total_trade_charges,
                        "gross_pnl": pair_gross_pnl,
                        "net_pnl": pair_net_trade_pnl,
                        "notes": pair_notes
                    })
                    st.success(f"Nifty pair trade saved. Net P&L: {currency_sym}{pair_net_trade_pnl:,.2f}")
                    st.rerun()

        preview_gross = pair_gross_pnl
        preview_charges = pair_total_trade_charges
        preview_net = preview_gross - preview_charges
        st.markdown(
            f"""
            <div style="margin-top: 14px; padding: 12px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--bg-secondary);">
                <div style="display:flex; justify-content:space-between; gap:12px;"><span>Preview Gross P&L</span><strong>{currency_sym}{preview_gross:,.2f}</strong></div>
                <div style="display:flex; justify-content:space-between; gap:12px;"><span>Total Charges</span><strong>{currency_sym}{preview_charges:,.2f}</strong></div>
                <div style="display:flex; justify-content:space-between; gap:12px; font-size:1.05rem; margin-top:6px;"><span>Preview Net P&L</span><strong style="color:{'var(--accent-green)' if preview_net >= 0 else 'var(--accent-red)'};">{currency_sym}{preview_net:,.2f}</strong></div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("<h5>Nifty Pair Trade Register</h5>", unsafe_allow_html=True)
    if df_pair_trades.empty:
        st.info("No Nifty pair trades logged yet.")
    else:
        pair_display = df_pair_trades.copy()
        pair_display = pair_display.rename(columns={
            "trade_date": "Date",
            "pair_name": "Pair",
            "leg1_symbol": "Leg 1",
            "leg1_action": "L1 Action",
            "leg1_qty": "L1 Qty",
            "leg1_entry": "L1 Entry",
            "leg1_exit": "L1 Exit",
            "leg2_symbol": "Leg 2",
            "leg2_action": "L2 Action",
            "leg2_qty": "L2 Qty",
            "leg2_entry": "L2 Entry",
            "leg2_exit": "L2 Exit",
            "brokerage": "Brokerage",
            "other_charges": "Manual Extra",
            "gross_pnl": "Gross P&L",
            "total_charges": "Charges",
            "net_pnl": "Net P&L",
            "notes": "Notes"
        })
        
        styled_df = style_dataframe_pnl(
            pair_display[[
                "id", "Date", "Pair", "Leg 1", "L1 Action", "L1 Qty", "L1 Entry", "L1 Exit",
                "Leg 2", "L2 Action", "L2 Qty", "L2 Entry", "L2 Exit", "Brokerage", "Manual Extra",
                "Gross P&L", "Charges", "Net P&L", "Notes"
            ]],
            gross_col="Gross P&L",
            net_col="Net P&L",
            other_cols_currency=["Brokerage", "Manual Extra", "Charges"]
        )
        
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True
        )

        with st.expander("Edit Saved Pair Trade", expanded=False):
            edit_pair_id = st.selectbox(
                "Select Pair Trade to Edit",
                options=["-- Select Trade --"] + [int(x) for x in df_pair_trades["id"].tolist()],
                key="edit_pair_trade_select"
            )

            if edit_pair_id != "-- Select Trade --":
                edit_row = df_pair_trades[df_pair_trades["id"] == int(edit_pair_id)].iloc[0]
                edit_key = f"edit_pair_{int(edit_pair_id)}"
                edit_option_rates = brokerage_rates.get("F&O - Index Options", {"buy": 20.0, "sell": 20.0})
                edit_buy_brokerage = float(edit_option_rates.get("buy", 20.0))
                edit_sell_brokerage = float(edit_option_rates.get("sell", 20.0))

                try:
                    edit_date_default = datetime.strptime(str(edit_row["trade_date"]), "%Y-%m-%d").date()
                except Exception:
                    edit_date_default = date.today()

                with st.form(f"{edit_key}_form"):
                    edit_date = st.date_input("Trade Date", value=edit_date_default, key=f"{edit_key}_date")
                    edit_pair_name = st.text_input("Pair Name", value=str(edit_row["pair_name"]), key=f"{edit_key}_name")

                    e_header_cols = st.columns([1.4, 0.8, 0.8, 0.8, 0.8])
                    e_header_cols[0].markdown("**Leg Symbol**")
                    e_header_cols[1].markdown("**Action**")
                    e_header_cols[2].markdown("**Qty**")
                    e_header_cols[3].markdown("**Entry**")
                    e_header_cols[4].markdown("**Exit**")

                    e1c1, e1c2, e1c3, e1c4, e1c5 = st.columns([1.4, 0.8, 0.8, 0.8, 0.8])
                    with e1c1:
                        edit_leg1_symbol = st.text_input("Edit Leg 1 Symbol", value=str(edit_row["leg1_symbol"]), label_visibility="collapsed", key=f"{edit_key}_leg1_symbol").upper()
                    with e1c2:
                        edit_leg1_action = st.selectbox("Edit Leg 1 Action", ["BUY", "SELL"], index=0 if edit_row["leg1_action"] == "BUY" else 1, label_visibility="collapsed", key=f"{edit_key}_leg1_action")
                    with e1c3:
                        edit_leg1_qty = st.number_input("Edit Leg 1 Qty", min_value=nifty_lot_size, step=nifty_lot_size, value=float(edit_row["leg1_qty"]), label_visibility="collapsed", key=f"{edit_key}_leg1_qty")
                    with e1c4:
                        edit_leg1_entry = st.number_input("Edit Leg 1 Entry", min_value=0.0, step=0.05, value=float(edit_row["leg1_entry"]), format="%.2f", label_visibility="collapsed", key=f"{edit_key}_leg1_entry")
                    with e1c5:
                        edit_leg1_exit = st.number_input("Edit Leg 1 Exit", min_value=0.0, step=0.05, value=float(edit_row["leg1_exit"]), format="%.2f", label_visibility="collapsed", key=f"{edit_key}_leg1_exit")

                    e2c1, e2c2, e2c3, e2c4, e2c5 = st.columns([1.4, 0.8, 0.8, 0.8, 0.8])
                    with e2c1:
                        edit_leg2_symbol = st.text_input("Edit Leg 2 Symbol", value=str(edit_row["leg2_symbol"]), label_visibility="collapsed", key=f"{edit_key}_leg2_symbol").upper()
                    with e2c2:
                        edit_leg2_action = st.selectbox("Edit Leg 2 Action", ["BUY", "SELL"], index=0 if edit_row["leg2_action"] == "BUY" else 1, label_visibility="collapsed", key=f"{edit_key}_leg2_action")
                    with e2c3:
                        edit_leg2_qty = st.number_input("Edit Leg 2 Qty", min_value=nifty_lot_size, step=nifty_lot_size, value=float(edit_row["leg2_qty"]), label_visibility="collapsed", key=f"{edit_key}_leg2_qty")
                    with e2c4:
                        edit_leg2_entry = st.number_input("Edit Leg 2 Entry", min_value=0.0, step=0.05, value=float(edit_row["leg2_entry"]), format="%.2f", label_visibility="collapsed", key=f"{edit_key}_leg2_entry")
                    with e2c5:
                        edit_leg2_exit = st.number_input("Edit Leg 2 Exit", min_value=0.0, step=0.05, value=float(edit_row["leg2_exit"]), format="%.2f", label_visibility="collapsed", key=f"{edit_key}_leg2_exit")

                    edit_leg1_brokerage = edit_buy_brokerage if edit_leg1_action == "BUY" else edit_sell_brokerage
                    edit_leg2_brokerage = edit_buy_brokerage if edit_leg2_action == "BUY" else edit_sell_brokerage
                    edit_pair_brokerage = edit_leg1_brokerage + edit_leg2_brokerage

                    eb1, eb2, eb3 = st.columns(3)
                    with eb1:
                        st.number_input("Index Option Buy Brokerage (₹)", min_value=0.0, step=1.0, value=float(edit_buy_brokerage), disabled=True, key=f"{edit_key}_buy_brokerage")
                    with eb2:
                        st.number_input("Index Option Sell Brokerage (₹)", min_value=0.0, step=1.0, value=float(edit_sell_brokerage), disabled=True, key=f"{edit_key}_sell_brokerage")
                    with eb3:
                        st.number_input("Pair Brokerage (₹)", min_value=0.0, step=1.0, value=float(edit_pair_brokerage), disabled=True, key=f"{edit_key}_pair_brokerage")

                    edit_other_charges = st.number_input(
                        "Other Charges (Slippage / Auto-squared off)",
                        min_value=0.0,
                        step=5.0,
                        value=float(edit_row.get("other_charges", 0.0)),
                        key=f"{edit_key}_other_charges"
                    )
                    edit_notes = st.text_area("Notes", value=str(edit_row["notes"] or ""), key=f"{edit_key}_notes")

                    edit_leg1_metrics = calculate_trade_metrics(
                        segment="F&O - Index Options",
                        action=edit_leg1_action,
                        quantity=edit_leg1_qty,
                        entry_price=edit_leg1_entry,
                        exit_price=edit_leg1_exit,
                        brokerage_input=edit_leg1_brokerage
                    )
                    edit_leg2_metrics = calculate_trade_metrics(
                        segment="F&O - Index Options",
                        action=edit_leg2_action,
                        quantity=edit_leg2_qty,
                        entry_price=edit_leg2_entry,
                        exit_price=edit_leg2_exit,
                        brokerage_input=edit_leg2_brokerage
                    )
                    edit_gross_pnl = edit_leg1_metrics["gross_pnl"] + edit_leg2_metrics["gross_pnl"]
                    edit_total_charges = edit_leg1_metrics["total_charges"] + edit_leg2_metrics["total_charges"] + edit_other_charges
                    edit_net_pnl = edit_gross_pnl - edit_total_charges

                    st.markdown(
                        f"""
                        <div style="margin: 10px 0 14px; padding: 12px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--bg-secondary);">
                            <div style="display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px;">
                                <div><span style="color:var(--text-secondary);">Gross P&L</span><br><strong>{currency_sym}{edit_gross_pnl:,.2f}</strong></div>
                                <div><span style="color:var(--text-secondary);">Total Charges</span><br><strong style="color:var(--accent-red);">{currency_sym}{edit_total_charges:,.2f}</strong></div>
                                <div><span style="color:var(--text-secondary);">Net P&L</span><br><strong style="color:{'var(--accent-green)' if edit_net_pnl >= 0 else 'var(--accent-red)'};">{currency_sym}{edit_net_pnl:,.2f}</strong></div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    save_edit_pair = st.form_submit_button("Update Pair Trade")

                    if save_edit_pair:
                        if not edit_leg1_symbol or not edit_leg2_symbol:
                            st.error("Please enter both option leg symbols.")
                        elif edit_leg1_qty <= 0 or edit_leg2_qty <= 0:
                            st.error("Please enter a valid quantity for both legs.")
                        elif not is_nifty_lot_multiple(edit_leg1_qty) or not is_nifty_lot_multiple(edit_leg2_qty):
                            st.error("Nifty quantities must be 65 or multiples of 65, such as 65, 130, 195, 260.")
                        else:
                            update_pair_trade(int(edit_pair_id), {
                                "trade_date": edit_date.strftime("%Y-%m-%d"),
                                "pair_name": edit_pair_name.strip() or "NIFTY Option Pair",
                                "leg1_symbol": edit_leg1_symbol,
                                "leg1_action": edit_leg1_action,
                                "leg1_qty": edit_leg1_qty,
                                "leg1_entry": edit_leg1_entry,
                                "leg1_exit": edit_leg1_exit,
                                "leg2_symbol": edit_leg2_symbol,
                                "leg2_action": edit_leg2_action,
                                "leg2_qty": edit_leg2_qty,
                                "leg2_entry": edit_leg2_entry,
                                "leg2_exit": edit_leg2_exit,
                                "brokerage": edit_pair_brokerage,
                                "other_charges": edit_other_charges,
                                "total_charges": edit_total_charges,
                                "gross_pnl": edit_gross_pnl,
                                "net_pnl": edit_net_pnl,
                                "notes": edit_notes
                            })
                            st.success("Pair trade updated.")
                            st.rerun()

        delete_pair_id = st.selectbox(
            "Delete Pair Trade",
            options=["-- Select Trade --"] + [int(x) for x in df_pair_trades["id"].tolist()],
            key="delete_pair_trade_select"
        )
        if st.button("Delete Selected Pair Trade", disabled=delete_pair_id == "-- Select Trade --", key="delete_pair_trade_btn"):
            delete_pair_trade(int(delete_pair_id))
            st.success("Pair trade deleted.")
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ==========================================
# TAB 9: SEGMENT RULES & RISK ALLOCATOR
# ==========================================
with tab_rules:
    st.markdown('<div class="glass-card preview-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0; color: var(--text-primary);">🛡️ Segment Rules & Risk Allocator</h3>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Set stricter rules by tying trade eligibility to your savings progress. Allocate your daily risk across segments, and optionally step up limits using trading profits.</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    rules = get_segment_rules()

    # Calculate step-up risk limit
    base_risk = float(rules.get("base_daily_risk", 250.0))
    enable_step_up = rules.get("enable_step_up", True)
    enforcement_mode = rules.get("enforcement_mode", "Hard Lock")
    
    monthly_pnl_val = get_monthly_total_pnl()
    step_up_bonus = 0.0
    if enable_step_up and monthly_pnl_val > 0:
        step_up_bonus = monthly_pnl_val * 0.10
        
    active_daily_risk = base_risk + step_up_bonus

    # Calculate Total Daily Increment
    start_date_str = get_db_settings("segment_rules_start_date", "2026-06-07")
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except Exception:
        start_date = date.today()
    days_passed = max(1, (date.today() - start_date).days + 1)
    total_daily_increment = active_daily_risk * days_passed

    # Metrics Row
    met1, met2, met3, met4, met5 = st.columns(5)
    with met1:
        st.metric("Base Daily Risk Limit", f"₹ {base_risk:,.2f}", help="Based on 25% of monthly projected income")
    with met2:
        pnl_color_str = "+" if monthly_pnl_val >= 0 else ""
        st.metric("Current Month Net P&L", f"₹ {monthly_pnl_val:,.2f}", delta=f"{pnl_color_str}10% step-up eligible" if enable_step_up else "Step-up disabled")
    with met3:
        st.metric("Step-Up Daily Bonus", f"₹ {step_up_bonus:,.2f}", delta="10% of monthly profit" if step_up_bonus > 0 else "No monthly profit bonus")
    with met4:
        st.metric("Active Daily Risk Limit", f"₹ {active_daily_risk:,.2f}", delta=f"Scaled up by ₹{step_up_bonus:,.2f}" if step_up_bonus > 0 else "Base limit active", delta_color="normal" if step_up_bonus > 0 else "off")
    with met5:
        st.metric("Total Daily Increment", f"₹ {total_daily_increment:,.2f}", delta=f"₹{active_daily_risk:,.2f} / day")

    rule_config_col, rule_segment_col = st.columns([1, 2])

    display_names = {
        "Commodities": "Commodity Segment",
        "Equity - Delivery": "Investment Segment",
        "F&O - Stock Options": "Stock Option Segment",
        "F&O - Index Options": "Nifty Index Options",
        "Equity - Intraday": "Intraday Segment"
    }

    with rule_config_col:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("<h5>Risk & Enforcement Config</h5>", unsafe_allow_html=True)
        
        with st.form("risk_config_form"):
            new_base_risk = st.number_input("Base Daily Risk (₹)", min_value=0.0, step=10.0, value=base_risk, help="Maximum overall loss budget per day before penalty box kicks in.")
            new_enable_step_up = st.checkbox("Enable 10% Profit Step-Up", value=enable_step_up, help="Automatically increases your active daily risk limit by 10% of your net profits this month.")
            new_enforce_mode = st.selectbox("Rule Enforcement Mode", options=["Hard Lock", "Soft Warning"], index=0 if enforcement_mode == "Hard Lock" else 1, help="Hard Lock completely disables trade logging for locked segments. Soft Warning only shows a notice.")
            
            # Input allocations and minimum savings targets inside the form
            new_allocations = {}
            st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
            for seg_key, seg_data in rules["rules"].items():
                st.markdown(f"**{display_names.get(seg_key, seg_key)}**")
                subcol1, subcol2 = st.columns(2)
                with subcol1:
                    alloc_pct = st.number_input(f"Allocation (%)", min_value=0.0, max_value=100.0, step=1.0, value=float(seg_data.get("allocation_pct", 15.0)), key=f"alloc_pct_{seg_key}")
                with subcol2:
                    min_sav = st.number_input(f"Min Savings (₹)", min_value=0.0, step=100.0, value=float(seg_data.get("min_savings", 3000.0)), key=f"min_sav_{seg_key}")
                
                # Retrieve manual adjustment value (updated in the other column, but must preserve it here)
                man_adj = float(seg_data.get("manual_adjustment", 0.0))
                new_allocations[seg_key] = {
                    "allocation_pct": alloc_pct,
                    "min_savings": min_sav,
                    "manual_adjustment": man_adj
                }
                
            save_config = st.form_submit_button("Save Configuration & Rules")
            if save_config:
                total_pct = sum(item["allocation_pct"] for item in new_allocations.values())
                if total_pct != 100.0:
                    st.error(f"Error: Total segment allocation percentage must sum to exactly 100%. Currently it is **{total_pct}%**.")
                else:
                    updated_rules = {
                        "base_daily_risk": new_base_risk,
                        "enable_step_up": new_enable_step_up,
                        "enforcement_mode": new_enforce_mode,
                        "rules": new_allocations
                    }
                    save_segment_rules(updated_rules)
                    st.success("Risk configuration and rules saved successfully!")
                    st.rerun()
                    
        st.markdown('</div>', unsafe_allow_html=True)

    with rule_segment_col:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("<h5>Segment Savings Ledger & Guard Status</h5>", unsafe_allow_html=True)
        st.markdown("<p style='font-size:0.85rem; color: var(--text-secondary); margin-top:-10px; margin-bottom:15px;'>Enter your current actual savings allocated for each segment. If it falls short of the target minimum savings, the segment will lock.</p>", unsafe_allow_html=True)
        
        # Form to update current savings
        with st.form("savings_update_form"):
            updated_savings_dict = {}
            
            for seg_key, seg_data in rules["rules"].items():
                savings_info = get_segment_savings(rules, seg_key, active_daily_risk)
                current_savings = savings_info["current_savings"]
                min_savings = float(seg_data.get("min_savings", 3000.0))
                alloc_pct = float(seg_data.get("allocation_pct", 15.0))
                seg_risk_allocation = savings_info["seg_risk_allocation"]
                
                # Calculate Status
                is_ready = savings_info["is_ready"]
                status_badge = "🟢 READY TO TRADE" if is_ready else "🔴 LOCKED (Below Target)"
                status_color = "var(--accent-green)" if is_ready else "var(--accent-red)"
                badge_bg = "#ECFDF5" if is_ready else "#FEF2F2"
                
                progress_pct = savings_info["progress_pct"]
                
                # Render Segment card container in custom HTML
                unlock_info_html = ""
                if not is_ready and savings_info.get("unlock_date"):
                    unlock_date_str = savings_info["unlock_date"].strftime("%d %b %Y")
                    days_needed = savings_info["days_needed"]
                    unlock_info_html = f"""
                    <div style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(0,0,0,0.08); font-size: 0.88rem; color: var(--text-secondary);">
                        ⏳ Est. Unlock: <strong style="color: var(--text-primary);">{unlock_date_str} (in {days_needed} days)</strong>
                    </div>
                    """

                st.markdown(
                    f"""
                    <div style="border: 1px solid var(--border-color); border-radius: 8px; padding: 15px; margin-bottom: 10px; background: var(--bg-secondary);">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <span style="font-weight:700; font-size:1.05rem; color: var(--text-primary);">{display_names.get(seg_key, seg_key)}</span>
                            <span style="background-color: {badge_bg}; color: {status_color}; border: 1.5px solid {status_color}; padding: 3px 8px; border-radius: 6px; font-weight: 700; font-size: 0.8rem; text-transform: uppercase;">
                                {status_badge}
                            </span>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; font-size:0.9rem; margin-bottom: 8px;">
                            <div><span style="color:var(--text-secondary);">Risk Allocation</span><br><strong>₹ {seg_risk_allocation:,.2f} ({alloc_pct}%)</strong></div>
                            <div><span style="color:var(--text-secondary);">Target Min Savings</span><br><strong>₹ {min_savings:,.2f}</strong></div>
                            <div><span style="color:var(--text-secondary);">Savings Progress</span><br><strong>{progress_pct:.1f}%</strong></div>
                        </div>
                        {unlock_info_html}
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                
                # Render progress bar
                progress_val = min(1.0, max(0.0, current_savings / min_savings)) if min_savings > 0 else 0.0
                st.progress(progress_val)
                
                # Input for updating current savings
                new_sav = st.number_input(f"Update Current Savings for {display_names.get(seg_key, seg_key)} (₹)", min_value=0.0, step=10.0, value=current_savings, key=f"input_sav_{seg_key}")
                updated_savings_dict[seg_key] = new_sav
                st.markdown("<br>", unsafe_allow_html=True)
                
            save_savings = st.form_submit_button("Save Current Savings Levels")
            if save_savings:
                # Update manual adjustments in settings
                for seg_key, new_val in updated_savings_dict.items():
                    savings_info = get_segment_savings(rules, seg_key, active_daily_risk)
                    accumulated_base = (savings_info["days_passed"] * savings_info["seg_risk_allocation"]) + savings_info["seg_pnl"]
                    new_adj = new_val - accumulated_base
                    rules["rules"][seg_key]["manual_adjustment"] = new_adj
                save_segment_rules(rules)
                st.success("Savings levels updated successfully!")
                st.rerun()
                
        st.markdown('</div>', unsafe_allow_html=True)


# ==========================================
# TAB 10: PAPER TRADING
# ==========================================
with tab_paper:
    st.markdown('<div class="glass-card preview-card">', unsafe_allow_html=True)
    st.markdown('<h3 style="margin-top:0; color: var(--text-primary);">🧪 Paper Trading Screener Reliability Sandbox</h3>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); margin-top:-10px;">Compare signals from the <strong>Trading Workstation</strong> (Live/INDmoney tokens) against the <strong>Nifty Scanner</strong> (Delayed ticks) in real-time. Calculate win rates, net profits, and reliability side-by-side without affecting your actual capital records.</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Fetch paper trades
    df_paper = fetch_paper_trades_df()
    
    # Compute sequential active trade numbers chronologically
    if not df_paper.empty:
        df_paper = df_paper.sort_values(by=['trade_date', 'id'], ascending=[True, True])
        df_paper['s_no'] = range(1, len(df_paper) + 1)
        df_paper = df_paper.sort_values(by=['trade_date', 'id'], ascending=[False, False])
    else:
        df_paper['s_no'] = pd.Series(dtype='int')
        
    screeners = ["Trading Workstation", "Nifty Scanner"]
    stats = {}
    
    for scr in screeners:
        df_scr = df_paper[df_paper['source_screener'] == scr] if not df_paper.empty else pd.DataFrame()
        total_trades_s = len(df_scr)
        
        if total_trades_s > 0:
            gross_profit_s = df_scr[df_scr['net_pnl'] > 0]['net_pnl'].sum()
            gross_loss_s = df_scr[df_scr['net_pnl'] < 0]['net_pnl'].sum()
            winning_trades_s = len(df_scr[df_scr['net_pnl'] > 0])
            losing_trades_s = len(df_scr[df_scr['net_pnl'] < 0])
            
            win_rate_s = (winning_trades_s / total_trades_s) * 100
            profit_factor_s = abs(gross_profit_s / gross_loss_s) if gross_loss_s != 0 else (gross_profit_s if gross_profit_s > 0 else 1.0)
            net_pnl_s = df_scr['net_pnl'].sum()
            total_charges_s = df_scr['total_charges'].sum()
            
            # Find best and worst trades
            best_idx = df_scr['net_pnl'].idxmax()
            worst_idx = df_scr['net_pnl'].idxmin()
            
            best_row = df_scr.loc[best_idx]
            worst_row = df_scr.loc[worst_idx]
            
            best_pnl = best_row['net_pnl']
            worst_pnl = worst_row['net_pnl']
            
            best_sign = "+" if best_pnl > 0 else ""
            best_color = "var(--accent-green)" if best_pnl >= 0 else "#EA580C"
            best_trade_info = f"<strong>{best_row['symbol']}</strong> ({best_row['trade_date']}) <span style='color: {best_color}; font-weight:700;'>{best_sign}{currency_sym}{best_pnl:,.2f}</span>"
            
            worst_sign = "+" if worst_pnl > 0 else ""
            worst_color = "var(--accent-green)" if worst_pnl >= 0 else "#EA580C"
            worst_trade_info = f"<strong>{worst_row['symbol']}</strong> ({worst_row['trade_date']}) <span style='color: {worst_color}; font-weight:700;'>{worst_sign}{currency_sym}{worst_pnl:,.2f}</span>"
        else:
            winning_trades_s = 0
            losing_trades_s = 0
            win_rate_s = 0.0
            profit_factor_s = 1.0
            net_pnl_s = 0.0
            total_charges_s = 0.0
            best_trade_info = "<span style='color: var(--text-secondary);'>None</span>"
            worst_trade_info = "<span style='color: var(--text-secondary);'>None</span>"
            
        stats[scr] = {
            "total": total_trades_s,
            "win_rate": win_rate_s,
            "profit_factor": profit_factor_s,
            "net_pnl": net_pnl_s,
            "charges": total_charges_s,
            "wins": winning_trades_s,
            "losses": losing_trades_s,
            "best_trade": best_trade_info,
            "worst_trade": worst_trade_info
        }
        
    # Render Metrics Row
    col_tw, col_ns = st.columns(2)
    
    for scr, col in zip(screeners, [col_tw, col_ns]):
        with col:
            s_data = stats[scr]
            pnl_val = s_data["net_pnl"]
            pnl_color = "var(--accent-green)" if pnl_val >= 0 else "#EA580C"
            pnl_sign = "+" if pnl_val > 0 else ""
            
            icon = "⚡" if scr == "Trading Workstation" else "🔍"
            desc = "Live Trading Signals (INDmoney)" if scr == "Trading Workstation" else "Delayed 15m Tick Analysis"
            
            st.markdown(
                f"""
                <div class="glass-card" style="padding: 20px; border-top: 5px solid {'#10B981' if scr == 'Trading Workstation' else '#3B82F6'}; margin-bottom: 20px;">
                    <div style="font-size: 1.25rem; font-weight: 800; color: var(--text-primary); margin-bottom: 3px;">
                        {icon} {scr}
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 15px; font-weight: 500;">
                        {desc}
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 10px;">
                        <div>
                            <span style="font-size: 0.9rem; color: var(--text-secondary); font-weight: 600;">Net P&L</span><br>
                            <span style="font-size: 1.6rem; font-weight: 800; color: {pnl_color};">{pnl_sign}{currency_sym}{pnl_val:,.2f}</span>
                        </div>
                        <div>
                            <span style="font-size: 0.9rem; color: var(--text-secondary); font-weight: 600;">Win Rate</span><br>
                            <span style="font-size: 1.6rem; font-weight: 800; color: var(--text-primary);">{s_data['win_rate']:.1f}%</span>
                        </div>
                        <div>
                            <span style="font-size: 0.9rem; color: var(--text-secondary); font-weight: 600;">Total Trades</span><br>
                            <span style="font-size: 1.6rem; font-weight: 800; color: var(--text-primary);">{s_data['total']}</span>
                        </div>
                        <div>
                            <span style="font-size: 0.9rem; color: var(--text-secondary); font-weight: 600;">Profit Factor</span><br>
                            <span style="font-size: 1.6rem; font-weight: 800; color: var(--text-primary);">{s_data['profit_factor']:.2f}x</span>
                        </div>
                    </div>
                    <div style="font-size: 0.82rem; color: var(--text-secondary); border-top: 1px dashed var(--border-color); padding-top: 8px; margin-top: 8px; display: flex; justify-content: space-between;">
                        <span>Record: <strong>{s_data['wins']}W - {s_data['losses']}L</strong></span>
                        <span>Charges: <strong>{currency_sym}{s_data['charges']:,.2f}</strong></span>
                    </div>
                    <div style="font-size: 0.85rem; border-top: 1px dashed var(--border-color); padding-top: 8px; margin-top: 8px; line-height: 1.45;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <span style="color: var(--text-secondary); font-weight: 600;">🏆 Best Trade:</span>
                            <span>{s_data['best_trade']}</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;">
                            <span style="color: var(--text-secondary); font-weight: 600;">⚠️ Worst Trade:</span>
                            <span>{s_data['worst_trade']}</span>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
    # Form to Log Paper Trade
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<h4>📝 Log a Paper Trade</h4>', unsafe_allow_html=True)
    st.markdown('<p style="color: var(--text-secondary); margin-top:-10px; font-size: 0.9rem;">Record a virtual trade to test your screener strategy. Fees and charges are computed dynamically.</p>', unsafe_allow_html=True)
    
    if "paper_form_id" not in st.session_state:
        st.session_state["paper_form_id"] = 0
        
    p_col1, p_col2 = st.columns(2)
    brokerage_rates = get_brokerage_rates()
    
    with p_col1:
        pt_date = st.date_input("Paper Trade Date", value=date.today(), key=f"paper_date_{st.session_state['paper_form_id']}")
        pt_symbol = st.text_input("Ticker / Symbol", value="", placeholder="e.g. HINDALCO, HDFCBANK", key=f"paper_symbol_{st.session_state['paper_form_id']}").upper()
        pt_source = st.selectbox("Screener Source", options=screeners, key=f"paper_source_{st.session_state['paper_form_id']}")
        pt_segment = st.selectbox(
            "Asset Segment",
            options=list(brokerage_rates.keys()),
            index=0,
            key=f"paper_segment_{st.session_state['paper_form_id']}"
        )
        pt_action = st.selectbox("Action", options=["BUY", "SELL"], format_func=lambda x: "BUY (Long)" if x == "BUY" else "SELL (Short)", key=f"paper_action_{st.session_state['paper_form_id']}")
    
    with p_col2:
        pt_qty = st.number_input("Quantity", min_value=0.0, step=1.0, value=0.0, key=f"paper_qty_{st.session_state['paper_form_id']}")
        pt_entry = st.number_input("Entry Price", min_value=0.0, step=0.05, value=0.0, key=f"paper_entry_{st.session_state['paper_form_id']}")
        pt_exit = st.number_input("Exit Price", min_value=0.0, step=0.05, value=0.0, key=f"paper_exit_{st.session_state['paper_form_id']}")
        
        default_base_lot_p = 0.0
        if pt_segment in ["F&O - Index Options", "F&O - Stock Options", "F&O - Index Futures"]:
            sym_upper = pt_symbol.upper().strip()
            if "NIFTY" in sym_upper:
                if "BANK" in sym_upper:
                    default_base_lot_p = 30.0
                elif "FIN" in sym_upper:
                    default_base_lot_p = 60.0
                elif "MIDCP" in sym_upper or "MID CAP" in sym_upper:
                    default_base_lot_p = 120.0
                else:
                    default_base_lot_p = 65.0
            else:
                default_base_lot_p = 65.0
                
        pt_base_lot = st.number_input("Base Lot Size (0 for flat)", min_value=0.0, step=1.0, value=float(default_base_lot_p), help="Set to minimum lot size (e.g. 65 or 75) to scale brokerage per lot automatically.", key=f"paper_base_lot_{st.session_state['paper_form_id']}")
        
        def_brokerage_buy_p = brokerage_rates[pt_segment]["buy"]
        def_brokerage_sell_p = brokerage_rates[pt_segment]["sell"]
        def_total_brokerage_p = def_brokerage_buy_p + def_brokerage_sell_p
        
        import math
        lots_p = 1
        if pt_base_lot > 0:
            lots_p = math.ceil(pt_qty / pt_base_lot)
        computed_brokerage_p = def_total_brokerage_p * lots_p
        
        pt_brokerage = st.number_input(
            "Total Brokerage (₹)",
            min_value=0.0,
            step=1.0,
            value=float(computed_brokerage_p),
            disabled=True,
            help="Automated based on global settings and lot scaling. Go to System Settings to edit base rates.",
            key=f"paper_brokerage_{st.session_state['paper_form_id']}"
        )
        
    pt_notes = st.text_area("Trade Notes / Signal Context", placeholder="Why did you log this signal? e.g. 'SMA crossover' or 'INDmoney notification'...", height=80, key=f"paper_notes_{st.session_state['paper_form_id']}")
    
    if pt_symbol:
        render_quantamental_health_card(pt_symbol, key_suffix="paper")
        
    pt_warning_msg = get_quote_mismatch_warning(pt_symbol, pt_segment)
    if pt_warning_msg:
        st.warning(pt_warning_msg)
        
    submit_paper_trade = st.button(
        "Log Paper Trade", 
        type="primary", 
        use_container_width=True,
        key=f"paper_submit_{st.session_state['paper_form_id']}"
    )
    
    if submit_paper_trade:
        if not pt_symbol.strip():
            st.error("Please provide a valid ticker symbol.")
        elif pt_qty <= 0:
            st.error("Quantity must be greater than zero.")
        elif pt_entry <= 0:
            st.error("Entry Price must be greater than zero.")
        elif pt_exit <= 0:
            st.error("Exit Price must be greater than zero.")
        else:
            metrics = calculate_trade_metrics(
                segment=pt_segment,
                action=pt_action,
                quantity=pt_qty,
                entry_price=pt_entry,
                exit_price=pt_exit,
                brokerage_input=computed_brokerage_p
            )
            
            paper_trade_to_save = {
                "trade_date": pt_date.strftime("%Y-%m-%d"),
                "symbol": pt_symbol,
                "segment": pt_segment,
                "action": pt_action,
                "quantity": pt_qty,
                "entry_price": pt_entry,
                "exit_price": pt_exit,
                "brokerage": metrics["brokerage"],
                "stt": metrics["stt"],
                "exchange_charges": metrics["exchange_charges"],
                "sebi_charges": metrics["sebi_charges"],
                "stamp_duty": metrics["stamp_duty"],
                "gst": metrics["gst"],
                "total_charges": metrics["total_charges"],
                "gross_pnl": metrics["gross_pnl"],
                "net_pnl": metrics["net_pnl"],
                "source_screener": pt_source,
                "notes": pt_notes
            }
            
            add_paper_trade(paper_trade_to_save)
            st.session_state["paper_form_id"] += 1
            st.success(f"Paper trade for {pt_symbol} ({pt_source}) successfully saved!")
            st.rerun()
            
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Paper Trade Logs and Search Table
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown('<h3>🔍 Paper Trading Log Sheets & Search</h3>', unsafe_allow_html=True)
    
    db_paper_segments = list(df_paper['segment'].unique()) if not df_paper.empty else []
    db_paper_sources = list(df_paper['source_screener'].unique()) if not df_paper.empty else []
    
    ps_col1, ps_col2, ps_col3 = st.columns(3)
    with ps_col1:
        search_paper_ticker = st.text_input("Search by Symbol", placeholder="e.g. HINDALCO", key="search_paper_symbol").upper()
    with ps_col2:
        filter_paper_segment = st.multiselect("Filter by Segment", options=db_paper_segments, key="filter_paper_seg")
    with ps_col3:
        filter_paper_source = st.multiselect("Filter by Screener Source", options=db_paper_sources, key="filter_paper_src")
        
    df_paper_filtered = df_paper.copy() if not df_paper.empty else pd.DataFrame(columns=[
        "id", "trade_date", "symbol", "segment", "action", "quantity", 
        "entry_price", "exit_price", "brokerage", "stt", "exchange_charges", 
        "sebi_charges", "stamp_duty", "gst", "total_charges", "gross_pnl", "net_pnl", 
        "source_screener", "notes"
    ])
    
    if not df_paper.empty:
        if search_paper_ticker.strip():
            df_paper_filtered = df_paper_filtered[df_paper_filtered['symbol'].str.contains(search_paper_ticker)]
        if filter_paper_segment:
            df_paper_filtered = df_paper_filtered[df_paper_filtered['segment'].isin(filter_paper_segment)]
        if filter_paper_source:
            df_paper_filtered = df_paper_filtered[df_paper_filtered['source_screener'].isin(filter_paper_source)]
            
    total_paper_count = len(df_paper)
    filtered_paper_count = len(df_paper_filtered)
    st.markdown(f"<p style='color: var(--text-secondary); font-size: 0.85rem;'>Showing {filtered_paper_count} of {total_paper_count} paper trades</p>", unsafe_allow_html=True)
    
    df_paper_display = df_paper_filtered.copy()
    if not df_paper_display.empty:
        df_paper_display = df_paper_display.rename(columns={"s_no": "Trade #"})
        
        styled_df = style_dataframe_pnl(
            df_paper_display[[
                "Trade #", "trade_date", "symbol", "segment", "action", 
                "quantity", "entry_price", "exit_price", 
                "gross_pnl", "total_charges", "net_pnl", "source_screener", "notes"
            ]],
            other_cols_currency=["total_charges"]
        )
        
        st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True
        )
    else:
        empty_cols = [
            "Trade #", "trade_date", "symbol", "segment", "action", 
            "quantity", "entry_price", "exit_price", 
            "gross_pnl", "total_charges", "net_pnl", "source_screener", "notes"
        ]
        st.dataframe(pd.DataFrame(columns=empty_cols), use_container_width=True, hide_index=True)
        
    st.markdown("<hr style='border-color: var(--border-color);'>", unsafe_allow_html=True)
    st.markdown("<h5>⚙️ Manage / Edit Paper Trade Entries</h5>", unsafe_allow_html=True)
    
    if df_paper_filtered.empty:
        st.info("No paper trades matched the filters or database is empty.")
    else:
        selectbox_paper_options = ["-- Select a Paper Trade to Edit / Manage --"]
        id_paper_map = {}
        df_paper_filtered_sorted = df_paper_filtered.sort_values(by=['s_no'], ascending=True)
        for index, row in df_paper_filtered_sorted.iterrows():
            label = f"Paper Trade #{row['s_no']} // {row['symbol']} ({row['source_screener']}) on {row['trade_date']}"
            selectbox_paper_options.append(label)
            id_paper_map[label] = row['id']
            
        selected_paper_label = st.selectbox("Select Paper Trade to Manage", options=selectbox_paper_options, index=0, key="select_paper_to_manage")
        
        if selected_paper_label == "-- Select a Paper Trade to Edit / Manage --":
            st.info("Select a paper trade from the dropdown above to view, edit, or delete its details.")
        else:
            selected_paper_trade_id = int(id_paper_map[selected_paper_label])
            pt_row = df_paper_filtered[df_paper_filtered['id'] == selected_paper_trade_id].iloc[0]
            
            st.markdown(f"**Editing Paper Trade #{pt_row['s_no']} ({pt_row['symbol']} - {pt_row['source_screener']})**")
            
            ep_col1, ep_col2 = st.columns(2)
            
            with ep_col1:
                edit_pt_date = st.date_input("Trade Date", value=datetime.strptime(pt_row['trade_date'], "%Y-%m-%d").date(), key=f"edit_paper_date_{selected_paper_trade_id}")
                edit_pt_symbol = st.text_input("Ticker / Symbol", value=pt_row['symbol'], key=f"edit_paper_symbol_{selected_paper_trade_id}").upper()
                edit_pt_source = st.selectbox("Screener Source", options=screeners, index=screeners.index(pt_row['source_screener']) if pt_row['source_screener'] in screeners else 0, key=f"edit_paper_source_{selected_paper_trade_id}")
                edit_pt_segment = st.selectbox("Asset Segment", options=list(brokerage_rates.keys()), index=list(brokerage_rates.keys()).index(pt_row['segment']) if pt_row['segment'] in brokerage_rates else 0, key=f"edit_paper_segment_{selected_paper_trade_id}")
                edit_pt_action = st.selectbox("Action", options=["BUY", "SELL"], format_func=lambda x: "BUY (Long)" if x == "BUY" else "SELL (Short)", index=0 if pt_row['action'] == "BUY" else 1, key=f"edit_paper_action_{selected_paper_trade_id}")
                
            with ep_col2:
                edit_pt_qty = st.number_input("Quantity", min_value=0.0, step=1.0, value=float(pt_row['quantity']), key=f"edit_paper_qty_{selected_paper_trade_id}")
                edit_pt_entry = st.number_input("Entry Price", min_value=0.0, step=0.05, value=float(pt_row['entry_price']), key=f"edit_paper_entry_{selected_paper_trade_id}")
                edit_pt_exit = st.number_input("Exit Price", min_value=0.0, step=0.05, value=float(pt_row['exit_price']), key=f"edit_paper_exit_{selected_paper_trade_id}")
                
                default_edit_lot = 0.0
                if edit_pt_segment in ["F&O - Index Options", "F&O - Stock Options", "F&O - Index Futures"]:
                    sym_upper = edit_pt_symbol.upper().strip()
                    if "NIFTY" in sym_upper:
                        if "BANK" in sym_upper:
                            default_edit_lot = 30.0
                        elif "FIN" in sym_upper:
                            default_edit_lot = 60.0
                        elif "MIDCP" in sym_upper or "MID CAP" in sym_upper:
                            default_edit_lot = 120.0
                        else:
                            default_edit_lot = 65.0
                    else:
                        default_edit_lot = 65.0
                
                edit_pt_base_lot = st.number_input("Base Lot Size (0 for flat)", min_value=0.0, step=1.0, value=float(default_edit_lot), key=f"edit_paper_base_lot_{selected_paper_trade_id}")
                
                def_broker_buy = brokerage_rates[edit_pt_segment]["buy"]
                def_broker_sell = brokerage_rates[edit_pt_segment]["sell"]
                def_total_broker = def_broker_buy + def_broker_sell
                
                lots_edit = 1
                if edit_pt_base_lot > 0:
                    lots_edit = math.ceil(edit_pt_qty / edit_pt_base_lot)
                computed_brokerage_edit = def_total_broker * lots_edit
                
                edit_pt_brokerage = st.number_input(
                    "Total Brokerage (₹)",
                    min_value=0.0,
                    step=1.0,
                    value=float(computed_brokerage_edit),
                    disabled=True,
                    key=f"edit_paper_brokerage_{selected_paper_trade_id}"
                )
                
            edit_pt_notes = st.text_area("Trade Notes / Signal Context", value=pt_row['notes'] if pt_row['notes'] else "", key=f"edit_paper_notes_{selected_paper_trade_id}")
            
            eb_col1, eb_col2 = st.columns(2)
            with eb_col1:
                update_paper_btn = st.button("Update Paper Trade Entry", type="primary", use_container_width=True, key=f"btn_update_paper_{selected_paper_trade_id}")
                if update_paper_btn:
                    if not edit_pt_symbol.strip():
                        st.error("Please enter a valid ticker symbol.")
                    elif edit_pt_qty <= 0:
                        st.error("Quantity must be greater than zero.")
                    elif edit_pt_entry <= 0:
                        st.error("Entry price must be greater than zero.")
                    elif edit_pt_exit <= 0:
                        st.error("Exit price must be greater than zero.")
                    else:
                        metrics_edit = calculate_trade_metrics(
                            segment=edit_pt_segment,
                            action=edit_pt_action,
                            quantity=edit_pt_qty,
                            entry_price=edit_pt_entry,
                            exit_price=edit_pt_exit,
                            brokerage_input=computed_brokerage_edit
                        )
                        
                        updated_pt_data = {
                            "trade_date": edit_pt_date.strftime("%Y-%m-%d"),
                            "symbol": edit_pt_symbol,
                            "segment": edit_pt_segment,
                            "action": edit_pt_action,
                            "quantity": edit_pt_qty,
                            "entry_price": edit_pt_entry,
                            "exit_price": edit_pt_exit,
                            "brokerage": metrics_edit["brokerage"],
                            "stt": metrics_edit["stt"],
                            "exchange_charges": metrics_edit["exchange_charges"],
                            "sebi_charges": metrics_edit["sebi_charges"],
                            "stamp_duty": metrics_edit["stamp_duty"],
                            "gst": metrics_edit["gst"],
                            "total_charges": metrics_edit["total_charges"],
                            "gross_pnl": metrics_edit["gross_pnl"],
                            "net_pnl": metrics_edit["net_pnl"],
                            "source_screener": edit_pt_source,
                            "notes": edit_pt_notes
                        }
                        
                        update_paper_trade(selected_paper_trade_id, updated_pt_data)
                        st.success(f"Paper Trade #{pt_row['s_no']} successfully updated!")
                        st.rerun()
                        
            with eb_col2:
                delete_paper_btn = st.button("Delete Paper Trade Entry", type="secondary", use_container_width=True, key=f"btn_delete_paper_{selected_paper_trade_id}")
                if delete_paper_btn:
                    delete_paper_trade(selected_paper_trade_id)
                    st.warning(f"Paper Trade #{pt_row['s_no']} deleted.")
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


