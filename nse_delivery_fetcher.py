"""
nse_delivery_fetcher.py
======================
Fetches delivery percentage data from NSE via nsepython.
Calculates 5-day rolling delivery % vs 20-day average baseline.

STRICT RULE: If nsepython fails or returns no data, returns None (displays '—').
NO volume proxy fallbacks allowed to prevent signal double-counting.
"""

from typing import Optional, Tuple, Dict
import pandas as pd


def fetch_delivery_data(symbol: str) -> Optional[float]:
    """
    Fetches latest delivery percentage for symbol using nsepython.
    Returns float (0.0 to 100.0) or None if fetch fails.
    """
    clean_sym = symbol.replace(".NS", "").strip().upper()
    try:
        from nsepython import nse_eq
        eq_data = nse_eq(clean_sym)
        if isinstance(eq_data, dict):
            sec_info = eq_data.get("securityInfo", {})
            del_pct = sec_info.get("deliveryToTradedQuantity")
            if del_pct is not None:
                return float(del_pct)
            
            # Alternative layout in nsepython json
            price_info = eq_data.get("priceInfo", {})
            del_pct_alt = price_info.get("deliveryToTradedQuantity")
            if del_pct_alt is not None:
                return float(del_pct_alt)
    except Exception:
        pass
        
    return None


def compute_delivery_trend_score(
    symbol: str,
    history_snapshots: list,
    current_delivery: Optional[float] = None
) -> Tuple[Optional[float], Dict]:
    """
    Component 2.3: Delivery % Trend Score (0-100).
    Compares 5-day rolling average delivery % to 20-day baseline.
    Requires at least 5 snapshot data points; otherwise returns None ('—').
    """
    breakdown = {
        "latest_delivery_pct": current_delivery,
        "del_5d_avg": None,
        "del_20d_avg": None,
        "delivery_score": None
    }
    
    # Collect delivery series from history snapshots + current
    del_series = []
    for snap in history_snapshots:
        val = snap.get("delivery_pct")
        if val is not None:
            del_series.append(float(val))
            
    if current_delivery is not None:
        del_series.append(float(current_delivery))
        breakdown["latest_delivery_pct"] = current_delivery
        
    if len(del_series) < 5:
        return None, breakdown
        
    del_5d = float(pd.Series(del_series).tail(5).mean())
    del_20d = float(pd.Series(del_series).tail(20).mean())
    
    breakdown["del_5d_avg"] = round(del_5d, 2)
    breakdown["del_20d_avg"] = round(del_20d, 2)
    
    # Score comparison
    if del_20d > 0:
        ratio = del_5d / del_20d
        if ratio >= 1.4:
            score = 100.0
        elif ratio >= 1.25:
            score = 85.0
        elif ratio >= 1.10:
            score = 70.0
        elif ratio >= 1.0:
            score = 50.0
        elif ratio >= 0.85:
            score = 30.0
        else:
            score = 10.0
    else:
        score = 50.0
        
    score_res = round(score, 1)
    breakdown["delivery_score"] = score_res
    return score_res, breakdown
