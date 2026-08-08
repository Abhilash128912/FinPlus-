"""
pre_breakout_engine.py
======================
Pre-Breakout Scoring Engine.
Computes precursor signals (0-100 score) to flag coiling/accumulating stocks before they break out.
Applies hard exclusion/penalty filters to extended stocks.
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, List, Optional


def compute_atr(history: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Computes Average True Range (ATR) over given period."""
    if history is None or len(history) < period + 1:
        return None
    
    high = history["High"]
    low = history["Low"]
    close = history["Close"]
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean().iloc[-1]
    return float(atr) if not pd.isna(atr) else None


def compute_vcp_score(history: pd.DataFrame) -> Tuple[Optional[float], Dict]:
    """
    Component 2.1: Volatility Contraction Pattern (VCP) Score (0-100).
    - ATR(14) / ATR(50) ratio (<0.6 is tight compression).
    - Bollinger Band Width (20,2) percentile low over trailing 60 days.
    - Sequential range contraction bonus.
    """
    breakdown = {
        "atr_ratio": None,
        "atr_pts": 0,
        "bb_percentile": None,
        "bb_pts": 0,
        "sequential_bonus": 0,
        "vcp_score": None
    }
    
    if history is None or len(history) < 50:
        return None, breakdown
        
    atr14 = compute_atr(history, 14)
    atr50 = compute_atr(history, 50)
    
    if not atr14 or not atr50 or atr50 == 0:
        return None, breakdown
        
    atr_ratio = round(atr14 / atr50, 3)
    breakdown["atr_ratio"] = atr_ratio
    
    if atr_ratio <= 0.50:
        atr_pts = 50
    elif atr_ratio <= 0.60:
        atr_pts = 42
    elif atr_ratio <= 0.75:
        atr_pts = 30
    elif atr_ratio <= 0.90:
        atr_pts = 15
    else:
        atr_pts = 0
    breakdown["atr_pts"] = atr_pts
    
    bb_pts = 0
    if len(history) >= 60:
        close = history["Close"]
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_width = (std20 * 4) / sma20.replace(0, 1e-6)
        
        recent_width = bb_width.tail(60).dropna()
        if len(recent_width) >= 30:
            curr_w = recent_width.iloc[-1]
            pctile = float((recent_width <= curr_w).mean() * 100)
            breakdown["bb_percentile"] = round(pctile, 1)
            
            if pctile <= 10:
                bb_pts = 50
            elif pctile <= 20:
                bb_pts = 40
            elif pctile <= 35:
                bb_pts = 25
            elif pctile <= 50:
                bb_pts = 10
            else:
                bb_pts = 0
    breakdown["bb_pts"] = bb_pts
    
    bonus = 0
    if len(history) >= 15:
        r1 = (history["High"].iloc[-15:-10] - history["Low"].iloc[-15:-10]).mean()
        r2 = (history["High"].iloc[-10:-5] - history["Low"].iloc[-10:-5]).mean()
        r3 = (history["High"].iloc[-5:] - history["Low"].iloc[-5:]).mean()
        if r1 > r2 > r3 > 0:
            bonus = 10
    breakdown["sequential_bonus"] = bonus
    
    total_vcp = min(100.0, atr_pts + bb_pts + bonus)
    breakdown["vcp_score"] = round(total_vcp, 1)
    return round(total_vcp, 1), breakdown


def compute_stealth_accumulation(
    history: pd.DataFrame,
    cmf_history: List[float] = None
) -> Tuple[Optional[float], Dict]:
    """
    Component 2.2: Volume-Without-Price & CMF Trend (0-100).
    - Relative volume: Vol(5d avg) / Vol(50d avg) between 1.3x–2.0x.
    - Tight price range: High-Low over 10 sessions < 8% of price.
    - CMF Slope: Turning positive over last 5-10 sessions.
    """
    breakdown = {
        "rel_vol_5_50": None,
        "price_band_10d_pct": None,
        "cmf_slope_positive": False,
        "stealth_score": None
    }
    
    if history is None or len(history) < 50 or "Volume" not in history.columns:
        return None, breakdown
        
    vol5 = float(history["Volume"].tail(5).mean())
    vol50 = float(history["Volume"].tail(50).mean())
    
    if vol50 == 0:
        return None, breakdown
        
    rel_vol = round(vol5 / vol50, 2)
    breakdown["rel_vol_5_50"] = rel_vol
    
    # Check 10-session price range band
    h10 = float(history["High"].tail(10).max())
    l10 = float(history["Low"].tail(10).min())
    curr_c = float(history["Close"].iloc[-1])
    
    if curr_c == 0:
        return None, breakdown
        
    range_pct = round(((h10 - l10) / curr_c) * 100, 2)
    breakdown["price_band_10d_pct"] = range_pct
    
    # CMF slope check
    cmf_slope_pts = 0
    if cmf_history and len(cmf_history) >= 5:
        s5 = cmf_history[-5:]
        if s5[-1] > s5[0] and s5[-1] > -0.05:
            cmf_slope_pts = 30
            breakdown["cmf_slope_positive"] = True
            
    # Stealth volume scoring
    if 1.3 <= rel_vol <= 2.0 and range_pct <= 8.0:
        stealth_pts = 70.0
    elif 1.1 <= rel_vol <= 2.2 and range_pct <= 10.0:
        stealth_pts = 45.0
    else:
        stealth_pts = 10.0
        
    total_stealth = min(100.0, stealth_pts + cmf_slope_pts)
    breakdown["stealth_score"] = round(total_stealth, 1)
    return round(total_stealth, 1), breakdown


def compute_sector_rs(
    stock_return_20d: Optional[float],
    sector_return_20d: Optional[float]
) -> Tuple[Optional[float], Dict]:
    """
    Component 2.5: Relative Strength vs Sector (0-100).
    Stock quietly outperforming sector while sector is consolidating (sector return near 0).
    """
    breakdown = {
        "stock_ret_20d": stock_return_20d,
        "sector_ret_20d": sector_return_20d,
        "rs_diff": None,
        "sector_rs_score": None
    }
    
    if stock_return_20d is None or sector_return_20d is None:
        return None, breakdown
        
    diff = round(stock_return_20d - sector_return_20d, 2)
    breakdown["rs_diff"] = diff
    
    # Sector consolidating check (-5% to +5% return)
    sector_is_basing = -5.0 <= sector_return_20d <= 5.0
    
    if diff >= 5.0 and sector_is_basing:
        score = 100.0
    elif diff >= 2.0 and sector_is_basing:
        score = 80.0
    elif diff >= 0.0:
        score = 60.0
    elif diff >= -3.0:
        score = 35.0
    else:
        score = 10.0
        
    breakdown["sector_rs_score"] = score
    return score, breakdown


def compute_tight_consolidation(
    history: pd.DataFrame,
    info: Dict
) -> Tuple[Optional[float], Dict]:
    """
    Component 2.6: Tight Consolidation Near Resistance (0-100).
    - Price within 3%-5% of 52W high / swing high (not above).
    - RSI(14) in 45-60 band.
    - Daily range (High-Low)/Close narrowing over trailing 10 sessions.
    """
    breakdown = {
        "pct_from_high": None,
        "rsi": None,
        "range_narrowing": False,
        "days_in_consolidation": 0,
        "consolidation_score": None
    }
    
    if history is None or len(history) < 15:
        return None, breakdown
        
    curr_c = float(history["Close"].iloc[-1])
    high_52w = float(info.get("fiftyTwoWeekHigh") or history["High"].max() or 0)
    
    if high_52w == 0 or curr_c == 0:
        return None, breakdown
        
    pct_from_high = round(((high_52w - curr_c) / high_52w) * 100, 2)
    breakdown["pct_from_high"] = pct_from_high
    
    # Calculate RSI 14
    delta = history["Close"].diff()
    gain = delta.clip(lower=0).tail(14).mean()
    loss = (-delta.clip(upper=0)).tail(14).mean()
    rsi_val = 50.0
    if loss and loss > 0:
        rs = gain / loss
        rsi_val = round(100 - (100 / (1 + rs)), 1)
    breakdown["rsi"] = rsi_val
    
    # Check range narrowing over last 10 days
    ranges = (history["High"] - history["Low"]) / history["Close"]
    r10 = ranges.tail(10)
    range_narrowing = bool(r10.iloc[-1] < r10.mean())
    breakdown["range_narrowing"] = range_narrowing
    
    # Days in consolidation (count days price stayed within 5% range)
    c10 = history["Close"].tail(15)
    days_cons = int((c10 >= curr_c * 0.95).sum())
    breakdown["days_in_consolidation"] = days_cons
    
    score = 0.0
    if 0.0 <= pct_from_high <= 5.0:  # Within 5% of high (not above)
        score += 40.0
    if 45.0 <= rsi_val <= 60.0:     # Neutral coiling RSI
        score += 40.0
    if range_narrowing:
        score += 20.0
        
    breakdown["consolidation_score"] = score
    return score, breakdown


def compute_exclusion_thresholds(universe_results: List[Dict], min_universe: int = 50) -> Optional[Dict]:
    """Computes decile/quartile thresholds. Guard: requires universe size N >= min_universe."""
    if not universe_results or len(universe_results) < min_universe:
        return None
        
    wk52_returns = [r.get("wk52_return_pct") for r in universe_results if r.get("wk52_return_pct") is not None]
    momentum_scores = [r.get("momentum") for r in universe_results if r.get("momentum") is not None]
    
    thresholds = {}
    if len(wk52_returns) >= min_universe:
        thresholds["wk52_p90"] = float(np.percentile(wk52_returns, 90))
    if len(momentum_scores) >= min_universe:
        thresholds["momentum_p75"] = float(np.percentile(momentum_scores, 75))
        
    return thresholds if thresholds else None


def apply_exclusion_filter(stock_metrics: Dict, thresholds: Optional[Dict]) -> Tuple[bool, float, List[str]]:
    """Section 3 Exclusion Filter: Penalizes/excludes extended stocks."""
    reasons = []
    penalty = 0.0
    
    wk52 = stock_metrics.get("wk52_return_pct")
    if thresholds and "wk52_p90" in thresholds and wk52 is not None:
        if wk52 >= thresholds["wk52_p90"]:
            penalty += 40.0
            reasons.append(f"52W Return ({wk52:.1f}%) in top decile (>= {thresholds['wk52_p90']:.1f}%)")
            
    vol_spike = stock_metrics.get("volume_spike", 0.0) or 0.0
    if vol_spike >= 2.5:
        penalty += 35.0
        reasons.append(f"Volume Spike ({vol_spike:.2f}x) >= 2.5x threshold")
        
    rsi = stock_metrics.get("rsi")
    if rsi is not None and rsi >= 70:
        penalty += 35.0
        reasons.append(f"RSI ({rsi:.1f}) >= 70 overbought threshold")
        
    mom = stock_metrics.get("momentum")
    if thresholds and "momentum_p75" in thresholds and mom is not None:
        if mom >= thresholds["momentum_p75"]:
            penalty += 30.0
            reasons.append(f"Momentum Score ({mom:.1f}) in top quartile (>= {thresholds['momentum_p75']:.1f})")
            
    is_excluded = penalty >= 40.0 or len(reasons) >= 2
    return is_excluded, penalty, reasons


def compute_pre_breakout_score(
    vcp_score: Optional[float],
    stealth_score: Optional[float],
    delivery_score: Optional[float],
    fno_oi_score: Optional[float],
    sector_rs_score: Optional[float],
    consolidation_score: Optional[float],
    is_fno: bool = False,
    exclusion_penalty: float = 0.0
) -> Tuple[Optional[float], Dict]:
    """Master PreBreakoutScore calculation (0-100) with dynamic weight redistribution."""
    weights = {
        "vcp": (30.0, vcp_score),
        "stealth": (20.0, stealth_score),
        "delivery": (20.0, delivery_score),
        "fno_oi": (10.0, fno_oi_score if is_fno else None),
        "sector_rs": (15.0, sector_rs_score),
        "consolidation": (5.0, consolidation_score)
    }
    
    valid_total_weight = 0.0
    weighted_score_sum = 0.0
    sub_scores = {}
    
    for key, (w, val) in weights.items():
        sub_scores[key] = val
        if val is not None:
            valid_total_weight += w
            weighted_score_sum += (w * val)
            
    if valid_total_weight == 0:
        return None, {"sub_scores": sub_scores, "penalty": exclusion_penalty, "raw_score": None}
        
    raw_score = weighted_score_sum / valid_total_weight
    final_score = max(0.0, raw_score - exclusion_penalty)
    
    return round(final_score, 1), {
        "sub_scores": sub_scores,
        "penalty": exclusion_penalty,
        "raw_score": round(raw_score, 1),
        "valid_weight_pct": round(valid_total_weight, 1)
    }
