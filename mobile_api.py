"""
Mobile API Endpoints for Stock Screener
Provides JSON data for React Native mobile app
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_JSON_FILE = os.path.join(BASE_DIR, "screener_data.json")
LT_WATCHLIST_FILE = os.path.join(BASE_DIR, "lt_watchlist.json")
# Written by process_lt_watchlist() on every scan. Holds the same enriched rows
# the web page renders (status, badge, ltp, trend, scores, GTT distance), so the
# mobile app and the desktop app cannot drift apart.
LT_ENRICHED_FILE = os.path.join(BASE_DIR, "lt_watchlist_enriched.json")
HOLDINGS_FILE = os.path.join(BASE_DIR, "holdings.json")


def load_json_file(filepath: str, default: Any = None) -> Any:
    """Safely load JSON file with fallback."""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"⚠ Error loading {filepath}: {e}")
    return default if default is not None else {}


def get_screener_data() -> Dict:
    """Get current screener scan results."""
    stocks = load_json_file(OUT_JSON_FILE, [])
    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "total_stocks": len(stocks),
        "stocks": stocks[:100] if isinstance(stocks, list) else []
    }


def get_lt_watchlist() -> Dict:
    """Get the LT watchlist with the computed buy/wait signals.

    Reads lt_watchlist_enriched.json, which process_lt_watchlist() writes on
    every scan. That file carries the status/badge/ltp/trend/score fields the
    app renders. lt_watchlist.json is only the static config (symbol, sector,
    gtt_mode...) and has no signals, so it is used purely as a fallback when no
    scan has run yet -- in which case the caller is told the data is stale.
    """
    holdings = load_json_file(HOLDINGS_FILE, {})
    enriched_rows = load_json_file(LT_ENRICHED_FILE, [])
    enriched_available = bool(enriched_rows)

    if not enriched_available:
        enriched_rows = load_json_file(LT_WATCHLIST_FILE, [])

    watchlist = []
    buy_now_count = 0
    wait_count = 0

    for stock in enriched_rows:
        if not isinstance(stock, dict):
            continue

        sym = stock.get('symbol', '')
        # Only active rows carry a tradable signal; mirrors the desktop counts.
        if stock.get('active', True):
            status = stock.get('status')
            if status == 'BUY_NOW':
                buy_now_count += 1
            elif status == 'WAIT':
                wait_count += 1

        watchlist.append({
            **stock,
            "holding": stock.get('holding') or holdings.get(sym)
        })

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "signals_available": enriched_available,
        "total": len(watchlist),
        "buy_now": buy_now_count,
        "wait": wait_count,
        "watchlist": watchlist
    }


def get_holdings() -> Dict:
    """Get user holdings."""
    holdings = load_json_file(HOLDINGS_FILE, {})
    total_invested = sum(
        float(h.get('avg_price', 0)) * int(h.get('qty', 0))
        for h in holdings.values()
    )
    total_value = sum(
        float(h.get('ltp', h.get('avg_price', 0))) * int(h.get('qty', 0))
        for h in holdings.values()
    )
    pnl = total_value - total_invested if total_invested > 0 else 0
    pnl_pct = (pnl / total_invested * 100) if total_invested > 0 else 0

    return {
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "total_invested": round(total_invested, 2),
        "total_value": round(total_value, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "holdings": holdings
    }


def search_stocks(query: str) -> Dict:
    """Search stocks by symbol or name."""
    stocks = load_json_file(OUT_JSON_FILE, [])
    query_lower = query.lower()

    results = [
        s for s in stocks
        if isinstance(s, dict) and (
            query_lower in (s.get('symbol', '') or '').lower() or
            query_lower in (s.get('name', '') or '').lower()
        )
    ][:20]

    return {
        "status": "success",
        "query": query,
        "results": results
    }


def get_stock_detail(symbol: str) -> Dict:
    """Get detailed info for a single stock."""
    stocks = load_json_file(OUT_JSON_FILE, [])

    for stock in stocks:
        if isinstance(stock, dict) and stock.get('symbol') == symbol.upper():
            return {
                "status": "success",
                "stock": stock
            }

    return {
        "status": "error",
        "message": f"Stock {symbol} not found"
    }


def get_app_status() -> Dict:
    """Get app health and sync status."""
    return {
        "status": "success",
        "app_version": "1.0.0",
        "api_version": "1.0.0",
        "server_time": datetime.now().isoformat(),
        "data_age": "~15 min (Yahoo Finance delay)",
        "market_status": "Check NSE market hours 09:15-15:30 IST",
        "sync": {
            "screener": os.path.exists(OUT_JSON_FILE),
            "watchlist": os.path.exists(LT_WATCHLIST_FILE),
            "holdings": os.path.exists(HOLDINGS_FILE)
        }
    }
