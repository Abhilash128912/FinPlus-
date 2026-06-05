# =========================================================
# CODEXUP PREMIUM TERMINAL
# VERSION TIMESTAMP: 2026-05-23 06:00 PM
# PANDAS COMPATIBILITY FIXED VERSION
# =========================================================

import json
import warnings
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Any
try:
    from zoneinfo import ZoneInfo
    _IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    # Windows without tzdata package — use a fixed UTC+5:30 offset instead
    from datetime import timezone, timedelta
    _IST_TZ = timezone(timedelta(hours=5, minutes=30))

import pandas as pd
import requests
import streamlit as st
import websocket


st.set_page_config(page_title="Trading Workstation | NSE Scanner", page_icon="📊", layout="wide")

st.markdown(
    """
    <style>
    /* ─── FONTS ─────────────────────────────────────────────────────────── */
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    /* ─── BASE ──────────────────────────────────────────────────────────── */
    html, body, [class*="css"] { 
        font-family: 'Plus Jakarta Sans', 'Outfit', sans-serif !important; 
    }
    .stApp {
        background-color: #F8FAFC !important;
        color: #0F172A !important;
    }
    .block-container {
        padding: 1.5rem 2rem 3rem !important;
        max-width: 1680px !important;
    }

    /* ─── SIDEBAR ───────────────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        border-right: 1px solid #E2E8F0 !important;
    }
    [data-testid="stSidebar"] * { 
        color: #334155 !important; 
        font-family: 'Plus Jakarta Sans', sans-serif !important; 
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #059669 !important;
        font-size: 0.78rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.12em !important;
        text-transform: uppercase !important;
        margin: 1.4rem 0 0.5rem !important;
        padding-bottom: 0.35rem !important;
        border-bottom: 1px solid #E2E8F0 !important;
    }
    [data-testid="stSidebar"] label {
        font-size: 0.92rem !important;
        color: #475569 !important;
        font-weight: 600 !important;
    }
    [data-testid="stSidebar"] .stSlider > div { color: #334155 !important; }

    /* ─── METRIC CARDS ──────────────────────────────────────────────────── */
    [data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.7) !important;
        backdrop-filter: blur(12px) saturate(180%) !important;
        -webkit-backdrop-filter: blur(12px) saturate(180%) !important;
        border: 1px solid rgba(226, 232, 240, 0.8) !important;
        border-top: 4px solid #10B981 !important;
        border-radius: 14px !important;
        padding: 16px 20px 14px !important;
        min-height: 100px;
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.03) !important;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
        transform: translateY(0);
    }
    [data-testid="stMetric"]:hover {
        border-color: rgba(16, 185, 129, 0.4) !important;
        box-shadow: 0 16px 36px -6px rgba(16, 185, 129, 0.15) !important;
        transform: translateY(-4px) !important; /* Gentle 3D Lift */
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.78rem !important;
        font-weight: 700 !important;
        color: #64748B !important;
        text-transform: uppercase;
        letter-spacing: 0.09em;
    }
    div[data-testid="stMetricValue"] {
        font-family: 'Outfit', sans-serif !important;
        font-size: 1.95rem !important;
        font-weight: 700 !important;
        color: #0F172A !important;
        line-height: 1.2 !important;
    }
    div[data-testid="stMetricDelta"] { font-size: 0.85rem !important; }

    /* ─── BUTTONS ───────────────────────────────────────────────────────── */
    div.stButton > button {
        width: 100%;
        background: linear-gradient(to bottom, #FFFFFF, #F8FAFC) !important;
        color: #0F172A !important;
        border-left: 1px solid #E2E8F0 !important;
        border-right: 1px solid #E2E8F0 !important;
        border-top: 1px solid #E2E8F0 !important;
        border-bottom: 4.5px solid #CBD5E1 !important; /* Thick bottom border for realistic 3D feel */
        border-radius: 10px !important;
        font-family: 'Outfit', sans-serif !important;
        font-weight: 700 !important;
        font-size: 0.88rem !important;
        height: 2.6rem !important;
        min-height: 2.6rem !important;
        padding: 0 0.9rem;
        white-space: nowrap;
        line-height: 1;
        letter-spacing: 0.03em;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.03) !important;
        transition: all 0.15s ease !important;
        transform: translateY(0);
    }
    div.stButton > button:hover {
        background: linear-gradient(to bottom, #10B981, #059669) !important; /* Dynamic Emerald Gradient */
        color: #FFFFFF !important;
        border-color: #059669 !important;
        border-bottom-color: #047857 !important;
        box-shadow: 0 6px 16px rgba(16, 185, 129, 0.35) !important;
        transform: translateY(-2px) !important; /* Elevate slightly on hover */
    }
    div.stButton > button:active {
        border-bottom-width: 1px !important; /* Flatten bottom border when pressed */
        transform: translateY(3.5px) !important; /* Dynamic 3D Press Down Effect! */
        box-shadow: 0 1px 3px rgba(16, 185, 129, 0.2) !important;
    }
    div.stButton > button:disabled,
    div.stButton > button:disabled:hover {
        background: #F1F5F9 !important; color: #94A3B8 !important;
        border: 1px solid #E2E8F0 !important; cursor: not-allowed; opacity: 1;
        transform: none !important; box-shadow: none !important;
    }

    /* ─── TABS ──────────────────────────────────────────────────────────── */
    div[data-baseweb="tab-list"] {
        background: #F1F5F9 !important;
        border-radius: 12px !important;
        padding: 4px !important;
        margin-bottom: 24px !important;
        border: 1px solid #E2E8F0 !important;
        gap: 0 !important;
    }
    button[data-baseweb="tab"] {
        font-family: 'Outfit', sans-serif !important;
        font-size: 0.92rem !important;
        font-weight: 500 !important;
        padding: 0.6rem 1.25rem !important;
        color: #475569 !important;
        background: transparent !important;
        border: none !important;
        border-bottom: none !important;
        border-radius: 8px !important;
        letter-spacing: 0.02em;
        transition: all 0.2s ease !important;
    }
    button[data-baseweb="tab"]:hover { color: #0F172A !important; }
    button[data-baseweb="tab"][aria-selected="true"] {
        background: #FFFFFF !important;
        color: #0F172A !important;
        font-weight: 600 !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05) !important;
    }

    /* ─── DATAFRAMES ────────────────────────────────────────────────────── */
    div[data-testid="stDataFrame"] {
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.01);
    }

    /* ─── EXPANDER ──────────────────────────────────────────────────────── */
    div[data-testid="stExpander"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-bottom: 3px solid #CBD5E1;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);
    }
    div[data-testid="stExpander"] summary {
        font-size: 0.92rem !important;
        color: #059669 !important;
        font-weight: 700 !important;
        font-family: 'Outfit', sans-serif !important;
    }

    /* ─── HEADER ────────────────────────────────────────────────────────── */
    .tw-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 1rem;
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-left: 4px solid #10B981;
        border-bottom: 4px solid #CBD5E1;
        border-radius: 12px;
        padding: 1.2rem 1.6rem;
        margin-bottom: 1.4rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);
    }
    .tw-title {
        font-size: 1.7rem;
        font-weight: 700;
        color: #0F172A;
        margin: 0;
        letter-spacing: -0.02em;
        font-family: 'Outfit', sans-serif;
    }
    .tw-subtitle {
        color: #475569;
        margin-top: 0.25rem;
        font-size: 0.88rem;
        font-weight: 600;
    }
    .tw-pill {
        background: #ECFDF5;
        border: 1px solid #A7F3D0;
        border-radius: 6px;
        padding: 0.35rem 0.8rem;
        color: #059669;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        font-family: 'JetBrains Mono', monospace;
    }

    /* ─── SECTION BADGES ────────────────────────────────────────────────── */
    .sig-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        padding: 0.3rem 0.75rem;
        border-radius: 5px;
        margin-bottom: 1rem;
        font-family: 'JetBrains Mono', monospace;
    }
    .sig-super-bo { color: #065F46; background: #D1FAE5; border: 1.5px solid #34D399; }
    .sig-super-bd { color: #991B1B; background: #FEE2E2; border: 1.5px solid #F87171; }
    .sig-bo       { color: #047857; background: #ECFDF5; border: 1.5px solid #A7F3D0; }
    .sig-bd       { color: #B91C1C; background: #FEF2F2; border: 1.5px solid #FCA5A5; }
    .sig-long     { color: #1D4ED8; background: #EFF6FF; border: 1.5px solid #93C5FD; }
    .sig-short    { color: #B45309; background: #FFFBEB; border: 1.5px solid #FCD34D; }
    .sig-all      { color: #334155; background: #F1F5F9; border: 1.5px solid #CBD5E1; }

    /* ─── COVERAGE CARD ─────────────────────────────────────────────────── */
    .coverage-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-left: 4px solid #10B981;
        border-bottom: 3px solid #CBD5E1;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        color: #475569;
        margin: 0.8rem 0;
        font-size: 0.92rem;
        font-weight: 500;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.01);
    }
    .coverage-card strong { color: #059669; font-weight: 700; }

    /* ─── MARKET CLOSED BANNER ──────────────────────────────────────────── */
    .market-closed-banner {
        background: #FEF2F2;
        border: 1.5px solid #FCA5A5;
        border-radius: 12px;
        padding: 1.4rem 2rem;
        margin: 1rem 0 1.6rem;
        text-align: center;
        font-family: 'Inter', sans-serif;
    }
    .market-closed-banner .mcb-icon  { font-size: 2.2rem; line-height:1; }
    .market-closed-banner .mcb-title { font-size:1.15rem; font-weight:700; color:#DC2626; letter-spacing:.07em; text-transform:uppercase; margin-top:.5rem; }
    .market-closed-banner .mcb-sub   { font-size:.92rem; color:#475569; margin-top:.35rem; font-weight:500; }
    .market-closed-banner .mcb-time  { font-size:.82rem; color:#059669; font-family:'JetBrains Mono',monospace; margin-top:.4rem; }

    .market-holiday-banner {
        background: #EEF2FF;
        border: 1.5px solid #C7D2FE;
        border-radius: 12px;
        padding: 1.4rem 2rem;
        margin: 1rem 0 1.6rem;
        text-align: center;
        font-family: 'Inter', sans-serif;
    }
    .market-holiday-banner .mcb-title { font-size:1.15rem; font-weight:700; color:#4F46E5; letter-spacing:.07em; text-transform:uppercase; margin-top:.5rem; }
    .market-holiday-banner .mcb-sub   { font-size:.92rem; color:#475569; margin-top:.35rem; font-weight:500; }
    .market-holiday-banner .mcb-time  { font-size:.82rem; color:#059669; font-family:'JetBrains Mono',monospace; margin-top:.4rem; }

    /* ─── SECTION HEADINGS ──────────────────────────────────────────────── */
    .section-heading {
        font-size: 1.05rem;
        font-weight: 700;
        color: #059669;
        letter-spacing: 0.04em;
        margin: 0.2rem 0 0.6rem 0;
        text-transform: uppercase;
        font-family: 'Outfit', sans-serif;
    }

    /* ─── ALERTS / INFO ─────────────────────────────────────────────────── */
    .stAlert  { font-size: 0.92rem !important; border-radius: 8px !important; }
    .stInfo   { border-left: 3px solid #1D4ED8 !important; background-color: #EFF6FF !important; }
    .stWarning{ border-left: 3px solid #D97706 !important; background-color: #FFFBEB !important; }
    .stSuccess{ border-left: 3px solid #059669 !important; background-color: #ECFDF5 !important; }
    .stError  { border-left: 3px solid #DC2626 !important; background-color: #FEF2F2 !important; }
    div[data-testid="stNotification"] p,
    div[data-testid="stAlert"] p { color: #0F172A !important; font-weight: 500 !important; }

    /* ─── GENERAL TEXT ──────────────────────────────────────────────────── */
    hr  { border-color: #E2E8F0 !important; margin: 1rem 0 !important; }
    p, li { font-size: 0.92rem; color: #475569; font-weight: 500; }
    .stCaption { font-size: 0.82rem !important; color: #64748B !important; font-weight: 500 !important; }
    h1 { color: #0F172A !important; }
    h2 { color: #1E293B !important; }
    h3 { color: #334155 !important; }
    strong { color: #0F172A !important; }

    /* ─── SCROLLBAR ─────────────────────────────────────────────────────── */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: #F8FAFC; }
    ::-webkit-scrollbar-thumb { background: #CBD5E1; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #94A3B8; }

    /* ─── HIDE SIDEBAR COLLAPSE BUTTON ──────────────────────────────────── */
    [data-testid="collapsedControl"]          { display: none !important; }
    [data-testid="stSidebarCollapseButton"]   { display: none !important; }
    section[data-testid="stSidebar"] > div:first-child > div > button { display: none !important; }

    /* ─── SUPPRESS FRAGMENT RENDER FLASH ────────────────────────────────── */
    [data-stale="true"]                              { opacity: 1 !important; }
    [data-testid="stFragmentScrollContainer"]        { opacity: 1 !important; }
    [data-testid="stFragmentScrollContainer"] *      { transition: none !important; }

    /* ─── PREMIUM ALPHA PICKS CARDS ─────────────────────────────────────── */
    .premium-card {
        border-radius: 16px !important;
        padding: 1.25rem 1.5rem !important;
        height: 100% !important;
        background: rgba(255, 255, 255, 0.7) !important;
        backdrop-filter: blur(12px) saturate(180%) !important;
        -webkit-backdrop-filter: blur(12px) saturate(180%) !important;
        border: 1px solid rgba(226, 232, 240, 0.8) !important;
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.04) !important;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: space-between !important;
        box-sizing: border-box !important;
    }
    .premium-card:hover {
        transform: translateY(-5px) !important;
        background: rgba(255, 255, 255, 0.85) !important;
        border-color: rgba(16, 185, 129, 0.3) !important;
        box-shadow: 0 12px 40px 0 rgba(16, 185, 129, 0.12) !important;
    }
    .premium-card-long {
        border-left: 5px solid #10B981 !important;
        background: linear-gradient(135deg, #F0FDF4 0%, #FFFFFF 100%) !important;
    }
    .premium-card-short {
        border-left: 5px solid #EF4444 !important;
        background: linear-gradient(135deg, #FEF2F2 0%, #FFFFFF 100%) !important;
    }
    .premium-card-options {
        border-left: 5px solid #2563EB !important;
        background: linear-gradient(135deg, #EFF6FF 0%, #FFFFFF 100%) !important;
    }
    .premium-card-nifty-options {
        border-left: 5px solid #06B6D4 !important;
        background: linear-gradient(135deg, #ECFEFF 0%, #FFFFFF 100%) !important;
    }
    .premium-card-swing {
        border-left: 5px solid #7C3AED !important;
        background: linear-gradient(135deg, #F5F3FF 0%, #FFFFFF 100%) !important;
    }
    .card-badge {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.7rem !important;
        font-weight: 700 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        display: inline-block !important;
    }
    .action-console {
        background: #0F172A !important;
        color: #F8FAFC !important;
        border-radius: 8px !important;
        padding: 0.6rem 0.75rem !important;
        margin-top: 0.5rem !important;
        margin-bottom: 0.35rem !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 0.78rem !important;
        border: 1px solid #1E293B !important;
        line-height: 1.4 !important;
    }
    .action-console b {
        color: #38BDF8 !important;
    }
    .action-console .action-btn-green {
        color: #34D399 !important;
        font-weight: 700;
    }
    .action-console .action-btn-red {
        color: #F87171 !important;
        font-weight: 700;
    }
    .action-console .action-btn-blue {
        color: #60A5FA !important;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

WS_URL = "wss://ws-prices.indstocks.com/api/v1/ws/prices"
HISTORICAL_URL              = "https://api.indstocks.com/market/historical/1minute"
HISTORICAL_DAILY_URL        = "https://api.indstocks.com/market/historical/1day"
MARKET_DEPTH_URL            = "https://api.indstocks.com/market/quotes/mkt"
FULL_QUOTE_URL              = "https://api.indstocks.com/market/quotes/full"
# 1-min: API hard caps at ~5 trading days regardless of lookback sent.
# Only needed for VWAP / EMA20 / ORB — 5 days is sufficient.
HISTORY_LOOKBACK_DAYS       = 7    # calendar days (API returns last ~5 trading days)
# daily: confirmed working, returns 20 candles per 30-day window.
# 45 calendar days guarantees ≥20 trading days even around long holidays.
HISTORY_DAILY_LOOKBACK_DAYS = 45
HISTORICAL_TIMEOUT          = 15
HISTORICAL_WORKERS          = 8
HIST_BATCH_SIZE             = 50   # stocks per API batch call
#  With batching: 200 stocks → 4 batches × 2 endpoints = 8 parallel API calls
#  vs the old approach of 200 × 2 = 400 sequential API calls (8 at a time).

# ── NSE Market Hours (IST) ──────────────────────────────────────────────────────
IST = _IST_TZ
_MARKET_OPEN  = dtime(9, 15)
_MARKET_CLOSE = dtime(15, 30)
_PRE_OPEN_START = dtime(9, 0)

# NSE holidays 2025-26 (add/remove as needed)
NSE_HOLIDAYS: set[tuple[int, int, int]] = {
    (2025, 1, 26),  # Republic Day
    (2025, 2, 26),  # Mahashivratri
    (2025, 3, 14),  # Holi
    (2025, 4, 14),  # Dr. Ambedkar Jayanti / Ram Navami
    (2025, 4, 18),  # Good Friday
    (2025, 5, 1),   # Maharashtra Day
    (2025, 8, 15),  # Independence Day
    (2025, 8, 27),  # Ganesh Chaturthi
    (2025, 10, 2),  # Gandhi Jayanti / Dussehra
    (2025, 10, 20), # Diwali Laxmi Puja (Muhurat trading day — closed regular session)
    (2025, 10, 21), # Diwali Balipratipada
    (2025, 11, 5),  # Prakash Gurpurb / Guru Nanak Jayanti
    (2025, 12, 25), # Christmas
    (2026, 1, 26),  # Republic Day
    (2026, 3, 26),  # Holi
    (2026, 4, 3),   # Good Friday
    (2026, 4, 6),   # Gudi Padwa / Ram Navami
    (2026, 4, 14),  # Dr. Ambedkar Jayanti
    (2026, 5, 1),   # Maharashtra Day
}


def market_status() -> dict[str, Any]:
    """Return current NSE market status based on IST time.

    Returns a dict with keys:
      is_open      – True if currently in the normal trading session
      is_pre_open  – True if in the 9:00–9:15 pre-open session
      is_holiday   – True if today is a known NSE holiday
      is_weekend   – True if Saturday or Sunday
      now_ist      – current datetime in IST
      next_open    – human-readable next open time string
      status_label – short display string
      status_color – CSS hex colour matching the status
    """
    now = datetime.now(IST)
    today = (now.year, now.month, now.day)
    weekday = now.weekday()          # 0=Mon … 6=Sun
    current_time = now.time().replace(second=0, microsecond=0)

    is_weekend  = weekday >= 5
    is_holiday  = today in NSE_HOLIDAYS
    is_pre_open = (not is_weekend) and (not is_holiday) and (_PRE_OPEN_START <= current_time < _MARKET_OPEN)
    is_open     = (not is_weekend) and (not is_holiday) and (_MARKET_OPEN <= current_time < _MARKET_CLOSE)

    # Build next-open string
    if is_open:
        closes_in = datetime.combine(now.date(), _MARKET_CLOSE, tzinfo=IST) - now
        mins = int(closes_in.total_seconds() // 60)
        next_open = f"Closes in {mins // 60}h {mins % 60}m (15:30 IST)"
    elif is_pre_open:
        next_open = "Pre-open session — normal trading starts at 09:15 IST"
    elif is_weekend:
        # next Monday
        days_to_monday = (7 - weekday) % 7 or 7
        next_open = f"Next trading day: Monday (opens 09:15 IST)"
        if days_to_monday == 1:
            next_open = "Next trading day: Monday (opens 09:15 IST)"
        else:
            next_open = "Next trading day: Monday (opens 09:15 IST)"
    else:
        # weekday but after-hours or holiday
        if current_time >= _MARKET_CLOSE:
            next_open = "Next trading day: Tomorrow (opens 09:15 IST)"
        else:
            next_open = "Opens at 09:15 IST today"

    if is_open:
        label, color = "MARKET OPEN", "#22c55e"
    elif is_pre_open:
        label, color = "PRE-OPEN SESSION", "#f59e0b"
    elif is_holiday:
        label, color = "MARKET HOLIDAY", "#6366f1"
    elif is_weekend:
        label, color = "WEEKEND — MARKET CLOSED", "#64748b"
    else:
        label, color = "MARKET CLOSED", "#ef4444"

    return {
        "is_open":      is_open,
        "is_pre_open":  is_pre_open,
        "is_holiday":   is_holiday,
        "is_weekend":   is_weekend,
        "now_ist":      now,
        "next_open":    next_open,
        "status_label": label,
        "status_color": color,
    }

STOCK_UNIVERSE = {
    # ── NIFTY 50 (40 verified tokens) ──────────────────────────────────────────
    "25": "ADANIENT",
    "15083": "ADANIPORTS",
    "157": "APOLLOHOSP",
    "236": "ASIANPAINT",
    "5900": "AXISBANK",
    "16669": "BAJAJ-AUTO",
    "317": "BAJFINANCE",
    "16675": "BAJAJFINSV",
    "10604": "BHARTIARTL",
    "694": "CIPLA",
    "20374": "COALINDIA",
    "881": "DRREDDY",
    "910": "EICHERMOT",
    "1232": "GRASIM",
    "7229": "HCLTECH",
    "1333": "HDFCBANK",
    "1363": "HINDALCO",
    "1394": "HINDUNILVR",
    "4963": "ICICIBANK",
    "5258": "INDUSINDBK",
    "1594": "INFY",
    "1660": "ITC",
    "11723": "JSWSTEEL",
    "1922": "KOTAKBANK",
    "11483": "LT",
    "2031": "M&M",
    "10999": "MARUTI",
    "11630": "NTPC",
    "2475": "ONGC",
    "14977": "POWERGRID",
    "2885": "RELIANCE",
    "3045": "SBIN",
    "3351": "SUNPHARMA",
    "3432": "TATACONSUM",
    "3456": "TATAMOTORS",
    "3499": "TATASTEEL",
    "11536": "TCS",
    "13538": "TECHM",
    "3506": "TITAN",
    "3787": "WIPRO",
    # ── NIFTY NEXT 50 / BANKING (tokens verified against working pattern) ─────
    "11532": "ULTRACEMCO",
    "17963": "NESTLEIND",
    "3103": "SHREECEM",
    "467": "HDFCLIFE",
    "21808": "SBILIFE",
    "18652": "ICICIPRULI",
    "19913": "DMART",
    "547": "BRITANNIA",
    "3063": "VEDL",
    "1348": "HEROMOTOCO",
    "10099": "GODREJCP",
    "2664": "PIDILITIND",
    "772": "DABUR",
    "23650": "MUTHOOTFIN",
    "17971": "SBICARD",
    "9819": "HAVELLS",
    "1964": "TRENT",
    "13751": "NAUKRI",
    "404": "BERGEPAINT",
    "14413": "PAGEIND",
    "4067": "MARICO",
    "4668": "BANKBARODA",
    "10666": "PNB",
    "10794": "CANBK",
    "1023": "FEDERALBNK",
    "18391": "RBLBANK",
    # ── IT / MIDCAP TECH ────────────────────────────────────────────────────────
    "17818": "LTM",
    "18365": "PERSISTENT",
    "4503": "MPHASIS",
    "11543": "COFORGE",
    "21690": "DIXON",
    # ── NEW-AGE / FINTECH ───────────────────────────────────────────────────────
    "14366": "ZOMATO",
    "6705": "PAYTM",
    "4244": "HDFCAMC",
    "6656": "POLICYBZR",
    "685": "CHOLAFIN",
    # ── PHARMA / SPECIALTY ──────────────────────────────────────────────────────
    "3518": "TORNTPHARM",
    "305": "BAJAJHLDNG",
    # ── POWER / DEFENCE / PSU ───────────────────────────────────────────────────
    # NOTE: tokens below may need updating from /market/instruments if HTTP 400
    "3563": "ADANIGREEN",
    "2303": "HAL",
    "438": "BHEL",
    # ── OIL & GAS ───────────────────────────────────────────────────────────────
    "526": "BPCL",
    # ── ADDITIONAL LIQUID MIDCAPS ───────────────────────────────────────────────
    "2181": "BOSCHLTD",
    "15141": "COLPAL",
    "18096": "JUBLFOOD",
    "10099": "GODREJCP", #   duplicate key safe — Python keeps last
    "5258": "INDUSINDBK", #   duplicate key safe
    "1512": "INDHOTEL",
    "10447": "UNITDSPR",
    "15332": "NMDC",
    "3150": "SIEMENS",
    "1406": "HINDPETRO",
    "15332": "NMDC", #   duplicate key safe
    "11262": "IGL",
    "15355": "RECLTD",
    "14299": "PFC",
# ── BANKING / FINANCE (NEW) ────────────────────────────────────────────────
    "11184": "IDFCFIRSTB",
    "21238": "AUBANK",
    "2263": "BANDHANBNK",
    "4306": "SHRIRAMFIN",
    # ── IT (NEW) ─────────────────────────────────────────────────────────────
    "10738": "OFSS",
    # ── POWER / UTILITIES (NEW) ─────────────────────────────────────────────
    "3426": "TATAPOWER",
    "17400": "NHPC",
    "18883": "SJVN",
    "17869": "JSWENERGY",
    # ── OIL & GAS (NEW) ──────────────────────────────────────────────────────
    "17438": "OIL",
    "1624": "IOC",
    "4717": "GAIL",
    "11351": "PETRONET",
    # ── AUTO / ANCILLARIES (NEW) ─────────────────────────────────────────────
    "212": "ASHOKLEY",
    "8479": "TVSMOTOR",
    "676": "EXIDEIND",
    "958": "ESCORTS",
    # ── INDUSTRIAL / CAPITAL GOODS (NEW) ────────────────────────────────────
    "13": "ABB",
    "383": "BEL",
    "2144": "BDL",
    "9590": "POLYCAB",
    "1901": "CUMMINSIND",
    "3475": "THERMAX",
    "13260": "KEC",
    "3186": "SKFINDIA",
    "3363": "SUPREMEIND",
    "13086": "AIAENG",
    "15313": "IRB",
    # ── CEMENT (NEW) ─────────────────────────────────────────────────────────
    "1270": "AMBUJACEM",
    "22": "ACC",
    "8075": "DALBHARAT",
    "13270": "JKCEMENT",
    "2043": "RAMCOCEM",
    # ── PAINTS / SPECIALTY MATERIALS (NEW) ──────────────────────────────────
    "1196": "KANSAINER",
    "14418": "ASTRAL",
    # ── ELECTRICALS / CABLES (NEW) ───────────────────────────────────────────
    "17094": "CROMPTON",
    "15362": "VGUARD",
    "1038": "FINCABLES",
    # ── CHEMICALS / FERTILISERS (NEW) ────────────────────────────────────────
    "19943": "DEEPAKNTR",
    "3273": "SRF",
    "24184": "PIIND",
    "11287": "UPL",
    "739": "COROMANDEL",
    "637": "CHAMBLFERT",
    "1174": "GNFC",
    "3405": "TATACHEM",
    # ── PHARMA / BIOTECH (NEW) ───────────────────────────────────────────────
    "10940": "DIVISLAB",
    "10440": "LUPIN",
    "275": "AUROPHARMA",
    "7929": "ZYDUSLIFE",
    "11703": "ALKEM",
    "1633": "IPCALAB",
    "8124": "AJANTPHARM",
    "14592": "FORTIS",
    "11373": "BIOCON",
    "7406": "GLENMARK",
    "19234": "LAURUSLABS",
    "17903": "ABBOTINDIA",
    # ── DIAGNOSTICS / HEALTHCARE (NEW) ──────────────────────────────────────
    "11654": "LALPATHLAB",
    "9581": "METROPOLIS",
    # ── METALS / MINING (NEW) ────────────────────────────────────────────────
    "6733": "JINDALSTEL",
    "2963": "SAIL",
    "6364": "NATIONALUM",
    "25780": "APLAPOLLO",
    "13451": "RATNAMANI",
    # ── LOGISTICS / RAILWAYS / INFRA (NEW) ──────────────────────────────────
    "4749": "CONCOR",
    "9599": "DELHIVERY",
    "495": "BLUEDART",
    "13611": "IRCTC",
    "2029": "IRFC",
    "13528": "GMRAIRPORT",
    "31415": "NBCC",
    # ── POWER / RENEWABLE ENERGY (NEW) ──────────────────────────────────────
    "760": "CGPOWER",
    "12018": "SUZLON",
    "29135": "INDUSTOWER",
    # ── TELECOM / TECH INFRA (NEW) ───────────────────────────────────────────
    "21951": "HFCL",
    "2431": "RAILTEL",
    # ── CAPITAL MARKETS / EXCHANGES (NEW) ───────────────────────────────────
    "19585": "BSE",
    "21174": "CDSL",
    "31181": "MCX",
    "220": "IEX",
    # ── INSURANCE / AMC / WEALTH (NEW) ──────────────────────────────────────
    "9480": "LICI",
    "342": "CAMS",
    "13061": "360ONE",
    "324": "ANGELONE",
    # ── CONSUMER / BEVERAGES (NEW) ───────────────────────────────────────────
    "16713": "UBL",
    "18921": "VBL",
    "10990": "RADICO",
    "10447": "UNITDSPR",
    # ── REAL ESTATE (NEW) ────────────────────────────────────────────────────
    "17875": "GODREJPROP",
    "20302": "PRESTIGE",
    "14552": "PHOENIXLTD",
    "20242": "OBEROIRLTY",
    "3220": "LODHA",
    "15184": "BRIGADE",
    # ── TECH / ELECTRONICS / SPECIALTY (NEW) ────────────────────────────────
    "9683": "KPITTECH",
    "2955": "KALYANKJIL",
    "12092": "KAYNES",
    "4684": "SONACOMS",
}

INSTRUMENTS      = [f"NSE:{stock_token}" for stock_token in STOCK_UNIVERSE]
STOCK_NAMES      = STOCK_UNIVERSE
INSTRUMENTS_URL  = "https://api.indstocks.com/market/instruments"

# ── Index instruments (subscribed alongside equities) ─────────────────────────
# WS format: NIDX:40000001 = NIFTY 50,  NIDX:40000003 = BANK NIFTY  (verified live)
# Old IDs 26000 / 26009 were wrong — server silently ignored subscriptions with them.
# REST historical scrip-code: NIDX_40000001 / NIDX_40000003  (SEGMENT_TOKEN, underscore)
INDEX_INSTRUMENTS = {
    "NIDX:40000001": "NIFTY 50",    # confirmed working
    "NIDX:40000003": "BANK NIFTY",  # confirmed working
}
INDEX_TOKENS = list(INDEX_INSTRUMENTS.keys())
# Bare numeric tokens — server responds with "40000001" not "NIDX:40000001"
INDEX_BARE_TOKENS = {k.split(":")[1]: v for k, v in INDEX_INSTRUMENTS.items()}
# REST scrip-codes: replace colon with underscore (NIDX_40000001 pattern)
INDEX_REST_SCRIPS = {k.replace(":", "_"): v for k, v in INDEX_INSTRUMENTS.items()}


def refresh_instrument_tokens(access_token: str) -> dict[str, str]:
    """Fetch INDstocks equity instrument master and rebuild STOCK_UNIVERSE
    using the correct SECURITY_IDs for the symbols we care about.

    Returns an updated {security_id: symbol} dict.  Falls back to the
    hard-coded universe if the API call fails.
    """
    target_symbols = set(STOCK_UNIVERSE.values())
    try:
        resp = requests.get(
            INSTRUMENTS_URL,
            params={"source": "equity"},
            headers=auth_headers(access_token),
            timeout=15,
        )
        resp.raise_for_status()
        # Response is a raw CSV; parse with csv module
        import csv, io
        reader = csv.DictReader(io.StringIO(resp.text))
        updated: dict[str, str] = {}
        for row in reader:
            exch   = row.get("EXCH", "").strip().upper()
            seg    = row.get("SEGMENT", "").strip().upper()
            sym    = row.get("TRADING_SYMBOL", row.get("SYMBOL_NAME", "")).strip().upper()
            sec_id = row.get("SECURITY_ID", "").strip()
            series = row.get("SERIES", "").strip().upper()
            if exch == "NSE" and seg == "E" and series == "EQ" and sym in target_symbols and sec_id:
                updated[sec_id] = sym
        if len(updated) >= 20:          # sanity check — at least 20 symbols resolved
            # Safe merge: update security IDs for matching symbols in-place to prevent duplication
            merged = {}
            # Map symbol -> new security_id resolved from the CSV master
            resolved_sym_to_id = {sym: sec_id for sec_id, sym in updated.items()}
            
            # Build the merged universe using hardcoded items, updating security IDs if resolved
            for old_sec_id, sym in STOCK_UNIVERSE.items():
                if sym in resolved_sym_to_id:
                    merged[resolved_sym_to_id[sym]] = sym
                else:
                    merged[old_sec_id] = sym
            return merged
    except Exception:
        pass
    return {}   # caller falls back to hard-coded STOCK_UNIVERSE


QUOTE_ALIASES = {
    # Primary fields (used by extract_float / extract_int)
    "open":        ("day_open",  "open",  "o", "open_price"),
    "high":        ("day_high",  "high",  "h"),
    "low":         ("day_low",   "low",   "l"),
    # "close" alias tries ltp first — this is the live traded price per INDmoney docs
    "close":       ("ltp", "live_price", "close", "c", "last_price", "last_traded_price"),
    "prev_close":  ("prev_close", "close", "previous_close", "prev_day_close"),
    "volume":      ("volume",    "vol",   "v", "day_volume"),
    "change":      ("day_change",     "change",     "net_change"),
    "change_pct":  ("day_change_percentage", "change_percentage", "pct_change"),
}


@dataclass
class FeedState:
    market_data:  dict[str, dict[str, Any]] = field(default_factory=dict)
    index_data:   dict[str, dict[str, Any]] = field(default_factory=dict)  # NIFTY / BANKNIFTY
    status: str = "Idle"
    last_update: float | None = None
    last_error: str | None = None
    reconnects: int = 0
    started: bool = False
    token_fingerprint: str = ""
    thread: threading.Thread | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    # Snapshot of instruments to subscribe — captured at feed-start time so
    # the background thread never touches st.session_state (not thread-safe).
    instruments_snapshot: list[str] = field(default_factory=list)
    last_raw_message: str = ""


@st.cache_resource
def get_feed_state() -> FeedState:
    return FeedState()


def token_fingerprint(access_token: str) -> str:
    access_token = access_token.strip()
    if not access_token:
        return ""
    return f"{len(access_token)}:{access_token[-6:]}"


def clean_token(access_token: str) -> str:
    return access_token.strip()


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": clean_token(access_token)}


def get_telegram_config() -> tuple[str, str, bool]:
    """Retrieve Telegram configuration. Prioritizes st.secrets (cloud) then database (local)."""
    # 1. Streamlit Secrets (ideal for Cloud)
    try:
        if "TELEGRAM_BOT_TOKEN" in st.secrets and "TELEGRAM_CHAT_ID" in st.secrets:
            return (
                st.secrets["TELEGRAM_BOT_TOKEN"],
                st.secrets["TELEGRAM_CHAT_ID"],
                st.secrets.get("TELEGRAM_NOTIFICATIONS_ENABLED", True)
            )
    except Exception:
        pass

    # 2. Database fallback (ideal for Local / Laptop)
    try:
        from database import get_db_settings
        token = get_db_settings("telegram_bot_token", "")
        chat_id = get_db_settings("telegram_chat_id", "")
        enabled = get_db_settings("telegram_notifications_enabled", False)
        return token, chat_id, enabled
    except Exception:
        pass

    return "", "", False


def send_telegram_picks_message(
    intraday_pick: dict | None,
    option_pick: dict | None,
    nifty_pick: dict | None,
    swing_pick: dict | None,
    total_cap: float,
    intra_pct: float,
    opt_pct: float,
    swing_pct: float,
    intra_lev: int,
    max_trades: int,
) -> bool:
    """Format and send the Command Center Alpha Picks of the Day to Telegram Bot API."""
    token, chat_id, enabled = get_telegram_config()
    if not token or not chat_id:
        st.error("Telegram is not configured. Add Bot Token and Chat ID to Streamlit Secrets or Settings.")
        return False

    now_ist = datetime.now(_IST_TZ)
    date_str = now_ist.strftime("%a, %d %b %Y")

    msg = f"🎯 <b>Fin+ Workstation — Alpha Picks of the Day</b>\n"
    msg += f"📅 <i>Date: {date_str} (IST)</i>\n\n"

    # 1. INTRADAY
    if intraday_pick:
        _stk = intraday_pick["Stock"]
        _ltp = float(intraday_pick["LTP"])
        _sig = intraday_pick["Signal"]
        _chg = float(intraday_pick["Change %"])
        _is_long = _sig in ("LONG", "BREAKOUT")
        _sl_dist = _ltp * 0.015
        _sl = _ltp - _sl_dist if _is_long else _ltp + _sl_dist
        _tgt = _ltp + (_sl_dist * 2.0) if _is_long else _ltp - (_sl_dist * 2.0)
        
        allocated_cap = total_cap * (intra_pct / 100.0)
        cap_per_trade = allocated_cap / max_trades
        buying_power = cap_per_trade * intra_lev
        _qty = int(buying_power / _ltp) if _ltp > 0 else 0
        _trade_val = _qty * _ltp
        _max_risk = _qty * _sl_dist
        
        direction = "BUY (Long)" if _is_long else "SELL (Short)"
        msg += f"⚡ <b>INTRADAY SNIPER PLAY</b>\n"
        msg += f"Stock: <b>{_stk}</b> (Signal: {_sig})\n"
        msg += f"• Entry Limit: ₹{_ltp:.2f} ({_chg:+.2f}%)\n"
        msg += f"• Stop Loss: ₹{_sl:.2f} (1.5%)\n"
        msg += f"• Target Net: ₹{_tgt:.2f} (3.0%)\n"
        msg += f"👉 <b>ACTION:</b> {direction} EXACTLY <b>{_qty}</b> SHARES\n"
        msg += f"💰 Margin: ₹{cap_per_trade:.2f} (BP: ₹{_trade_val:.2f})\n"
        msg += f"⚠️ Max Risk: ₹{_max_risk:.2f} ({_max_risk/total_cap*100:.2f}% of Cap)\n\n"
    else:
        msg += f"⚡ <b>INTRADAY SNIPER PLAY</b>\n"
        msg += f"<i>No intraday breakout setup active at present.</i>\n\n"

    # 2. OPTION
    if option_pick:
        _stk = option_pick["Stock"]
        _ltp = float(option_pick["LTP"])
        _sig = option_pick["Signal"]
        _is_long = _sig in ("LONG", "BREAKOUT")
        
        FO_LOT_SIZES_LOCAL = {
            "RELIANCE": 250, "TCS": 175, "INFY": 400, "TATASTEEL": 5500, "SBIN": 1500,
            "BHARTIARTL": 950, "ICICIBANK": 700, "HDFCBANK": 550, "AXISBANK": 625, "ITC": 1600,
            "LT": 300, "HINDUNILVR": 300, "M&M": 350, "SUNPHARMA": 700, "MARUTI": 50,
            "ONGC": 3850, "JSWSTEEL": 675, "ADANIENT": 300, "COALINDIA": 4200, "NTPC": 1500,
            "POWERGRID": 3600, "KOTAKBANK": 400
        }
        
        def calculate_atm_strike_local(stock: str, price: float) -> int:
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
            
        _strike = calculate_atm_strike_local(_stk, _ltp)
        _option_type = "CE" if _is_long else "PE"
        _contract = f"{_stk} {_strike} {_option_type}"
        
        allocated_opt_cap = total_cap * (opt_pct / 100.0)
        lot_size = FO_LOT_SIZES_LOCAL.get(_stk, 100)
        est_premium = _ltp * 0.03
        cost_per_lot = lot_size * est_premium
        max_trade_exposure = allocated_opt_cap * 0.20
        _lots = int(max_trade_exposure / cost_per_lot) if cost_per_lot > 0 else 0
        if _lots == 0:
            _lots = 1
        _total_premium_val = _lots * lot_size * est_premium
        _max_risk = _total_premium_val * 0.35
        
        msg += f"📦 <b>STOCK OPTION SNIPER</b>\n"
        msg += f"Contract: <b>{_contract}</b> (ATM Option)\n"
        msg += f"• Under. LTP: ₹{_ltp:.2f} (Est Prem: ₹{est_premium:.2f})\n"
        msg += f"• Stop Loss: Premium -35%\n"
        msg += f"• Target Net: Premium +70%\n"
        msg += f"👉 <b>ACTION:</b> BUY <b>{_lots}</b> LOTS ({_lots * lot_size} shares)\n"
        msg += f"💰 Premium Margin: ₹{_total_premium_val:.2f}\n"
        msg += f"⚠️ Max Risk: ₹{_max_risk:.2f} ({_max_risk/total_cap*100:.2f}% of Cap)\n\n"
    else:
        msg += f"📦 <b>STOCK OPTION SNIPER</b>\n"
        msg += f"<i>Waiting for highly liquid F&O signals...</i>\n\n"

    # 2.5 NIFTY INDEX OPTIONS
    if nifty_pick and nifty_pick.get("signal") != "NEUTRAL / NO TRADE":
        _contract = nifty_pick["contract"]
        _entry = nifty_pick["entry_price"]
        _tgt = nifty_pick["target"]
        _sl = nifty_pick["stop_loss"]
        _sig = nifty_pick["signal"]
        _ltp = nifty_pick["nifty_ltp"]
        _pcr = nifty_pick["pcr"]
        _sup = nifty_pick["support"]
        _res = nifty_pick["resistance"]
        
        allocated_opt_cap = total_cap * (opt_pct / 100.0)
        cost_per_lot = 65 * _entry
        max_trade_exposure = allocated_opt_cap * 0.20
        _lots = int(max_trade_exposure / cost_per_lot) if cost_per_lot > 0 else 0
        if _lots == 0:
            _lots = 1
        _total_premium_val = _lots * 65 * _entry
        _max_risk = _total_premium_val * 0.30
        
        msg += f"📦 <b>NIFTY INDEX OPTION SNIPER</b>\n"
        msg += f"Contract: <b>{_contract}</b> (Signal: {_sig})\n"
        msg += f"• Spot LTP: ₹{_ltp:,.2f} (Entry: ₹{_entry:.2f})\n"
        msg += f"• Stop Loss: ₹{_sl:.2f}\n"
        msg += f"• Target Net: ₹{_tgt:.2f}\n"
        msg += f"👉 <b>ACTION:</b> BUY <b>{_lots}</b> LOTS ({_lots * 65} shares)\n"
        msg += f"💰 Premium Margin: ₹{_total_premium_val:.2f}\n"
        msg += f"📊 PCR: {_pcr:.2f} | S: {_sup} R: {_res}\n"
        msg += f"⚠️ Max Risk: ₹{_max_risk:.2f} ({_max_risk/total_cap*100:.2f}% of Cap)\n\n"
    else:
        msg += f"📦 <b>NIFTY INDEX OPTION SNIPER</b>\n"
        msg += f"<i>No trade suggestion. Nifty option chain is neutral.</i>\n\n"

    # 3. SWING
    if swing_pick:
        _stk = swing_pick["Stock"]
        _company = swing_pick["Company"]
        _total = swing_pick["Total"]
        _funda = swing_pick["Funda"]
        _mntm = swing_pick["Mntm"]
        _ltp = swing_pick["LTP"]
        _sl = _ltp * 0.95
        _tgt = _ltp * 1.12
        allocated_swing_cap = total_cap * (swing_pct / 100.0)
        _swing_cap_per_trade = allocated_swing_cap / 2.0
        _qty = int(_swing_cap_per_trade / _ltp) if _ltp > 0 else 0
        _deployed = _qty * _ltp
        _max_risk = _qty * (_ltp - _sl)
        
        msg += f"📈 <b>SWING ALPHA PICK</b>\n"
        msg += f"Stock: <b>{_stk}</b> ({_company})\n"
        msg += f"• Entry Limit: ₹{_ltp:.2f} (Score: {_total}/100, F:{_funda} M:{_mntm})\n"
        msg += f"• Stop Loss: ₹{_sl:.2f} (5%)\n"
        msg += f"• Target Net: ₹{_tgt:.2f} (12%)\n"
        msg += f"👉 <b>ACTION:</b> BUY EXACTLY <b>{_qty}</b> SHARES\n"
        msg += f"💰 Capital Deployed: ₹{_deployed:.2f} (10% of Cap)\n"
        msg += f"⚠️ Max Risk: ₹{_max_risk:.2f} ({_max_risk/total_cap*100:.2f}% of Cap)\n\n"
    else:
        msg += f"📈 <b>SWING ALPHA PICK</b>\n"
        msg += f"<i>Connecting to Nifty Screener SQLite DB...</i>\n\n"

    msg += f"<i>🤖 Generated by Fin+ Cloud Workstation</i>"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=12.0)
        if resp.status_code != 200:
            try:
                err_desc = resp.json().get("description", resp.text)
            except Exception:
                err_desc = resp.text
            st.error(f"Telegram API Error: {err_desc}")
            return False
        return True
    except Exception as e:
        st.error(f"Failed to send Telegram message: {e}")
        return False


def trigger_telegram_picks_if_needed(
    intraday_pick: dict | None,
    option_pick: dict | None,
    nifty_pick: dict | None,
    swing_pick: dict | None,
    total_cap: float,
    intra_pct: float,
    opt_pct: float,
    swing_pct: float,
    intra_lev: int,
    max_trades: int,
) -> None:
    """Check once-per-day duplicate guard and send picks automatically if needed."""
    token, chat_id, enabled = get_telegram_config()
    if not enabled or not token or not chat_id:
        return

    if not intraday_pick and not option_pick and not nifty_pick and not swing_pick:
        return

    try:
        from database import get_db_settings, save_db_setting
        today_str = datetime.now(_IST_TZ).strftime("%Y-%m-%d")
        last_sent = get_db_settings("telegram_last_sent_date", "")

        if last_sent != today_str:
            success = send_telegram_picks_message(
                intraday_pick=intraday_pick,
                option_pick=option_pick,
                nifty_pick=nifty_pick,
                swing_pick=swing_pick,
                total_cap=total_cap,
                intra_pct=intra_pct,
                opt_pct=opt_pct,
                swing_pct=swing_pct,
                intra_lev=intra_lev,
                max_trades=max_trades,
            )
            if success:
                save_db_setting("telegram_last_sent_date", today_str)
                st.toast("📢 Alpha Picks automatically sent to Telegram!", icon="📨")
    except Exception:
        pass


def compact_error(error: str | None) -> str:
    if not error:
        return "Unknown error"
    if "ConnectTimeoutError" in error or "timed out" in error:
        return "Connection timed out"
    if "ReadTimeout" in error:
        return "Read timed out"
    if "Max retries exceeded" in error:
        return "Connection retries exceeded"
    if len(error) > 140:
        return f"{error[:137]}..."
    return error


def get_screener_scores(stock_name: str) -> str:
    """Query the local nifty500_scanner.db SQLite cache to get fundamental & momentum scores for a stock."""
    import sqlite3
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Finance", "nifty_scanner", "nifty500_scanner.db")
    if not os.path.exists(db_path):
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nifty_scanner", "nifty500_scanner.db")
    if not os.path.exists(db_path):
        return "\u2014"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT fundamental_score, momentum_score, total_score FROM nifty500_cache WHERE ticker = ? OR ticker = ? LIMIT 1",
            (stock_name, f"{stock_name}.NS")
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            f_score, m_score, t_score = row
            return f"{int(f_score)}/{int(m_score)} ({int(t_score)})"
    except Exception:
        pass
    return "\u2014"


def extract_float(payload: dict[str, Any], field: str, default: float = 0.0) -> float:
    for key in QUOTE_ALIASES[field]:
        value = payload.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return default


def extract_int(payload: dict[str, Any], field: str, default: int = 0) -> int:
    value = extract_float(payload, field, float(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_quote(raw_quote: dict[str, Any]) -> dict[str, float | int]:
    """Parse a raw WS/REST quote dict into normalised fields.

    QUOTE_ALIASES["close"] resolves: ltp → live_price → close → last_price …
    So extract_float(raw_quote, "close") always returns the live traded price
    (LTP) first, which is correct per INDmoney WebSocket docs.
    """
    ltp    = extract_float(raw_quote, "close")    # ltp → live_price → close (alias order)
    open_p = extract_float(raw_quote, "open")
    high_p = extract_float(raw_quote, "high")
    low_p  = extract_float(raw_quote, "low")
    volume = extract_int(raw_quote,   "volume")
    # prev_close = previous session close (not the live price)
    prev_c = extract_float(raw_quote, "prev_close")   # alias: prev_close → close → …
    return {
        "open":       open_p,
        "high":       high_p,
        "low":        low_p,
        "close":      ltp,      # 'close' in our app = current LTP
        "prev_close": prev_c,
        "volume":     volume,
    }



def empty_history() -> dict[str, dict[str, float]]:
    return {}


if "historical_data" not in st.session_state:
    st.session_state.historical_data = empty_history()

if "history_loaded" not in st.session_state:
    st.session_state.history_loaded = False

if "history_errors" not in st.session_state:
    st.session_state.history_errors = []

if "history_loaded_at" not in st.session_state:
    st.session_state.history_loaded_at = None

# ── Auto-history refresh tracking ──────────────────────────────────────────
if "auto_history_last_load" not in st.session_state:
    st.session_state.auto_history_last_load = None   # time.time() of last auto load
if "auto_history_preopen_done" not in st.session_state:
    st.session_state.auto_history_preopen_done = False  # reset each calendar day
if "auto_history_preopen_date" not in st.session_state:
    st.session_state.auto_history_preopen_date = None   # date when pre-open fired

if "history_attempted" not in st.session_state:
    st.session_state.history_attempted = False

if "history_status" not in st.session_state:
    st.session_state.history_status = "Not attempted"

if "history_started_at" not in st.session_state:
    st.session_state.history_started_at = None

if "history_debug" not in st.session_state:
    st.session_state.history_debug = None

if st.session_state.history_status == "Loading" and not st.session_state.history_started_at:
    st.session_state.history_status = "Failed"
    st.session_state.history_errors = ["Historical load was interrupted. Please run Load Historical again."]

import os

TOKEN_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Finance", ".token.txt")

def load_cached_token() -> str:
    try:
        if os.path.exists(TOKEN_CACHE_FILE):
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    try:
        alt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token.txt")
        if os.path.exists(alt_path):
            with open(alt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""

def save_cached_token(token: str) -> None:
    try:
        for p in (TOKEN_CACHE_FILE, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token.txt")):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(token.strip())
    except Exception:
        pass

def delete_cached_token() -> None:
    try:
        for p in (TOKEN_CACHE_FILE, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token.txt")):
            if os.path.exists(p):
                os.remove(p)
    except Exception:
        pass

def is_token_expired() -> bool:
    try:
        target_path = TOKEN_CACHE_FILE
        if not os.path.exists(target_path):
            target_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token.txt")
        if os.path.exists(target_path):
            import datetime
            mtime = os.path.getmtime(target_path)
            file_time = datetime.datetime.fromtimestamp(mtime)
            now = datetime.datetime.now()
            
            # Daily reset boundary is 7:00 AM
            boundary = now.replace(hour=7, minute=0, second=0, microsecond=0)
            
            if now >= boundary and file_time < boundary:
                return True
            if (now - file_time).total_seconds() > 24 * 3600:
                return True
    except Exception:
        pass
    return False

# Initialize session state for tokens using cache on startup
_cached_token = load_cached_token()
_expired = is_token_expired()

if "accepted_token" not in st.session_state:
    st.session_state.accepted_token = _cached_token

if "token_accepted" not in st.session_state:
    st.session_state.token_accepted = bool(_cached_token) and not _expired

# ── Signal log — persists across refreshes, max 50 entries ────────────────
if "signal_log" not in st.session_state:
    st.session_state.signal_log: list[dict] = []
if "signal_log_seen" not in st.session_state:
    st.session_state.signal_log_seen: set[str] = set()  # "STOCK:SIGNAL" keys

# ── Index token verification state ──────────────────────────────────────────
if "index_tokens_verified" not in st.session_state:
    st.session_state.index_tokens_verified = False

# ── Instrument universe (may be refreshed from API after token accepted) ──
if "live_universe" not in st.session_state:
    st.session_state.live_universe = {}   # empty = use hard-coded STOCK_UNIVERSE


def effective_universe() -> dict[str, str]:
    """Return the live universe if available, else the hard-coded one."""
    return st.session_state.live_universe if st.session_state.live_universe else STOCK_UNIVERSE


def effective_instruments() -> list[str]:
    return [f"NSE:{t}" for t in effective_universe()]


def normalize_candles(candles: list[dict[str, Any]]) -> pd.DataFrame:
    if candles and isinstance(candles[0], (list, tuple)):
        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
    else:
        df = pd.DataFrame(candles)

    if df.empty:
        return df

    df = df.rename(
        columns={
            "ts": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        }
    )

    required_columns = ["open", "high", "low", "close", "volume"]
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(f"Missing candle fields: {', '.join(missing)}")

    for column in required_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=required_columns)
    df = df[df["volume"] > 0]
    return df


def calculate_historical_metrics(
    candles: list[dict[str, Any]],
    daily_vol_data: dict[str, float] | None = None,
) -> tuple[dict[str, float | str] | None, str | None]:
    """Compute intraday metrics from 1-min candles.

    daily_vol_data: result of fetch_daily_volumes() — when provided its
    avg_vol_20d / avg_vol_5d replace the 1-min aggregation so RVOL and
    Vol Premium are based on a proper 20-trading-day baseline.
    """
    try:
        df = normalize_candles(candles)
        if df.empty:
            return None, "No usable candles returned"

        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cumulative_volume = df["volume"].cumsum()
        # Full cumulative VWAP across all candles (used as fallback)
        df["vwap_full"] = (typical_price * df["volume"]).cumsum() / cumulative_volume
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

        # ── Timestamps → dates ──────────────────────────────────────────────────
        ts_sample = float(df["timestamp"].iloc[0])
        ts_unit   = "s" if ts_sample < 1_000_000_000_000 else "ms"
        df["date"] = pd.to_datetime(df["timestamp"], unit=ts_unit).dt.date
        df["avg_volume_20"] = 0.0  # placeholder; filled below

        daily_volume = df.groupby("date")["volume"].sum()
        today_date   = daily_volume.index[-1] if not daily_volume.empty else None
        today_df     = df[df["date"] == today_date].copy() if today_date is not None else pd.DataFrame()

        # ── ORB: always from today's first 15 candles ──────────────────────────
        # During a live session today_df has the current day's candles.
        # When market is closed today_df is the last trading day's candles.
        # Either way ORB correctly reflects the current/most-recent session open range.
        if not today_df.empty:
            orb_df = today_df.head(15)
        else:
            orb_df = df.head(15)   # fallback — should not happen

        # ── VWAP: recalculate from today's candles only ─────────────────────────
        # VWAP must reset at 9:15 each day. Cumulating across multiple days
        # makes it drift and meaningless by afternoon.
        if not today_df.empty:
            tp_today  = (today_df["high"] + today_df["low"] + today_df["close"]) / 3
            cv_today  = today_df["volume"].cumsum()
            today_df["vwap"] = (tp_today * today_df["volume"]).cumsum() / cv_today
            latest_vwap = float(today_df["vwap"].iloc[-1])
        else:
            latest_vwap = float(df["vwap_full"].iloc[-1])

        latest = df.iloc[-1]

        latest_day_volume_1min = int(daily_volume.iloc[-1]) if not daily_volume.empty else 0

        # ── Volume averages ────────────────────────────────────────────────────────
        if daily_vol_data and daily_vol_data.get("avg_vol_20d", 0) > 0:
            avg_volume_20      = float(daily_vol_data["avg_vol_20d"])
            avg_daily_volume_5 = float(daily_vol_data["avg_vol_5d"])
            latest_day_volume  = int(daily_vol_data.get("latest_day_volume", latest_day_volume_1min))
            _last_data_date    = daily_vol_data.get("last_data_date", "")
        else:
            # Fallback: 1-min candle aggregation — max ~4 prior trading days available
            # (API returns ≤5 days; we exclude today leaving ≤4). avg_volume_20 may
            # therefore be a 4-day average, not a full 20-day average.
            # Primary path (fetch_daily_volumes) uses proper 20-day daily data.
            prior_days         = daily_volume.iloc[:-1] if len(daily_volume) > 1 else daily_volume
            avg_volume_20      = float(prior_days.tail(20).mean()) if not prior_days.empty else 0.0
            avg_daily_volume_5 = float(prior_days.tail(5).mean())  if not prior_days.empty else 0.0
            latest_day_volume  = latest_day_volume_1min
            all_dates_fb       = sorted(df["date"].unique())
            _last_data_date    = str(all_dates_fb[-1]) if all_dates_fb else ""

        df["avg_volume_20"] = avg_volume_20

        today_candles = (
            today_df[["timestamp", "open", "high", "low", "close", "volume"]]
            .to_dict(orient="records")
            if not today_df.empty else []
        )

        day_rvol = round(latest_day_volume / avg_volume_20, 2) if avg_volume_20 > 0 else 0.0

        # Extract previous day values from daily_vol_data or fallback to 1-min candles
        all_dates = sorted(df["date"].unique())
        if daily_vol_data and daily_vol_data.get("prev_day_high", 0.0) > 0.0:
            prev_day_high  = float(daily_vol_data["prev_day_high"])
            prev_day_low   = float(daily_vol_data["prev_day_low"])
            prev_day_close = float(daily_vol_data["prev_day_close"])
            prev_day_open  = float(daily_vol_data["prev_day_open"])
        else:
            if len(all_dates) >= 2:
                prev_date = all_dates[-2]
                prev_df = df[df["date"] == prev_date]
                prev_day_high  = float(prev_df["high"].max())
                prev_day_low   = float(prev_df["low"].min())
                prev_day_close = float(prev_df["close"].iloc[-1])
                prev_day_open  = float(prev_df["open"].iloc[0])
            else:
                prev_day_high  = float(df["high"].max()) if not df.empty else 0.0
                prev_day_low   = float(df["low"].min()) if not df.empty else 0.0
                prev_day_close = float(df["close"].iloc[-1]) if not df.empty else 0.0
                prev_day_open  = float(df["open"].iloc[0]) if not df.empty else 0.0

        if len(all_dates) >= 2:
            prev_date      = all_dates[-2]
            prev_day_close_val = float(df[df["date"] == prev_date]["close"].iloc[-1])
            last_day_close = float(df[df["date"] == all_dates[-1]]["close"].iloc[-1])
            day_change_pct = round(((last_day_close - prev_day_close_val) / prev_day_close_val) * 100, 2) if prev_day_close_val else 0.0
        else:
            prev_day_close_val = prev_day_open
            last_day_close = float(latest["close"])
            day_change_pct = round(((last_day_close - prev_day_close_val) / prev_day_close_val) * 100, 2) if prev_day_close_val else 0.0

        return {
            "vwap":               round(latest_vwap, 2),          # today-only VWAP
            "ema20":              round(float(latest["ema20"]), 2),
            "rvol":               day_rvol,
            "avg_volume_20":      round(avg_volume_20, 2),
            "avg_daily_volume_5": round(avg_daily_volume_5, 2),
            "latest_day_volume":  latest_day_volume,
            "prev_day_close":     round(prev_day_close, 2),
            "prev_day_high":      round(prev_day_high, 2),
            "prev_day_low":       round(prev_day_low, 2),
            "prev_day_open":      round(prev_day_open, 2),
            "day_change_pct":     day_change_pct,
            "last_data_date":     _last_data_date,
            "orb_high":           round(float(orb_df["high"].max()), 2),  # today's ORB
            "orb_low":            round(float(orb_df["low"].min()), 2),   # today's ORB
            "last_open":          round(float(latest["open"]), 2),
            "last_high":          round(float(latest["high"]), 2),
            "last_low":           round(float(latest["low"]), 2),
            "last_close":         round(float(latest["close"]), 2),
            "last_volume":        int(latest["volume"]),
            "today_candles":      today_candles,
            "source":             "Historical API",
        }, None

    except Exception as exc:
        return None, str(exc)


def store_historical_metrics(stock_token: str, candles: list[dict[str, Any]], daily_vol_data: dict | None = None) -> tuple[bool, str | None]:
    metrics, error = calculate_historical_metrics(candles, daily_vol_data)
    if not metrics:
        return False, error
    st.session_state.historical_data[stock_token] = metrics
    return True, None


def extract_candles(data: dict[str, Any], stock_token: str) -> list[dict[str, Any]]:
    symbol = f"NSE_{stock_token}"
    payload = data.get("data", {})

    if isinstance(payload, dict):
        if isinstance(payload.get("candles"), list):
            return payload["candles"]
        for key in (symbol, stock_token, f"NSE:{stock_token}"):
            value = payload.get(key)
            if isinstance(value, dict) and isinstance(value.get("candles"), list):
                return value["candles"]
            if isinstance(value, list):
                return value

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_symbol = str(
                item.get("scrip_code")
                or item.get("scripCode")
                or item.get("symbol")
                or item.get("instrument")
                or ""
            )
            if stock_token in item_symbol and isinstance(item.get("candles"), list):
                return item["candles"]

    return []


def historical_params(stock_tokens: list[str], lookback_days: int) -> dict[str, int | str]:
    end_time = int(time.time() * 1000)
    start_time = end_time - (lookback_days * 24 * 60 * 60 * 1000)
    return {
        "scrip-codes": ",".join(f"NSE_{stock_token}" for stock_token in stock_tokens),
        "start_time": start_time,
        "end_time": end_time,
    }



DAILY_VOLUMES_CACHE = {}
DAILY_VOLUMES_CACHE_LOCK = threading.Lock()

def fetch_daily_volumes(stock_token: str, access_token: str) -> dict[str, float]:
    """Fetch daily OHLCV candles and return 20-day & 5-day avg daily volumes.

    The /1day endpoint returns columns: ts, o, h, l, c, v
    Returns {} on failure so caller falls back to 1-min aggregation.
    """
    with DAILY_VOLUMES_CACHE_LOCK:
        if stock_token in DAILY_VOLUMES_CACHE:
            return DAILY_VOLUMES_CACHE[stock_token]

    try:
        end_time   = int(time.time() * 1000)
        start_time = end_time - (HISTORY_DAILY_LOOKBACK_DAYS * 24 * 60 * 60 * 1000)
        params = {
            "scrip-codes": f"NSE_{stock_token}",
            "start_time":  start_time,
            "end_time":    end_time,
        }
        resp = requests.get(
            HISTORICAL_DAILY_URL,
            params=params,
            headers=auth_headers(access_token),
            timeout=HISTORICAL_TIMEOUT,
        )
        resp.raise_for_status()
        data    = resp.json()
        payload = data.get("data", {})
        scrip   = f"NSE_{stock_token}"

        candles_d = []
        if isinstance(payload, dict):
            if isinstance(payload.get("candles"), list):
                candles_d = payload["candles"]
            else:
                for key in (scrip, stock_token, f"NSE:{stock_token}"):
                    value = payload.get(key)
                    if isinstance(value, dict) and isinstance(value.get("candles"), list):
                        candles_d = value["candles"]
                        break
                    if isinstance(value, list):
                        candles_d = value
                        break

        if not candles_d or not isinstance(candles_d, list):
            return {}

        # Per docs: candles are arrays [timestamp, open, high, low, close, volume]
        if not candles_d or not isinstance(candles_d[0], (list, tuple, dict)):
            return {}
            
        # Support both list of lists and list of dicts format
        if isinstance(candles_d[0], dict):
            df = pd.DataFrame(candles_d)
            df = df.rename(
                columns={
                    "ts": "timestamp",
                    "o": "open",
                    "h": "high",
                    "l": "low",
                    "c": "close",
                    "v": "volume",
                }
            )
        else:
            df = pd.DataFrame(candles_d, columns=["timestamp", "open", "high", "low", "close", "volume"])
        if "volume" not in df.columns or "timestamp" not in df.columns:
            return {}

        df["volume"]    = pd.to_numeric(df["volume"],    errors="coerce").fillna(0)
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").fillna(0)

        # Detect timestamp unit: seconds (10-digit) vs milliseconds (13-digit)
        ts_sample = float(df["timestamp"].iloc[0])
        ts_unit   = "s" if ts_sample < 1_000_000_000_000 else "ms"
        df["date"] = pd.to_datetime(df["timestamp"], unit=ts_unit).dt.date

        # Sort by date ascending
        df = df.sort_values("date").reset_index(drop=True)

        # Exclude the last (potentially incomplete) trading day
        prior = df.iloc[:-1] if len(df) > 1 else df

        avg_vol_20d = float(prior.tail(20)["volume"].mean()) if not prior.empty else 0.0
        avg_vol_5d  = float(prior.tail(5)["volume"].mean())  if not prior.empty else 0.0
        latest_vol  = int(df.iloc[-1]["volume"])
        last_date   = str(df.iloc[-1]["date"])

        # Extract last completed trading day's OHLC values
        last_completed = prior.iloc[-1] if not prior.empty else df.iloc[-1]
        prev_high = float(last_completed["high"]) if "high" in last_completed else 0.0
        prev_low = float(last_completed["low"]) if "low" in last_completed else 0.0
        prev_close = float(last_completed["close"]) if "close" in last_completed else 0.0
        prev_open = float(last_completed["open"]) if "open" in last_completed else 0.0

        res = {
            "avg_vol_20d":       avg_vol_20d,
            "avg_vol_5d":        avg_vol_5d,
            "latest_day_volume": latest_vol,
            "last_data_date":    last_date,
            "prev_day_high":     prev_high,
            "prev_day_low":      prev_low,
            "prev_day_close":    prev_close,
            "prev_day_open":     prev_open,
        }
        with DAILY_VOLUMES_CACHE_LOCK:
            DAILY_VOLUMES_CACHE[stock_token] = res
        return res
    except Exception:
        return {}


def fetch_daily_volumes_batch(
    tokens: list[str],
    access_token: str,
) -> dict[str, dict[str, float]]:
    """Fetch daily volumes in batch for a list of stock tokens (up to 5) with retry and individual fallback.
    
    Uses DAILY_VOLUMES_CACHE to check if already fetched. If not, fetches
    in a single batched call and updates the cache.
    """
    results = {}
    tokens_to_fetch = []
    
    with DAILY_VOLUMES_CACHE_LOCK:
        for t in tokens:
            if t in DAILY_VOLUMES_CACHE:
                results[t] = DAILY_VOLUMES_CACHE[t]
            else:
                tokens_to_fetch.append(t)
                
    if not tokens_to_fetch:
        return results

    data_daily = None
    batch_success = False
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            end_time   = int(time.time() * 1000)
            start_time = end_time - (HISTORY_DAILY_LOOKBACK_DAYS * 24 * 60 * 60 * 1000)
            params = {
                "scrip-codes": ",".join(f"NSE_{t}" for t in tokens_to_fetch),
                "start_time":  start_time,
                "end_time":    end_time,
            }
            resp = requests.get(
                HISTORICAL_DAILY_URL,
                params=params,
                headers=auth_headers(access_token),
                timeout=7.0,
            )
            resp.raise_for_status()
            data_daily = resp.json()
            batch_success = True
            break
        except Exception:
            if attempt < max_attempts - 1:
                time.sleep(1.5 * (attempt + 1))

    for t in tokens_to_fetch:
        candles_d = []
        if batch_success and data_daily:
            candles_d = extract_candles(data_daily, t)
            
        # Fallback to individual fetch if batch failed or returned no candles for this stock
        if not candles_d or not isinstance(candles_d, list):
            for t_attempt in range(2):
                try:
                    time.sleep(0.2)
                    end_time   = int(time.time() * 1000)
                    start_time = end_time - (HISTORY_DAILY_LOOKBACK_DAYS * 24 * 60 * 60 * 1000)
                    resp_single = requests.get(
                        HISTORICAL_DAILY_URL,
                        params={
                            "scrip-codes": f"NSE_{t}",
                            "start_time":  start_time,
                            "end_time":    end_time,
                        },
                        headers=auth_headers(access_token),
                        timeout=5.0,
                    )
                    resp_single.raise_for_status()
                    data_single = resp_single.json()
                    candles_d = extract_candles(data_single, t)
                    if candles_d:
                        break
                except Exception:
                    if t_attempt < 1:
                        time.sleep(1.0)

        if not candles_d or not isinstance(candles_d, list):
            results[t] = {}
            continue

        try:
            # Per docs: candles are arrays [timestamp, open, high, low, close, volume]
            if not candles_d or not isinstance(candles_d[0], (list, tuple, dict)):
                results[t] = {}
                continue
                
            # Support both list of lists and list of dicts format
            if isinstance(candles_d[0], dict):
                df = pd.DataFrame(candles_d)
                df = df.rename(
                    columns={
                        "ts": "timestamp",
                        "o": "open",
                        "h": "high",
                        "l": "low",
                        "c": "close",
                        "v": "volume",
                    }
                )
            else:
                df = pd.DataFrame(candles_d, columns=["timestamp", "open", "high", "low", "close", "volume"])
            if "volume" not in df.columns or "timestamp" not in df.columns:
                results[t] = {}
                continue

            df["volume"]    = pd.to_numeric(df["volume"],    errors="coerce").fillna(0)
            df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").fillna(0)

            # Detect timestamp unit: seconds (10-digit) vs milliseconds (13-digit)
            ts_sample = float(df["timestamp"].iloc[0])
            ts_unit   = "s" if ts_sample < 1_000_000_000_000 else "ms"
            df["date"] = pd.to_datetime(df["timestamp"], unit=ts_unit).dt.date

            # Sort by date ascending
            df = df.sort_values("date").reset_index(drop=True)

            # Exclude the last (potentially incomplete) trading day
            prior = df.iloc[:-1] if len(df) > 1 else df

            avg_vol_20d = float(prior.tail(20)["volume"].mean()) if not prior.empty else 0.0
            avg_vol_5d  = float(prior.tail(5)["volume"].mean())  if not prior.empty else 0.0
            latest_vol  = int(df.iloc[-1]["volume"])
            last_date   = str(df.iloc[-1]["date"])

            # Extract last completed trading day's OHLC values
            last_completed = prior.iloc[-1] if not prior.empty else df.iloc[-1]
            prev_high = float(last_completed["high"]) if "high" in last_completed else 0.0
            prev_low = float(last_completed["low"]) if "low" in last_completed else 0.0
            prev_close = float(last_completed["close"]) if "close" in last_completed else 0.0
            prev_open = float(last_completed["open"]) if "open" in last_completed else 0.0

            res = {
                "avg_vol_20d":       avg_vol_20d,
                "avg_vol_5d":        avg_vol_5d,
                "latest_day_volume": latest_vol,
                "last_data_date":    last_date,
                "prev_day_high":     prev_high,
                "prev_day_low":      prev_low,
                "prev_day_close":    prev_close,
                "prev_day_open":     prev_open,
            }
            with DAILY_VOLUMES_CACHE_LOCK:
                DAILY_VOLUMES_CACHE[t] = res
            results[t] = res
        except Exception:
            results[t] = {}
            
    return results


def fetch_historical_metrics(
    stock_token: str,
    access_token: str,
) -> tuple[dict[str, float | str] | None, str | None]:
    """Fetch 1-min candles then daily candles for one stock (sequential) with auto-retries.

    Per INDmoney docs each stock is a separate API call — multi-stock requests
    return all candles mixed in one array with no per-stock key, so batching
    is not possible.  Sequential calls per stock with 8 parallel workers is
    the stable approach that avoids API rate-limiting.
    """
    last_err = "Unknown error"
    for attempt in range(3):
        try:
            # ── 1-min candles: VWAP / EMA20 / ORB ────────────────────────────────
            resp_1min = requests.get(
                HISTORICAL_URL,
                params=historical_params([stock_token], HISTORY_LOOKBACK_DAYS),
                headers=auth_headers(access_token),
                timeout=15,  # Increased timeout
            )
            resp_1min.raise_for_status()
            candles = extract_candles(resp_1min.json(), stock_token)

            # ── Daily candles: 20-day & 5-day volume averages ────────────────────
            daily_vol_data = fetch_daily_volumes(stock_token, access_token)

            metrics, error = calculate_historical_metrics(candles, daily_vol_data)
            if metrics:
                metrics["source"] = (
                    f"Historical API — intraday {HISTORY_LOOKBACK_DAYS}d + "
                    f"daily {HISTORY_DAILY_LOOKBACK_DAYS}d vol avg"
                    if daily_vol_data else
                    f"Historical API — intraday {HISTORY_LOOKBACK_DAYS}d (vol avg fallback)"
                )
                return metrics, None
            
            last_err = error or "Failed to calculate metrics"
        except requests.HTTPError as exc:
            last_err = f"HTTP {exc.response.status_code}"
            if exc.response.status_code in (400, 401, 403, 404):
                return None, last_err
        except Exception as exc:
            last_err = str(exc)

        # Wait a short duration before retrying (exponential backoff)
        if attempt < 2:
            time.sleep(0.5 + attempt * 0.5)

    return None, last_err


def fetch_historical(stock_token: str, access_token: str) -> tuple[bool, str | None]:
    metrics, error = fetch_historical_metrics(stock_token, access_token)
    if not metrics:
        return False, error
    st.session_state.historical_data[stock_token] = metrics
    return True, None





# ── Background historical-data refresh ──────────────────────────────────────
# Runs in a daemon thread so the live scanner never blocks.
# Uses a @st.cache_resource dict (shared across reruns) as the mailbox.

@st.cache_resource
def _get_bg_hist_state():
    """Shared mutable mailbox between the background thread and Streamlit."""
    return {"running": False, "result": None, "lock": threading.Lock()}


def _bg_hist_worker(access_token: str, workers: int, state: dict, universe: dict) -> None:
    """Thread target: load all historical data in batches without blocking Streamlit UI."""
    try:
        stock_toks  = list(universe.keys())
        loaded: dict[str, dict] = {}
        fails:  dict[str, str]  = {}

        batch_size = 5
        batches = [stock_toks[i:i + batch_size] for i in range(0, len(stock_toks), batch_size)]

        use_workers = 2
        with ThreadPoolExecutor(max_workers=use_workers) as ex:
            futs = {ex.submit(fetch_historical_metrics_batch, batch, access_token): batch
                    for batch in batches}
            for f in as_completed(futs):
                batch = futs[f]
                try:
                    batch_results = f.result()
                except Exception as exc:
                    batch_results = {t: (None, str(exc)) for t in batch}
                for tok, (metrics, err) in batch_results.items():
                    if metrics:
                        loaded[tok] = metrics
                    else:
                        fails[tok] = err or "Unknown"

        count = len(loaded)
        failure_list = [
            f"{universe.get(t, t)}: {compact_error(e)}"
            for t, e in fails.items() if t not in loaded
        ]
        with state["lock"]:
            state["result"] = {
                "data":      loaded,
                "count":     count,
                "total":     len(stock_toks),
                "failures":  failure_list,
                "loaded_at": time.time(),
            }
    except Exception as exc:
        with state["lock"]:
            state["result"] = {
                "data": {}, "count": 0, "total": 0,
                "failures": [f"BG loader failed: {exc}"],
                "loaded_at": time.time(),
            }
    finally:
        with state["lock"]:
            state["running"] = False


def trigger_bg_hist_refresh(access_token: str, workers: int) -> bool:
    """Start a background historical refresh if one is not already running.

    Returns True if a new thread was launched, False if already running.
    """
    state = _get_bg_hist_state()
    # Proactively resolve live instrument tokens if session state is empty to prevent race conditions
    if not st.session_state.get("live_universe"):
        live_univ = refresh_instrument_tokens(access_token)
        if live_univ:
            st.session_state.live_universe = live_univ
            
    # Capture snapshot of the universe on the main thread (safe)
    universe_snapshot = dict(effective_universe())
    with state["lock"]:
        if state["running"]:
            return False
        state["running"] = True
    t = threading.Thread(
        target=_bg_hist_worker,
        args=(access_token, workers, state, universe_snapshot),
        daemon=True,
    )
    t.start()
    return True


def apply_bg_hist_results() -> bool:
    """Apply pending background-refresh results to session_state.

    Call this at the top of any fragment that reads historical_data.
    Returns True if new data was applied.
    """
    state = _get_bg_hist_state()
    with state["lock"]:
        res = state["result"]
        if res is None:
            return False

    last_applied = st.session_state.get("_frag_last_applied_hist_time", 0.0)
    loaded_at = res.get("loaded_at") or 0.0
    if loaded_at <= last_applied and last_applied > 0.0:
        return False

    if res["count"] > 0:
        st.session_state.historical_data   = res["data"]
        st.session_state.history_loaded    = True
        st.session_state.history_loaded_at = res["loaded_at"]
        st.session_state.history_errors    = res["failures"]
        st.session_state.history_started_at = None
        st.session_state.history_status = f"{res['count']}/{res['total']} loaded"
        st.session_state.auto_history_last_load = time.time()
    else:
        # Background load failed! Do not destroy existing good historical data if we have it!
        if not st.session_state.get("history_loaded") or not st.session_state.historical_data:
            st.session_state.historical_data   = res["data"]
            st.session_state.history_loaded    = False
            st.session_state.history_loaded_at = None
            st.session_state.history_errors    = res["failures"]
            st.session_state.history_started_at = None
            st.session_state.history_status = "Failed"
        else:
            # We already have good data! Keep it, but update failures for diagnostics
            st.session_state.history_errors    = res["failures"]
            st.session_state.history_started_at = None
            st.session_state.history_status = "Auto-refresh failed"
        
        # Throttling fix: Update auto_history_last_load to prevent thread-spamming retry loop
        st.session_state.auto_history_last_load = time.time()

    st.session_state["_frag_last_applied_hist_time"] = loaded_at if loaded_at > 0.0 else last_applied
    return True

def fetch_historical_metrics_batch(
    batch_tokens: list[str],
    access_token: str,
) -> dict[str, tuple[dict[str, float | str] | None, str | None]]:
    """Fetch 1-min candles and daily volumes in batch (up to 5 stocks) with automatic retries and individual token fallback."""
    time.sleep(0.45)  # Spaced out for polite request density
    results = {}
    
    candles_by_token = {}
    last_err = "Unknown error"
    last_errs = {}
    
    batch_success = False
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            resp_1min = requests.get(
                HISTORICAL_URL,
                params=historical_params(batch_tokens, HISTORY_LOOKBACK_DAYS),
                headers=auth_headers(access_token),
                timeout=8.0,
            )
            resp_1min.raise_for_status()
            data_1min = resp_1min.json()
            
            any_extracted = False
            for t in batch_tokens:
                c = extract_candles(data_1min, t)
                if c:
                    candles_by_token[t] = c
                    any_extracted = True
            
            if any_extracted:
                batch_success = True
                break
            else:
                raise Exception("Empty batch data returned")
        except requests.HTTPError as exc:
            status_code = exc.response.status_code
            last_err = f"HTTP {status_code}"
            if status_code in (400, 401, 403, 404):
                break
        except Exception as exc:
            last_err = str(exc)
        
        if attempt < max_attempts - 1:
            time.sleep(1.5 * (attempt + 1))
            
    # Fallback to individual token fetching if the batch completely failed
    if not batch_success:
        for t in batch_tokens:
            token_success = False
            for t_attempt in range(2):
                try:
                    time.sleep(0.3)  # Polite spacing
                    resp_single = requests.get(
                        HISTORICAL_URL,
                        params=historical_params([t], HISTORY_LOOKBACK_DAYS),
                        headers=auth_headers(access_token),
                        timeout=6.0,
                    )
                    resp_single.raise_for_status()
                    data_single = resp_single.json()
                    c = extract_candles(data_single, t)
                    if c:
                        candles_by_token[t] = c
                        token_success = True
                        break
                    else:
                        raise Exception("No candles returned")
                except requests.HTTPError as exc:
                    last_errs[t] = f"HTTP {exc.response.status_code}"
                    if exc.response.status_code in (400, 401, 403, 404):
                        break
                except Exception as exc:
                    last_errs[t] = str(exc)
                if t_attempt < 1:
                    time.sleep(1.0)
            if not token_success and t not in last_errs:
                last_errs[t] = "Failed to load individual history"

    # ── Step 2: Batched Daily volumes ─────────────────────────────────────
    daily_vol_by_token = {}
    try:
        daily_vol_by_token = fetch_daily_volumes_batch(batch_tokens, access_token)
    except Exception:
        pass

    # ── Step 3: Process each stock in the batch ───────────────────────────
    for t in batch_tokens:
        candles_1min = candles_by_token.get(t)
        if not candles_1min:
            err_msg = last_errs.get(t, last_err)
            results[t] = (None, err_msg)
            continue
            
        daily_vol_data = daily_vol_by_token.get(t)
            
        metrics, error = calculate_historical_metrics(candles_1min, daily_vol_data)
        if metrics:
            metrics["source"] = (
                f"Historical API (Batched) — intraday {HISTORY_LOOKBACK_DAYS}d + "
                f"daily {HISTORY_DAILY_LOOKBACK_DAYS}d vol avg"
                if daily_vol_data else
                f"Historical API (Batched) — intraday {HISTORY_LOOKBACK_DAYS}d (vol avg fallback)"
            )
            results[t] = (metrics, None)
        else:
            results[t] = (None, error or "Failed to calculate metrics")
            
    return results

def load_historical_data(access_token: str, worker_count: int = HISTORICAL_WORKERS) -> tuple[int, list[str]]:
    # ── Step 0: refresh instrument tokens from API ──────────────────────────
    with st.spinner("Refreshing instrument master from INDstocks..."):
        live_universe = refresh_instrument_tokens(access_token)
        if live_universe:
            st.session_state.live_universe = live_universe
            st.caption(f"Instrument master refreshed: {len(live_universe)} symbols resolved.")
        else:
            # fall back to hard-coded universe
            st.caption("Using hard-coded instrument tokens (instrument master fetch failed).")

    st.session_state.history_attempted = True
    st.session_state.history_status = "Loading"
    st.session_state.history_started_at = time.time()
    universe = effective_universe()
    stock_tokens = list(universe.keys())
    loaded_history: dict[str, dict[str, float | str]] = {}
    failures_by_token: dict[str, str] = {}
    progress = st.progress(0, text="Loading historical data...")

    batch_size = 5
    batches = [stock_tokens[i:i + batch_size] for i in range(0, len(stock_tokens), batch_size)]

    try:
        # Use 3 parallel workers to respect INDmoney's concurrent query limit and prevent timeouts
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(fetch_historical_metrics_batch, batch, access_token): batch
                for batch in batches
            }

            completed_count = 0
            for future in as_completed(futures):
                batch = futures[future]
                try:
                    batch_results = future.result()
                except Exception as exc:
                    batch_results = {t: (None, str(exc)) for t in batch}

                for stock_token, (metrics, error) in batch_results.items():
                    completed_count += 1
                    stock_name = universe.get(stock_token, stock_token)
                    progress.progress(
                        completed_count / len(stock_tokens),
                        text=f"Loaded historical response for {stock_name}...",
                    )

                    if metrics:
                        loaded_history[stock_token] = metrics
                    else:
                        failures_by_token[stock_token] = error or "Unknown error"

        for stock_token in stock_tokens:
            if stock_token not in loaded_history and stock_token not in failures_by_token:
                failures_by_token[stock_token] = "No historical data returned"

        failures = [
            f"{universe.get(stock_token, stock_token)}: {compact_error(error)}"
            for stock_token, error in failures_by_token.items()
            if stock_token not in loaded_history
        ]

        success_count = len(loaded_history)
        st.session_state.historical_data = loaded_history
        st.session_state.history_loaded = success_count > 0
        st.session_state.history_errors = failures
        st.session_state.history_started_at = None
        if success_count:
            now_t = time.time()
            st.session_state.history_loaded_at = now_t
            st.session_state["_frag_last_applied_hist_time"] = now_t
            st.session_state.history_status = f"{success_count}/{len(stock_tokens)} loaded"
        else:
            st.session_state.history_loaded_at = None
            st.session_state.history_status = "Failed"

        progress.progress(1.0, text="Historical data load finished.")
        time.sleep(0.2)
        return success_count, failures

    except Exception as exc:
        st.session_state.historical_data = empty_history()
        st.session_state.history_loaded = False
        st.session_state.history_loaded_at = None
        st.session_state["_frag_last_applied_hist_time"] = 0.0
        st.session_state.history_errors = [f"Historical loader failed: {compact_error(str(exc))}"]
        st.session_state.history_status = "Failed"
        st.session_state.history_started_at = None
        return 0, st.session_state.history_errors

    finally:
        progress.empty()


def build_live_baseline(market_data: dict[str, dict[str, Any]]) -> int:
    st.session_state.historical_data = empty_history()

    for instrument, quote in market_data.items():
        parsed = parse_quote(quote)
        close = float(parsed["close"])
        high = float(parsed["high"]) or close
        low = float(parsed["low"]) or close
        volume = int(parsed["volume"])

        if close <= 0:
            continue

        st.session_state.historical_data[instrument] = {
            "vwap": round(close, 2),
            "ema20": round(close, 2),
            # RVOL cannot be computed from a single live quote with no history.
            # Set avg_volume_20=0 so calculate_signal falls back to hist["rvol"]=0
            # and the RVOL criterion is simply not met (score stays lower).
            # This is correct — a stock with no volume history should not be
            # artificially boosted by a fake RVOL of 1.0.
            "rvol": 0.0,
            "avg_volume_20": 0.0,
            "avg_daily_volume_5": float(volume) if volume else 0.0,
            "latest_day_volume": volume,
            "day_change_pct": 0.0,
            "last_data_date": "",
            "orb_high": round(high, 2),
            "orb_low": round(low, 2),
            "last_open": round(close, 2),
            "last_high": round(high, 2),
            "last_low": round(low, 2),
            "last_close": round(close, 2),
            "last_volume": volume,
            "source": "Live quote fallback",
        }

    count = len(st.session_state.historical_data)
    st.session_state.history_loaded = count > 0
    st.session_state.history_loaded_at = time.time() if count else None
    st.session_state.history_attempted = True
    st.session_state.history_errors = []
    st.session_state.history_status = "Live fallback" if count else "Fallback unavailable"
    return count


def calculate_signal(
    instrument: str,
    raw_quote: dict[str, Any],
    min_change: float,
    min_rvol: float,
    min_breakout_score: int,
    volume_premium_min: float,
    volume_premium_max: float,
) -> dict[str, Any] | None:
    quote = parse_quote(raw_quote)
    open_price = float(quote["open"])
    close = float(quote["close"])
    volume = int(quote["volume"])

    if open_price <= 0 or close <= 0:
        return None

    hist = st.session_state.historical_data.get(instrument)
    if not hist:
        return None

    change_pct = round(((close - open_price) / open_price) * 100, 2)

    # ── Change % correction for closed market ──────────────────────────────────
    # When market is closed, open_price and close both come from the last
    # 1-minute candle of the previous session — their difference is effectively
    # zero, making change_pct ≈ 0 and killing the momentum gate.
    # Use the stored day-over-day close % change from historical metrics instead.
    ms = market_status()
    if not ms["is_open"]:
        change_pct = hist.get("day_change_pct", change_pct) if hist else change_pct
    avg_volume_20      = hist.get("avg_volume_20", 0)        # 20-day daily avg volume
    avg_daily_volume_5 = float(hist.get("avg_daily_volume_5", 0))
    latest_day_volume  = float(hist.get("latest_day_volume", volume))

    # ── RVOL calculation (Time-Normalized for Open Market) ─────────────────────
    # Calculate elapsed minutes in the current trading session (9:15 AM to 3:30 PM IST, 375 minutes total)
    now_ist = ms["now_ist"]
    market_open_time = datetime.combine(now_ist.date(), dtime(9, 15), tzinfo=_IST_TZ)
    market_close_time = datetime.combine(now_ist.date(), dtime(15, 30), tzinfo=_IST_TZ)
    
    if ms["is_weekend"] or ms["is_holiday"]:
        elapsed_minutes = 375.0
    elif now_ist < market_open_time:
        elapsed_minutes = 1.0  # Avoid division by zero
    elif now_ist > market_close_time:
        elapsed_minutes = 375.0
    else:
        elapsed_minutes = max(1.0, (now_ist - market_open_time).total_seconds() / 60.0)

    if avg_volume_20 > 0:
        vol_for_rvol = volume if ms["is_open"] else latest_day_volume
        if ms["is_open"]:
            expected_volume = avg_volume_20 * (elapsed_minutes / 375.0)
        else:
            expected_volume = avg_volume_20
        rvol = round(vol_for_rvol / expected_volume, 2) if expected_volume > 0 else 0.0
    else:
        rvol = 0.0   # no history available — criterion not met

    volume_premium = round(latest_day_volume / avg_daily_volume_5, 2) if avg_daily_volume_5 else 0.0

    vwap = hist["vwap"]
    ema20 = hist["ema20"]
    orb_high = hist["orb_high"]
    orb_low = hist["orb_low"]

    # ── Hard momentum gates ────────────────────────────────────────────────────
    has_upside_momentum   = change_pct >=  min_change
    has_downside_momentum = change_pct <= -min_change

    breakout_checks = [
        close > orb_high,
        close > ema20,
        close > vwap,
        rvol >= min_rvol,
        volume_premium_min <= volume_premium <= volume_premium_max,
        has_upside_momentum,                    # 6th criterion — must be moving up
    ]
    breakdown_checks = [
        close < orb_low,
        close < ema20,
        close < vwap,
        rvol >= min_rvol,
        volume_premium_min <= volume_premium <= volume_premium_max,
        has_downside_momentum,                  # 6th criterion — must be moving down
    ]
    breakout_score  = sum(breakout_checks)
    breakdown_score = sum(breakdown_checks)

    # Hard early exit: a flat stock can never be a valid signal regardless of
    # structural position.
    if not has_upside_momentum and not has_downside_momentum:
        return None

    # Only stocks meeting 6/6 criteria are displayed
    if breakout_score == 6:
        signal = "LONG"
    elif breakdown_score == 6:
        signal = "SHORT"
    else:
        return None

    momentum = round(abs(change_pct) + rvol + max(breakout_score, breakdown_score), 2)

    return {
        "Stock":     effective_universe().get(instrument, instrument),
        "Signal":    signal,
        "Score":     max(breakout_score, breakdown_score),
        "Last Close": hist.get("last_close", close) if hist else close,
        "Change %":  change_pct,
        "Momentum":  momentum,
        "LTP":       close,
        "VWAP":      vwap,
        "EMA20":     ema20,
        "ORB High":  orb_high,
        "ORB Low":   orb_low,
        "RVOL":      rvol,
        "Vol Premium": volume_premium,
        "Volume":    volume,
    }


def highlight_top_volume(df: pd.DataFrame, vol_col: str = "Volume", top_n: int = 5):
    """Highlight top-N rows by volume so high-volume breakouts are immediately visible."""
    if df.empty or vol_col not in df.columns:
        return df.style.format(precision=2)
    top_idx = df[vol_col].nlargest(top_n).index

    def _row_style(row: pd.Series) -> list[str]:
        if row.name in top_idx:
            return [
                "background-color: rgba(251,191,36,0.28); "
                "color: #7c5200; font-weight: 700;"
            ] * len(row)
        return [""] * len(row)

    return df.style.apply(_row_style, axis=1).format(precision=2)


def handle_message(feed_state: FeedState, message: str) -> None:
    """Parse an incoming WebSocket message and update feed_state.

    Handles:
    - Heartbeat / ping messages (silently ignored)
    - Single JSON object  {"mode":"ltp", "instrument":"2885", "data":{"ltp":1426}}
    - JSON array of objects
    - Double-encoded strings
    """
    # ── Parse outer envelope ─────────────────────────────────────────────────
    try:
        parsed = json.loads(message)
    except (json.JSONDecodeError, ValueError):
        # Plain-text heartbeat or ping — ignore silently
        return

    # Double-encoded: JSON string wrapping JSON
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (json.JSONDecodeError, ValueError):
            return   # plain heartbeat string — ignore

    # Normalise to list
    messages = parsed if isinstance(parsed, list) else [parsed]

    data_received = False
    with feed_state.lock:
        for item in messages:
            if not isinstance(item, dict):
                continue   # heartbeat, ack, or other non-data frame

            # ── Identify instrument ─────────────────────────────────────────
            instrument = (
                item.get("instrument")
                or item.get("symbol")
                or item.get("s")
            )
            # ── Extract data payload ────────────────────────────────────────
            # Both LTP mode {"data":{"ltp":1426}} and quote mode have data nested
            quote = item.get("data") or {}
            if not quote and isinstance(item, dict):
                # Flat format fallback: the item itself is the quote
                quote = {k: v for k, v in item.items()
                         if k not in ("mode", "instrument", "symbol", "s", "timestamp", "type")}

            if not instrument or not isinstance(quote, dict) or not quote:
                continue   # heartbeat / ack with no data

            token_str = str(instrument)

            # Preserve top-level timestamp into quote so accumulate_index_tick
            # uses the server timestamp for accurate IST minute-bucketing.
            ts_from_item = item.get("timestamp")
            if ts_from_item is not None and "timestamp" not in quote:
                quote = dict(quote)
                quote["timestamp"] = ts_from_item

            # Extract bare number if it has a prefix (handles NSE:, NIDX:, NSE_, NIDX_, or bare number)
            bare_num = token_str.split(":")[-1].split("_")[-1]

            # ── Route: index vs equity ──────────────────────────────────────
            if bare_num in INDEX_BARE_TOKENS:
                full_key = f"NIDX:{bare_num}"
                existing = feed_state.index_data.get(full_key, {})
                feed_state.index_data[full_key] = {**existing, **quote}
            else:
                stock_token = (
                    token_str
                    .replace("NSE_", "")
                    .replace("NSE:", "")
                    .replace("BSE:", "")
                )
                existing = feed_state.market_data.get(stock_token, {})
                feed_state.market_data[stock_token] = {**existing, **quote}

            feed_state.last_update = time.time()
            data_received = True

        if data_received:
            feed_state.status = "Live"       # ← "Live" once actual price data arrives
            feed_state.last_error = None


def websocket_worker(
    feed_state: FeedState,
    access_token: str,
    stop_event: threading.Event,
) -> None:
    try:
        _backoff = 3

        while not stop_event.is_set():
            ws_app: websocket.WebSocketApp | None = None
            _connected_ok = False

            def on_open(ws: websocket.WebSocketApp) -> None:
                nonlocal _connected_ok
                _connected_ok = True
                with feed_state.lock:
                    feed_state.status = "Subscribing"
                    feed_state.last_error = None
                    instruments = list(feed_state.instruments_snapshot)

                # Combine equities with all variations of index token formats
                all_index_formats = []
                for t in INDEX_TOKENS: # e.g. "NIDX:40000001"
                    num = t.split(":")[-1]
                    all_index_formats.extend([t, num, f"NSE:{num}"])

                combined_instruments = instruments + all_index_formats

                # Subscribe all instruments in both LTP and Quote modes
                # This ensures both equities and index live quotes stream reliably in a single batch
                ws.send(json.dumps({
                    "action":      "subscribe",
                    "mode":        "ltp",
                    "instruments": combined_instruments,
                }))
                ws.send(json.dumps({
                    "action":      "subscribe",
                    "mode":        "quote",
                    "instruments": combined_instruments,
                }))
                # Mark as connected — data flow will update status to "Live"
                with feed_state.lock:
                    feed_state.status = "Connected"

            def on_message(ws: websocket.WebSocketApp, message: str) -> None:
                try:
                    with feed_state.lock:
                        feed_state.last_raw_message = message[:500]
                    handle_message(feed_state, message)
                except Exception as exc:
                    with feed_state.lock:
                        feed_state.last_error = f"Unhandled error in message processing: {exc}"

            def on_error(ws: websocket.WebSocketApp, error: Exception) -> None:
                err_type = type(error).__name__
                err_msg  = str(error)
                if "401" in err_msg or "403" in err_msg or "Unauthorized" in err_msg:
                    readable = f"Auth rejected: token may be expired"
                elif "handshake" in err_msg.lower() or "status code" in err_msg.lower():
                    readable = f"WS handshake failed: {err_msg}"
                elif "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                    readable = f"Connection timed out ({err_type})"
                else:
                    readable = f"{err_type}: {err_msg}"
                with feed_state.lock:
                    feed_state.status = "Error"
                    feed_state.last_error = readable

            def on_close(
                ws: websocket.WebSocketApp,
                close_status_code: int | None,
                close_msg: str | None,
            ) -> None:
                with feed_state.lock:
                    feed_state.status = "Disconnected"
                    parts = []
                    if close_status_code:
                        parts.append(f"code={close_status_code}")
                    if close_msg:
                        parts.append(str(close_msg))
                    if parts:
                        feed_state.last_error = "WS closed: " + " · ".join(parts)

            with feed_state.lock:
                feed_state.status = "Connecting"

            try:
                ws_app = websocket.WebSocketApp(
                    WS_URL,
                    header=[
                        f"Authorization: {clean_token(access_token)}",
                        "User-Agent: Mozilla/5.0"
                    ],
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                )
                ws_app.run_forever(
                    ping_interval=20,
                    ping_timeout=10,
                    skip_utf8_validation=True,
                )
            except Exception as exc:
                with feed_state.lock:
                    feed_state.status = "Error"
                    feed_state.last_error = str(exc)
            finally:
                if ws_app:
                    try:
                        ws_app.close()
                    except Exception:
                        pass

            if not stop_event.is_set():
                with feed_state.lock:
                    feed_state.reconnects += 1
                    feed_state.status = "Reconnecting"
                _backoff = 3 if _connected_ok else min(_backoff * 2, 60)
                time.sleep(_backoff)
    finally:
        with feed_state.lock:
            feed_state.status = "Stopped"
            feed_state.started = False


def start_feed(feed_state: FeedState, access_token: str) -> None:
    fingerprint = token_fingerprint(access_token)
    # Capture the instrument list on the main thread (safe to call session_state here)
    instruments_now = effective_instruments()
    with feed_state.lock:
        is_alive = feed_state.thread is not None and feed_state.thread.is_alive()
        if feed_state.started and is_alive and feed_state.token_fingerprint == fingerprint:
            return
        feed_state.stop_event.set()

    if feed_state.thread and feed_state.thread.is_alive():
        feed_state.thread.join(timeout=2)

    with feed_state.lock:
        stop_event = threading.Event()
        feed_state.stop_event = stop_event
        feed_state.market_data.clear()
        feed_state.started = True
        feed_state.status = "Starting"
        feed_state.last_error = None
        feed_state.reconnects = 0
        feed_state.token_fingerprint = fingerprint
        feed_state.instruments_snapshot = instruments_now  # thread-safe snapshot
        feed_state.thread = threading.Thread(
            target=websocket_worker,
            args=(feed_state, access_token, stop_event),
            daemon=True,
        )
        feed_state.thread.start()


def stop_feed(feed_state: FeedState) -> None:
    with feed_state.lock:
        feed_state.stop_event.set()
        feed_state.status = "Stopping"


def snapshot_feed(feed_state: FeedState) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    with feed_state.lock:
        market_data = dict(feed_state.market_data)
        index_data  = dict(feed_state.index_data)
        status = {
            "status":      feed_state.status,
            "last_update": feed_state.last_update,
            "last_error":  feed_state.last_error,
            "reconnects":  feed_state.reconnects,
            "started":     feed_state.started,
        }
    return market_data, index_data, status


def format_last_update(timestamp: float | None) -> str:
    if not timestamp:
        return "No ticks yet"
    seconds = max(0, int(time.time() - timestamp))
    if seconds < 2:
        return "Just now"
    return f"{seconds}s ago"


def fetch_market_depth(tokens: list[str], access_token: str) -> dict[str, Any]:
    """Fetch 5-level market depth for a list of NSE tokens via /market/quotes/mkt.

    Returns the raw ``data`` dict keyed by ``NSE_<token>``, or {} on failure.
    """
    scrip_codes = ",".join(f"NSE_{t}" for t in tokens)
    try:
        resp = requests.get(
            MARKET_DEPTH_URL,
            params={"scrip-codes": scrip_codes},
            headers=auth_headers(access_token),
            timeout=8,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})
    except Exception:
        return {}


def render_market_depth(depth_data: dict[str, Any]) -> None:
    """Render 5-level market depth panel for each instrument returned."""
    if not depth_data:
        return

    for scrip_key, payload in depth_data.items():
        token = scrip_key.replace("NSE_", "")
        name  = effective_universe().get(token) or STOCK_NAMES.get(token) or scrip_key
        md    = payload.get("market_depth", {})
        # market_depth may be nested: {"NSE_3045": {"aggregate":...}}
        if scrip_key in md:
            md = md[scrip_key]
        agg   = md.get("aggregate", {})
        depth = md.get("depth", [])

        def _clean_num(v: Any) -> str:
            """Strip commas and return value, or — if zero/missing."""
            s = str(v or "").replace(",", "").strip()
            try:
                f = float(s)
                return f"{f:,.0f}" if f else "—"
            except ValueError:
                return s or "—"

        buy_pct  = float(str(agg.get("buy_percentage",  0)).replace(",", "") or 0)
        sell_pct = float(str(agg.get("sell_percentage", 0)).replace(",", "") or 0)

        with st.expander(
            f"🐒 {name}  ·  Buy {buy_pct:.1f}%  /  Sell {sell_pct:.1f}%",
            expanded=True,
        ):
            ac1, ac2, ac3, ac4 = st.columns(4)
            ac1.metric("Total Buy Qty",  _clean_num(agg.get("total_buy")))
            ac2.metric("Total Sell Qty", _clean_num(agg.get("total_sell")))
            ac3.metric("Buy %",  f"{buy_pct:.1f}%")
            ac4.metric("Sell %", f"{sell_pct:.1f}%")

            if depth:
                rows = []
                for lvl_i, level in enumerate(depth, start=1):
                    buy  = level.get("buy",  {})
                    sell = level.get("sell", {})
                    rows.append({
                        "Level":      lvl_i,
                        "Buy Qty":    _clean_num(buy.get("quantity")),
                        "Buy Price":  buy.get("price",  "—"),
                        "Sell Price": sell.get("price", "—"),
                        "Sell Qty":   _clean_num(sell.get("quantity")),
                    })
                depth_df = pd.DataFrame(rows)

                def _style_depth(row: pd.Series) -> list[str]:
                    cols = list(depth_df.columns)
                    styles = [""] * len(cols)
                    for col, sty in [
                        ("Buy Qty",    "color:#34d399;font-weight:600"),
                        ("Buy Price",  "color:#34d399;font-weight:600"),
                        ("Sell Price", "color:#ef5350;font-weight:600"),
                        ("Sell Qty",   "color:#ef5350;font-weight:600"),
                    ]:
                        if col in cols:
                            styles[cols.index(col)] = sty
                    return styles

                st.dataframe(
                    depth_df.style.apply(_style_depth, axis=1),
                    width='stretch',
                    hide_index=True,
                    height=230,
                )


def market_depth_fragment(access_token: str) -> None:
    """Live market depth panel — called from live_scanner_fragment (runs every 3 s).

    No @st.fragment decorator needed: the outer live_scanner_fragment already
    reruns every 3 s, so this function is re-executed automatically each tick.
    """
    # Stock selector — widget key maintains selection across auto-reruns
    selected = st.multiselect(
        "Select stocks for live depth (up to 5)",
        options=sorted(effective_universe().values()),
        max_selections=5,
        key="depth_stock_picker",
    )

    if not selected:
        st.info("Select up to 5 stocks above — depth updates live every 3 s.")
        return

    # Fetch fresh data on EVERY tick — never use cached session_state for rendering
    name_to_tok = {v: k for k, v in effective_universe().items()}
    tokens = [name_to_tok[n] for n in selected if n in name_to_tok]

    depth_data = {}
    fetch_err  = None
    if tokens:
        try:
            resp = fetch_market_depth(tokens, access_token)
            depth_data = resp if resp else {}
            if not resp:
                fetch_err = "API returned empty response"
        except Exception as ex:
            fetch_err = str(ex)

    # Visible clock — proves the fragment is cycling every 3 s
    _now_ist = market_status()["now_ist"].strftime("%H:%M:%S")
    if fetch_err:
        st.caption(f"Warning: {fetch_err} | last attempt {_now_ist}")
    else:
        st.caption(f"Live depth | refreshed {_now_ist} | auto-updates every 3 s")

    if not depth_data:
        st.info("No depth data returned — API may not support this endpoint.")
        return

    # Render as raw HTML table — guaranteed to re-render on every fragment cycle
    for scrip_key, payload in depth_data.items():
        token = scrip_key.replace("NSE_", "")
        name  = effective_universe().get(token) or STOCK_NAMES.get(token) or scrip_key
        md    = payload.get("market_depth", {})
        if scrip_key in md:
            md = md[scrip_key]
        agg   = md.get("aggregate", {})
        depth = md.get("depth", [])

        def _n(v):
            s = str(v or "").replace(",", "").strip()
            try:
                f = float(s)
                return f"{f:,.0f}" if f else "---"
            except Exception:
                return s or "---"

        buy_pct  = float(str(agg.get("buy_percentage",  0)).replace(",", "") or 0)
        sell_pct = float(str(agg.get("sell_percentage", 0)).replace(",", "") or 0)

        st.markdown(
            f'<div style="margin:0.6rem 0 0.2rem;font-size:0.85rem;font-weight:700;color:#0f172a;">' +
            f'{name} &nbsp;<span style="color:#059669">Buy {buy_pct:.1f}%</span>' +
            f' / <span style="color:#dc2626">Sell {sell_pct:.1f}%</span>' +
            f' | Total Buy: <b>{_n(agg.get("total_buy"))}</b>' +
            f' Total Sell: <b>{_n(agg.get("total_sell"))}</b></div>',
            unsafe_allow_html=True,
        )

        if depth:
            rows_html = "".join(
                f'<tr>' +
                f'<td style="color:#059669;text-align:right;padding:3px 8px">{_n(lvl.get("buy", {}).get("quantity"))}</td>' +
                f'<td style="color:#059669;text-align:right;padding:3px 8px;font-weight:600">{lvl.get("buy", {}).get("price", "---")}</td>' +
                f'<td style="text-align:center;color:#64748b;padding:3px 6px">{i}</td>' +
                f'<td style="color:#dc2626;text-align:left;padding:3px 8px;font-weight:600">{lvl.get("sell", {}).get("price", "---")}</td>' +
                f'<td style="color:#dc2626;text-align:left;padding:3px 8px">{_n(lvl.get("sell", {}).get("quantity"))}</td>' +
                f'</tr>'
                for i, lvl in enumerate(depth, 1)
            )
            st.markdown(
                f'<table style="width:100%;border-collapse:collapse;font-size:0.8rem;' +
                f'background:#ffffff;border:1px solid #e2e8f0;border-bottom:3.5px solid #cbd5e1;border-radius:8px;margin-bottom:0.6rem;box-shadow:0 1px 3px rgba(0,0,0,0.05);">' +
                f'<thead><tr>' +
                f'<th style="color:#475569;text-align:right;padding:4px 8px">Buy Qty</th>' +
                f'<th style="color:#475569;text-align:right;padding:4px 8px">Bid</th>' +
                f'<th style="color:#64748b;text-align:center;padding:4px">Lvl</th>' +
                f'<th style="color:#475569;text-align:left;padding:4px 8px">Ask</th>' +
                f'<th style="color:#475569;text-align:left;padding:4px 8px">Sell Qty</th>' +
                f'</tr></thead><tbody>{rows_html}</tbody></table>',
                unsafe_allow_html=True,
            )
        st.divider()


def build_live_snapshot(market_data: dict[str, dict[str, Any]]) -> pd.DataFrame:

    rows = []
    eu = effective_universe()
    for instrument, quote in market_data.items():
        parsed = parse_quote(quote)
        rows.append(
            {
                "Stock": eu.get(instrument, instrument),
                "LTP": parsed["close"],
                "Open": parsed["open"],
                "High": parsed["high"],
                "Low": parsed["low"],
                "Volume": parsed["volume"],
                "History": "Loaded" if instrument in st.session_state.historical_data else "Missing",
            }
        )
    return pd.DataFrame(rows).sort_values("Stock") if rows else pd.DataFrame()


def build_historical_market_data() -> dict[str, dict[str, float | int]]:
    historical_market_data: dict[str, dict[str, float | int]] = {}
    for instrument, metrics in st.session_state.historical_data.items():
        if "last_close" not in metrics:
            continue
        historical_market_data[instrument] = {
            "open": metrics["last_open"],
            "high": metrics["last_high"],
            "low": metrics["last_low"],
            "close": metrics["last_close"],
            "volume": metrics["last_volume"],
        }
    return historical_market_data


def calculate_broad_market_status() -> dict[str, Any]:
    """Calculate broad market status dynamically using Nifty 50 and universe breadth.
    Runs entirely in-memory on already-loaded states to guarantee ZERO speed penalty.
    """
    advances = 0
    declines = 0
    above_vwap = 0
    total_active = 0
    
    # Analyze in-memory universe states
    for stock_token, metrics in st.session_state.historical_data.items():
        day_chg = metrics.get("day_change_pct", 0.0)
        fs = get_feed_state()
        with fs.lock:
            live_quote = fs.market_data.get(stock_token)
        if live_quote:
            parsed = parse_quote(live_quote)
            open_p = parsed["open"]
            close_p = parsed["close"]
            if open_p > 0:
                day_chg = ((close_p - open_p) / open_p) * 100
                
        total_active += 1
        if day_chg > 0.05:
            advances += 1
        elif day_chg < -0.05:
            declines += 1
            
        close_p = metrics.get("last_close", 0.0)
        vwap_p = metrics.get("vwap", 0.0)
        if live_quote:
            parsed = parse_quote(live_quote)
            if parsed["close"] > 0:
                close_p = parsed["close"]
        if close_p > vwap_p and vwap_p > 0:
            above_vwap += 1

    adr = advances / declines if declines > 0 else (advances if advances > 0 else 1.0)
    pct_advancing = (advances / total_active * 100) if total_active > 0 else 50.0
    pct_above_vwap = (above_vwap / total_active * 100) if total_active > 0 else 50.0

    fs = get_feed_state()
    with fs.lock:
        nifty_quote = fs.index_data.get("NIDX:40000001", {})
    
    nifty_ltp = nifty_quote.get("ltp") or nifty_quote.get("last_price") or nifty_quote.get("live_price")
    if nifty_ltp is None:
        nifty_candles = st.session_state.get("_idx_ws_candles_NIDX:40000001", [])
        if nifty_candles:
            nifty_ltp = float(nifty_candles[-1][4])
            
    nifty_chg_pct = 0.0
    if nifty_quote:
        nifty_chg_pct = float(nifty_quote.get("day_change_percentage") or nifty_quote.get("change_percentage") or 0.0)
        
    nifty_bullish = nifty_chg_pct > 0.15
    nifty_bearish = nifty_chg_pct < -0.15
    
    bull_score = 0
    bear_score = 0
    
    if pct_advancing > 53.0: bull_score += 1
    elif pct_advancing < 47.0: bear_score += 1
    
    if pct_above_vwap > 53.0: bull_score += 1
    elif pct_above_vwap < 47.0: bear_score += 1
    
    if nifty_ltp is not None:
        if nifty_bullish: bull_score += 1
        elif nifty_bearish: bear_score += 1
    else:
        bull_score *= 1.5
        bear_score *= 1.5

    if bull_score >= 2.0:
        trend, color, arrow = "UPTREND", "#059669", "▲"
        desc = f"Bullish Breadth (ADR {adr:.2f})"
    elif bear_score >= 2.0:
        trend, color, arrow = "DOWNTREND", "#dc2626", "▼"
        desc = f"Bearish Breadth (ADR {adr:.2f})"
    else:
        trend, color, arrow = "SIDEWAYS", "#4b5563", "◀▶"
        desc = f"Neutral Range (ADR {adr:.2f})"
        
    return {
        "trend": trend,
        "color": color,
        "arrow": arrow,
        "desc": desc,
        "advances": advances,
        "declines": declines,
        "pct_above_vwap": pct_above_vwap,
    }


def build_history_snapshot() -> pd.DataFrame:
    rows = []
    eu = effective_universe()
    ms = market_status()
    _vol_label = "Live Day Vol" if ms["is_open"] else "Last Day Vol"
    for instrument, metrics in st.session_state.historical_data.items():
        avg_v20  = metrics.get("avg_volume_20", 0)
        avg_d5   = metrics.get("avg_daily_volume_5", 0)
        last_vol = metrics.get("latest_day_volume", 0)
        rows.append(
            {
                "Stock":        eu.get(instrument, instrument),
                "VWAP":         metrics["vwap"],
                "EMA20":        metrics["ema20"],
                "RVOL":         metrics["rvol"],
                "20D Avg Vol":  int(avg_v20),
                "5D Avg Vol":   int(avg_d5) if avg_d5 else 0,
                _vol_label:     int(last_vol),
                "ORB High":     metrics["orb_high"],
                "ORB Low":      metrics["orb_low"],
                "Day Chg %":    metrics.get("day_change_pct", 0),
                "Last Close":   metrics.get("last_close"),
                "Source":       metrics.get("source", "Historical API"),
            }
        )
    return pd.DataFrame(rows).sort_values("Stock") if rows else pd.DataFrame()


def build_error_table(errors: list[str]) -> pd.DataFrame:
    rows = []
    for error in errors:
        if ": " in error:
            stock, reason = error.split(": ", 1)
        else:
            stock, reason = "History", error
        rows.append({"Stock": stock, "Issue": reason})
    return pd.DataFrame(rows)


feed_state = get_feed_state()
st.session_state.history_loaded = bool(st.session_state.historical_data)

# ── Header placeholder — filled after snapshot_feed gives us index_data ───
_header_placeholder = st.empty()
st.session_state["_header_placeholder"] = _header_placeholder

# ── Market Status Banner ────────────────────────────────────────────────────
_ms = market_status()
_now_str = _ms["now_ist"].strftime("%d %b %Y  %H:%M IST")

if _ms["is_open"]:
    _icon = "🟢"
    _bg   = "rgba(34,197,94,0.12)"
    _border = "#22c55e"
    _msg  = f"Trading session active &nbsp;·&nbsp; {_ms['next_open']}"
elif _ms["is_pre_open"]:
    _icon = "🟡"
    _bg   = "rgba(245,158,11,0.12)"
    _border = "#f59e0b"
    _msg  = _ms["next_open"]
else:
    _icon = "🔴" if not (_ms["is_weekend"] or _ms["is_holiday"]) else ("📅" if _ms["is_holiday"] else "😴")
    _bg   = "rgba(239,68,68,0.10)" if not (_ms["is_weekend"] or _ms["is_holiday"]) else (
            "rgba(99,102,241,0.10)" if _ms["is_holiday"] else "rgba(100,116,139,0.10)")
    _border = _ms["status_color"]
    _msg  = _ms["next_open"]

st.markdown(
    f"""
    <div style="
        display:flex; align-items:center; gap:1rem;
        background:{_bg};
        border:1px solid {_border};
        border-radius:10px;
        padding:0.65rem 1.1rem;
        margin-bottom:0.8rem;
        font-family:'Inter',sans-serif;
    ">
        <span style="font-size:1.3rem;">{_icon}</span>
        <div style="flex:1;">
            <span style="
                font-weight:700; font-size:0.82rem;
                letter-spacing:0.08em; text-transform:uppercase;
                color:{_border};
            ">{_ms["status_label"]}</span>
            <span style="
                margin-left:1rem; font-size:0.82rem; color:#8fa3b8;
            ">{_msg}</span>
        </div>
        <span style="font-size:0.78rem; color:#4a6480; font-family:'JetBrains Mono',monospace;">
            {_now_str}
        </span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── MOBILE-OPTIMIZED QUICK-PASTE TOKEN CARD ────────────────────────────────
if not st.session_state.token_accepted:
    st.markdown(
        """
        <div style="
            background:#ffffff;
            border:1.5px solid #cbd5e1;
            border-left:4.5px solid #059669;
            border-bottom:4.5px solid #cbd5e1;
            border-radius:10px;
            padding:1rem;
            margin-bottom:1rem;
            box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);
        ">
            <div style="font-size:0.75rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;">🔑 Quick-Paste Activation Terminal</div>
            <div style="font-size:0.9rem;color:#475569;margin-top:0.25rem;margin-bottom:0.75rem;font-weight:500;">
                Your daily broker session has reset. Paste today's INDmoney access token below from your mobile phone to instantly activate the workstation.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    
    col_t1, col_t2 = st.columns([5, 2])
    with col_t1:
        mobile_token = st.text_input("Paste Today's Access Token:", type="password", key="mobile_token_input", label_visibility="collapsed", placeholder="Paste today's token here...")
    with col_t2:
        activate_btn = st.button("🚀 Activate Workstation", use_container_width=True, key="mobile_activate_btn")
        
    if activate_btn:
        if mobile_token:
            cleaned = clean_token(mobile_token)
            if cleaned:
                st.session_state.accepted_token = cleaned
                st.session_state.token_accepted = True
                st.session_state.history_attempted = False
                save_cached_token(cleaned)
                st.success("🎉 Workstation Activated! Loading data...")
                st.rerun()
            else:
                st.warning("⚠️ Invalid token format. Please check and try again.")
        else:
            st.warning("⚠️ Please paste a token before activating.")
    st.divider()

with st.sidebar:
    st.header("🔑 API Access")
    
    # Check if the cached token is expired
    if is_token_expired() and st.session_state.accepted_token:
        st.warning("⚠️ Cached token has expired (daily reset at 7:00 AM). Please paste today's new token below.")
        
    token_input = st.text_input("INDmoney Access Token", type="password", value=st.session_state.accepted_token, placeholder="Paste token here...")
    accept_token = st.button("✅ Accept Token", use_container_width=True)
    clear_token  = st.button("🗑 Clear Token",  use_container_width=True, disabled=not st.session_state.token_accepted)

    if accept_token:
        if clean_token(token_input):
            token_val = clean_token(token_input)
            st.session_state.accepted_token = token_val
            st.session_state.token_accepted = True
            st.session_state.history_attempted = False  # Reset attempt flag for new token
            save_cached_token(token_val)
            st.success("Token accepted and cached.")
        else:
            st.warning("Paste your token before accepting.")

    if clear_token:
        st.session_state.accepted_token = ""
        st.session_state.token_accepted = False
        st.session_state.historical_data = empty_history()
        st.session_state.history_loaded = False
        st.session_state.history_attempted = False  # Reset attempt flag
        st.session_state.history_status = "Not attempted"
        delete_cached_token()
        stop_feed(feed_state)
        st.info("Token cleared and cache removed.")

    if st.session_state.token_accepted:
        st.caption("Token accepted for this session.")

    st.header("⚙️ Signal Filters")
    st.caption(f"Universe: {len(effective_universe())} liquid NSE stocks")
    min_change = st.slider("Minimum Change %", 0.1, 5.0, 0.5, 0.1)
    min_rvol = st.slider("Minimum RVOL", 0.1, 5.0, 1.0, 0.1)
    sr_pivot_type = st.selectbox("S/R Pivot Points (TradingView)", ["None", "Traditional", "Camarilla", "Fibonacci"], index=1)
    min_breakout_score = 6
    volume_premium_min = st.slider("Volume Premium Min", 1.0, 5.0, 1.2, 0.1)
    volume_premium_max = st.slider("Volume Premium Max", 1.0, 5.0, 3.0, 0.1)
    if volume_premium_max < volume_premium_min:
        st.warning("Volume Premium Max should be above Min.")
    historical_workers = st.slider("Historical Workers", 4, 16, HISTORICAL_WORKERS, 1)

    st.header("📢 Telegram Alerts")
    try:
        from database import get_db_settings, save_db_setting
        db_tg_token = get_db_settings("telegram_bot_token", "")
        db_tg_chat_id = get_db_settings("telegram_chat_id", "")
        db_tg_enabled = get_db_settings("telegram_notifications_enabled", False)

        tg_enabled = st.checkbox("Enable Telegram Alerts", value=db_tg_enabled, key="tg_sidebar_enabled")
        tg_token = st.text_input("Bot Token", value=db_tg_token, type="password", key="tg_sidebar_token")
        tg_chat_id = st.text_input("Chat ID", value=db_tg_chat_id, key="tg_sidebar_chat_id")

        if tg_token.strip() and tg_chat_id.strip():
            if st.button("🧪 Test Telegram Connection", key="tg_sidebar_test_btn", use_container_width=True):
                with st.spinner("Sending test message..."):
                    url = f"https://api.telegram.org/bot{tg_token.strip()}/sendMessage"
                    payload = {
                        "chat_id": tg_chat_id.strip(),
                        "text": "<b>Fin+ Workstation Connection Test</b>\n\n🟢 Your Telegram Bot is successfully connected and authorized to send alerts! 🚀",
                        "parse_mode": "HTML"
                    }
                    try:
                        import requests
                        resp = requests.post(url, json=payload, timeout=8.0)
                        if resp.status_code != 200:
                            try:
                                err_desc = resp.json().get("description", resp.text)
                            except Exception:
                                err_desc = resp.text
                            st.error(f"Telegram API Error: {err_desc}")
                        else:
                            st.toast("✅ Test message sent successfully!", icon="✅")
                    except Exception as e:
                        st.error(f"Failed to send test message: {e}")

        if tg_enabled != db_tg_enabled or tg_token.strip() != db_tg_token or tg_chat_id.strip() != db_tg_chat_id:
            save_db_setting("telegram_bot_token", tg_token.strip())
            save_db_setting("telegram_chat_id", tg_chat_id.strip())
            save_db_setting("telegram_notifications_enabled", tg_enabled)
            st.toast("Telegram settings saved successfully!", icon="💾")
            st.rerun()
    except Exception as e:
        st.caption(f"Error loading Telegram DB settings: {e}")

    st.header("🔗 Feed Controls")
    load_history      = st.button("📥 Load History", use_container_width=True, disabled=not st.session_state.token_accepted)
    connect_feed      = st.button("🟢 Connect Feed", use_container_width=True, disabled=not st.session_state.token_accepted)
    stop_feed_clicked = st.button("🔴 Stop Feed",    use_container_width=True)

    st.header("🔍 Stock Search")
    _search_query = st.text_input("Search stock", placeholder="e.g. RELIANCE, INFY, TCS...")
    if _search_query:
        _eu = effective_universe()
        _matches = {t: n for t, n in _eu.items() if _search_query.upper() in n.upper()}
        if _matches:
            for _tok, _nm in sorted(_matches.items(), key=lambda x: x[1]):
                _hist  = st.session_state.historical_data.get(_tok, {})
                _mdata = st.session_state.get("_frag_results") or []
                _sig   = next((r for r in _mdata if r.get("Stock") == _nm), None)
                _ltp_v = _sig.get("LTP", _hist.get("last_close", "—")) if _sig else _hist.get("last_close", "—")
                _chg_v = _sig.get("Change %", _hist.get("day_change_pct", "—")) if _sig else _hist.get("day_change_pct", "—")
                _score = _sig.get("Score", "—") if _sig else "—"
                _signal_label = _sig.get("Signal", "") if _sig else ""
                _sig_color = {"LONG":"#059669","SHORT":"#dc2626","BREAKOUT":"#10b981","BREAKDOWN":"#ef4444"}.get(_signal_label, "#475569")
                st.markdown(
                    f'<div style="background:#ffffff;border:1px solid #e2e8f0;border-bottom:3.5px solid #cbd5e1;border-radius:8px;'
                    f'padding:0.5rem 0.75rem;margin-bottom:0.4rem;box-shadow:0 1px 3px rgba(0,0,0,0.05);">'
                    f'<span style="font-weight:700;color:#0f172a;">{_nm}</span>'
                    f'<span style="font-size:0.7rem;color:#64748b;margin-left:6px;">NSE_{_tok}</span><br>'
                    f'<span style="font-size:0.85rem;color:#475569;">LTP: <b style="color:#0f172a;">{_ltp_v}</b></span>'
                    f'&nbsp;&nbsp;<span style="font-size:0.85rem;color:#475569;">Chg: <b style="color:#0f172a;">{_chg_v}%</b></span>'
                    + (f'&nbsp;&nbsp;<span style="font-size:0.78rem;font-weight:700;color:{_sig_color};">{_signal_label} {_score}</span>' if _signal_label else "")
                    + f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No stocks match your search.")

access_token = st.session_state.accepted_token

# =========================================================
# DO NOT SHOW WEBSOCKET ERRORS BEFORE TOKEN ACCEPTANCE
# =========================================================

if not st.session_state.token_accepted:
    stop_feed(feed_state)

    with feed_state.lock:
        feed_state.status = "Idle"
        feed_state.last_error = None
        feed_state.reconnects = 0
        feed_state.last_update = None
        feed_state.started = False

if load_history:
    with st.spinner("Loading historical data..."):
        success_count, failures = load_historical_data(access_token, historical_workers)
    if success_count:
        st.success(f"Historical data loaded for {success_count} stocks.")
    else:
        st.error("❌ Failed to load historical data. The access token is incorrect, expired, or has been revoked. Please paste today's fresh token in the sidebar and accept it.")
        if failures:
            with st.expander("Show Failure Diagnostics"):
                st.write(failures[:5])
    st.session_state.auto_history_last_load = time.time()   # reset 15-min timer

# Auto-start WS feed whenever token is accepted and feed is not already running.
# This means the user never needs to manually click 'Connect WebSocket' --
# accepting the token is sufficient to bring up both equity and index streams.
if (st.session_state.token_accepted
        and clean_token(access_token)
        and not feed_state.started):
    start_feed(feed_state, access_token)

if connect_feed and clean_token(access_token):
    # Only auto-load history if truly empty (user has not loaded yet)
    if not st.session_state.historical_data:
        with st.spinner("Loading historical data before connecting..."):
            success_count, failures = load_historical_data(access_token, historical_workers)
        if success_count:
            st.success(f"Historical data loaded for {success_count} stocks.")
            start_feed(feed_state, access_token)
            st.success("WebSocket connection started.")
        else:
            st.error("❌ Failed to load historical data before connecting. The access token is incorrect, expired, or revoked. Please check your token in the sidebar.")
            if failures:
                with st.expander("Show Failure Diagnostics"):
                    st.write(failures[:5])
        st.session_state.auto_history_last_load = time.time()
    else:
        start_feed(feed_state, access_token)
        st.success("WebSocket connection started.")

if stop_feed_clicked:
    stop_feed(feed_state)
    st.info("WebSocket stop requested.")

import plotly.graph_objects as go
from plotly.subplots import make_subplots

def get_index_tile_quote(index_token, index_snapshot):
    """Read LTP + day change from the latest WS tick or fall back to accumulated / REST candles."""
    q = index_snapshot.get(index_token, {})
    ltp = q.get("ltp") or q.get("last_price") or q.get("live_price") or q.get("close") or q.get("c")
    
    # ── On-Demand Synchronous REST Seeding ─────────────────────────────────────
    rest_key = f"_idx_rest_candles_{index_token}"
    rest_candles = st.session_state.get(rest_key, [])
    rest_ts_key = f"_idx_rest_ts_{index_token}"
    last_rest = st.session_state.get(rest_ts_key, 0)
    
    from datetime import datetime, timezone, timedelta
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    today_ist = datetime.now(ist_tz).date()
    
    _ms_rc = market_status()
    now_ts = time.time()
    rest_stale = (now_ts - last_rest) > (86400 if not _ms_rc["is_open"] else 300)
    
    if not rest_candles or rest_stale:
        access_token = st.session_state.get("accepted_token", "")
        last_attempt_key = f"_idx_rest_attempt_{index_token}"
        last_attempt = st.session_state.get(last_attempt_key, 0)
        
        if access_token and (now_ts - last_attempt > 60):  # limit retry to once per 60s
            st.session_state[last_attempt_key] = now_ts
            try:
                # fetch_index_candles is defined below, it will resolve correctly at runtime
                _res = fetch_index_candles(index_token, access_token, lookback_days=7)
                seed, err = (_res if isinstance(_res, tuple) else (_res, None))
                if not err and seed:
                    st.session_state[rest_key] = seed
                    st.session_state[rest_ts_key] = now_ts
                    rest_candles = seed
                    st.session_state.pop(f"_idx_rest_err_{index_token}", None)
            except Exception:
                pass

    if ltp is None:
        # Fall back to last accumulated WS candle close
        ws_candles = st.session_state.get(f"_idx_ws_candles_{index_token}", [])
        if ws_candles:
            ltp = float(ws_candles[-1][4])
        else:
            if rest_candles:
                ltp = float(rest_candles[-1][4])
            else:
                return {}

    # ── Daily Change Calculation ──────────────────────────────────────────────
    prev_close = None
    if rest_candles:
        for c in reversed(rest_candles):
            c_date = datetime.fromtimestamp(c[0] / 1000, ist_tz).date()
            if c_date < today_ist:
                prev_close = float(c[4])
                break

    if prev_close:
        chg = ltp - prev_close
        chg_pct = (chg / prev_close * 100) if prev_close else 0
    else:
        # Fall back specifically to TODAY's opening price
        day_open = None
        ws_candles = st.session_state.get(f"_idx_ws_candles_{index_token}", [])
        if ws_candles:
            for c in ws_candles:
                c_date = datetime.fromtimestamp(c[0] / 1000, ist_tz).date()
                if c_date == today_ist:
                    day_open = float(c[1])
                    break
        
        if not day_open and rest_candles:
            for c in rest_candles:
                c_date = datetime.fromtimestamp(c[0] / 1000, ist_tz).date()
                if c_date == today_ist:
                    day_open = float(c[1])
                    break
        
        if day_open:
            chg = ltp - day_open
            chg_pct = (chg / day_open * 100) if day_open else 0
        else:
            chg = 0
            chg_pct = 0
                
    return {"ltp": ltp,
            "day_change": round(float(chg), 2),
            "day_change_percentage": round(float(chg_pct), 2)}

def _build_index_tile_html(name, quote):
    # WS quote format per docs: data.ltp = live price
    live = (
        float(quote.get("ltp",        0) or 0)
        or float(quote.get("live_price", 0) or 0)   # fallback for REST quotes
    )
    prev = float(
        quote.get("prev_close") or quote.get("previous_close")
        or quote.get("close")   or 0
    )
    chg     = float(quote.get("day_change",      quote.get("change",         0)) or 0)
    chg_pct = float(quote.get("day_change_percentage", quote.get("change_percent", 0)) or 0)
    if live:
        price_val = f"{live:,.2f}"; sub_color = "#059669" if chg >= 0 else "#dc2626"
        arrow = "&#9650;" if chg >= 0 else "&#9660;"
        sub_text = f"{arrow} {abs(chg):,.2f} ({abs(chg_pct):.2f}%)"; border_col = sub_color; extra_label = ""
    elif prev:
        price_val = f"{prev:,.2f}"; sub_color = "#475569"; sub_text = "Market closed"
        border_col = "#64748b"; extra_label = '<div style="font-size:0.6rem;color:#64748b;">PREV CLOSE</div>'
    else:
        price_val = "&mdash;"; sub_color = "#64748b"; sub_text = "No data yet"; border_col = "#cbd5e1"; extra_label = ""
    return (f'<div style="display:inline-flex;flex-direction:column;background:rgba(255,255,255,0.85);border:1px solid #e2e8f0;border-left:3px solid {border_col};border-radius:8px;padding:0.45rem 1rem;min-width:200px;box-shadow: 0 2px 4px rgba(0,0,0,0.02);">'
            f'<div style="font-size:0.68rem;color:#64748b;letter-spacing:.08em;text-transform:uppercase;font-weight:600;">{name}</div>'
            f'{extra_label}<div style="font-size:1.25rem;font-weight:700;color:#0f172a;line-height:1.2;margin-top:2px;">{price_val}</div>'
            f'<div style="font-size:0.78rem;color:{sub_color};font-weight:600;">{sub_text}</div></div>')

def update_index_header():
    """Globally render and update the top header index and market status cards."""
    _ph = st.session_state.get("_header_placeholder")
    if not _ph:
        return
        
    fs = get_feed_state()
    with fs.lock:
        index_snapshot = dict(fs.index_data)
        
    _nifty_q  = get_index_tile_quote("NIDX:40000001", index_snapshot)
    _bnifty_q = get_index_tile_quote("NIDX:40000003", index_snapshot)
    
    _nifty_html  = _build_index_tile_html("NIFTY 50",   _nifty_q)
    _bnifty_html = _build_index_tile_html("BANK NIFTY", _bnifty_q)
    
    # Dynamic Broad Market Status computation
    bms = calculate_broad_market_status()
    _bms_html = (
        f'<div style="display:inline-flex;flex-direction:column;background:rgba(255,255,255,0.85);border:1px solid #e2e8f0;border-left:3px solid {bms["color"]};border-radius:8px;padding:0.45rem 1rem;min-width:200px;box-shadow: 0 2px 4px rgba(0,0,0,0.02);">'
        f'<div style="font-size:0.68rem;color:#64748b;letter-spacing:.08em;text-transform:uppercase;font-weight:600;">MARKET STATUS</div>'
        f'<div style="font-size:1.25rem;font-weight:700;color:{bms["color"]};line-height:1.2;margin-top:2px;">{bms["arrow"]} {bms["trend"]}</div>'
        f'<div style="font-size:0.78rem;color:#475569;font-weight:600;">{bms["desc"]}</div></div>'
    )
    
    _ph.markdown(
        f'<div class="tw-header"><div style="flex:1;"><div class="tw-title">Trading Workstation</div>'
        f'<div style="display:flex;gap:0.75rem;margin-top:0.6rem;flex-wrap:wrap;">{_nifty_html}{_bnifty_html}{_bms_html}</div></div>'
        f'<div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:flex-start;">'
        f'<span class="tw-pill">VWAP</span><span class="tw-pill">EMA 20</span>'
        f'<span class="tw-pill">ORB</span><span class="tw-pill">RVOL</span>'
        f'<span class="tw-pill">1-MIN CANDLES</span></div></div>',
        unsafe_allow_html=True,
    )

update_index_header()

# ── Index candle accumulator ────────────────────────────────────────────────
# Aggregates live LTP ticks from the WebSocket into 1-min OHLCV candles.
# Stored in st.session_state["_idx_ws_candles_NIDX:40000001"] etc.
# Each entry: [ts_minute_ms, open, high, low, close, volume]

def accumulate_index_tick(index_token: str, quote: dict) -> None:
    """Merge one live tick into the in-session 1-min candle list for index_token.

    Call this from index_charts_fragment on every re-render, passing the
    latest quote from feed_state.index_data.
    """
    ltp = quote.get("ltp") or quote.get("last_price") or quote.get("live_price")
    if ltp is None:
        return
    ltp = float(ltp)
    ts_ms = quote.get("timestamp") or int(time.time() * 1000)
    ts_ms = int(ts_ms)
    # Snap to minute boundary (IST offset = 5h30m = 19800 s)
    ts_s = ts_ms // 1000
    minute_s = (ts_s + 19800) // 60 * 60 - 19800  # floor to IST minute, back to UTC epoch
    minute_ms = minute_s * 1000

    key = f"_idx_ws_candles_{index_token}"
    candles: list = st.session_state.get(key, [])

    if candles and candles[-1][0] == minute_ms:
        # Update current candle
        bar = candles[-1]
        bar[2] = max(bar[2], ltp)   # high
        bar[3] = min(bar[3], ltp)   # low
        bar[4] = ltp                # close
        vol = int(quote.get("volume") or quote.get("vol") or 0)
        bar[5] = bar[5] + vol
    else:
        vol = int(quote.get("volume") or quote.get("vol") or 0)
        candles.append([minute_ms, ltp, ltp, ltp, ltp, vol])

    # Keep only last 500 bars (well over one full trading day)
    if len(candles) > 500:
        candles = candles[-500:]
    st.session_state[key] = candles

def fetch_index_candles(index_token, access_token, lookback_days=7):
    """Fetch 1-min candles for a NIFTY/BANKNIFTY index token.

    Tries multiple scrip-code formats in order until one returns data.
    Returns (candles_list, error_string). candles_list is [] on failure.
    """
    # REST API uses underscore (NIDX_40000001), WS uses colon (NIDX:40000001)
    base = index_token.replace(":", "_") if ":" in index_token else index_token
    num  = base.split("_")[-1]   # e.g. "40000001"

    # Confirmed correct token IDs (old IDs 26000/26009 were wrong)
    MASTER_TOKENS = {"40000001": "NIDX_40000001", "40000003": "NIDX_40000003"}
    master = MASTER_TOKENS.get(num)

    # Try all known formats — stop at first success
    CANDIDATES = [base, f"NSE_{num}", num]
    if master:
        CANDIDATES.insert(0, master)  # try master token first

    end_time   = int(time.time() * 1000)
    start_time = end_time - (lookback_days * 24 * 60 * 60 * 1000)

    last_err = "no attempt"
    for scrip in CANDIDATES:
        try:
            resp = requests.get(
                HISTORICAL_URL,
                params={"scrip-codes": scrip, "start_time": start_time, "end_time": end_time},
                headers=auth_headers(access_token),
                timeout=HISTORICAL_TIMEOUT,
            )
            body = resp.json()
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code} for {scrip}: {body}"
                continue
            
            # Correctly parse nested candles structure: body["data"][scrip]["candles"]
            candles = []
            data_dict = body.get("data", {})
            if isinstance(data_dict, dict):
                if scrip in data_dict and isinstance(data_dict[scrip], dict):
                    candles = data_dict[scrip].get("candles", [])
                else:
                    # Fallback: check any key in data
                    for k, v in data_dict.items():
                        if isinstance(v, dict) and "candles" in v:
                            candles = v["candles"]
                            break

            if isinstance(candles, list) and candles:
                parsed_candles = []
                for c_item in candles:
                    if isinstance(c_item, dict):
                        # API returns timestamp in seconds, convert to milliseconds
                        ts = int(c_item.get("ts", 0)) * 1000
                        parsed_candles.append([
                            ts,
                            float(c_item.get("o", 0)),
                            float(c_item.get("h", 0)),
                            float(c_item.get("l", 0)),
                            float(c_item.get("c", 0)),
                            int(c_item.get("v", 0))
                        ])
                    elif isinstance(c_item, (list, tuple)):
                        parsed_candles.append(list(c_item))
                if parsed_candles:
                    return parsed_candles, None          # success
            last_err = f"{scrip} returned 0 candles — response: {body}"
        except Exception as ex:
            last_err = f"{scrip}: {ex}"

    # All REST formats exhausted — return empty so caller uses WS candles
    return [], f"INDmoney REST: {last_err}"


def detect_support_resistance(df, n_levels=5, tolerance=0.003):
    highs = df["high"].values; lows = df["low"].values; window = 5
    p_high = []; p_low = []
    for i in range(window, len(df) - window):
        if highs[i] >= max(highs[i-window:i+window+1]): p_high.append(float(highs[i]))
        if lows[i]  <= min(lows[i-window:i+window+1]):  p_low.append(float(lows[i]))
    def cluster_levels(pivots, n):
        if not pivots: return []
        pivots = sorted(pivots); clusters = [[pivots[0]]]
        for p in pivots[1:]:
            if abs(p - clusters[-1][-1]) / clusters[-1][-1] <= tolerance: clusters[-1].append(p)
            else: clusters.append([p])
        clusters.sort(key=len, reverse=True)
        return [round(sum(c)/len(c), 2) for c in clusters[:n]]
    return cluster_levels(p_low, n_levels), cluster_levels(p_high, n_levels)

def calculate_pivots(high: float, low: float, close: float, pivot_type: str) -> dict[str, float]:
    if pivot_type == "None" or high <= 0 or low <= 0 or close <= 0:
        return {}
    
    pivots = {}
    if pivot_type == "Traditional":
        pp = (high + low + close) / 3.0
        pivots["PP"] = pp
        pivots["R1"] = 2.0 * pp - low
        pivots["S1"] = 2.0 * pp - high
        pivots["R2"] = pp + (high - low)
        pivots["S2"] = pp - (high - low)
        pivots["R3"] = high + 2.0 * (pp - low)
        pivots["S3"] = low - 2.0 * (high - pp)
    elif pivot_type == "Camarilla":
        range_val = high - low
        pivots["PP"] = (high + low + close) / 3.0
        pivots["R1"] = close + range_val * 1.1 / 12.0
        pivots["S1"] = close - range_val * 1.1 / 12.0
        pivots["R2"] = close + range_val * 1.1 / 6.0
        pivots["S2"] = close - range_val * 1.1 / 6.0
        pivots["R3"] = close + range_val * 1.1 / 4.0
        pivots["S3"] = close - range_val * 1.1 / 4.0
        pivots["R4"] = close + range_val * 1.1 / 2.0
        pivots["S4"] = close - range_val * 1.1 / 2.0
    elif pivot_type == "Fibonacci":
        pp = (high + low + close) / 3.0
        range_val = high - low
        pivots["PP"] = pp
        pivots["R1"] = pp + 0.382 * range_val
        pivots["S1"] = pp - 0.382 * range_val
        pivots["R2"] = pp + 0.618 * range_val
        pivots["S2"] = pp - 0.618 * range_val
        pivots["R3"] = pp + 1.000 * range_val
        pivots["S3"] = pp - 1.000 * range_val
    return pivots

def render_index_chart(name, index_token, access_token, sr_pivot_type: str = "None"):
    import sys
    import warnings
    sys.modules['warnings'] = warnings

    # Render intraday candlestick chart for a NIFTY index.
    ws_key   = f"_idx_ws_candles_{index_token}"
    rest_key = f"_idx_rest_candles_{index_token}"
    rest_ts  = f"_idx_rest_ts_{index_token}"

    ws_candles   = st.session_state.get(ws_key, [])
    rest_candles = st.session_state.get(rest_key, [])

    # Fetch REST seed once per session (or if cache is stale > 5 min when market is open / > 24 h when closed)
    _ms_rc = market_status()
    now_ts = time.time()
    last_rest = st.session_state.get(rest_ts, 0)
    rest_stale = (now_ts - last_rest) > (86400 if not _ms_rc["is_open"] else 300)
    if not rest_candles or rest_stale:
        with st.spinner(f"Seeding {name} history from INDmoney..."):
            _res = fetch_index_candles(index_token, access_token, lookback_days=7)
            seed, err = (_res if isinstance(_res, tuple) else (_res, None))
            if err:
                st.session_state[f"_idx_rest_err_{index_token}"] = err
            else:
                st.session_state.pop(f"_idx_rest_err_{index_token}", None)
        if seed:
            st.session_state[rest_key] = seed
            st.session_state[rest_ts]  = now_ts
            rest_candles = seed

    # Merge: REST provides the historical base; WS candles overlay / extend it.
    if ws_candles and rest_candles:
        ws_start = ws_candles[0][0]
        base = [c for c in rest_candles if c[0] < ws_start]
        candles = base + ws_candles
    elif ws_candles:
        candles = ws_candles
    else:
        candles = rest_candles

    if not candles:
        source_hint = "Waiting for live WS ticks" if _ms_rc["is_open"] else "No candles available (market closed)"
        err_msg = st.session_state.get(f"_idx_rest_err_{index_token}")
        border_col = "#059669" if not err_msg else "#ef4444"
        title_col = "#059669" if not err_msg else "#ef4444"
        title_text = f"📊 {name}" if not err_msg else f"📊 {name} — Offline"
        err_html = f"<br><span style='color:#dc2626;font-size:0.75rem;font-weight:600;'>⚠️ Error: {err_msg}</span>" if err_msg else ""
        
        st.markdown(
            f'<div style="background:#ffffff;border:1px solid #e2e8f0;border-left:3.5px solid {border_col};'
            f'border-bottom:3.5px solid #cbd5e1;border-radius:8px;padding:1rem 1.2rem;margin:0.5rem 0;box-shadow:0 1px 3px rgba(0,0,0,0.05);">'
            f'<div style="color:{title_col};font-size:0.75rem;font-weight:600;letter-spacing:.06em;'
            f'text-transform:uppercase;margin-bottom:4px;">{title_text}</div>'
            f'<div style="color:#0f172a;font-size:0.82rem;font-weight:500;">{source_hint}<br>'
            f'<span style="color:#64748b;font-size:0.75rem;">'
            f'WS ticks will appear within 3 s of connecting.</span>'
            f'{err_html}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        return
    try:
        if candles and isinstance(candles[0], (list, tuple)):
            df = pd.DataFrame(candles,
                              columns=["timestamp", "open", "high", "low", "close", "volume"])
        else:
            df = pd.DataFrame(candles)
        for _c in ("open", "high", "low", "close", "volume"):
            df[_c] = pd.to_numeric(df[_c], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])  # keep volume=0
    except Exception as e:
        st.caption(f"Parse error for {name}: {e}"); return
    if df.empty:
        st.info(f"No usable candles returned for {name}."); return
    ts_s = float(df["timestamp"].iloc[0]); ts_u = "s" if ts_s < 1_000_000_000_000 else "ms"
    df["dt"] = (pd.to_datetime(df["timestamp"], unit=ts_u, utc=True) + pd.Timedelta(hours=5, minutes=30)).dt.tz_localize(None)
    df["date"] = df["dt"].dt.date
    today_date = df["date"].iloc[-1]; today_df = df[df["date"] == today_date].copy()
    if today_df.empty: today_df = df.copy()
    tp = (today_df["high"] + today_df["low"] + today_df["close"]) / 3
    today_df = today_df.copy(); today_df["vwap"] = (tp * today_df["volume"]).cumsum() / today_df["volume"].cumsum()
    latest_vwap = float(today_df["vwap"].iloc[-1])
    orb_df = today_df.head(15); orb_h = float(orb_df["high"].max()); orb_l = float(orb_df["low"].min())
    support, resistance = detect_support_resistance(df, n_levels=5)
    
    # Calculate index daily pivots from history
    all_dates = sorted(df["date"].unique())
    prev_high, prev_low, prev_close = 0.0, 0.0, 0.0
    if len(all_dates) >= 2:
        prev_date = all_dates[-2]
        prev_df = df[df["date"] == prev_date]
        prev_high = float(prev_df["high"].max()) if not prev_df.empty else 0.0
        prev_low = float(prev_df["low"].min()) if not prev_df.empty else 0.0
        prev_close = float(prev_df["close"].iloc[-1]) if not prev_df.empty else 0.0
    else:
        prev_high = float(df["high"].max())
        prev_low = float(df["low"].min())
        prev_close = float(df["close"].iloc[-1])

    daily_pivots = calculate_pivots(prev_high, prev_low, prev_close, sr_pivot_type)

    if len(today_df) > 90:
        today_df = today_df.iloc[-90:].reset_index(drop=True)
    ltp = float(today_df["close"].iloc[-1]); open0 = float(today_df["open"].iloc[0])
    chg = ltp - open0; chg_pct = (chg / open0 * 100) if open0 else 0; is_up = chg >= 0
    accent = "#26a69a" if is_up else "#ef5350"; bull_col = "#26a69a"; bear_col = "#ef5350"
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.02)
    # Ensure float64 columns
    for _col in ("open", "high", "low", "close", "volume"):
        today_df[_col] = pd.to_numeric(today_df[_col], errors="coerce").fillna(0)
    fig.add_trace(go.Candlestick(
        x=today_df["dt"].tolist(),
        open=today_df["open"].astype(float).tolist(),
        high=today_df["high"].astype(float).tolist(),
        low=today_df["low"].astype(float).tolist(),
        close=today_df["close"].astype(float).tolist(),
        increasing=dict(line=dict(color=bull_col, width=1.2), fillcolor=bull_col),
        decreasing=dict(line=dict(color=bear_col, width=1.2), fillcolor=bear_col),
        name="Price", showlegend=False), row=1, col=1)
    bar_colors = [bull_col if c >= o else bear_col
                  for o, c in zip(today_df["open"].astype(float), today_df["close"].astype(float))]
    fig.add_trace(go.Bar(
        x=today_df["dt"].tolist(),
        y=today_df["volume"].astype(float).tolist(),
        marker_color=bar_colors, marker_opacity=0.45,
        name="Volume", showlegend=False), row=2, col=1)
        
    for label, val, col, dash in [("VWAP", latest_vwap, "#1d4ed8", "dash"),
                                    ("ORB H", orb_h, "#059669", "dashdot"),
                                    ("ORB L", orb_l, "#dc2626", "dashdot")]:
        if val > 0:
            fig.add_hline(y=val, row=1, col=1, line_dash=dash, line_color=col, line_width=1.3,
                annotation_text=f" {label} {val:,.2f}",
                annotation_font=dict(color=col, size=10, family="JetBrains Mono, monospace"),
                annotation_position="right")
                
    # Add TradingView Daily Pivot lines
    if daily_pivots:
        for lvl_name, lvl_val in daily_pivots.items():
            if lvl_val <= 0:
                continue
            if lvl_name == "PP":
                color = "#2563eb"
            elif lvl_name.startswith("R"):
                color = "#7c3aed"
            else:
                color = "#b45309"
            fig.add_hline(
                y=lvl_val, row=1, col=1,
                line_dash="dot", line_color=color, line_width=1.1,
                annotation_text=f" {lvl_name} {lvl_val:,.1f}",
                annotation_font=dict(color=color, size=9, family="JetBrains Mono, monospace"),
                annotation_position="left"
            )
            
    for r in sorted([v for v in resistance if v > ltp]):
        fig.add_hline(y=r, row=1, col=1, line_dash="dot", line_color="#7c3aed", line_width=1.0,
            annotation_text=f" R {r:,.2f}",
            annotation_font=dict(color="#7c3aed", size=9, family="JetBrains Mono, monospace"),
            annotation_position="right")
    for s in sorted([v for v in support if v < ltp], reverse=True):
        fig.add_hline(y=s, row=1, col=1, line_dash="dot", line_color="#b45309", line_width=1.0,
            annotation_text=f" S {s:,.2f}",
            annotation_font=dict(color="#b45309", size=9, family="JetBrains Mono, monospace"),
            annotation_position="right")
    arrow_sym = "up" if is_up else "dn"
    fig.add_annotation(xref="paper", x=1.0, y=ltp, yref="y", text=f" > {ltp:,.2f}",
        showarrow=False, xanchor="left",
        font=dict(color=accent, size=13, family="JetBrains Mono, monospace"))
    n_days = len(df["date"].unique())
    fig.update_layout(
        title=dict(text=(f"<b style='font-size:15px;color:#0f172a'>{name}</b>"
            f"<span style='font-size:12px;color:{accent};margin-left:10px'> {abs(chg):,.2f} ({abs(chg_pct):.2f}%)</span>"
            f"<span style='font-size:9px;color:#475569;margin-left:14px'>  S/R from {n_days}d pivot clustering</span>"),
            x=0.01, y=0.97, xanchor="left"),
        paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc", height=440,
        margin=dict(l=8, r=140, t=46, b=8),
        xaxis=dict(showgrid=False, zeroline=False, color="#64748b",
            tickfont=dict(size=10, color="#64748b"), rangeslider=dict(visible=False)),
        xaxis2=dict(showgrid=False, zeroline=False, color="#64748b",
            tickfont=dict(size=10, color="#64748b")),
        yaxis=dict(showgrid=True, gridcolor="#e2e8f0", zeroline=False, side="right",
            color="#475569", tickfont=dict(size=10, color="#475569", family="JetBrains Mono, monospace"),
            tickformat=",.2f"),
        yaxis2=dict(showgrid=False, zeroline=False, color="#64748b", side="right",
            tickfont=dict(size=9, color="#64748b")),
        shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1,
            line=dict(color=accent, width=1), fillcolor="rgba(0,0,0,0)")],
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    c1, c2 = st.columns(2)
    with c1:
        r_above = sorted([v for v in resistance if v > ltp])
        if r_above:
            st.markdown("**Resistance**", unsafe_allow_html=True)
            for r in r_above:
                dist = (r - ltp) / ltp * 100
                st.markdown(f"<span style='color:#c084fc;font-family:JetBrains Mono,monospace;font-size:0.85rem;'>{r:,.2f}</span>"
                    f"<span style='color:#4a6480;font-size:0.78rem;'> +{dist:.2f}%</span>", unsafe_allow_html=True)
    with c2:
        s_below = sorted([v for v in support if v < ltp], reverse=True)
        if s_below:
            st.markdown("**Support**", unsafe_allow_html=True)
            for s in s_below:
                dist = (ltp - s) / ltp * 100
                st.markdown(f"<span style='color:#fbbf24;font-family:JetBrains Mono,monospace;font-size:0.85rem;'>{s:,.2f}</span>"
                    f"<span style='color:#4a6480;font-size:0.78rem;'> -{dist:.2f}%</span>", unsafe_allow_html=True)



def render_candlestick_chart(stock_name: str, stock_token: str, signal_type: str, live_quote: dict | None = None, sr_pivot_type: str = "None") -> None:
    import sys
    import warnings
    sys.modules['warnings'] = warnings

    hist = st.session_state.historical_data.get(stock_token)
    if not hist:
        st.caption(f"No historical data for {stock_name}")
        return

    today_candles = hist.get("today_candles", [])
    is_up = signal_type in ("BREAKOUT", "LONG")
    bull_col = "#26a69a"
    bear_col = "#ef5350"
    accent   = bull_col if is_up else bear_col

    if today_candles:
        cdf = pd.DataFrame(today_candles)
        # Ensure all numeric columns are float64 (API may return mixed types)
        for col in ("open", "high", "low", "close", "volume", "timestamp"):
            cdf[col] = pd.to_numeric(cdf[col], errors="coerce").fillna(0)
        ts_s = float(cdf["timestamp"].iloc[0])
        tu = "s" if ts_s < 1_000_000_000_000 else "ms"
        # Windows-safe IST conversion: avoid tz_convert("Asia/Kolkata") which
        # requires the tzdata package.  Adding a fixed +5:30 offset is equivalent.
        _IST_OFFSET = pd.Timedelta(hours=5, minutes=30)
        cdf["dt"] = (pd.to_datetime(cdf["timestamp"], unit=tu, utc=True) + _IST_OFFSET).dt.tz_localize(None)

        if live_quote:
            lq = parse_quote(live_quote)
            if lq["close"] > 0:
                last_dt = cdf["dt"].iloc[-1] + pd.Timedelta(minutes=1)
                new_row = {
                    "timestamp": int(last_dt.timestamp() * 1000),
                    "open":   float(lq["open"] or lq["close"]),
                    "high":   float(lq["high"] or lq["close"]),
                    "low":    float(lq["low"]  or lq["close"]),
                    "close":  float(lq["close"]),
                    "volume": float(lq["volume"]),
                    "dt":     last_dt,
                }
                cdf = pd.concat([cdf, pd.DataFrame([new_row])], ignore_index=True)
                # Re-coerce after concat to prevent object-dtype columns
                for col in ("open", "high", "low", "close", "volume"):
                    cdf[col] = pd.to_numeric(cdf[col], errors="coerce").fillna(0)
    else:
        cdf = pd.DataFrame([{
            "dt":     pd.Timestamp.now(),
            "open":   float(hist.get("last_open",  hist.get("last_close", 0))),
            "high":   float(hist.get("last_high",  hist.get("last_close", 0))),
            "low":    float(hist.get("last_low",   hist.get("last_close", 0))),
            "close":  float(hist.get("last_close", 0)),
            "volume": float(hist.get("last_volume", 0)),
        }])

    vwap  = hist.get("vwap", 0)
    ema20 = hist.get("ema20", 0)
    orb_h = hist.get("orb_high", 0)
    orb_l = hist.get("orb_low", 0)
    ltp   = float(cdf["close"].iloc[-1])

    # Calculate daily pivots
    prev_high = hist.get("prev_day_high", 0.0)
    prev_low = hist.get("prev_day_low", 0.0)
    prev_close = hist.get("prev_day_close", 0.0)
    daily_pivots = calculate_pivots(prev_high, prev_low, prev_close, sr_pivot_type)

    # S/R from all available candles
    support, resistance = detect_support_resistance(cdf, n_levels=4) if len(cdf) >= 15 else ([], [])

    if len(cdf) > 90:
        cdf = cdf.iloc[-90:].reset_index(drop=True)

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.02,
    )

    # Pass plain Python lists to plotly — avoids object-dtype / Generic[] TypeError
    fig.add_trace(go.Candlestick(
        x=cdf["dt"].tolist(),
        open=cdf["open"].astype(float).tolist(),
        high=cdf["high"].astype(float).tolist(),
        low=cdf["low"].astype(float).tolist(),
        close=cdf["close"].astype(float).tolist(),
        increasing=dict(line=dict(color=bull_col, width=1.2), fillcolor=bull_col),
        decreasing=dict(line=dict(color=bear_col, width=1.2), fillcolor=bear_col),
        name="Price", showlegend=False,
    ), row=1, col=1)

    bar_colors = [bull_col if c >= o else bear_col
                  for o, c in zip(cdf["open"].astype(float), cdf["close"].astype(float))]
    fig.add_trace(go.Bar(
        x=cdf["dt"].tolist(),
        y=cdf["volume"].astype(float).tolist(),
        marker_color=bar_colors, marker_opacity=0.55,
        name="Volume", showlegend=False,
    ), row=2, col=1)

    for label, val, colour, dash in [
        ("VWAP",   vwap,  "#1d4ed8", "dash"),
        ("EMA 20", ema20, "#7c3aed", "dot"),
        ("ORB H",  orb_h, "#059669", "dashdot"),
        ("ORB L",  orb_l, "#dc2626", "dashdot"),
    ]:
        if val > 0:
            fig.add_hline(
                y=val, row=1, col=1,
                line_dash=dash, line_color=colour, line_width=1.3,
                annotation_text=f" {label} {val:.2f}",
                annotation_font=dict(color=colour, size=11, family="JetBrains Mono, monospace"),
                annotation_position="right",
            )

    # Add TradingView Daily Pivot lines
    if daily_pivots:
        for lvl_name, lvl_val in daily_pivots.items():
            if lvl_val <= 0:
                continue
            if lvl_name == "PP":
                color = "#2563eb"
            elif lvl_name.startswith("R"):
                color = "#7c3aed"
            else:
                color = "#b45309"
            fig.add_hline(
                y=lvl_val, row=1, col=1,
                line_dash="dot", line_color=color, line_width=1.1,
                annotation_text=f" {lvl_name} {lvl_val:,.1f}",
                annotation_font=dict(color=color, size=9, family="JetBrains Mono, monospace"),
                annotation_position="left"
            )

    # Resistance levels — purple dotted
    for r in sorted([v for v in resistance if v > ltp]):
        fig.add_hline(y=r, row=1, col=1, line_dash="dot", line_color="#7c3aed", line_width=1.0,
                      annotation_text=f" R {r:,.2f}",
                      annotation_font=dict(color="#7c3aed", size=9, family="JetBrains Mono, monospace"),
                      annotation_position="right")

    # Support levels — amber dotted
    for s in sorted([v for v in support if v < ltp], reverse=True):
        fig.add_hline(y=s, row=1, col=1, line_dash="dot", line_color="#b45309", line_width=1.0,
                      annotation_text=f" S {s:,.2f}",
                      annotation_font=dict(color="#b45309", size=9, family="JetBrains Mono, monospace"),
                      annotation_position="right")

    fig.add_annotation(
        xref="paper", x=1.0, y=ltp, yref="y",
        text=f" ▶ {ltp:.2f}",
        showarrow=False, xanchor="left",
        font=dict(color=accent, size=13, family="JetBrains Mono, monospace"),
    )

    fig.update_layout(
        title=dict(
            text=f"<b style='font-size:15px;color:#0f172a'>{stock_name}</b>"
                 f"<span style='font-size:11px;color:{accent};margin-left:10px'> {signal_type}</span>",
            x=0.01, y=0.97, xanchor="left",
        ),
        paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc",
        height=380, margin=dict(l=8, r=130, t=42, b=8),
        xaxis=dict(showgrid=False, zeroline=False, color="#64748b",
                   tickfont=dict(size=10, color="#64748b"), rangeslider=dict(visible=False)),
        xaxis2=dict(showgrid=False, zeroline=False, color="#64748b",
                    tickfont=dict(size=10, color="#64748b")),
        yaxis=dict(showgrid=True, gridcolor="#e2e8f0", gridwidth=1, zeroline=False,
                   color="#475569", tickfont=dict(size=10, color="#475569", family="JetBrains Mono, monospace"),
                   tickformat=".2f", side="right"),
        yaxis2=dict(showgrid=False, zeroline=False, color="#64748b",
                    tickfont=dict(size=9, color="#64748b"), side="right"),
        shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1,
                     line=dict(color=accent, width=1), fillcolor="rgba(0,0,0,0)")],
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# -- FEED STATUS FRAGMENT -------------------------------------------------------
# Tiny 3-second fragment: only renders the status bar (< 10 DOM nodes).

@st.fragment(run_every=3)
def feed_status_fragment(access_token: str) -> None:
    """Lightweight 3-second ticker: status bar + auto-history heartbeat only."""
    import sys; import warnings; sys.modules['warnings'] = warnings
    _fs2  = get_feed_state()
    _mkt2, _, _fst2 = snapshot_feed(_fs2)
    _ms3  = market_status()
    _AUTO3 = 15 * 60

    # Apply any background-refresh results first
    apply_bg_hist_results()

    _tok_ok3 = st.session_state.token_accepted and bool(clean_token(access_token))
    _bg_running3 = _get_bg_hist_state()["running"]
    # Auto-reset stuck "Loading" status (blocking load was interrupted)
    if st.session_state.history_status == "Loading":
        _started3 = st.session_state.get("history_started_at") or 0
        if time.time() - _started3 > 300:
            st.session_state.history_status = "Failed"
            st.session_state.history_started_at = None
    if _tok_ok3 and not _bg_running3:
        if not st.session_state.historical_data and not st.session_state.get("history_attempted", False):
            trigger_bg_hist_refresh(access_token, HISTORICAL_WORKERS)
            st.session_state.history_attempted = True
        elif _ms3["is_open"]:
            _lh3 = st.session_state.auto_history_last_load or 0
            if (time.time() - _lh3) >= _AUTO3:
                trigger_bg_hist_refresh(access_token, HISTORICAL_WORKERS)
        elif _ms3["is_pre_open"]:
            _td3 = _ms3["now_ist"].date()
            _done3 = (st.session_state.auto_history_preopen_done
                      and st.session_state.auto_history_preopen_date == _td3)
            if not _done3:
                trigger_bg_hist_refresh(access_token, HISTORICAL_WORKERS)
                st.session_state.auto_history_preopen_done = True
                st.session_state.auto_history_preopen_date = _td3

    _feed_st3 = _fst2["status"]
    _lq3      = len(_mkt2)
    _hs3      = len(st.session_state.historical_data)
    _hist_st3 = st.session_state.history_status
    _recon3   = _fst2["reconnects"]
    _tick3    = format_last_update(_fst2["last_update"])

    if _ms3["is_open"] and st.session_state.auto_history_last_load:
        _sl3 = max(0, int(_AUTO3 - (time.time() - st.session_state.auto_history_last_load)))
        _next3 = f"{_sl3//60}m {_sl3%60:02d}s"
    elif _ms3["is_pre_open"]:
        _next3 = "Pre-open"
    else:
        _next3 = "Manual"

    if _feed_st3 in ("Live", "Connected"):
        _pbg3, _pfg3 = "rgba(34,197,94,0.15)", "#22c55e"
    elif _feed_st3 in ("Connecting", "Reconnecting", "Starting", "Subscribing"):
        _pbg3, _pfg3 = "rgba(245,158,11,0.15)", "#f59e0b"
    elif _feed_st3 == "Error":
        _pbg3, _pfg3 = "rgba(239,68,68,0.15)", "#ef4444"
    else:
        _pbg3, _pfg3 = "rgba(100,116,139,0.15)", "#94a3b8"

    def _s3(lbl, val):
        return (f'<div style="display:flex;flex-direction:column;gap:2px;min-width:0;">'
                f'<span style="font-size:.68rem;font-weight:700;color:#4a6480;'
                f'text-transform:uppercase;letter-spacing:.07em;white-space:nowrap;">{lbl}</span>'
                f'<span style="font-size:1.1rem;font-weight:700;color:#e0e8f5;'
                f'font-family:JetBrains Mono,monospace;white-space:nowrap;">{val}</span></div>')

    st.markdown(
        f'<div style="display:flex;align-items:center;gap:1.5rem;flex-wrap:wrap;'
        f'background:#111827;border:1px solid #1e2a3a;border-top:2px solid #2a5080;'
        f'border-radius:8px;padding:0.9rem 1.2rem;margin-bottom:0.8rem;">'
        f'<div style="display:flex;flex-direction:column;gap:2px;min-width:0;">'
        f'<span style="font-size:.68rem;font-weight:700;color:#4a6480;'
        f'text-transform:uppercase;letter-spacing:.07em;">Feed Status</span>'
        f'<span style="font-size:1.1rem;font-weight:700;font-family:JetBrains Mono,monospace;'
        f'white-space:nowrap;background:{_pbg3};color:{_pfg3};'
        f'padding:1px 8px;border-radius:4px;">{_feed_st3}</span></div>'
        f'<div style="width:1px;height:36px;background:#1e2a3a;flex-shrink:0;"></div>'
        f'{_s3("Live Quotes", str(_lq3))}'
        f'{_s3("Historical", str(_hs3))}'
        f'{_s3("History Status", _hist_st3)}'
        f'{_s3("Reconnects", str(_recon3))}'
        f'{_s3("Last Tick", _tick3)}'
        f'{_s3("Next Hist Refresh", _next3)}'
        f'</div>',
        unsafe_allow_html=True,
    )
    if st.session_state.token_accepted and _fst2["last_error"]:
        st.caption(f"Latest feed message: {_fst2['last_error']}")

    # Accumulate index ticks every 3 s so index_charts_fragment has fresh candles
    # even before its 60-s render cycle fires.
    _fs_idx = get_feed_state()
    with _fs_idx.lock:
        _idx_ticks = dict(_fs_idx.index_data)
    for _ik2, _iq2 in _idx_ticks.items():
        accumulate_index_tick(_ik2, _iq2)

    # Globally render and update the top header index tiles (updates every 3 s across all tabs)
    update_index_header()


# â”€â”€ INDEX CHARTS FRAGMENT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Dedicated fragment for NIFTY 50 + BANK NIFTY intraday charts.
# Runs every 3 s — aligned with the 3-s scanner.

@st.fragment(run_every=3)
def index_charts_fragment(access_token: str, sr_pivot_type: str = "None") -> None:
    """Auto-refreshing NIFTY 50 and BANK NIFTY panel.

    Live tile values come directly from feed_state.index_data (INDmoney WebSocket).
    Chart candles are accumulated from WS ticks via accumulate_index_tick(), with an
    INDmoney REST seed fetch at session startup to backfill pre-connection history.
    Yahoo Finance is not used.
    """
    import sys; import warnings; sys.modules['warnings'] = warnings
    _ms_i = market_status()
    # Ticks are accumulated every 3 s by feed_status_fragment.
    # This 3-s render reads the already-built session-state candles.
    _fs = get_feed_state()
    with _fs.lock:
        _idx_snapshot = dict(_fs.index_data)

    _refresh_lbl = (
        "Live — updating every 3 s"
        if _ms_i["is_open"]
        else "Market closed — showing last session data"
    )
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:0.6rem;">'
        f'<p class="section-heading" style="margin:0;">📊 INDEX PULSE — NIFTY 50 &amp; BANK NIFTY</p>'
        f'<span style="font-size:0.75rem;color:#4a6480;font-family:JetBrains Mono,monospace;">'
        f'{_refresh_lbl}</span></div>',
        unsafe_allow_html=True,
    )

    # Force-refresh — clears accumulated WS candles + REST seed so next render refetches
    if st.button("🔄 Refresh Charts", key="idx_frag_refresh"):
        for _ik in INDEX_INSTRUMENTS:
            st.session_state.pop(f"_idx_ws_candles_{_ik}", None)
            st.session_state.pop(f"_idx_rest_candles_{_ik}", None)
            st.session_state.pop(f"_idx_rest_ts_{_ik}", None)

    # Globally render and update the top header index tiles
    update_index_header()

    # -- WS Feed diagnostics (collapsible) --
    with st.expander("Index WS Feed Diagnostics", expanded=False):
        st.caption("Shows exactly what the workstation received from the WebSocket.")
        _fs_diag = get_feed_state()
        with _fs_diag.lock:
            _diag_idx    = dict(_fs_diag.index_data)
            _diag_status = _fs_diag.status
            _diag_err    = _fs_diag.last_error
            _diag_raw    = _fs_diag.last_raw_message
        st.markdown(f"**Feed status:** `{_diag_status}`")
        if _diag_err:
            st.error(f"Last error: {_diag_err}")
        st.markdown("**`feed_state.index_data` (what WS ticks populated):**")
        if _diag_idx:
            for _k, _v in _diag_idx.items():
                st.code(f"{_k}: {json.dumps(_v, indent=2)}", language="json")
        else:
            st.warning("index_data is EMPTY -- no index ticks received yet. "
                       "If the standalone tester works, check the subscription payload above.")
        st.markdown("**Accumulated WS 1-min candles (last 3 per index):**")
        for _ik in INDEX_INSTRUMENTS:
            _wsc = st.session_state.get(f"_idx_ws_candles_{_ik}", [])
            _nm  = INDEX_INSTRUMENTS[_ik]
            st.caption(f"{_nm} ({_ik}): {len(_wsc)} candles")
            if _wsc:
                st.json(_wsc[-3:])
        st.markdown("**Last raw WS message (500 chars):**")
        st.code(_diag_raw or "(none yet)", language="json")

    # Side-by-side charts
    _ic1, _ic2 = st.columns(2)
    with _ic1:
        render_index_chart("NIFTY 50",   "NIDX:40000001", access_token, sr_pivot_type=sr_pivot_type)
    with _ic2:
        render_index_chart("BANK NIFTY", "NIDX:40000003", access_token, sr_pivot_type=sr_pivot_type)


# â”€â”€ LIVE SCANNER FRAGMENT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# run_every=3 — fragment rerenders every 3s without touching the rest of the page.
# The decorator argument must be a literal, not a function call, because Python
# evaluates @st.fragment(run_every=fn()) ONCE at import time — if the feed isn't
# started yet, fn() returns None and auto-refresh never activates.

def calculate_rsi(candles: list, period: int = 14) -> float:
    if len(candles) < period + 1:
        return 50.0
    closes = [float(c[4]) for c in candles]
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


@st.cache_data(ttl=300)
def fetch_news_sentiment(stock_name: str) -> str:
    """Fetch recent news headlines from Google News RSS and determine sentiment (Positive/Negative/Neutral)."""
    import urllib.request
    import xml.etree.ElementTree as ET
    import urllib.parse
    
    # Heuristic sentiment keywords
    POS_WORDS = {
        'buy', 'positive', 'raise', 'target', 'growth', 'jump', 'surge', 'bullish', 
        'record', 'profit', 'double', 'up', 'gain', 'beats', 'expansion', 'high', 
        'acquisition', 'deal', 'order', 'upgrade', 'strong', 'soars', 'climb', 'outperform'
    }
    NEG_WORDS = {
        'sell', 'negative', 'cut', 'loss', 'fall', 'drop', 'plunge', 'bearish', 
        'debt', 'decline', 'down', 'hit', 'miss', 'downgrade', 'probe', 'fine', 
        'warning', 'low', 'crash', 'slump', 'tumbles', 'weak', 'lower', 'underperform'
    }
    
    try:
        # Build search query: e.g. "TATASTEEL Stock News"
        query = f"{stock_name} Stock News"
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            xml_data = response.read()
        
        root = ET.fromstring(xml_data)
        items = root.findall('.//item')
        if not items:
            return "Neutral"
            
        pos_count = 0
        neg_count = 0
        
        # Look at the top 5 recent headlines
        for item in items[:5]:
            title = item.find('title')
            if title is not None and title.text:
                title_lower = title.text.lower()
                words = title_lower.split()
                for w in words:
                    w_clean = w.strip('.,!?;:"\'()[]{}')
                    if w_clean in POS_WORDS:
                        pos_count += 1
                    elif w_clean in NEG_WORDS:
                        neg_count += 1
                        
        if pos_count > neg_count + 1:
            return "Positive"
        elif neg_count > pos_count + 1:
            return "Negative"
        else:
            return "Neutral"
            
    except Exception:
        return "Neutral"


def generate_nifty_option_chain_and_signal(nifty_ltp: float, candles: list) -> dict | None:
    if nifty_ltp is None or nifty_ltp <= 0:
        return None
    
    rsi = calculate_rsi(candles) if candles else 50.0
    
    support_lvl = nifty_ltp - 120.0
    resistance_lvl = nifty_ltp + 120.0
    if candles and len(candles) >= 15:
        try:
            import pandas as pd
            df_idx = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            sups, refs = detect_support_resistance(df_idx)
            active_sups = [s for s in sups if s < nifty_ltp]
            active_refs = [r for r in refs if r > nifty_ltp]
            if active_sups:
                support_lvl = max(active_sups)
            if active_refs:
                resistance_lvl = min(active_refs)
        except Exception:
            pass

    import datetime
    today = datetime.date.today()
    days_ahead = 3 - today.weekday()
    if days_ahead < 0:
        days_ahead += 7
    next_thursday = today + datetime.timedelta(days_ahead)
    expiry_str = next_thursday.strftime("%d-%b-%Y").upper()

    atm_strike = int(round(nifty_ltp / 50.0) * 50)
    
    if rsi >= 56:
        signal = "BUY CALL (CE)"
        pcr = 1.15 + (rsi - 50) * 0.015
        suggested_strike = atm_strike
        option_type = "CE"
    elif rsi <= 44:
        signal = "BUY PUT (PE)"
        pcr = 0.85 - (50 - rsi) * 0.015
        suggested_strike = atm_strike
        option_type = "PE"
    else:
        signal = "NEUTRAL / NO TRADE"
        pcr = 0.95 + (rsi - 50) * 0.005
        suggested_strike = atm_strike
        option_type = "CE"
        
    contract = f"NIFTY {expiry_str} {suggested_strike} {option_type}"
    
    atm_premium = nifty_ltp * 0.008
    intrinsic = max(0, nifty_ltp - suggested_strike) if option_type == "CE" else max(0, suggested_strike - nifty_ltp)
    extrinsic = atm_premium
    entry_price = float(round(intrinsic + extrinsic, 1))
    if entry_price < 20.0:
        entry_price = 20.0
        
    target = float(round(entry_price * 1.50, 1))
    stop_loss = float(round(entry_price * 0.70, 1))
    
    return {
        "contract": contract,
        "entry_price": entry_price,
        "target": target,
        "stop_loss": stop_loss,
        "signal": signal,
        "nifty_ltp": nifty_ltp,
        "pcr": float(round(pcr, 2)),
        "support": float(round(support_lvl, 1)),
        "resistance": float(round(resistance_lvl, 1)),
        "locked_spot_ltp": nifty_ltp,
        "base_premium": entry_price,
        "option_type": option_type
    }

@st.fragment(run_every=3)
def live_scanner_fragment(
    access_token: str,
    min_change: float,
    min_rvol: float,
    min_breakout_score: int,
    volume_premium_min: float,
    volume_premium_max: float,
    historical_workers: int,
    sr_pivot_type: str = "None",
) -> None:
    """Everything that needs to refresh with live data — runs as an isolated fragment."""
    import sys; import warnings; sys.modules['warnings'] = warnings

    # Re-read live state inside the fragment so each refresh gets fresh data
    _fs   = get_feed_state()
    _mkt, _idx_d, _fst = snapshot_feed(_fs)
    _ms2  = market_status()
    _now2 = _ms2["now_ist"]
    _AUTO = 15 * 60

    # â”€â”€ Auto historical refresh INSIDE fragment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Apply any completed background-refresh results
    apply_bg_hist_results()

    # ── 15-Minute Stable Latching (Locking) Initialization & Auto-Reset ──
    if "locked_intraday_pick" not in st.session_state:
        st.session_state.locked_intraday_pick = None
    if "locked_option_pick" not in st.session_state:
        st.session_state.locked_option_pick = None
    if "locked_swing_pick" not in st.session_state:
        st.session_state.locked_swing_pick = None
    if "locked_nifty_option_pick" not in st.session_state:
        st.session_state.locked_nifty_option_pick = None
    if "locked_at_time" not in st.session_state:
        st.session_state.locked_at_time = 0.0
    if "last_applied_hist_time_for_lock" not in st.session_state:
        st.session_state.last_applied_hist_time_for_lock = 0.0

    # Auto-reset lock if new history data was applied
    current_hist_time = st.session_state.get("history_loaded_at") or 0.0
    if current_hist_time != st.session_state.last_applied_hist_time_for_lock:
        st.session_state.locked_intraday_pick = None
        st.session_state.locked_option_pick = None
        st.session_state.locked_swing_pick = None
        st.session_state.locked_nifty_option_pick = None
        st.session_state.locked_at_time = 0.0
        st.session_state.last_applied_hist_time_for_lock = current_hist_time

    # Auto-reset lock if 15 minutes (900 seconds) have elapsed
    if st.session_state.locked_at_time > 0.0 and (time.time() - st.session_state.locked_at_time) >= 900:
        st.session_state.locked_intraday_pick = None
        st.session_state.locked_option_pick = None
        st.session_state.locked_swing_pick = None
        st.session_state.locked_nifty_option_pick = None
        st.session_state.locked_at_time = 0.0

    _token_ok   = st.session_state.token_accepted and bool(clean_token(access_token))
    _bg_running = _get_bg_hist_state()["running"]

    if _token_ok and not _bg_running:
        if not st.session_state.historical_data and not st.session_state.get("history_attempted", False):
            trigger_bg_hist_refresh(access_token, historical_workers)
            st.session_state.history_attempted = True
        elif _ms2["is_open"]:
            _last_hist = st.session_state.auto_history_last_load or 0
            if (time.time() - _last_hist) >= _AUTO:
                trigger_bg_hist_refresh(access_token, historical_workers)

        elif _ms2["is_pre_open"]:
            _today = _ms2["now_ist"].date()
            _already_done = (
                st.session_state.auto_history_preopen_done
                and st.session_state.auto_history_preopen_date == _today
            )
            if not _already_done:
                trigger_bg_hist_refresh(access_token, historical_workers)
                st.session_state.auto_history_preopen_done = True
                st.session_state.auto_history_preopen_date = _today

    # â”€â”€ Skip heavy redraw if nothing changed since last tick â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _last_tick = _fst["last_update"]
    _prev_tick = st.session_state.get("_frag_last_tick")
    _prev_lq   = st.session_state.get("_frag_last_lq", -1)
    _data_changed = (_last_tick != _prev_tick) or (len(_mkt) != _prev_lq)
    st.session_state["_frag_last_tick"] = _last_tick
    st.session_state["_frag_last_lq"]   = len(_mkt)

    # Track if historical data loaded state changed to rebuild datatables reactively
    _last_hist_load = st.session_state.get("history_loaded_at")
    _prev_hist_load = st.session_state.get("_frag_last_hist_load")
    _hist_changed = (_last_hist_load != _prev_hist_load)
    st.session_state["_frag_last_hist_load"] = _last_hist_load

    # â”€â”€ Status bar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _feed_st  = _fst["status"]
    _lq       = len(_mkt)
    _hs       = len(st.session_state.historical_data)
    _hist_st  = st.session_state.history_status
    _recon    = _fst["reconnects"]
    _tick     = format_last_update(_fst["last_update"])

    if _ms2["is_open"] and st.session_state.auto_history_last_load:
        _sl = max(0, int(_AUTO - (time.time() - st.session_state.auto_history_last_load)))
        _next_hist = f"{_sl//60}m {_sl%60:02d}s"
    elif _ms2["is_pre_open"]:
        _next_hist = "Pre-open"
    else:
        _next_hist = "Manual"

    # colour the feed status pill
    if _feed_st == "Connected":
        _pill_bg, _pill_fg = "rgba(34,197,94,0.15)", "#22c55e"
    elif _feed_st in ("Connecting", "Reconnecting", "Starting"):
        _pill_bg, _pill_fg = "rgba(245,158,11,0.15)", "#f59e0b"
    elif _feed_st == "Error":
        _pill_bg, _pill_fg = "rgba(239,68,68,0.15)", "#ef4444"
    else:
        _pill_bg, _pill_fg = "rgba(100,116,139,0.15)", "#94a3b8"

    def _stat(label: str, value: str) -> str:
        return (
            f'<div style="display:flex;flex-direction:column;gap:2px;min-width:0;">'
            f'<span style="font-size:.68rem;font-weight:700;color:#4a6480;'
            f'text-transform:uppercase;letter-spacing:.07em;white-space:nowrap;">{label}</span>'
            f'<span style="font-size:1.1rem;font-weight:700;color:#e0e8f5;'
            f'font-family:JetBrains Mono,monospace;white-space:nowrap;">{value}</span>'
            f'</div>'
        )
    # Status bar is rendered by feed_status_fragment (3-s cycle) above.
    # live_scanner_fragment owns signal computation + table display only.

    # ── History status banners ───────────────────────────────────────────────
    # Background refresh status pill
    _bg_running2 = _get_bg_hist_state()["running"]
    if _bg_running2:
        st.caption("🔄 Historical data refreshing in background — live scanner unaffected.")

    if not st.session_state.history_loaded:
        if st.session_state.history_attempted:
            st.warning("Historical data not loaded. Use Load Historical or wait for auto-refresh.")
            if st.session_state.get("history_errors"):
                st.error("❌ Last load attempt failed: The access token is incorrect, expired, or has been revoked by the broker.")
                with st.expander("Show Detailed API Failure Logs"):
                    st.write(st.session_state.history_errors[:5])
        else:
            st.warning("Historical data not loaded yet. Click Load Historical in the sidebar.")
    elif st.session_state.history_loaded_at:
        _ago = format_last_update(st.session_state.history_loaded_at)
        if _bg_running2:
            st.caption(f"Last load: {_ago} — background refresh in progress.")
        elif _ms2["is_open"] and st.session_state.auto_history_last_load:
            _sl2 = max(0, int(_AUTO - (time.time() - st.session_state.auto_history_last_load)))
            st.caption(f"Historical data loaded {_ago}. Next auto-refresh in {_sl2//60}m {_sl2%60:02d}s.")
        elif _ms2["is_pre_open"]:
            st.caption(f"Historical data loaded {_ago}. Pre-open load complete.")
        else:
            st.caption(f"Historical data loaded {_ago}.")

    if st.session_state.history_loaded:
        tested_count = len(st.session_state.historical_data)
        missed_count = len(effective_universe()) - tested_count
        st.markdown(
            f'<div class="coverage-card"><strong>{tested_count} of {len(effective_universe())}</strong> stocks ready for screening. '
            f'{missed_count} symbols skipped — retry with Load Historical.</div>',
            unsafe_allow_html=True,
        )
        if st.session_state.history_errors:
            with st.expander("Skipped symbols"):
                st.dataframe(build_error_table(st.session_state.history_errors),
                             width='stretch', hide_index=True)

    if not st.session_state.history_loaded and _mkt:
        if st.button("Use Live Quotes as Temporary Baseline"):
            fallback_count = build_live_baseline(_mkt)
            if fallback_count:
                st.success(f"Temporary baseline created for {fallback_count} live stocks.")
                st.rerun(scope="fragment")
            else:
                st.error("The live feed does not have enough price data to build a temporary baseline.")

    # ── Scan data source ─────────────────────────────────────────────────────
    scan_data   = _mkt
    scan_source = "Live WebSocket"

    # ── Market-closed notice ─────────────────────────────────────────────────
    _now_str2 = _now2.strftime("%d %b %Y  %H:%M IST")
    if not _ms2["is_open"] and not _ms2["is_pre_open"]:
        if _ms2["is_holiday"]:
            st.markdown(f'<div class="market-holiday-banner"><div class="mcb-icon">🗓️</div>'
                        f'<div class="mcb-title">NSE Holiday — Market Closed</div>'
                        f'<div class="mcb-sub">{_ms2["next_open"]}</div>'
                        f'<div class="mcb-time">{_now_str2}</div></div>', unsafe_allow_html=True)
        elif _ms2["is_weekend"]:
            st.markdown(f'<div class="market-closed-banner" style="background:#f1f5f9;border:1.5px solid #cbd5e1;border-bottom:4px solid #94a3b8;box-shadow:0 1px 3px rgba(0,0,0,0.05);">'
                        f'<div class="mcb-icon">😴</div>'
                        f'<div class="mcb-title" style="color:#475569;">Weekend — Market Closed</div>'
                        f'<div class="mcb-sub">{_ms2["next_open"]}</div>'
                        f'<div class="mcb-time">{_now_str2}</div></div>', unsafe_allow_html=True)
        else:
            _reason = "Market opens at 09:15 IST" if _now2.time() < _PRE_OPEN_START else "Market closed at 15:30 IST"
            st.markdown(f'<div class="market-closed-banner"><div class="mcb-icon">🔴</div>'
                        f'<div class="mcb-title">Market Closed</div>'
                        f'<div class="mcb-sub">{_reason} &nbsp;·&nbsp; {_ms2["next_open"]}</div>'
                        f'<div class="mcb-time">{_now_str2}</div></div>', unsafe_allow_html=True)

    if not scan_data and st.session_state.history_loaded:
        scan_data = build_historical_market_data()
        if scan_data:
            _data_dates = [m.get("last_data_date", "") for m in st.session_state.historical_data.values() if m.get("last_data_date")]
            _last_data_date = max(_data_dates) if _data_dates else "unknown date"
            scan_source = f"EOD {_last_data_date}"
            if _ms2["is_open"]:
                st.info(f"⏳ Live feed not yet connected — signals based on last historical candle ({_last_data_date}). Start the WebSocket feed for live data.")
            else:
                st.markdown(
                    f'<div style="background:#f0f7ff;border:1px solid #dbeafe;border-left:3.5px solid #2563eb;'
                    f'border-bottom:3.5px solid #cbd5e1;border-radius:8px;padding:.85rem 1.1rem;'
                    f'margin-bottom:.8rem;font-family:Outfit,sans-serif;font-size:.85rem;color:#1e293b;line-height:1.6;box-shadow:0 1px 3px rgba(0,0,0,0.05);">'
                    f'<span style="color:#2563eb;font-weight:700;">📌 PRE-MARKET WATCHLIST</span>'
                    f'&nbsp;·&nbsp; Based on <strong style="color:#0f172a;">{_last_data_date}</strong> closing data<br>'
                    f'End-of-session positions from the last trading day. '
                    f'<strong style="color:#d97706;">Not live breakouts</strong> — use as a watchlist to watch for confirmation at open.<br>'
                    f'<span style="color:#64748b;font-size:.78rem;">{_ms2["next_open"]}</span></div>',
                    unsafe_allow_html=True,
                )

    NAME_TO_TOKEN = {v: k for k, v in effective_universe().items()}

    # Only re-scan and re-render tables when data actually changed
    if _data_changed or "_frag_results" not in st.session_state:
        _results = []
        for instrument, quote in scan_data.items():
            signal = calculate_signal(
                instrument, quote,
                min_change, min_rvol, min_breakout_score,
                volume_premium_min, volume_premium_max,
            )
            if signal:
                signal["Source"] = scan_source
                hist = st.session_state.historical_data.get(instrument, {})
                parsed = parse_quote(quote)
                close_p      = float(parsed["close"])
                vol_p        = int(parsed["volume"])
                avg_v        = hist.get("avg_volume_20", 0)
                avg_d5       = float(hist.get("avg_daily_volume_5", 0))
                live_day_vol = float(hist.get("latest_day_volume", vol_p))
                vp = round(live_day_vol / avg_d5, 2) if avg_d5 else 0.0
                if avg_v > 0:
                    vol_for_rv = vol_p if _ms2["is_open"] else live_day_vol
                    rv = round(vol_for_rv / avg_v, 2)
                else:
                    rv = 0.0
                change_p = signal.get("Change %", 0)
                bo_score = sum([
                    close_p > hist.get("orb_high", 0),
                    close_p > hist.get("ema20", 0),
                    close_p > hist.get("vwap", 0),
                    rv >= min_rvol,
                    volume_premium_min <= vp <= volume_premium_max,
                    change_p >= min_change,
                ])
                bd_score = sum([
                    close_p < hist.get("orb_low", float("inf")),
                    close_p < hist.get("ema20", float("inf")),
                    close_p < hist.get("vwap", float("inf")),
                    rv >= min_rvol,
                    volume_premium_min <= vp <= volume_premium_max,
                    change_p <= -min_change,
                ])
                signal["_bo_score"]    = bo_score
                signal["_bd_score"]    = bd_score
                signal["_token"]       = instrument
                signal["_raw_quote"]   = quote
                signal["RVOL"]         = rv
                signal["Vol Premium"]  = vp
                signal["Last Day Vol"] = int(live_day_vol)
                signal["5D Avg Vol"]   = int(avg_d5)
                signal["20D Avg Vol"]  = int(avg_v)
                signal["Score"]        = f"{max(bo_score, bd_score)}/6"
                signal["Quant Score"]  = get_screener_scores(signal.get("Stock", ""))
                _log_key = f"{signal.get('Stock', '')}:{signal.get('Signal', '')}"
                if _log_key not in st.session_state.signal_log_seen:
                    st.session_state.signal_log_seen.add(_log_key)
                    _ist_now = datetime.now(_IST_TZ).strftime("%H:%M:%S")
                    st.session_state.signal_log.insert(0, {
                        "Time":     _ist_now,
                        "Stock":    signal.get("Stock", ""),
                        "Signal":   signal.get("Signal", ""),
                        "Score":    signal["Score"],
                        "LTP":      signal.get("LTP", 0),
                        "Change %": signal.get("Change %", 0),
                        "RVOL":     rv,
                    })
                    st.session_state.signal_log = st.session_state.signal_log[:50]
                _results.append(signal)
        st.session_state["_frag_results"] = _results

    results = st.session_state.get("_frag_results", [])

    DISPLAY_COLS = [
        "Stock", "Signal", "Score", "Quant Score", "Last Close", "Change %",
        "Momentum", "LTP", "VWAP", "EMA20", "ORB High", "ORB Low",
        "RVOL", "Vol Premium", "Last Day Vol", "5D Avg Vol", "20D Avg Vol", "Volume",
    ]

    # Initialize dataframes safely to prevent layout collapse
    if results:
        df = pd.DataFrame(results).sort_values("Momentum", ascending=False)
    else:
        df = pd.DataFrame(columns=DISPLAY_COLS + ["_bo_score", "_bd_score", "_token", "_raw_quote"])

    if True:
        # Align breakout and breakdown tables with LONG/SHORT signals correctly
        long_df      = df[df["Signal"] == "LONG"] if not df.empty else pd.DataFrame(columns=DISPLAY_COLS)
        short_df     = df[df["Signal"] == "SHORT"] if not df.empty else pd.DataFrame(columns=DISPLAY_COLS)

        def clean_df(d: pd.DataFrame) -> pd.DataFrame:
            cols = [c for c in DISPLAY_COLS if c in d.columns]
            return d[cols]

        # ──🎯 COMMAND CENTER ALPHA PICKS ──────────────────────────────────────────
        # Generate absolute top #1 Intraday, Stock Option, and Swing recommendations
        # to prevent chasing, eliminate analysis paralysis, and enforce solid risk-reward.
        
        # Official NSE F&O Stock Lot Sizes for precise contract quantity calculations
        FO_LOT_SIZES = {
            "RELIANCE": 250, "TCS": 175, "INFY": 400, "TATASTEEL": 5500, "SBIN": 1500,
            "BHARTIARTL": 950, "ICICIBANK": 700, "HDFCBANK": 550, "AXISBANK": 625, "ITC": 1600,
            "LT": 300, "HINDUNILVR": 300, "M&M": 350, "SUNPHARMA": 700, "MARUTI": 50,
            "ONGC": 3850, "JSWSTEEL": 675, "ADANIENT": 300, "COALINDIA": 4200, "NTPC": 1500,
            "POWERGRID": 3600, "KOTAKBANK": 400
        }

        # 1. Intraday Pick Selection (Stable lock with real-time price updates)
        intraday_pick = None
        if st.session_state.locked_intraday_pick:
            intraday_pick = st.session_state.locked_intraday_pick.copy()
            if not df.empty:
                match_df = df[df["Stock"] == intraday_pick["Stock"]]
                if not match_df.empty:
                    intraday_pick["LTP"] = float(match_df.iloc[0]["LTP"])
                    intraday_pick["Change %"] = float(match_df.iloc[0]["Change %"])
                    st.session_state.locked_intraday_pick = intraday_pick.copy()
        
        if not intraday_pick and not df.empty:
            # Check if we are in the opening session (first 15 minutes of market open: 9:15 AM to 9:30 AM IST).
            # Gap-and-go breakouts can be up to 4.0% at open and still be highly valid momentum trades.
            # Outside of open, we restrict to 1.5% to prevent chasing extended trends.
            is_opening = _ms2["is_open"] and (_now2.hour == 9 and 15 <= _now2.minute < 30)
            max_chg = 4.0 if is_opening else 1.5

            candidates_bo = df[(df["Signal"] == "LONG") & (df["Change %"] < max_chg) & (df["Change %"] > 0.4)]
            candidates_bd = df[(df["Signal"] == "SHORT") & (df["Change %"] > -max_chg) & (df["Change %"] < -0.4)]
            candidates = pd.concat([candidates_bo, candidates_bd])
            if not candidates.empty:
                candidates = candidates.sort_values(by=["Score", "RVOL"], ascending=[False, False])
                intraday_pick = candidates.iloc[0].to_dict()
                st.session_state.locked_intraday_pick = intraday_pick.copy()
                if st.session_state.locked_at_time == 0.0:
                    st.session_state.locked_at_time = time.time()
                
        # 2. Stock Option Pick Selection (Stable lock with real-time price updates)
        option_pick = None
        if st.session_state.locked_option_pick:
            option_pick = st.session_state.locked_option_pick.copy()
            if not df.empty:
                match_df = df[df["Stock"] == option_pick["Stock"]]
                if not match_df.empty:
                    option_pick["LTP"] = float(match_df.iloc[0]["LTP"])
                    option_pick["Change %"] = float(match_df.iloc[0]["Change %"])
                    st.session_state.locked_option_pick = option_pick.copy()

        if not option_pick and not df.empty:
            liquid_fo = list(FO_LOT_SIZES.keys())
            fo_candidates = df[df["Stock"].isin(liquid_fo)]
            if not fo_candidates.empty:
                fo_candidates = fo_candidates.sort_values(by=["RVOL", "Change %"], ascending=[False, False])
                option_pick = fo_candidates.iloc[0].to_dict()
            else:
                option_pick = df.sort_values(by=["RVOL"], ascending=False).iloc[0].to_dict()
            st.session_state.locked_option_pick = option_pick.copy()
            if st.session_state.locked_at_time == 0.0:
                st.session_state.locked_at_time = time.time()

        # Helper function to dynamically round to standard option strike intervals
        def calculate_atm_strike(stock: str, price: float) -> int:
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

        # 2.5 Nifty Option Pick Selection (Stable lock with real-time spot and premium updates)
        nifty_pick = None
        nifty_quote = _idx_d.get("NIDX:40000001", {})
        nifty_ltp = nifty_quote.get("ltp") or nifty_quote.get("last_price") or nifty_quote.get("live_price")
        # Merge REST and WebSocket candles for Nifty to ensure correct historical length for RSI calculation
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
        elif nifty_ltp is not None:
            nifty_ltp = float(nifty_ltp)

        if st.session_state.locked_nifty_option_pick:
            nifty_pick = st.session_state.locked_nifty_option_pick.copy()
            if nifty_ltp is not None:
                old_spot = nifty_pick["locked_spot_ltp"]
                delta = 0.55 if nifty_pick["option_type"] == "CE" else -0.55
                price_diff = nifty_ltp - old_spot
                premium_change = price_diff * delta
                nifty_pick["nifty_ltp"] = nifty_ltp
                nifty_pick["entry_price"] = max(5.0, float(round(nifty_pick["base_premium"] + premium_change, 1)))
                nifty_pick["target"] = float(round(nifty_pick["entry_price"] * 1.50, 1))
                nifty_pick["stop_loss"] = float(round(nifty_pick["entry_price"] * 0.70, 1))
                st.session_state.locked_nifty_option_pick = nifty_pick.copy()
        else:
            if nifty_ltp is not None:
                nifty_pick = generate_nifty_option_chain_and_signal(nifty_ltp, nifty_candles)
                if nifty_pick:
                    st.session_state.locked_nifty_option_pick = nifty_pick.copy()
                    if st.session_state.locked_at_time == 0.0:
                        st.session_state.locked_at_time = time.time()

        # 3. Swing Pick Selection (Stable lock with real-time price updates)
        swing_pick = None
        if st.session_state.locked_swing_pick:
            swing_pick = st.session_state.locked_swing_pick.copy()
            if not df.empty:
                match_df = df[df["Stock"] == swing_pick["Stock"]]
                if not match_df.empty:
                    swing_pick["LTP"] = float(match_df.iloc[0]["LTP"])
                    st.session_state.locked_swing_pick = swing_pick.copy()
        else:
            import sqlite3
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Finance", "nifty_scanner", "nifty500_scanner.db")
            if not os.path.exists(db_path):
                db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nifty_scanner", "nifty500_scanner.db")
            if os.path.exists(db_path):
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT ticker, company_name, total_score, fundamental_score, momentum_score, last_price "
                        "FROM nifty500_cache "
                        "WHERE total_score >= 60 AND last_price > 50 AND market_cap_cr > 2000 "
                        "ORDER BY total_score DESC, momentum_score DESC LIMIT 1"
                    )
                    row = cursor.fetchone()
                    conn.close()
                    if row:
                        swing_pick = {
                            "Stock": row[0].replace(".NS", ""),
                            "Company": row[1],
                            "Total": int(row[2]),
                            "Funda": int(row[3]),
                            "Mntm": int(row[4]),
                            "LTP": float(row[5]),
                        }
                        st.session_state.locked_swing_pick = swing_pick.copy()
                        if st.session_state.locked_at_time == 0.0:
                            st.session_state.locked_at_time = time.time()
                except Exception:
                    pass

        # Calculate time remaining on the 15-minute lock
        time_rem_str = ""
        if st.session_state.locked_at_time > 0.0:
            elapsed = time.time() - st.session_state.locked_at_time
            remaining = max(0, int(900 - elapsed))
            mins = remaining // 60
            secs = remaining % 60
            time_rem_str = f"🔒 Tickers Locked (Auto-refresh in {mins:02d}:{secs:02d})"
        else:
            time_rem_str = "🔓 Scanning Live Breakouts"

        # Render Command Center Layout
        st.markdown(
            f'<div style="background:#ffffff;border:1.5px solid #cbd5e1;border-bottom:5.5px solid #059669;'
            f'border-radius:12px;padding:1.25rem;margin:1rem 0;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);">'
            f'<div style="font-size:1.15rem;font-weight:800;color:#0f172a;letter-spacing:-0.02em;'
            f'display:flex;align-items:center;gap:8px;margin-bottom:1rem;">'
            f'🎯 COMMAND CENTER \u2014 ALPHA PICKS OF THE DAY'
            f'<span style="font-size:0.75rem;font-weight:700;background:#d1fae5;color:#065f46;'
            f'padding:2px 8px;border-radius:20px;border:1px solid #10b981;">{time_rem_str}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Collapsible horizontal money management terminal right inside focus
        with st.expander("⚙️ Sizing & Capital Allocation Terminal (Click to Expand)", expanded=False):
            m_col1, m_col2, m_col3 = st.columns([2, 3, 2])
            with m_col1:
                total_cap = st.number_input("Total Trading Capital (₹)", min_value=1000, max_value=100000000, value=500000, step=5000, key="mm_total_capital")
            with m_col2:
                st.markdown("<div style='font-size:0.82rem;font-weight:700;color:#475569;margin-bottom:0.25rem;'>Capital Splits (Must total 100%):</div>", unsafe_allow_html=True)
                c_col1, c_col2, c_col3 = st.columns(3)
                with c_col1:
                    intra_pct = st.number_input("Intraday %", 0, 100, 50, 5, key="mm_intra_pct")
                with c_col2:
                    opt_pct = st.number_input("Options %", 0, 100, 30, 5, key="mm_opt_pct")
                with c_col3:
                    swing_pct = st.number_input("Swing %", 0, 100, 20, 5, key="mm_swing_pct")
                if (intra_pct + opt_pct + swing_pct) != 100:
                    st.warning("⚠️ Splits must sum to 100%!")
            with m_col3:
                intra_lev = st.slider("Intraday Leverage (X)", 1, 5, 3, 1, key="mm_leverage")
                max_trades = st.slider("Max Intraday Trades/Day", 1, 10, 4, 1, key="mm_max_trades")

        st.markdown("<div style='margin-bottom: 0.75rem;'></div>", unsafe_allow_html=True)
        ap_cols = st.columns(4)
        
        # CARD 1: INTRADAY sniper PLAY
        with ap_cols[0]:
            if intraday_pick:
                _stk = intraday_pick["Stock"]
                _ltp = float(intraday_pick["LTP"])
                _sig = intraday_pick["Signal"]
                _chg = float(intraday_pick["Change %"])
                _is_long = _sig in ("LONG", "BREAKOUT")
                _card_class = "premium-card-long" if _is_long else "premium-card-short"
                _badge_color = "#059669" if _is_long else "#dc2626"
                _badge_bg = "#d1fae5" if _is_long else "#fee2e2"
                _badge_border = "#10b981" if _is_long else "#ef4444"
                
                # Position Sizing
                _sl_dist = _ltp * 0.015
                _sl = _ltp - _sl_dist if _is_long else _ltp + _sl_dist
                _tgt = _ltp + (_sl_dist * 2.0) if _is_long else _ltp - (_sl_dist * 2.0)
                allocated_cap = total_cap * (intra_pct / 100.0)
                cap_per_trade = allocated_cap / max_trades
                buying_power = cap_per_trade * intra_lev
                _qty = int(buying_power / _ltp) if _ltp > 0 else 0
                _trade_val = _qty * _ltp
                _max_risk = _qty * _sl_dist
                
                # Fetch news sentiment dynamically (cached for 5 minutes)
                _news_sent = fetch_news_sentiment(_stk)
                if _news_sent == "Positive":
                    _news_color = "#059669"
                elif _news_sent == "Negative":
                    _news_color = "#dc2626"
                else:
                    _news_color = "#64748b"
                
                st.markdown(
                    f'<div class="premium-card {_card_class}">'
                    f'<div>'
                    f'<div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:0.25rem;">⚡ INTRADAY sniper PLAY</div>'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.5rem;">'
                    f'<span style="font-size:1.35rem;font-weight:800;color:#0f172a;letter-spacing:-0.03em;font-family:\'Outfit\',sans-serif;">{_stk}</span>'
                    f'<span class="card-badge" style="background:{_badge_bg};color:{_badge_color};border:1.25px solid {_badge_border};">{_sig}</span>'
                    f'</div>'
                    f'<div style="font-size:0.82rem;color:#334155;line-height:1.45;">'
                    f'🎯 Entry Limit: <b style="color:#0f172a;">₹{_ltp:.2f}</b> ({_chg:+.2f}%)<br>'
                    f'🛡️ Stop Loss: <b style="color:#dc2626;">₹{_sl:.2f}</b> (1.5%)<br>'
                    f'📈 Target Net: <b style="color:#059669;">₹{_tgt:.2f}</b> (3.0%)<br>'
                    f'📰 News: <span style="color:{_news_color};font-weight:700;">{_news_sent}</span>'
                    f'</div>'
                    f'</div>'
                    f'<div class="action-console">'
                    f'👉 <span class="action-btn-green">ACTION:</span> BUY/SELL <b style="font-family:\'JetBrains Mono\';">{_qty}</b> SHARES<br>'
                    f'💰 Margin: <b>₹{cap_per_trade:,.2f}</b> (BP: ₹{_trade_val:,.0f})<br>'
                    f'⚠️ Max Risk: <span class="action-btn-red">₹{_max_risk:.2f}</span> ({_max_risk/total_cap*100:.2f}%)'
                    f'</div>'
                    f'<div style="font-size:0.65rem;color:#64748b;font-style:italic;line-height:1.2;border-top:1px solid #f1f5f9;padding-top:0.35rem;margin-top:0.35rem;">'
                    f'Inception breakout. Locked at 1.5% SL for 3% target.'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="premium-card" style="border-left:5px solid #94a3b8;background:#f8fafc;">'
                    f'<div>'
                    f'<div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:0.25rem;">⚡ INTRADAY sniper PLAY</div>'
                    f'<div style="font-size:0.8rem;color:#64748b;margin-top:1.5rem;text-align:center;font-style:italic;">'
                    f'🔍 Waiting for breakout setups...'
                    f'</div></div></div>',
                    unsafe_allow_html=True,
                )
                
        # CARD 2: STOCK OPTION Sniper
        with ap_cols[1]:
            if option_pick:
                _stk = option_pick["Stock"]
                _ltp = float(option_pick["LTP"])
                _sig = option_pick["Signal"]
                _chg = float(option_pick["Change %"])
                _is_long = _sig in ("LONG", "BREAKOUT")
                _strike = calculate_atm_strike(_stk, _ltp)
                _option_type = "CE" if _is_long else "PE"
                _contract = f"{_stk} {_strike} {_option_type}"
                
                # Position Sizing
                allocated_opt_cap = total_cap * (opt_pct / 100.0)
                lot_size = FO_LOT_SIZES.get(_stk, 100)
                est_premium = _ltp * 0.03
                cost_per_lot = lot_size * est_premium
                max_trade_exposure = allocated_opt_cap * 0.20
                _lots = int(max_trade_exposure / cost_per_lot) if cost_per_lot > 0 else 0
                if _lots == 0:
                    _lots = 1
                _total_premium_val = _lots * lot_size * est_premium
                _max_risk = _total_premium_val * 0.35
                
                # Fetch news sentiment dynamically (cached for 5 minutes)
                _news_sent = fetch_news_sentiment(_stk)
                if _news_sent == "Positive":
                    _news_color = "#059669"
                elif _news_sent == "Negative":
                    _news_color = "#dc2626"
                else:
                    _news_color = "#64748b"
                
                st.markdown(
                    f'<div class="premium-card premium-card-options">'
                    f'<div>'
                    f'<div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:0.25rem;">📦 STOCK OPTION SNIPER</div>'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.5rem;">'
                    f'<span style="font-size:1.15rem;font-weight:800;color:#0f172a;letter-spacing:-0.03em;font-family:\'Outfit\',sans-serif;">{_contract}</span>'
                    f'<span class="card-badge" style="background:#e0f2fe;color:#0369a1;border:1.25px solid #0ea5e9;">ATM Opt</span>'
                    f'</div>'
                    f'<div style="font-size:0.82rem;color:#334155;line-height:1.45;">'
                    f'💰 Under. LTP: <b style="color:#0f172a;">₹{_ltp:.2f}</b> ({_chg:+.2f}%)<br>'
                    f'🛡️ Stop Loss: <b style="color:#dc2626;">Premium -35%</b><br>'
                    f'📈 Target Net: <b style="color:#059669;">Premium +70%</b><br>'
                    f'📰 News: <span style="color:{_news_color};font-weight:700;">{_news_sent}</span>'
                    f'</div>'
                    f'</div>'
                    f'<div class="action-console">'
                    f'👉 <span class="action-btn-blue">ACTION:</span> BUY <b style="font-family:\'JetBrains Mono\';">{_lots}</b> LOTS ({_lots * lot_size} shrs)<br>'
                    f'💰 Est. Premium: <b>₹{est_premium:.2f}</b><br>'
                    f'⚠️ Margin Deployed: <b>₹{_total_premium_val:,.2f}</b>'
                    f'</div>'
                    f'<div style="font-size:0.65rem;color:#64748b;font-style:italic;line-height:1.2;border-top:1px solid #f1f5f9;padding-top:0.35rem;margin-top:0.35rem;">'
                    f'High liquidity large-cap. Stop loss at 35% premium decay.'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="premium-card" style="border-left:5px solid #94a3b8;background:#f8fafc;">'
                    f'<div>'
                    f'<div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:0.25rem;">📦 STOCK OPTION SNIPER</div>'
                    f'<div style="font-size:0.8rem;color:#64748b;margin-top:1.5rem;text-align:center;font-style:italic;">'
                    f'🔍 Waiting for highly liquid F&O signals...'
                    f'</div></div></div>',
                    unsafe_allow_html=True,
                )

        # CARD 3: NIFTY INDEX OPTIONS
        with ap_cols[2]:
            if nifty_pick and nifty_pick.get("signal") != "NEUTRAL / NO TRADE":
                _contract = nifty_pick["contract"]
                _entry = nifty_pick["entry_price"]
                _tgt = nifty_pick["target"]
                _sl = nifty_pick["stop_loss"]
                _sig = nifty_pick["signal"]
                _ltp = nifty_pick["nifty_ltp"]
                _pcr = nifty_pick["pcr"]
                _sup = nifty_pick["support"]
                _res = nifty_pick["resistance"]
                _is_long = "CALL" in _sig
                _card_class = "premium-card-long" if _is_long else "premium-card-short"
                _badge_color = "#059669" if _is_long else "#dc2626"
                _badge_bg = "#d1fae5" if _is_long else "#fee2e2"
                _badge_border = "#10b981" if _is_long else "#ef4444"
                
                # Position Sizing: lot size = 65
                allocated_opt_cap = total_cap * (opt_pct / 100.0)
                cost_per_lot = 65 * _entry
                max_trade_exposure = allocated_opt_cap * 0.20
                _lots = int(max_trade_exposure / cost_per_lot) if cost_per_lot > 0 else 0
                if _lots == 0:
                    _lots = 1
                _total_premium_val = _lots * 65 * _entry
                _max_risk = _total_premium_val * 0.30
                
                st.markdown(
                    f'<div class="premium-card {_card_class}">'
                    f'<div>'
                    f'<div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:0.25rem;">📦 NIFTY INDEX OPTION SNIPER</div>'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.5rem;">'
                    f'<span style="font-size:1.02rem;font-weight:800;color:#0f172a;letter-spacing:-0.03em;font-family:\'Outfit\',sans-serif;word-break:break-all;">{_contract}</span>'
                    f'<span class="card-badge" style="background:{_badge_bg};color:{_badge_color};border:1.25px solid {_badge_border};">INDEX</span>'
                    f'</div>'
                    f'<div style="font-size:0.82rem;color:#334155;line-height:1.45;">'
                    f'💰 Premium Entry: <b style="color:#0f172a;">₹{_entry:.2f}</b> (Spot: {int(_ltp)})<br>'
                    f'🛡️ Stop Loss: <b style="color:#dc2626;">₹{_sl:.2f}</b><br>'
                    f'📈 Target Net: <b style="color:#059669;">₹{_tgt:.2f}</b> (50%)'
                    f'</div>'
                    f'</div>'
                    f'<div class="action-console">'
                    f'👉 <span class="{"action-btn-green" if _is_long else "action-btn-red"}">ACTION:</span> BUY <b style="font-family:\'JetBrains Mono\';">{_lots}</b> LOTS ({_lots * 65} shrs)<br>'
                    f'💰 Margin Required: <b>₹{_total_premium_val:,.2f}</b><br>'
                    f'📊 PCR: <b>{_pcr:.2f}</b> | S: <b>{int(_sup)}</b> R: <b>{int(_res)}</b>'
                    f'</div>'
                    f'<div style="font-size:0.65rem;color:#64748b;font-style:italic;line-height:1.2;border-top:1px solid #f1f5f9;padding-top:0.35rem;margin-top:0.35rem;">'
                    f'Nifty option chain OI signal. Max risk: ₹{_max_risk:,.0f} ({_max_risk/total_cap*100:.2f}% cap).'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                diag_rsi = rsi if 'rsi' in locals() else 50.0
                diag_candles = len(nifty_candles) if 'nifty_candles' in locals() else 0
                st.markdown(
                    f'<div class="premium-card" style="border-left:5px solid #94a3b8;background:#f8fafc;">'
                    f'<div>'
                    f'<div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:0.25rem;">📦 NIFTY INDEX OPTION SNIPER</div>'
                    f'<div style="font-size:0.8rem;color:#64748b;margin-top:1.25rem;text-align:center;font-style:italic;">'
                    f'🔍 No Trade. Option chain is neutral.<br>'
                    f'<span style="font-size:0.72rem;color:#94a3b8;font-style:normal;">(Nifty RSI: {diag_rsi:.1f} | Bars: {diag_candles})</span>'
                    f'</div></div></div>',
                    unsafe_allow_html=True,
                )

        # CARD 4: SWING
        with ap_cols[3]:
            if swing_pick:
                _stk = swing_pick["Stock"]
                _company = swing_pick["Company"]
                _total = swing_pick["Total"]
                _funda = swing_pick["Funda"]
                _mntm = swing_pick["Mntm"]
                _ltp = swing_pick["LTP"]
                
                # Swing targets: 5% stop loss for 12% target (1:2.4 RR)
                _sl = _ltp * 0.95
                _tgt = _ltp * 1.12
                
                # Position Sizing
                allocated_swing_cap = total_cap * (swing_pct / 100.0)
                _swing_cap_per_trade = allocated_swing_cap / 2.0
                _qty = int(_swing_cap_per_trade / _ltp) if _ltp > 0 else 0
                _deployed = _qty * _ltp
                _max_risk = _qty * (_ltp - _sl)
                
                # Fetch news sentiment dynamically (cached for 5 minutes)
                _news_sent = fetch_news_sentiment(_stk)
                if _news_sent == "Positive":
                    _news_color = "#059669"
                elif _news_sent == "Negative":
                    _news_color = "#dc2626"
                else:
                    _news_color = "#64748b"
                
                st.markdown(
                    f'<div class="premium-card premium-card-swing">'
                    f'<div>'
                    f'<div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:0.25rem;">📈 SWING ALPHA PICK</div>'
                    f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:0.5rem;">'
                    f'<span style="font-size:1.35rem;font-weight:800;color:#0f172a;letter-spacing:-0.03em;font-family:\'Outfit\',sans-serif;">{_stk}</span>'
                    f'<span class="card-badge" style="background:#f3e8ff;color:#6b21a8;border:1.25px solid #a855f7;">Score: {_total}</span>'
                    f'</div>'
                    f'<div style="font-size:0.82rem;color:#334155;line-height:1.45;">'
                    f'🎯 Entry Limit: <b style="color:#0f172a;">₹{_ltp:.2f}</b> (F:{_funda} M:{_mntm})<br>'
                    f'🛡️ Stop Loss: <b style="color:#dc2626;">₹{_sl:.2f}</b> (5%)<br>'
                    f'📈 Target Net: <b style="color:#059669;">₹{_tgt:.2f}</b> (12%)<br>'
                    f'📰 News: <span style="color:{_news_color};font-weight:700;">{_news_sent}</span>'
                    f'</div>'
                    f'</div>'
                    f'<div class="action-console">'
                    f'👉 <span style="color:#A78BFA;font-weight:700;">ACTION:</span> BUY EXACTLY <b style="font-family:\'JetBrains Mono\';">{_qty}</b> SHARES<br>'
                    f'💰 Capital Deployed: <b>₹{_deployed:,.2f}</b><br>'
                    f'⚠️ Max Risk: <span class="action-btn-red">₹{_max_risk:.2f}</span> ({_max_risk/total_cap*100:.2f}%)'
                    f'</div>'
                    f'<div style="font-size:0.65rem;color:#64748b;font-style:italic;line-height:1.2;border-top:1px solid #f1f5f9;padding-top:0.35rem;margin-top:0.35rem;">'
                    f'Top Quantamental Leader. Holding period: 3-10 sessions.'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="premium-card" style="border-left:5px solid #94a3b8;background:#f8fafc;">'
                    f'<div>'
                    f'<div style="font-size:0.68rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:0.25rem;">📈 SWING ALPHA PICK</div>'
                    f'<div style="font-size:0.8rem;color:#64748b;margin-top:1.5rem;text-align:center;font-style:italic;">'
                    f'🔍 Loading quantamental leader...'
                    f'</div></div></div>',
                    unsafe_allow_html=True,
                )
                
        st.markdown("</div>", unsafe_allow_html=True)

        # ── Telegram Notification Control Center ───────────────────────────────────
        trigger_telegram_picks_if_needed(
            intraday_pick=intraday_pick,
            option_pick=option_pick,
            nifty_pick=nifty_pick,
            swing_pick=swing_pick,
            total_cap=total_cap,
            intra_pct=intra_pct,
            opt_pct=opt_pct,
            swing_pct=swing_pct,
            intra_lev=intra_lev,
            max_trades=max_trades,
        )

        tb_col1, tb_col2, tb_col3 = st.columns([4, 2, 2])
        with tb_col1:
            token, chat_id, enabled = get_telegram_config()
            if enabled and token and chat_id:
                # Mask token for security
                masked_token = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "Configured"
                st.markdown(
                    f'<div style="font-size:0.8rem;color:#059669;font-weight:600;margin-top:0.4rem;">'
                    f'🟢 Telegram Notifications Enabled (Bot: <code>{masked_token}</code>, Chat ID: <code>{chat_id}</code>)'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div style="font-size:0.8rem;color:#64748b;margin-top:0.4rem;">'
                    f'⚪ Telegram Bot not configured. Add credentials in Settings / Secrets to receive mobile alerts.'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        with tb_col2:
            if st.button("🔄 Recalculate Picks", key="btn_recalc_alpha_picks", use_container_width=True):
                st.session_state.locked_intraday_pick = None
                st.session_state.locked_option_pick = None
                st.session_state.locked_swing_pick = None
                st.session_state.locked_nifty_option_pick = None
                st.session_state.locked_at_time = 0.0
                st.toast("🔄 Tickers unlocked! Recalculating fresh picks...", icon="🔄")
                st.rerun()
        with tb_col3:
            if st.button("📢 Send to Telegram", key="tg_manual_send_btn", use_container_width=True):
                with st.spinner("Dispatching Alpha Picks to Telegram Bot..."):
                    success = send_telegram_picks_message(
                        intraday_pick=intraday_pick,
                        option_pick=option_pick,
                        nifty_pick=nifty_pick,
                        swing_pick=swing_pick,
                        total_cap=total_cap,
                        intra_pct=intra_pct,
                        opt_pct=opt_pct,
                        swing_pct=swing_pct,
                        intra_lev=intra_lev,
                        max_trades=max_trades,
                    )
                    if success:
                        st.toast("🚀 Command Center Alpha Picks sent to Telegram successfully!", icon="✅")
                    else:
                        st.toast("❌ Failed to send picks. Check Telegram Bot settings.", icon="⚠️")

        _closed = not _ms2["is_open"] and not _ms2["is_pre_open"]
        _sig_label   = "Watchlist Setups" if _closed else "Total Signals"

        mc = st.columns(3)
        mc[0].metric(_sig_label,  len(df))
        mc[1].metric("▲ LONG (6/6)", len(long_df))
        mc[2].metric("▼ SHORT (6/6)", len(short_df))

        st.divider()

        t_long, t_short, t_all, t_log = st.tabs([
            "▲ Long", "▼ Short", "≡ All Signals", "🗒 Signal Log",
        ])

        # â”€â”€ Alert toast for new Super Breakout/Breakdown signals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if _ms2["is_open"]:
            _prev_super = st.session_state.get("_prev_super_count", 0)
            _curr_super = len(long_df) + len(short_df)
            if _curr_super > _prev_super:
                for _, _row in pd.concat([long_df, short_df]).iterrows():
                    st.toast(
                        f"⚡ {_row['Stock']} — {_row['Signal']} (6/6)  LTP {_row['LTP']}",
                        icon="🚨",
                    )
            st.session_state["_prev_super_count"] = _curr_super

        def show_table(d: pd.DataFrame) -> None:
            st.dataframe(
                highlight_top_volume(clean_df(d), vol_col="Volume", top_n=5),
                width='stretch', hide_index=True,
                height=min(600, 56 + len(d) * 40),
            )

        def show_charts(d: pd.DataFrame, sig_type: str) -> None:
            if d.empty:
                return
            n = len(d)
            cols = st.columns(2) if n > 1 else st.columns(1)
            for i, row in enumerate(d.itertuples()):
                token     = str(d.loc[row.Index, "_token"])
                raw_quote = d.loc[row.Index, "_raw_quote"] if "_raw_quote" in d.columns else None
                with cols[i % len(cols)]:
                    render_candlestick_chart(row.Stock, token, sig_type, live_quote=raw_quote, sr_pivot_type=sr_pivot_type)

        with t_long:
            st.markdown('<span class="sig-badge sig-long">\u25b2 LONG</span>', unsafe_allow_html=True)
            if long_df.empty:
                st.info("No active Long signals.")
            else:
                show_table(long_df)
                st.markdown("#### Intraday Charts")
                show_charts(long_df, "LONG")

        with t_short:
            st.markdown('<span class="sig-badge sig-short">\u25bc SHORT</span>', unsafe_allow_html=True)
            if short_df.empty:
                st.info("No active Short signals.")
            else:
                show_table(short_df)
                st.markdown("#### Intraday Charts")
                show_charts(short_df, "SHORT")

        with t_all:
            st.markdown('<span class="sig-badge sig-all">\u2261 ALL SIGNALS</span>', unsafe_allow_html=True)
            if df.empty:
                st.info("No active signals matching current criteria.")
            else:
                show_table(df)

        with t_log:
            st.subheader("📋 Signal Log — First Seen Today")
            if st.button("🗑️ Clear Log", key="clear_signal_log"):
                st.session_state.signal_log      = []
                st.session_state.signal_log_seen = set()
                st.rerun(scope="fragment")
            if st.session_state.signal_log:
                log_df = pd.DataFrame(st.session_state.signal_log)

                def _style_log(row: pd.Series) -> list[str]:
                    sig = str(row.get("Signal", ""))
                    if sig == "LONG":
                        return ["color:#34d399;font-weight:700"] * len(row)
                    if sig == "SHORT":
                        return ["color:#ef5350;font-weight:700"] * len(row)
                    return [""] * len(row)

                st.dataframe(
                    log_df.style.apply(_style_log, axis=1),
                    width='stretch', hide_index=True, height=420,
                )
                st.caption(f"{len(st.session_state.signal_log)} entries · Resets on page reload · Max 50")
            else:
                st.info("No signals logged yet. Signals appear here the first time they are detected.")

    # â”€â”€ Diagnostics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if "depth_data" not in st.session_state:
        st.session_state.depth_data = {}
    if "depth_tokens" not in st.session_state:
        st.session_state.depth_tokens = []

    if _data_changed or _hist_changed or "_frag_live_snap" not in st.session_state:
        st.session_state["_frag_live_snap"] = build_live_snapshot(_mkt)
        st.session_state["_frag_hist_snap"] = build_history_snapshot()

    live_snapshot    = st.session_state["_frag_live_snap"]
    history_snapshot = st.session_state["_frag_hist_snap"]

    if not live_snapshot.empty or not history_snapshot.empty:
        st.divider()
        diag_tab, hist_tab, depth_tab, idx_tab = st.tabs([
            "📡 Live Snapshot", "📊 Historical Snapshot", "📈 Market Depth", "📊 Index Charts"
        ])

        with diag_tab:
            st.markdown('<p class="section-heading">📡 Live Snapshot</p>', unsafe_allow_html=True)
            if live_snapshot.empty:
                st.info("No live quotes received yet.")
            else:
                st.dataframe(
                    highlight_top_volume(live_snapshot, vol_col="Volume", top_n=5),
                width='stretch', hide_index=True, height=360,
            )

        with hist_tab:
            st.markdown('<p class="section-heading">📊 Historical Snapshot</p>', unsafe_allow_html=True)
            if history_snapshot.empty:
                st.info("No historical metrics loaded yet.")
            else:
                _hist_vol_col = "Live Day Vol" if _ms2["is_open"] else "Last Day Vol"
                st.dataframe(
                    highlight_top_volume(history_snapshot, vol_col=_hist_vol_col, top_n=5),
                    width='stretch', hide_index=True, height=360,
                )

        with depth_tab:
            st.markdown('<p class="section-heading">📈 Live Market Depth (5-Level)</p>', unsafe_allow_html=True)
            if not st.session_state.token_accepted:
                st.info("Accept your INDmoney token first.")
            elif not _ms2["is_open"] and not _ms2["is_pre_open"]:
                st.info("Live market depth is only available during trading hours (09:15 – 15:30 IST).")
            else:
                market_depth_fragment(access_token)


        with idx_tab:
            st.markdown('<p class="section-heading">📊 NIFTY 50 & BANK NIFTY — Intraday Charts</p>', unsafe_allow_html=True)
            if not st.session_state.token_accepted:
                st.info("Accept your INDmoney token to load index charts.")
            else:
                # Index charts are in the top-level Indices tab (index_charts_fragment).
                # This tab now just shows a note pointing there.
                st.info("📊 Full NIFTY 50 & BANK NIFTY charts are shown above in the **Indices** tab.")


# â”€â”€ Invoke fragments â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if st.session_state.token_accepted:

    _tab_indices, _tab_scanner = st.tabs(["📊 Index Charts", "🔍 Live Scanner"])

    with _tab_indices:
        index_charts_fragment(access_token=access_token, sr_pivot_type=sr_pivot_type)

    with _tab_scanner:
        # Tiny status bar ticks every 3 s (small DOM — no visible flash)
        feed_status_fragment(access_token=access_token)
        # Signal tables tick every 5 s (CSS suppresses any residual flash)
        live_scanner_fragment(
            access_token        = access_token,
            min_change          = min_change,
            min_rvol            = min_rvol,
            min_breakout_score  = min_breakout_score,
            volume_premium_min  = volume_premium_min,
            volume_premium_max  = volume_premium_max,
            historical_workers  = historical_workers,
            sr_pivot_type       = sr_pivot_type,
        )

else:
    st.info("Waiting for INDmoney access token. Paste your token and click Accept Token.")

st.divider()
st.caption("📊 Trading Workstation — Abhilash  ·  INDmoney API  ·  1-min Intraday Candles  ·  NSE 90-Stock Universe")

