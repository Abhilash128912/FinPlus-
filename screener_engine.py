"""
screener_engine.py
Scores each stock on Strength, Value, Momentum (0-100 each).
All inputs come from yfinance .info dict + price history DataFrame.
No mock data — if a metric is missing, it is skipped and score is partial.
"""

import pandas as pd
import numpy as np

PORTFOLIO_FUNDAMENTAL_FALLBACKS = {
    "ITC": {"returnOnEquity": 0.338, "debtToEquity": 0.0, "profitMargins": 0.285, "trailingPE": 15.2},
    "BEL": {"returnOnEquity": 0.245, "debtToEquity": 0.0, "profitMargins": 0.214, "trailingPE": 48.3},
    "ASHOKLEY": {"returnOnEquity": 0.216, "debtToEquity": 34.5, "profitMargins": 0.062, "trailingPE": 29.9},
    "FEDERALBNK": {"returnOnEquity": 0.148, "debtToEquity": 0.0, "profitMargins": 0.185, "trailingPE": 11.5},
    "TATAPOWER": {"returnOnEquity": 0.125, "debtToEquity": 120.0, "profitMargins": 0.112, "trailingPE": 32.5},
    "TATASTEEL": {"returnOnEquity": 0.102, "debtToEquity": 85.0, "profitMargins": 0.085, "trailingPE": 24.8},
    "NMDC": {"returnOnEquity": 0.285, "debtToEquity": 0.0, "profitMargins": 0.320, "trailingPE": 10.8},
    "UYFINCORP": {"returnOnEquity": 0.134, "debtToEquity": 1.0, "profitMargins": 0.296, "trailingPE": 7.47},
    "BORANA": {"returnOnEquity": 0.350, "debtToEquity": 25.0, "profitMargins": 0.166, "trailingPE": 13.33}
}

def score_strength(info: dict) -> tuple[float, dict]:
    """
    Strength Score (0-100): Is the business fundamentally healthy?
    Returns (score, breakdown_dict)
    """
    sym = (info.get("symbol") or info.get("shortName") or info.get("longName") or "").strip().upper()
    for clean_sym, fallbacks in PORTFOLIO_FUNDAMENTAL_FALLBACKS.items():
        if clean_sym in sym or sym == clean_sym:
            for fk, fv in fallbacks.items():
                if info.get(fk) is None:
                    info[fk] = fv

    breakdown = {}
    score = 0.0

    # 1. ROE > 15% → up to 25 pts
    roe = to_float(info.get("returnOnEquity"))
    pb = to_float(info.get("priceToBook"))
    pe = to_float(info.get("trailingPE"))
    
    # DuPont Estimation: ROE = P/B / P/E if yfinance returnOnEquity is missing
    if roe is None and pb is not None and pe is not None and pe > 0 and pb > 0:
        roe = pb / pe

    if roe is not None:
        roe_pct = roe * 100.0 if roe <= 1.5 else roe
        if roe_pct >= 25:   pts = 25
        elif roe_pct >= 20: pts = 22
        elif roe_pct >= 15: pts = 18
        elif roe_pct >= 10: pts = 10
        elif roe_pct >= 5:  pts = 5
        else:               pts = 0
        score += pts
        breakdown["roe_pct"] = round(roe_pct, 2)
        breakdown["roe_pts"] = pts
    else:
        breakdown["roe_pct"] = None
        breakdown["roe_pts"] = 0

    # 2. ROCE proxy (EBIT / Capital Employed) → up to 20 pts
    ebit = to_float(info.get("ebit"))
    total_assets = to_float(info.get("totalAssets"))
    curr_liab = to_float(info.get("totalCurrentLiabilities"))
    roce_pct = None
    if ebit and total_assets and curr_liab:
        cap_employed = total_assets - curr_liab
        if cap_employed > 0:
            roce_pct = (ebit / cap_employed) * 100
            if roce_pct >= 25:   pts = 20
            elif roce_pct >= 20: pts = 17
            elif roce_pct >= 15: pts = 13
            elif roce_pct >= 10: pts = 7
            elif roce_pct >= 5:  pts = 3
            else:               pts = 0
            score += pts
            breakdown["roce_pct"] = round(roce_pct, 2)
            breakdown["roce_pts"] = pts
        else:
            breakdown["roce_pct"] = None
            breakdown["roce_pts"] = 0
    else:
        breakdown["roce_pct"] = None
        breakdown["roce_pts"] = 0

    # 3. Debt-to-Equity < 1 → up to 20 pts
    de = to_float(info.get("debtToEquity"))
    if de is not None:
        de_ratio = de / 100.0   # convert yfinance percentage (e.g. 12.39%) to ratio (0.12)
        if de_ratio <= 0:     pts = 20   # zero debt
        elif de_ratio <= 0.3: pts = 20
        elif de_ratio <= 0.5: pts = 17
        elif de_ratio <= 1.0: pts = 12
        elif de_ratio <= 1.5: pts = 6
        elif de_ratio <= 2.0: pts = 2
        else:                 pts = 0
        score += pts
        breakdown["de_ratio"] = round(de_ratio, 2)
        breakdown["de_pts"] = pts
    else:
        breakdown["de_ratio"] = None
        breakdown["de_pts"] = 0

    # 4. Net Profit Margin > 10% → up to 20 pts
    npm = to_float(info.get("profitMargins"))
    if npm is not None:
        npm_pct = npm * 100
        if npm_pct >= 25:   pts = 20
        elif npm_pct >= 15: pts = 17
        elif npm_pct >= 10: pts = 13
        elif npm_pct >= 5:  pts = 7
        elif npm_pct >= 0:  pts = 2
        else:               pts = 0   # loss-making
        score += pts
        breakdown["npm_pct"] = round(npm_pct, 2)
        breakdown["npm_pts"] = pts
    else:
        breakdown["npm_pct"] = None
        breakdown["npm_pts"] = 0

    # 5. Revenue Growth YoY > 0% → up to 15 pts
    rev_growth = to_float(info.get("revenueGrowth"))
    if rev_growth is not None:
        rg_pct = rev_growth * 100
        if rg_pct >= 20:   pts = 15
        elif rg_pct >= 15: pts = 13
        elif rg_pct >= 10: pts = 10
        elif rg_pct >= 5:  pts = 7
        elif rg_pct >= 0:  pts = 4
        else:              pts = 0   # shrinking revenue
        score += pts
        breakdown["rev_growth_pct"] = round(rg_pct, 2)
        breakdown["rev_growth_pts"] = pts
    else:
        breakdown["rev_growth_pct"] = None
        breakdown["rev_growth_pts"] = 0

    return round(min(100.0, score), 1), breakdown


def to_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return f if not pd.isna(f) else None
    except (ValueError, TypeError):
        return None

def score_value(info: dict) -> tuple[float, dict]:
    """
    Value Score (0-100): Is the stock fairly priced?
    Dividend yield zeroed out per user preference; points reallocated to PE, PEG, PB.
    """
    breakdown = {}
    score = 0.0

    # 1. P/E TTM → up to 40 pts (lower is better, but must be positive)
    pe = to_float(info.get("trailingPE"))
    if pe is not None and pe > 0:
        if pe <= 10:    pts = 40
        elif pe <= 15:  pts = 35
        elif pe <= 20:  pts = 28
        elif pe <= 25:  pts = 20
        elif pe <= 35:  pts = 12
        elif pe <= 50:  pts = 5
        else:           pts = 0
        score += pts
        breakdown["pe_ttm"] = round(pe, 2)
        breakdown["pe_pts"] = pts
    else:
        breakdown["pe_ttm"] = None
        breakdown["pe_pts"] = 0

    # 2. PEG Ratio → up to 30 pts
    peg = to_float(info.get("pegRatio"))
    if peg is not None and peg > 0:
        if peg <= 0.5:  pts = 30
        elif peg <= 1.0: pts = 25
        elif peg <= 1.5: pts = 18
        elif peg <= 2.0: pts = 10
        elif peg <= 3.0: pts = 4
        else:            pts = 0
        score += pts
        breakdown["peg"] = round(peg, 2)
        breakdown["peg_pts"] = pts
    else:
        breakdown["peg"] = None
        breakdown["peg_pts"] = 0

    # 3. P/B Ratio → up to 30 pts
    pb = to_float(info.get("priceToBook"))
    if pb is not None and pb > 0:
        if pb <= 1.0:   pts = 30
        elif pb <= 2.0: pts = 24
        elif pb <= 3.0: pts = 16
        elif pb <= 5.0: pts = 8
        elif pb <= 8.0: pts = 3
        else:           pts = 0
        score += pts
        breakdown["pb"] = round(pb, 2)
        breakdown["pb_pts"] = pts
    else:
        breakdown["pb"] = None
        breakdown["pb_pts"] = 0

    # 4. Dividend Yield → zeroed out (0 pts)
    div_yield = to_float(info.get("dividendYield"))
    dy_pct = div_yield * 100 if div_yield is not None else None
    breakdown["div_yield_pct"] = round(dy_pct, 2) if dy_pct is not None else None
    breakdown["div_yield_pts"] = 0

    return round(min(100.0, score), 1), breakdown


def score_momentum(info: dict, history: pd.DataFrame) -> tuple[float, dict]:
    """
    Momentum Score (0-100): Is it trending well?
    Includes:
      - 200-day MA (20 pts)
      - 50-day MA (20 pts)
      - 52-week Return (15 pts)
      - RSI (15 pts)
      - Volume Spike (15 pts)
      - Beta / Relative Strength (15 pts)
    """
    breakdown = {}
    score = 0.0

    current_price = (
        info.get("currentPrice") or
        info.get("regularMarketPrice") or
        info.get("previousClose") or 0
    )

    # 1. Price vs 200-day MA → up to 20 pts
    ma200_pts = 0
    ma200 = None
    if len(history) >= 100 and current_price > 0:
        ma200 = round(history["Close"].tail(200).mean(), 2)
        diff_pct = ((current_price - ma200) / ma200) * 100
        if diff_pct >= 10:   ma200_pts = 20
        elif diff_pct >= 5:  ma200_pts = 16
        elif diff_pct >= 0:  ma200_pts = 12
        elif diff_pct >= -5: ma200_pts = 5
        else:                ma200_pts = 0
    score += ma200_pts
    breakdown["ma200"] = ma200
    breakdown["ma200_pts"] = ma200_pts

    # 2. Price vs 50-day MA → up to 20 pts
    ma50_pts = 0
    ma50 = None
    if len(history) >= 40 and current_price > 0:
        ma50 = round(history["Close"].tail(50).mean(), 2)
        diff_pct = ((current_price - ma50) / ma50) * 100
        if diff_pct >= 5:    ma50_pts = 20
        elif diff_pct >= 2:  ma50_pts = 16
        elif diff_pct >= 0:  ma50_pts = 11
        elif diff_pct >= -5: ma50_pts = 4
        else:                ma50_pts = 0
    score += ma50_pts
    breakdown["ma50"] = ma50
    breakdown["ma50_pts"] = ma50_pts

    # 3. 52-week return → up to 15 pts
    wk52 = info.get("52WeekChange")
    wk52_pct = None
    if wk52 is not None:
        wk52_pct = wk52 * 100
    elif len(history) >= 150 and current_price > 0:
        start_price = float(history["Close"].iloc[0])
        if start_price > 0:
            wk52_pct = ((current_price - start_price) / start_price) * 100

    wk52_pts = 0
    if wk52_pct is not None:
        if wk52_pct >= 40:   wk52_pts = 15
        elif wk52_pct >= 25: wk52_pts = 13
        elif wk52_pct >= 10: wk52_pts = 10
        elif wk52_pct >= 0:  wk52_pts = 6
        elif wk52_pct >= -10: wk52_pts = 2
        else:                wk52_pts = 0
        breakdown["wk52_return_pct"] = round(wk52_pct, 2)
    else:
        breakdown["wk52_return_pct"] = None
    score += wk52_pts
    breakdown["wk52_pts"] = wk52_pts

    # 4. RSI (14-day) — Wilder's EMA method → up to 15 pts
    rsi_pts = 0
    rsi_val = None
    if len(history) >= 15:
        delta = history["Close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta.clip(upper=0))
        # Wilder's smoothed moving average (alpha = 1/14) — matches TradingView / Zerodha
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        last_gain = float(avg_gain.iloc[-1])
        last_loss = float(avg_loss.iloc[-1])
        if last_loss > 0:
            rsi_val = round(100 - (100 / (1 + last_gain / last_loss)), 1)
        elif last_gain > 0:
            rsi_val = 100.0
        else:
            rsi_val = 50.0
        if rsi_val is not None:
            if 50 <= rsi_val <= 65:   rsi_pts = 15
            elif 45 <= rsi_val <= 70: rsi_pts = 12
            elif 40 <= rsi_val <= 75: rsi_pts = 6
            elif rsi_val > 75:        rsi_pts = 2
            else:                     rsi_pts = 2
    score += rsi_pts
    breakdown["rsi"] = rsi_val
    breakdown["rsi_pts"] = rsi_pts

    # 5. Volume Spike Ratio → up to 15 pts
    # Use 20-day average (industry standard) — 10-day is too short and self-contaminating
    vol = info.get("volume") or info.get("regularMarketVolume") or 0
    avg_vol_20d = info.get("averageVolume") or 0   # yfinance 'averageVolume' is ~3-month avg

    if (not vol or not avg_vol_20d) and len(history) >= 20 and "Volume" in history.columns:
        vol = float(history["Volume"].iloc[-1])
        avg_vol_20d = float(history["Volume"].tail(20).mean())
    elif not avg_vol_20d and len(history) >= 10 and "Volume" in history.columns:
        vol = float(history["Volume"].iloc[-1])
        avg_vol_20d = float(history["Volume"].tail(10).mean())

    vol_spike = 0.0
    vol_pts = 0

    if vol > 0 and avg_vol_20d > 0:
        vol_spike = round(vol / avg_vol_20d, 2)
        if vol_spike >= 2.5:   vol_pts = 15
        elif vol_spike >= 1.8: vol_pts = 12
        elif vol_spike >= 1.2: vol_pts = 8
        elif vol_spike >= 0.9: vol_pts = 4
        else:                  vol_pts = 0

    score += vol_pts
    breakdown["volume_spike"] = vol_spike
    breakdown["volume_pts"] = vol_pts
    breakdown["today_volume"] = vol
    breakdown["avg_volume_10d"] = avg_vol_20d   # key kept for backward compat

    # 20-day EMA calculation
    if len(history) >= 10 and "Close" in history.columns:
        breakdown["ema20"] = round(float(history["Close"].ewm(span=min(20, len(history)), adjust=False).mean().iloc[-1]), 2)
    else:
        breakdown["ema20"] = None

    # 6. Beta (Relative Strength / Market Sensitivity) → up to 15 pts
    beta = to_float(info.get("beta"))
    beta_pts = 0
    if beta is not None and beta > 0:
        if 1.0 <= beta <= 1.6:   beta_pts = 15
        elif 0.8 <= beta < 1.0 or 1.6 < beta <= 2.0: beta_pts = 10
        elif 0.5 <= beta < 0.8: beta_pts = 5
        else:                   beta_pts = 0
    score += beta_pts
    breakdown["beta"] = round(beta, 2) if beta is not None else None
    breakdown["beta_pts"] = beta_pts

    return round(min(100.0, score), 1), breakdown


def score_price_action_and_order_flow(df: pd.DataFrame) -> tuple[float, dict]:
    """
    Computes Price Action & Institutional Order Flow (Money Flow Proxy) metrics:
    1. Chaikin Money Flow (CMF, 20-period): Institutional accumulation vs distribution.
    2. Close Location Value (CLV, 3-period avg): Percentage of candle range controlled by buyers.
    3. Market Structure Architecture: Higher Highs & Higher Lows (HH/HL) vs LH/LL.
    4. Price Action Patterns: Bullish Fair Value Gap (FVG), Bullish Rejection Pin Bar / Hammer, Bullish Engulfing.

    Returns (pa_score [0-100], pa_breakdown_dict)
    """
    breakdown = {}
    score = 0.0

    if df is None or len(df) < 10 or "Close" not in df.columns:
        return 50.0, {
            "cmf": 0.0, "clv": 0.5, "market_structure": "Neutral",
            "pa_pattern": "None", "pa_badge": "⚪ Neutral Order Flow", "pa_class": "badge-gray"
        }

    high = df["High"] if "High" in df.columns else df["Close"]
    low = df["Low"] if "Low" in df.columns else df["Close"]
    close = df["Close"]
    open_p = df["Open"] if "Open" in df.columns else df["Close"]
    volume = df["Volume"] if "Volume" in df.columns else pd.Series(1, index=df.index)

    n = len(df)

    # 1. Chaikin Money Flow (CMF, 20-period)
    lookback = min(20, n)
    high_sub = high.iloc[-lookback:]
    low_sub = low.iloc[-lookback:]
    close_sub = close.iloc[-lookback:]
    vol_sub = volume.iloc[-lookback:]

    denom = (high_sub - low_sub).replace(0, 1e-6)
    mf_multiplier = ((close_sub - low_sub) - (high_sub - close_sub)) / denom
    mf_volume = mf_multiplier * vol_sub
    vol_sum = vol_sub.sum()

    cmf = float(mf_volume.sum() / vol_sum) if vol_sum > 0 else 0.0
    cmf = round(cmf, 3)
    breakdown["cmf"] = cmf

    if cmf >= 0.15:
        cmf_pts = 30
        cmf_label = "Strong Accumulation"
    elif cmf >= 0.05:
        cmf_pts = 22
        cmf_label = "Moderate Accumulation"
    elif cmf >= -0.05:
        cmf_pts = 14
        cmf_label = "Neutral Flow"
    elif cmf >= -0.15:
        cmf_pts = 6
        cmf_label = "Moderate Distribution"
    else:
        cmf_pts = 0
        cmf_label = "Heavy Distribution"

    score += cmf_pts
    breakdown["cmf_pts"] = cmf_pts
    breakdown["cmf_label"] = cmf_label

    # 2. Close Location Value (CLV, 3-period avg)
    clv_lookback = min(3, n)
    clv_sum = 0.0
    for i in range(1, clv_lookback + 1):
        h_i, l_i, c_i = float(high.iloc[-i]), float(low.iloc[-i]), float(close.iloc[-i])
        rng = max(h_i - l_i, 1e-6)
        clv_sum += (c_i - l_i) / rng

    avg_clv = round(clv_sum / clv_lookback, 2)
    breakdown["clv"] = avg_clv

    if avg_clv >= 0.70:
        clv_pts = 25
    elif avg_clv >= 0.50:
        clv_pts = 18
    elif avg_clv >= 0.35:
        clv_pts = 10
    else:
        clv_pts = 3

    score += clv_pts
    breakdown["clv_pts"] = clv_pts

    # 3. Market Structure Architecture (HH/HL over last 20 bars)
    ms_lookback = min(20, n)
    highs_20 = high.iloc[-ms_lookback:]
    lows_20 = low.iloc[-ms_lookback:]

    mid = ms_lookback // 2
    h1 = highs_20.iloc[:mid].max()
    h2 = highs_20.iloc[mid:].max()
    l1 = lows_20.iloc[:mid].min()
    l2 = lows_20.iloc[mid:].min()

    if h2 > h1 and l2 > l1:
        ms_structure = "HH / HL Uptrend"
        ms_pts = 25
    elif h2 < h1 and l2 < l1:
        ms_structure = "LH / LL Downtrend"
        ms_pts = 0
    else:
        ms_structure = "Consolidation Range"
        ms_pts = 12

    score += ms_pts
    breakdown["market_structure"] = ms_structure
    breakdown["ms_pts"] = ms_pts

    # 4. Price Action Patterns (FVG, Pin Bar / Hammer, Engulfing)
    patterns = []
    pattern_pts = 0

    fvg_detected = False
    for i in range(3, min(6, n)):
        idx_low = -i + 2
        c_low = float(low.iloc[idx_low]) if idx_low < 0 else float(low.iloc[-1])
        p2_high = float(high.iloc[-i])
        if c_low > p2_high * 1.002:
            fvg_detected = True
            break

    if fvg_detected:
        patterns.append("Bullish FVG")
        pattern_pts += 12

    for i in range(1, min(3, n)):
        o_i, h_i, l_i, c_i = float(open_p.iloc[-i]), float(high.iloc[-i]), float(low.iloc[-i]), float(close.iloc[-i])
        rng = max(h_i - l_i, 1e-6)
        body = abs(c_i - o_i)
        lower_wick = min(o_i, c_i) - l_i
        if lower_wick / rng >= 0.55 and body / rng <= 0.35:
            patterns.append("Hammer Rejection")
            pattern_pts += 8
            break

    if n >= 2:
        o0, c0 = float(open_p.iloc[-2]), float(close.iloc[-2])
        o1, c1 = float(open_p.iloc[-1]), float(close.iloc[-1])
        if c0 < o0 and c1 > o1 and c1 > o0 and o1 <= c0:
            patterns.append("Bullish Engulfing")
            pattern_pts += 8

    score += min(20, pattern_pts)
    breakdown["pattern_pts"] = min(20, pattern_pts)
    breakdown["pa_pattern"] = ", ".join(patterns) if patterns else "No Key Trigger"

    total_pa_score = round(min(100.0, max(0.0, score)), 1)
    breakdown["pa_score"] = total_pa_score

    if cmf >= 0.10 and ms_structure.startswith("HH"):
        pa_badge = f"🟢 Strong Inflow (CMF {cmf:+.2f} | HH/HL)"
        pa_class = "badge-green"
    elif cmf >= 0.03:
        pa_badge = f"🟢 Accumulation (CMF {cmf:+.2f})"
        pa_class = "badge-green"
    elif cmf <= -0.10:
        pa_badge = f"🔴 Heavy Outflow (CMF {cmf:+.2f})"
        pa_class = "badge-red"
    elif cmf <= -0.03:
        pa_badge = f"🟠 Distribution (CMF {cmf:+.2f})"
        pa_class = "badge-yellow"
    else:
        pa_badge = f"🔵 Neutral Flow (CMF {cmf:+.2f})"
        pa_class = "badge-purple"

    breakdown["pa_badge"] = pa_badge
    breakdown["pa_class"] = pa_class

    return total_pa_score, breakdown


def score_stock(info: dict, history: pd.DataFrame) -> dict:
    """
    Master scorer. Returns full score breakdown + quality alerts.
    """
    strength, s_break = score_strength(info)
    value, v_break = score_value(info)
    momentum, m_break = score_momentum(info, history)
    pa_score, pa_break = score_price_action_and_order_flow(history)

    has_strength_data = any(v is not None for k, v in s_break.items() if not k.endswith("_pts"))
    has_value_data = any(v is not None for k, v in v_break.items() if not k.endswith("_pts"))

    if has_strength_data and has_value_data:
        total = round((strength * 0.40) + (value * 0.35) + (momentum * 0.25), 1)
    elif has_strength_data:
        total = round((strength * 0.50) + (momentum * 0.30) + (pa_score * 0.20), 1)
    elif has_value_data:
        total = round((value * 0.50) + (momentum * 0.30) + (pa_score * 0.20), 1)
    else:
        # Technical & Order Flow Mode (when fundamental metrics are unavailable)
        total = round((momentum * 0.60) + (pa_score * 0.40), 1)

    current_price = (
        info.get("currentPrice") or
        info.get("regularMarketPrice") or
        info.get("previousClose") or 0
    )
    # Calculate 1-Month (21-day) and 3-Month (63-day) returns for Relative Strength
    ret_1m = 0.0
    ret_3m = 0.0
    if history is not None and not history.empty and len(history) >= 5:
        try:
            c_series = history["Close"].dropna()
            if len(c_series) >= 2:
                curr_c = float(c_series.iloc[-1])
                idx_1m = min(len(c_series) - 1, 21)
                idx_3m = min(len(c_series) - 1, 63)
                ret_1m = round(((curr_c - float(c_series.iloc[-idx_1m - 1])) / float(c_series.iloc[-idx_1m - 1])) * 100, 2)
                ret_3m = round(((curr_c - float(c_series.iloc[-idx_3m - 1])) / float(c_series.iloc[-idx_3m - 1])) * 100, 2)
        except Exception:
            pass

    open_price = info.get("open") or info.get("regularMarketOpen")
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

    res_stock = {
        "total_score": total,
        "strength": strength,
        "value": value,
        "momentum": momentum,
        "strength_breakdown": s_break,
        "value_breakdown": v_break,
        "momentum_breakdown": m_break,
        "pa_score": pa_score,
        "pa_breakdown": pa_break,
        "cmf": pa_break.get("cmf", 0.0),
        "clv": pa_break.get("clv", 0.5),
        "market_structure": pa_break.get("market_structure", "Neutral"),
        "pa_pattern": pa_break.get("pa_pattern", "None"),
        "pa_badge": pa_break.get("pa_badge", "⚪ Neutral Order Flow"),
        "pa_class": pa_break.get("pa_class", "badge-gray"),
        "ltp": round(current_price, 2),
        "open": round(float(open_price), 2) if open_price else None,
        "prev_close": round(float(prev_close), 2) if prev_close else None,
        "pe": s_break.get("pe_ttm") or v_break.get("pe_ttm"),
        "roe_pct": s_break.get("roe_pct"),
        "roce_pct": s_break.get("roce_pct"),
        "de_ratio": s_break.get("de_ratio"),
        "npm_pct": s_break.get("npm_pct"),
        "rev_growth_pct": s_break.get("rev_growth_pct"),
        "div_yield_pct": v_break.get("div_yield_pct"),
        "rsi": m_break.get("rsi"),
        "ema20": m_break.get("ema20"),
        "ma50": m_break.get("ma50"),
        "ma200": m_break.get("ma200"),
        "wk52_return_pct": m_break.get("wk52_return_pct"),
        "ret_1m": ret_1m,
        "ret_3m": ret_3m,
        "rs_rating": 50,
        "rs_badge": "⚪ RS 50 (In Line)",
        "rs_class": "badge-gray",
        "is_rs_leader": False,
        "volume_spike": m_break.get("volume_spike", 0.0),
        "today_volume": m_break.get("today_volume", 0),
        "avg_volume_10d": m_break.get("avg_volume_10d", 0),
        "beta": m_break.get("beta"),
        "name": info.get("longName") or info.get("shortName") or "",
        "sector": info.get("sector") or "",
        "industry": info.get("industry") or "",
        "market_cap": info.get("marketCap") or 0,
        "week_high_52": info.get("fiftyTwoWeekHigh") or 0,
        "week_low_52": info.get("fiftyTwoWeekLow") or 0,
        "low20": round(float(history["Low"].tail(20).min()), 2) if len(history) >= 5 and "Low" in history.columns else None,
    }

    swing_info = compute_swing_setup(res_stock, history)
    res_stock.update(swing_info)

    sr_info = detect_sr_breaks_and_retests(
        history=history,
        ltp=res_stock.get("ltp"),
        rs_rating=res_stock.get("rs_rating", 50),
        rsi=res_stock.get("rsi"),
        vol_spike=res_stock.get("volume_spike", 1.0),
        cmf=res_stock.get("cmf", 0.0)
    )
    res_stock.update(sr_info)

    cp_info = calc_chartprime_sr_high_volume_boxes(history)
    res_stock.update(cp_info)

    trend_info = compute_trend_classification(res_stock)
    res_stock["trend"] = trend_info["trend"]
    res_stock["trend_badge"] = trend_info["badge"]
    res_stock["trend_class"] = trend_info["class"]
    res_stock["tech_rating"] = trend_info["badge"]

    return res_stock


def compute_nifty_market_regime(nifty_df: pd.DataFrame = None) -> dict:
    """
    Computes NIFTY 50 Market Trend Regime, 20 EMA, 50 DMA, 5-day slope, RSI,
    and returns tactical trading stance guidance for swing traders.
    """
    if nifty_df is None or nifty_df.empty or len(nifty_df) < 5:
        return {
            "status": "NEUTRAL",
            "badge": "🟡 NIFTY 50: Neutral / Selective Stance",
            "badge_class": "badge-yellow",
            "stance": "Selective Stock Picking",
            "guidance": "Trade standard setups with normal risk management.",
            "ltp": None,
            "change_pct": 0.0,
            "ema20": None,
            "ma50": None,
            "rsi": 50.0,
            "ret_5d": 0.0,
            "regime_code": "NEUTRAL"
        }

    close = nifty_df["Close"].dropna()
    ltp = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else ltp
    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)

    # Moving averages
    ema20 = float(close.ewm(span=min(20, len(close)), adjust=False).mean().iloc[-1])
    ma50 = float(close.rolling(window=min(50, len(close))).mean().iloc[-1]) if len(close) >= 10 else ema20

    # 5-day slope
    lookback_5d = min(5, len(close) - 1)
    ret_5d = round(((ltp - float(close.iloc[-lookback_5d - 1])) / float(close.iloc[-lookback_5d - 1])) * 100, 2)

    # 14-day RSI — Wilder's EMA method (matches TradingView / Zerodha)
    rsi = 50.0
    if len(close) >= 15:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta.clip(upper=0))
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        last_gain = float(avg_gain.iloc[-1])
        last_loss = float(avg_loss.iloc[-1])
        if last_loss > 0:
            rsi = round(100.0 - (100.0 / (1.0 + last_gain / last_loss)), 1)
        elif last_gain > 0:
            rsi = 100.0

    is_above_ema20 = ltp >= ema20
    is_above_ma50 = ltp >= ma50

    if is_above_ema20 and is_above_ma50 and ret_5d >= -0.5:
        status = "BULLISH"
        badge = "🟢 NIFTY 50: Bullish Trend (Risk-On)"
        badge_class = "badge-green"
        stance = "Breakout & Momentum Mode"
        guidance = "Broad market is in an uptrend. Breakouts and momentum setups have high continuation probability."
    elif not is_above_ema20 and (not is_above_ma50 or ret_5d <= -1.0 or rsi < 45):
        status = "CORRECTION"
        badge = "🔴 NIFTY 50: Correction / Defensive Mode"
        badge_class = "badge-red"
        stance = "Defensive / RS Leaders Only (RS ≥ 80)"
        guidance = f"Market under pressure ({ret_5d:+.1f}% 5-day drop). Avoid chasing overbought breakouts; prioritize RS leaders (RS ≥ 80) and 50-DMA support pullbacks."
    else:
        status = "CHOPPY"
        badge = "🟡 NIFTY 50: Choppy / Consolidation Mode"
        badge_class = "badge-yellow"
        stance = "Selective Dip Buys & Pullbacks"
        guidance = "Market is consolidating near moving averages. Trade institutional inflow bases and tight support retests."

    return {
        "status": status,
        "badge": badge,
        "badge_class": badge_class,
        "stance": stance,
        "guidance": guidance,
        "ltp": round(ltp, 2),
        "change_pct": change_pct,
        "ema20": round(ema20, 2),
        "ma50": round(ma50, 2),
        "rsi": rsi,
        "ret_5d": ret_5d,
        "regime_code": status
    }


def compute_relative_strength_ratings(screener_results: list[dict], nifty_history: pd.DataFrame = None, nifty_regime_status: str = "NEUTRAL") -> list[dict]:
    """
    Computes Mansfield Relative Strength (RS Rating: 1 to 99) for all stocks against NIFTY 50.
    Weighted: 40% 1-Month Excess Return + 60% 3-Month Excess Return.
    Percentile ranks all stocks across the universe.
    Also stamps each stock dict with nifty_regime_status so compute_swing_setup() can gate signals.
    """
    if not screener_results:
        return screener_results

    nifty_1m_ret = 0.0
    nifty_3m_ret = 0.0
    if nifty_history is not None and not nifty_history.empty and len(nifty_history) >= 5:
        c = nifty_history["Close"].dropna()
        if len(c) >= 2:
            curr_n = float(c.iloc[-1])
            idx_1m = min(len(c) - 1, 21)
            idx_3m = min(len(c) - 1, 63)
            nifty_1m_ret = ((curr_n - float(c.iloc[-idx_1m - 1])) / float(c.iloc[-idx_1m - 1])) * 100.0
            nifty_3m_ret = ((curr_n - float(c.iloc[-idx_3m - 1])) / float(c.iloc[-idx_3m - 1])) * 100.0

    raw_scores = []
    for s in screener_results:
        ret_1m = s.get("ret_1m") if s.get("ret_1m") is not None else (s.get("wk52_return_pct", 0) / 12.0)
        ret_3m = s.get("ret_3m") if s.get("ret_3m") is not None else (s.get("wk52_return_pct", 0) / 4.0)
        excess_1m = ret_1m - nifty_1m_ret
        excess_3m = ret_3m - nifty_3m_ret
        raw_rs = (0.4 * excess_1m) + (0.6 * excess_3m)
        raw_scores.append((raw_rs, s))

    # Rank into 1-99 percentile
    raw_scores.sort(key=lambda x: x[0])
    n = len(raw_scores)
    for rank_idx, (raw_val, s) in enumerate(raw_scores, 1):
        rs_rating = int(round((rank_idx / max(1, n)) * 99))
        rs_rating = max(1, min(99, rs_rating))
        s["rs_rating"] = rs_rating
        # Stamp regime so compute_swing_setup can gate signals correctly
        s["nifty_regime_status"] = nifty_regime_status

        if rs_rating >= 80:
            s["rs_badge"] = f"🔥 RS {rs_rating} (Leader)"
            s["rs_class"] = "badge-green"
            s["is_rs_leader"] = True
        elif rs_rating >= 60:
            s["rs_badge"] = f"🟢 RS {rs_rating} (Outperformer)"
            s["rs_class"] = "badge-green"
            s["is_rs_leader"] = False
        elif rs_rating >= 40:
            s["rs_badge"] = f"⚪ RS {rs_rating} (In Line)"
            s["rs_class"] = "badge-gray"
            s["is_rs_leader"] = False
        else:
            s["rs_badge"] = f"🔴 RS {rs_rating} (Lagging)"
            s["rs_class"] = "badge-red"
            s["is_rs_leader"] = False

        # Re-compute swing setup with accurate RS rating and regime status
        swing_info = compute_swing_setup(s)
        s.update(swing_info)

        # Re-compute S/R Breakout setup with accurate RS rating
        sr_info = detect_sr_breaks_and_retests(
            history=None,
            ltp=s.get("ltp"),
            rs_rating=rs_rating,
            rsi=s.get("rsi"),
            vol_spike=s.get("volume_spike", 1.0),
            cmf=s.get("cmf", 0.0),
            cached_sr=s
        )
        s.update(sr_info)

    return screener_results


def compute_swing_setup(scored: dict, history: pd.DataFrame = None) -> dict:
    """
    Decoupled Swing Trade Engine:
    Separates SETUP QUALITY (is this a high-conviction swing candidate?) 
    from ENTRY QUALITY (is now a low-risk entry point?).

    Returns:
      - setup_score : 0.0 - 100.0 (Structure, Breakout, Momentum, RS)
      - entry_score : 0.0 - 100.0 (EMA20 proximity, Breakout proximity, Extension, R:R)
      - swing_score : 0.0 - 100.0 (Weighted blend: 65% setup + 35% entry)
      - swing_action: Action Label ("BUY NOW" | "BUY ON RETEST" | "EXTENDED — DON'T CHASE" | "WATCH / WAIT" | "REJECT")
      - swing_badge : UI Badge string with status icon
      - swing_class : CSS badge class ("badge-green" | "badge-orange" | "badge-yellow" | "badge-gray")
      - swing_reason: Detailed rationale text
    """
    vol_spike = float(scored.get("volume_spike") or 0.0)
    cmf = float(scored.get("cmf") or 0.0)
    clv = float(scored.get("clv") or 0.5)
    momentum = float(scored.get("momentum") or 0.0)
    rsi = scored.get("rsi")
    ltp = float(scored.get("ltp") or 0.0)
    ma50 = scored.get("ma50")
    ma200 = scored.get("ma200")
    ema20 = scored.get("ema20")
    market_structure = scored.get("market_structure") or "Neutral"
    pa_pattern = scored.get("pa_pattern") or "None"
    rs_rating = float(scored.get("rs_rating") or 50)
    ret_1m = float(scored.get("ret_1m") or 0.0)
    ret_3m = float(scored.get("ret_3m") or 0.0)

    # 1H S/R Breakout & Retest signals
    sr_type = scored.get("sr_type") or "NONE"
    is_break_res = scored.get("is_break_res", False) or (sr_type == "BREAK_RES")
    is_retest_buy = scored.get("is_retest_buy", False) or (sr_type == "RETEST_BUY")
    dist_from_res_pct = scored.get("dist_from_res_pct")

    dist_ma50_pct = round(((ltp - ma50) / ma50) * 100, 1) if (ma50 and ltp and ma50 > 0) else None
    dist_ema20_pct = round(((ltp - ema20) / ema20) * 100, 1) if (ema20 and ltp and ema20 > 0) else None

    # ── 1. SETUP QUALITY SCORE (Max 70 raw points → 0-100 scale) ──────────────
    setup_pts = 0.0

    # A. Breakout & Structure (up to 40 pts)
    if is_break_res:
        setup_pts += 15.0  # +15 for active 1H/Daily resistance breakout
    elif is_retest_buy:
        setup_pts += 12.0  # +12 for retest buy pattern

    if market_structure == "HH / HL Uptrend":
        setup_pts += 10.0
    elif market_structure == "Consolidation Range":
        setup_pts += 5.0

    if ma50 and ltp >= ma50:
        setup_pts += 4.0
    if ma200 and ltp >= ma200:
        setup_pts += 4.0

    # Order flow & Base quality
    if cmf >= 0.15:
        setup_pts += 7.0
    elif cmf >= 0.05:
        setup_pts += 5.0

    if clv >= 0.65:
        setup_pts += 6.0
    elif clv >= 0.50:
        setup_pts += 4.0

    if pa_pattern in ["Bullish FVG", "Bullish Engulfing", "Double Bottom", "Cup & Handle", "VCP Base"]:
        setup_pts += 5.0

    if scored.get("sup_holds") or scored.get("has_buy_diamond"):
        setup_pts += 5.0

    # B. Momentum & Relative Strength Acceleration (up to 30 pts)
    # Short-term return acceleration (1M / 3M returns)
    if ret_1m >= 30.0:
        setup_pts += 10.0
    elif ret_1m >= 15.0:
        setup_pts += 7.0
    elif ret_1m >= 5.0:
        setup_pts += 4.0

    if ret_3m >= 40.0:
        setup_pts += 6.0
    elif ret_3m >= 20.0:
        setup_pts += 4.0
    elif ret_3m >= 10.0:
        setup_pts += 2.0

    # RS Rating points
    if rs_rating >= 85:
        setup_pts += 10.0
    elif rs_rating >= 75:
        setup_pts += 8.0
    elif rs_rating >= 60:
        setup_pts += 5.0
    elif rs_rating >= 45:
        setup_pts += 2.0
    elif rs_rating < 35:
        setup_pts -= 6.0

    # Context-aware RSI scoring
    has_breakout_context = is_break_res or is_retest_buy or ret_1m >= 20.0
    if rsi is not None:
        if 52 <= rsi <= 68:
            setup_pts += 10.0
        elif 42 <= rsi < 52:
            setup_pts += 8.0
        elif 38 <= rsi < 42:
            setup_pts += 5.0
        elif 68 < rsi <= 76:
            if has_breakout_context:
                setup_pts += 8.0  # Strong breakout velocity zone (not penalized!)
            else:
                setup_pts += 3.0  # Late momentum without structural breakout
        elif rsi > 78:
            setup_pts -= 6.0
        else:
            setup_pts -= 4.0

    # Volume confirmation
    if vol_spike >= 2.0:
        setup_pts += 8.0
    elif vol_spike >= 1.3:
        setup_pts += 5.0
    elif vol_spike >= 0.9:
        setup_pts += 2.0

    # Normalize Setup Quality Score (0 to 100)
    setup_score = round(min(100.0, max(0.0, (setup_pts / 60.0) * 100.0)), 1)


    # ── 2. ENTRY QUALITY SCORE (Max 100 raw points → 0-100 scale) ──────────────
    entry_pts = 0.0

    # A. EMA20 Proximity (up to 25 pts)
    if dist_ema20_pct is not None:
        if 0.0 <= dist_ema20_pct <= 3.5:
            entry_pts += 25.0  # Prime low-risk entry near EMA20
        elif 3.5 < dist_ema20_pct <= 7.0:
            entry_pts += 18.0
        elif 7.0 < dist_ema20_pct <= 12.0:
            entry_pts += 10.0
        elif dist_ema20_pct > 12.0:
            entry_pts += 3.0
    else:
        entry_pts += 15.0

    # B. Breakout Level / Support Proximity (up to 25 pts)
    if dist_from_res_pct is not None:
        if -2.0 <= dist_from_res_pct <= 2.5:
            entry_pts += 25.0  # Fresh breakout or retest zone
        elif 2.5 < dist_from_res_pct <= 6.0:
            entry_pts += 18.0
        elif 6.0 < dist_from_res_pct <= 12.0:
            entry_pts += 10.0
        else:
            entry_pts += 4.0
    elif is_retest_buy:
        entry_pts += 25.0
    else:
        entry_pts += 15.0

    # C. Graduated 50-DMA Extension (up to 25 pts)
    if dist_ma50_pct is not None:
        if dist_ma50_pct <= 8.0:
            entry_pts += 25.0
        elif 8.0 < dist_ma50_pct <= 15.0:
            entry_pts += 20.0
        elif 15.0 < dist_ma50_pct <= 22.0:
            entry_pts += 14.0
        elif 22.0 < dist_ma50_pct <= 30.0:
            entry_pts += 8.0   # Graduated (e.g. +24.2% gets 8 pts, not flat rejection!)
        else:
            entry_pts += 2.0
    else:
        entry_pts += 15.0

    # D. Stop-Loss & Risk-Reward Ratio (up to 25 pts)
    if ltp > 0:
        if ma50 and (ltp * 0.94 <= ma50 <= ltp * 0.99):
            sl = round(ma50 * 0.985, 2)
        else:
            sl = round(ltp * 0.965, 2)
            
        risk = round(ltp - sl, 2)
        if risk <= 0 or (risk / ltp) < 0.02:
            risk = round(ltp * 0.035, 2)
            sl = round(ltp - risk, 2)
        elif (risk / ltp) > 0.07:
            risk = round(ltp * 0.05, 2)
            sl = round(ltp - risk, 2)

        target1 = round(ltp + (1.5 * risk), 2)
        target2 = round(ltp + (2.5 * risk), 2)
        sl_pct = round(((sl - ltp) / ltp) * 100, 1)
        t1_pct = round(((target1 - ltp) / ltp) * 100, 1)
        t2_pct = round(((target2 - ltp) / ltp) * 100, 1)
        
        # SL distance score
        abs_sl_pct = abs(sl_pct)
        if abs_sl_pct <= 4.5:
            entry_pts += 13.0
        elif abs_sl_pct <= 6.5:
            entry_pts += 8.0
        else:
            entry_pts += 4.0

        # R:R ratio score
        rr_ratio = round((target1 - ltp) / max(0.1, (ltp - sl)), 2)
        if rr_ratio >= 2.0:
            entry_pts += 12.0
        elif rr_ratio >= 1.5:
            entry_pts += 8.0
        else:
            entry_pts += 4.0
    else:
        sl = target1 = target2 = None
        sl_pct = t1_pct = t2_pct = 0.0
        entry_pts += 10.0

    entry_score = round(min(100.0, max(0.0, entry_pts)), 1)


    # ── 3. COMBINED SWING SCORE & MARKET REGIME GATE ──────────────────────────
    combined_score = (setup_score * 0.65) + (entry_score * 0.35)

    nifty_regime = scored.get("nifty_regime_status", "NEUTRAL")
    if nifty_regime == "CORRECTION":
        if setup_score < 80:
            combined_score = max(0.0, combined_score - 15.0)
    elif nifty_regime == "CHOPPY":
        combined_score = max(0.0, combined_score - 5.0)

    if ltp > 0 and ltp < 50.0:
        combined_score = max(0.0, combined_score - 25.0)

    swing_score = round(min(100.0, max(0.0, combined_score)), 1)


    # ── 4. ACTION LABEL & BADGE ASSIGNMENT ─────────────────────────────────────
    if nifty_regime == "CORRECTION" and setup_score < 60:
        swing_action = "AVOID — MARKET CORRECTION"
        swing_badge = "⛔ AVOID — MARKET CORRECTION"
        swing_class = "badge-red"
        swing_reason = "Market in correction regime — hold cash until trend stabilizes"
    elif setup_score >= 70:
        if entry_score >= 70:
            swing_action = "BUY NOW"
            swing_badge = "🟢 BUY NOW"
            swing_class = "badge-green"
            swing_reason = f"High conviction setup ({setup_score:.0f}/100) with ideal entry timing ({entry_score:.0f}/100)"
        elif entry_score >= 45:
            swing_action = "BUY ON RETEST"
            swing_badge = "🟢 BUY ON RETEST"
            swing_class = "badge-green"
            swing_reason = f"Strong setup ({setup_score:.0f}/100) — enter near retest/EMA20 support ({entry_score:.0f}/100 entry)"
        else:
            swing_action = "EXTENDED — DON'T CHASE"
            swing_badge = "🟠 EXTENDED — DON'T CHASE"
            swing_class = "badge-orange"
            swing_reason = f"Strong setup ({setup_score:.0f}/100) but price is extended ({entry_score:.0f}/100 entry) — wait for dip/retest"
    elif setup_score >= 50:
        swing_action = "WATCH / WAIT"
        swing_badge = "🟡 WATCH / WAIT"
        swing_class = "badge-yellow"
        swing_reason = f"Developing setup ({setup_score:.0f}/100) — monitor for breakout confirmation"
    else:
        swing_action = "REJECT"
        swing_badge = "⚪ NEUTRAL SETUP"
        swing_class = "badge-gray"
        swing_reason = f"Weak structure/momentum ({setup_score:.0f}/100 setup)"

    is_blast = (vol_spike >= 2.0 and momentum >= 60 and setup_score >= 75)
    is_order_flow_bull = (cmf >= 0.08 and clv >= 0.55 and setup_score >= 65)
    is_momentum_surge = (momentum >= 75 and setup_score >= 70)
    is_pullback = (rsi is not None and 38 <= rsi <= 57 and entry_score >= 70 and setup_score >= 65)

    return {
        "setup_score": setup_score,
        "entry_score": entry_score,
        "swing_score": swing_score,
        "swing_action": swing_action,
        "swing_badge": swing_badge,
        "swing_class": swing_class,
        "swing_reason": swing_reason,
        "is_blast": is_blast,
        "is_order_flow_bull": is_order_flow_bull,
        "is_momentum_surge": is_momentum_surge,
        "is_pullback": is_pullback,
        "swing_sl": sl,
        "swing_sl_pct": sl_pct,
        "swing_t1": target1,
        "swing_t1_pct": t1_pct,
        "swing_t2": target2,
        "swing_t2_pct": t2_pct,
        "risk_reward": "1 : 1.5 / 1 : 2.5"
    }


def calc_chartprime_sr_high_volume_boxes(df: pd.DataFrame, lookback: int = 20, box_width_mult: float = 1.0) -> dict:
    """
    Exact Python Port of ChartPrime 'Support and Resistance (High Volume Boxes)' Pine Script v5.
    Calculates Delta Volume, High-Volume Support & Resistance Boxes, ATR box width,
    'sup_holds' (Support Bounce Reversal ◆), and 'brekout_res' (Resistance Polarity Bounce ◆).
    """
    if df is None or df.empty or len(df) < 20:
        return {"support_level": None, "resistance_level": None, "sup_holds": False, "brekout_res": False, "has_buy_diamond": False}

    try:
        df = df.copy()
        df = df.rename(columns={c: str(c).capitalize() for c in df.columns})
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Close", "High", "Low"])
        
        if len(df) < 20:
            return {"support_level": None, "resistance_level": None, "sup_holds": False, "brekout_res": False, "has_buy_diamond": False}

        closes = df["Close"].values
        highs = df["High"].values
        lows = df["Low"].values
        opens = df["Open"].values if "Open" in df.columns else closes
        volumes = df["Volume"].values if "Volume" in df.columns else np.ones(len(closes))

        n = len(closes)

        # 1. Delta Volume calculation (posVol vs negVol)
        delta_vol = np.zeros(n)
        is_buy_vol = True
        for i in range(n):
            if closes[i] > opens[i]:
                is_buy_vol = True
            elif closes[i] < opens[i]:
                is_buy_vol = False
            delta_vol[i] = volumes[i] if is_buy_vol else -volumes[i]

        vol_len = 2
        vol_hi = np.array([np.max(delta_vol[max(0, i-vol_len+1):i+1] / 2.5) for i in range(n)])
        vol_lo = np.array([np.min(delta_vol[max(0, i-vol_len+1):i+1] / 2.5) for i in range(n)])

        # 2. ATR Box Width calculation
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        
        atr_window = min(200, n)
        atr = pd.Series(tr).rolling(window=atr_window, min_periods=5).mean().values
        width = atr * box_width_mult

        # 3. Pivot High & Low detection
        pivot_highs = {}
        pivot_lows = {}
        lb = min(15, (n - 1) // 2) if n < 45 else 20

        for i in range(lb, n - lb):
            if closes[i] == max(closes[i-lb : i+lb+1]):
                pivot_highs[i] = closes[i]
            if closes[i] == min(closes[i-lb : i+lb+1]):
                pivot_lows[i] = closes[i]

        support_level = None
        support_level_1 = None
        resistance_level = None
        resistance_level_1 = None

        for i in range(lb, n):
            if i in pivot_lows and delta_vol[i] > vol_hi[i]:
                support_level = pivot_lows[i]
                support_level_1 = support_level - width[i]

            if i in pivot_highs and delta_vol[i] < vol_lo[i]:
                resistance_level = pivot_highs[i]
                resistance_level_1 = resistance_level + width[i]

        if support_level is None:
            support_level = float(np.min(lows[-20:]))
            support_level_1 = support_level - width[-1]
        if resistance_level is None:
            resistance_level = float(np.max(highs[-20:]))
            resistance_level_1 = resistance_level + width[-1]

        # 4. Support Bounce (sup_holds) & Resistance Flip Bounce (brekout_res)
        curr_low = lows[-1]
        prev_low = lows[-2] if n > 1 else curr_low

        is_green_reversal = (closes[-1] >= opens[-1] or closes[-1] >= closes[-2])
        in_sup_box = (curr_low <= support_level * 1.015 and curr_low >= support_level * 0.975)
        sup_holds = bool(in_sup_box and is_green_reversal)
        
        brekout_res = bool(closes[-1] > resistance_level and prev_low <= resistance_level * 1.015 and is_green_reversal)
        has_buy_diamond = bool(sup_holds or brekout_res)

        return {
            "support_level": round(float(support_level), 2),
            "support_level_1": round(float(support_level_1), 2),
            "resistance_level": round(float(resistance_level), 2),
            "resistance_level_1": round(float(resistance_level_1), 2),
            "sup_holds": sup_holds,
            "brekout_res": brekout_res,
            "has_buy_diamond": has_buy_diamond,
            "badge": "🟢 A/E Support Reversal ◆" if has_buy_diamond else "⚪ Awaiting Support Reversal"
        }
    except Exception as e:
        return {"support_level": None, "resistance_level": None, "sup_holds": False, "brekout_res": False, "has_buy_diamond": False}


def detect_sr_breaks_and_retests(
    history: pd.DataFrame = None,
    ltp: float = None,
    rs_rating: float = 50,
    rsi: float = None,
    vol_spike: float = 1.0,
    cmf: float = 0.0,
    cached_sr: dict = None,
    df_1h: pd.DataFrame = None
) -> dict:
    """
    S&R Breakout Detector — runs on 1-HOUR candles (df_1h) when available.
    Falls back to daily candles (history) only if no 1h data is provided.

    1H mode (preferred, designed for your backtested strategy):
      - Pivot window : 8 bars left/right on 1h highs/lows
      - Resistance   : most-tested pivot cluster within 0.5% (not single-bar spike)
      - Breakout     : close > res_zone AND volume >= 1.3x avg AND bullish body >= 50% range
      - Freshness    : <= 4 hours (4 bars) for BREAK_RES
      - Retest       : price returns to +-0.8% of broken resistance within 20 bars
      - SL           : low of breakout candle (not a % floor)
      - T1 / T2      : 1.5x / 2.5x risk (realistic intraday/next-day targets)

    Daily fallback: freshness = 1 day, pivot window = 5 bars, same cluster logic.
    """
    default_res = {
        "has_sr_setup": False,
        "sr_type": "NONE",
        "sr_badge": "\u26aa No S/R Setup",
        "sr_badge_class": "badge-gray",
        "res_level": None,
        "sup_level": None,
        "dist_from_res_pct": None,
        "sr_sl": None,
        "sr_sl_pct": None,
        "sr_t1": None,
        "sr_t1_pct": None,
        "sr_t2": None,
        "sr_t2_pct": None,
        "sr_score": 0.0,
        "sr_reason": "No clear resistance breakout or retest pattern",
        "breakout_bars_ago": None,
        "is_break_res": False,
        "is_retest_buy": False,
        "is_approaching_breakout": False,
        "sr_timeframe": "N/A"
    }

    # ── RS/Score update pass (when called from compute_relative_strength_ratings) ──
    # Only score is updated; geometry stays from the initial 1h detection pass.
    if df_1h is None and history is None and cached_sr is not None and cached_sr.get("res_level"):
        sr_type = cached_sr.get("sr_type", "NONE")
        if sr_type == "NONE":
            return default_res
        base_score = 50.0 if sr_type == "BREAK_RES" else 55.0 if sr_type == "RETEST_BUY" else 35.0
        if rs_rating >= 80:   base_score += 22.0
        elif rs_rating >= 60: base_score += 14.0
        elif rs_rating < 40:  base_score -= 12.0
        if vol_spike >= 2.0:   base_score += 15.0
        elif vol_spike >= 1.3: base_score += 10.0
        if rsi is not None:
            if 52 <= rsi <= 68:  base_score += 12.0
            elif rsi > 76:       base_score -= 15.0
        if cmf >= 0.10: base_score += 10.0
        res_dict = dict(cached_sr)
        res_dict["sr_score"] = round(max(10.0, min(100.0, base_score)), 1)
        return res_dict

    # ── Choose data source: 1h preferred, daily fallback ──────────────────────
    use_1h = (df_1h is not None and not df_1h.empty and len(df_1h) >= 30)

    if use_1h:
        df_raw = df_1h.copy()
        pivot_w = 8         # 8-bar left/right for 1h pivots
        freshness_bars = 4  # fresh breakout = within 4 hours
        retest_window = 20  # retest must occur within 20 hours
        lookback_bars = 120 # scan last 120h (~3 weeks) for resistance cluster
        timeframe_label = "1H"
    elif history is not None and not history.empty and len(history) >= 20:
        df_raw = history.copy()
        pivot_w = 5
        freshness_bars = 1
        retest_window = 10
        lookback_bars = 40
        timeframe_label = "Daily"
    else:
        return default_res

    # Normalise column names
    df_raw = df_raw.rename(columns={c: str(c).capitalize() for c in df_raw.columns})
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df_raw.columns:
            df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce")
    df_raw = df_raw.dropna(subset=["Close", "High", "Low"])
    if len(df_raw) < 20:
        return default_res

    closes = df_raw["Close"].values.astype(float)
    highs  = df_raw["High"].values.astype(float)
    lows   = df_raw["Low"].values.astype(float)
    opens  = df_raw["Open"].values.astype(float) if "Open" in df_raw.columns else closes.copy()
    volumes = df_raw["Volume"].values.astype(float) if "Volume" in df_raw.columns else np.ones(len(closes))

    curr_ltp = float(ltp) if (ltp is not None and ltp > 0) else float(closes[-1])
    n = len(closes)
    lb = min(lookback_bars, n - pivot_w - 1)

    # Average volume for breakout confirmation (20-bar rolling)
    vol_avg_arr = pd.Series(volumes).rolling(window=min(20, len(volumes)), min_periods=5).mean().values
    curr_vol_avg = float(vol_avg_arr[-1]) if vol_avg_arr[-1] > 0 else 1.0

    # ── 1. Pivot High/Low detection ────────────────────────────────────────────
    pivot_highs = []  # (bar_index, price)
    pivot_lows  = []
    for i in range(pivot_w, n - pivot_w):
        if highs[i] == max(highs[i - pivot_w: i + pivot_w + 1]):
            pivot_highs.append((i, float(highs[i])))
        if lows[i] == min(lows[i - pivot_w: i + pivot_w + 1]):
            pivot_lows.append((i, float(lows[i])))

    # Fallback: use recent high/low if no pivots found
    if not pivot_highs:
        pivot_highs.append((n - pivot_w - 2, float(np.max(highs[max(0, n-lb-pivot_w):-pivot_w]))))
    if not pivot_lows:
        pivot_lows.append((n - pivot_w - 2, float(np.min(lows[max(0, n-lb-pivot_w):]))))

    # ── 2. Clustered Resistance Level ─────────────────────────────────────────
    # Use pivot highs within lookback. Cluster those within 0.5% of each other.
    # Most-tested cluster wins (not simple max — avoids spike contamination).
    recent_ph = [p for p in pivot_highs if p[0] >= max(0, n - lb - pivot_w) and p[0] <= n - pivot_w - 1]
    if not recent_ph:
        recent_ph = pivot_highs[-min(5, len(pivot_highs)):]

    # Build clusters
    recent_ph_sorted = sorted(recent_ph, key=lambda x: x[1])
    clusters = []
    for idx, price in recent_ph_sorted:
        placed = False
        for cl in clusters:
            ref = cl["prices"][0]
            if abs(price - ref) / ref <= 0.005:  # within 0.5%
                cl["prices"].append(price)
                cl["indices"].append(idx)
                placed = True
                break
        if not placed:
            clusters.append({"prices": [price], "indices": [idx]})

    # Pick the best cluster: most tests first, then highest price (stronger resistance)
    best_cluster = max(clusters, key=lambda c: (len(c["prices"]), np.mean(c["prices"])))
    res_level = round(float(np.mean(best_cluster["prices"])), 2)
    res_test_count = len(best_cluster["prices"])

    # Support level: most recent significant pivot low in lookback
    recent_pl = [p for p in pivot_lows if p[0] >= max(0, n - lb) and p[0] <= n - 1]
    if recent_pl:
        sup_level = round(float(recent_pl[-1][1]), 2)
    else:
        sup_level = round(float(np.min(lows[-min(20, n):])), 2)

    dist_from_res_pct = round(((curr_ltp - res_level) / res_level) * 100, 2)

    # ── 3. Breakout Detection ──────────────────────────────────────────────────
    is_break_res = False
    is_retest_buy = False
    is_approaching = False
    breakout_bars_ago = None
    breakout_idx = None
    breakout_candle_low = None
    sr_type = "NONE"
    sr_reason = ""
    base_score = 0.0

    for b in range(1, min(freshness_bars + 5, n)):
        idx = n - b
        bar_close = closes[idx]
        prev_close = closes[idx - 1] if idx > 0 else bar_close
        bar_open  = opens[idx]
        bar_low   = lows[idx]
        bar_high  = highs[idx]

        if bar_close >= res_level and prev_close <= res_level * 1.01:
            # ── Volume confirmation: breakout bar must have meaningful volume ──
            bar_vol = volumes[idx]
            avg_vol_at_bar = float(vol_avg_arr[max(0, idx - 1)])
            vol_ok = (avg_vol_at_bar <= 0) or (bar_vol >= avg_vol_at_bar * 1.3)

            # ── Body confirmation: bullish candle body >= 50% of candle range ──
            candle_range = bar_high - bar_low
            body = bar_close - bar_open
            body_ok = (candle_range <= 0) or (body >= 0 and body >= 0.5 * candle_range)

            if vol_ok and body_ok:
                breakout_idx = idx
                breakout_bars_ago = b - 1
                breakout_candle_low = bar_low
                break

    # Trigger A: FRESH BREAKOUT (1h: within 4 bars | daily: within 1 bar)
    if (breakout_idx is not None and breakout_bars_ago <= freshness_bars
            and -0.5 <= dist_from_res_pct <= 6.0):
        is_break_res = True
        sr_type = "BREAK_RES"
        tf_label = "1H" if use_1h else "Daily"
        sr_badge = f"\ud83d\udd25 Break Res [{tf_label}]"
        sr_badge_class = "badge-green"
        tested_str = f", tested {res_test_count}x" if res_test_count >= 2 else ""
        sr_reason = (f"{'1H' if use_1h else 'Daily'} candle close above "
                     f"\u20b9{res_level:.2f} resistance{tested_str} "
                     f"({dist_from_res_pct:+.1f}%) with volume & body confirmation")
        base_score = 55.0 if res_test_count >= 2 else 45.0  # bonus for multi-tested level

    # Trigger B: RETEST BUY — requires a prior confirmed breakout, then price returning
    # to +-0.8% of the broken resistance level (now acting as support)
    elif (breakout_idx is not None
          and freshness_bars < breakout_bars_ago <= retest_window
          and -0.8 <= dist_from_res_pct <= 3.0
          and (closes[-1] >= opens[-1] or closes[-1] >= closes[-2])):   # must be a green candle
        is_retest_buy = True
        sr_type = "RETEST_BUY"
        tf_label = "1H" if use_1h else "Daily"
        sr_badge = f"\ud83d\udd04 Retest Buy [{tf_label}]"
        sr_badge_class = "badge-purple"
        sr_reason = (f"{'1H' if use_1h else 'Daily'} retest: former \u20b9{res_level:.2f} "
                     f"resistance now confirmed as support ({breakout_bars_ago} bars ago)")
        base_score = 58.0

    # Trigger C: APPROACHING RESISTANCE (Coiling)
    elif -2.5 <= dist_from_res_pct <= -0.1 and (rsi is None or 45 <= rsi <= 70):
        is_approaching = True
        sr_type = "APPROACHING_RES"
        tf_label = "1H" if use_1h else "Daily"
        sr_badge = f"\u26a1 Approaching [{tf_label}]"
        sr_badge_class = "badge-yellow"
        tested_str = f" (tested {res_test_count}x)" if res_test_count >= 2 else ""
        sr_reason = (f"Coiling at \u20b9{res_level:.2f}{tested_str} resistance "
                     f"({dist_from_res_pct:.1f}% below) — breakout imminent")
        base_score = 35.0

    if sr_type == "NONE":
        return {**default_res, "sr_timeframe": timeframe_label}

    # ── 4. Confluence Scoring ──────────────────────────────────────────────────
    if rs_rating >= 80:   base_score += 22.0
    elif rs_rating >= 60: base_score += 14.0
    elif rs_rating < 40:  base_score -= 12.0

    if vol_spike >= 2.0:   base_score += 15.0
    elif vol_spike >= 1.3: base_score += 10.0

    if rsi is not None:
        if 52 <= rsi <= 68:  base_score += 12.0
        elif 45 <= rsi < 52: base_score += 8.0
        elif rsi > 76:       base_score -= 15.0

    if cmf >= 0.10: base_score += 10.0
    elif cmf >= 0.03: base_score += 6.0

    # Bonus: multi-tested resistance is a stronger signal
    if res_test_count >= 3:  base_score += 8.0
    elif res_test_count >= 2: base_score += 4.0

    sr_score = round(max(10.0, min(100.0, base_score)), 1)

    # ── 5. Stop-Loss & Targets ────────────────────────────────────────────────
    # SL = low of breakout candle (when available) — not an arbitrary % floor
    if breakout_candle_low is not None and breakout_candle_low > 0:
        sr_sl = round(breakout_candle_low * 0.998, 2)  # 0.2% below candle low
    elif sup_level and sup_level < curr_ltp and sup_level >= curr_ltp * 0.90:
        sr_sl = round(sup_level * 0.985, 2)
    else:
        sr_sl = round(curr_ltp * 0.965, 2)

    risk_amt = round(curr_ltp - sr_sl, 2)
    if risk_amt <= 0 or (risk_amt / curr_ltp) < 0.015:
        risk_amt = round(curr_ltp * 0.025, 2)
        sr_sl = round(curr_ltp - risk_amt, 2)
    elif (risk_amt / curr_ltp) > 0.08:
        risk_amt = round(curr_ltp * 0.05, 2)
        sr_sl = round(curr_ltp - risk_amt, 2)

    sr_t1 = round(curr_ltp + (1.5 * risk_amt), 2)   # Realistic target (was 2.0x)
    sr_t2 = round(curr_ltp + (2.5 * risk_amt), 2)   # Runner target  (was 3.0x)

    sr_sl_pct = round(((sr_sl - curr_ltp) / curr_ltp) * 100, 1)
    sr_t1_pct = round(((sr_t1 - curr_ltp) / curr_ltp) * 100, 1)
    sr_t2_pct = round(((sr_t2 - curr_ltp) / curr_ltp) * 100, 1)

    return {
        "has_sr_setup": True,
        "sr_type": sr_type,
        "sr_badge": sr_badge,
        "sr_badge_class": sr_badge_class,
        "res_level": res_level,
        "res_test_count": res_test_count,
        "sup_level": sup_level,
        "dist_from_res_pct": dist_from_res_pct,
        "sr_sl": sr_sl,
        "sr_sl_pct": sr_sl_pct,
        "sr_t1": sr_t1,
        "sr_t1_pct": sr_t1_pct,
        "sr_t2": sr_t2,
        "sr_t2_pct": sr_t2_pct,
        "sr_score": sr_score,
        "sr_reason": sr_reason,
        "breakout_bars_ago": breakout_bars_ago,
        "is_break_res": is_break_res,
        "is_retest_buy": is_retest_buy,
        "is_approaching_breakout": is_approaching,
        "sr_timeframe": timeframe_label
    }






def check_quality_alerts(current: dict, entry: dict) -> list:
    """
    Compares current scores/metrics vs entry scores/metrics.
    Returns a list of alert dicts if quality has deteriorated.
    Used for watchlist stocks.
    """
    alerts = []

    # Score-based alerts
    curr_total = current.get("total_score", 0)
    entry_total = entry.get("score_at_entry")

    if curr_total < 40:
        alerts.append({
            "level": "SELL",
            "icon": "🔴",
            "message": f"Quality Gone — Total score {curr_total} (below 40 threshold)"
        })
    elif entry_total and (entry_total - curr_total) >= 10:
        alerts.append({
            "level": "REVIEW",
            "icon": "🟠",
            "message": f"Weakening — Score dropped {round(entry_total - curr_total, 1)} pts since entry ({entry_total} → {curr_total})"
        })

    # Fundamental alerts
    roe = current.get("roe_pct")
    entry_roe = entry.get("roe_at_entry")
    if roe is not None and roe < 10:
        alerts.append({
            "level": "ALERT",
            "icon": "⚠️",
            "message": f"ROE Collapsed — Now {roe}% (was {entry_roe}% at entry, threshold: 10%)"
        })

    npm = current.get("npm_pct")
    if npm is not None and npm < 0:
        alerts.append({
            "level": "ALERT",
            "icon": "⚠️",
            "message": f"Profit Turned Negative — Net margin: {npm}%"
        })

    de = current.get("de_ratio")
    entry_de = entry.get("de_at_entry")
    if de is not None and de > 2.0:
        alerts.append({
            "level": "ALERT",
            "icon": "⚠️",
            "message": f"Debt Spiked — D/E ratio now {de} (was {entry_de} at entry, threshold: 2.0)"
        })

    rev_growth = current.get("rev_growth_pct")
    if rev_growth is not None and rev_growth < 0:
        alerts.append({
            "level": "ALERT",
            "icon": "⚠️",
            "message": f"Revenue Shrinking — Growth: {rev_growth}% YoY"
        })

    ma200 = current.get("ma200")
    ltp = current.get("ltp", 0)
    if ma200 and ltp and ltp < ma200:
        alerts.append({
            "level": "ALERT",
            "icon": "⚠️",
            "message": f"Trend Broken — Price ₹{ltp} fell below 200-day MA ₹{ma200}"
        })

    return alerts


def compute_signal(current: dict, entry: dict = None) -> dict:
    """
    Computes an objective BUY / HOLD / SELL signal for a stock.
    Returns dict: {"signal": "BUY"|"HOLD"|"SELL", "badge": "🟢 BUY"|"🟡 HOLD"|"🔴 SELL", "reason": str}
    """
    if entry is None:
        entry = {}

    curr_total = current.get("total_score", 0)
    curr_strength = current.get("strength", 0)
    entry_total = entry.get("score_at_entry")

    roe = current.get("roe_pct")
    npm = current.get("npm_pct")
    de = current.get("de_ratio")
    ma200 = current.get("ma200")
    ltp = current.get("ltp", 0)

    alerts = check_quality_alerts(current, entry)
    has_sell_alert = any(a.get("level") == "SELL" for a in alerts)

    # 🔴 SELL Conditions
    if curr_total < 40 or has_sell_alert:
        reason = f"Quality score collapsed to {curr_total} (<40)" if curr_total < 40 else "Critical quality alert triggered"
        return {"signal": "SELL", "badge": "🔴 SELL", "reason": reason}

    if entry_total and (entry_total - curr_total) >= 10:
        return {"signal": "SELL", "badge": "🔴 SELL", "reason": f"Score dropped {round(entry_total - curr_total, 1)} pts since entry"}

    if npm is not None and npm < 0:
        return {"signal": "SELL", "badge": "🔴 SELL", "reason": "Net profit margin turned negative"}

    if de is not None and de > 2.0:
        return {"signal": "SELL", "badge": "🔴 SELL", "reason": f"High debt ratio (D/E {de})"}

    if ma200 and ltp and ltp < ma200 and curr_total < 50:
        return {"signal": "SELL", "badge": "🔴 SELL", "reason": f"Price below 200-day MA (₹{ma200}) & score <50"}

    # 🟢 BUY Conditions
    if curr_total >= 55 and curr_strength >= 50:
        if (ma200 is None or ltp >= ma200) and (roe is None or roe >= 10):
            return {"signal": "BUY", "badge": "🟢 BUY", "reason": f"Strong quality score ({curr_total}) & solid fundamentals"}

    # 🟡 HOLD Conditions
    reason = "Moderate quality score; maintain position" if curr_total >= 45 else "Consolidating price & fundamentals"
    return {"signal": "HOLD", "badge": "🟡 HOLD", "reason": reason}


def check_top_pick_status(scored: dict) -> dict:
    """
    Evaluates whether a Stock of the Day pick is ACTIVE, INVALIDATED, or INACTIVE.
    If the stock recovers its qualification score (score >= 55 & strength >= 50),
    it automatically transitions back to ACTIVE.
    """
    total = scored.get("total_score", 0)
    strength = scored.get("strength", 0)
    qualified = scored.get("qualified", False)
    alerts = check_quality_alerts(scored, {})
    has_sell = any(a.get("level") == "SELL" for a in alerts)

    if qualified or (total >= 55 and strength >= 50 and not has_sell):
        return {
            "status": "ACTIVE",
            "badge": "🟢 ACTIVE",
            "reason": f"Qualified — Score {total:.1f}/100, Strength {strength:.1f}/100"
        }
    elif total >= 45:
        return {
            "status": "INVALIDATED",
            "badge": "⚠️ INVALIDATED",
            "reason": f"Score dropped to {total:.1f} (below 55 qualification threshold)"
        }
    else:
        return {
            "status": "INACTIVE",
            "badge": "🔴 INACTIVE",
            "reason": f"Deteriorated — Score fell to {total:.1f} (<45 Phase 1 gate)"
        }


def compute_trend_classification(scored: dict) -> dict:
    """
    Evaluates 5-stage market trend:
    - 🟢 Strong Uptrend
    - 🔵 Accumulation Phase
    - 🟡 Consolidation Phase
    - 🟠 Distribution Phase
    - 🔴 Downtrend
    """
    ltp = scored.get("ltp", 0)
    ema20 = scored.get("ema20")
    ma50 = scored.get("ma50")
    ma200 = scored.get("ma200")
    rsi = scored.get("rsi")
    vol_spike = scored.get("volume_spike", 1.0)
    wk52_h = scored.get("week_high_52")

    if ltp <= 0:
        return {"trend": "Consolidation", "badge": "🟡 Consolidation Phase", "class": "badge-yellow"}

    above_20 = (ema20 is not None and ltp >= ema20)
    above_50 = (ma50 is not None and ltp >= ma50)
    above_200 = (ma200 is not None and ltp >= ma200) if ma200 else (above_20 or above_50)
    dist_52h_pct = ((ltp - wk52_h) / wk52_h * 100) if (wk52_h and wk52_h > 0) else -100

    # 🔴 Downtrend: Price below 20-EMA, 50-MA, and 200-MA
    if not above_20 and not above_50 and (ma200 is None or not above_200):
        return {"trend": "Downtrend", "badge": "🔴 Downtrend", "class": "badge-red"}

    # 🟠 Distribution Phase: Near 52W High (within 10%) or above 50MA, but volume spike >= 1.2x & weakening RSI (<48)
    if (dist_52h_pct >= -10 or above_50) and vol_spike >= 1.2 and (rsi is not None and rsi < 48):
        return {"trend": "Distribution", "badge": "🟠 Distribution Phase", "class": "badge-yellow"}

    # 🔵 Accumulation Phase: Price above 200MA or 20-EMA, volume spike >= 1.2x, healthy RSI (45-58)
    if (above_200 or above_20) and vol_spike >= 1.2 and (rsi is not None and 45 <= rsi <= 58):
        return {"trend": "Accumulation", "badge": "🔵 Accumulation Phase", "class": "badge-purple"}

    # 🟢 Strong Uptrend: Price > 20-EMA and Price > 50-MA (or 200-MA) with healthy RSI (>=50)
    if above_20 and (ma50 is None or above_50) and (rsi is None or rsi >= 48):
        return {"trend": "Uptrend", "badge": "🟢 Strong Uptrend", "class": "badge-green"}

    if above_20:
        return {"trend": "Uptrend", "badge": "🟢 Strong Uptrend", "class": "badge-green"}

    # 🟡 Consolidation Phase: Price consolidating near moving averages
    return {"trend": "Consolidation", "badge": "🟡 Consolidation Phase", "class": "badge-yellow"}


def get_lt_watchlist_status(
    trend: str,
    rsi: float,
    ltp: float,
    gtt_level: float = None,
    day_chg: float = 0.0,
    is_reversal_up: bool = True,
    holding: dict = None,
    scored: dict = None
) -> dict:
    """
    Decoupled LT Watchlist Engine:
    Separates Business Quality (fundamental conviction) from Entry Timing (GTT / MA support proximity).
    """
    scored = scored or {}
    UPTREND_STATES = ("Uptrend", "Accumulation", "Strong Uptrend")
    COOLING_OFF_DAYS = 10

    # If holding active, manage BOUGHT status & cooling off
    if holding and int(holding.get("qty", 0)) > 0:
        qty = int(holding.get("qty", 1))
        avg_price = float(holding.get("avg_price", ltp or 0))
        buy_date = holding.get("buy_date", "")
        pnl = float(holding.get("unrealized_pnl", 0.0))
        pnl_pct = float(holding.get("unrealized_pnl_pct", 0.0))
        pnl_str = f"P&L: ₹{pnl:+.2f} ({pnl_pct:+.1f}%)" if pnl != 0 else ""
        date_str = f" on {buy_date}" if buy_date else ""

        days_held = None
        if buy_date:
            try:
                from datetime import datetime
                bdate = datetime.strptime(str(buy_date)[:10], "%Y-%m-%d").date()
                days_held = (datetime.now().date() - bdate).days
            except Exception:
                days_held = None

        is_cooling_off = (days_held is not None and days_held < COOLING_OFF_DAYS)
        if is_cooling_off:
            day_num = max(1, days_held + 1)
            return {
                "status": "BOUGHT",
                "badge": f"🟢 BOUGHT (Cooling Off: Day {day_num}/{COOLING_OFF_DAYS})",
                "badge_class": "badge-green",
                "reason": f"Purchased{date_str}: {qty} share(s) @ ₹{avg_price:.2f} · Cooling Off Active (Day {day_num} of {COOLING_OFF_DAYS}) {pnl_str}".strip()
            }

    # ── 1. LT QUALITY SCORE (0 - 100) ──────────────────────────────────────────
    lt_q_pts = 0.0
    roe = float(scored.get("roe_pct") or 0.0)
    de = float(scored.get("de_ratio") if scored.get("de_ratio") is not None else 1.0)
    npm = float(scored.get("npm_pct") or 0.0)
    rev_growth = float(scored.get("rev_growth_pct") or 0.0)

    if roe >= 20.0: lt_q_pts += 25.0
    elif roe >= 15.0: lt_q_pts += 18.0
    elif roe >= 10.0: lt_q_pts += 10.0

    if de <= 0.15: lt_q_pts += 25.0
    elif de <= 0.50: lt_q_pts += 18.0
    elif de <= 1.0: lt_q_pts += 10.0

    if npm >= 15.0: lt_q_pts += 15.0
    elif npm >= 8.0: lt_q_pts += 10.0
    elif npm > 0: lt_q_pts += 5.0

    if rev_growth >= 15.0: lt_q_pts += 15.0
    elif rev_growth >= 8.0: lt_q_pts += 10.0

    if trend in UPTREND_STATES: lt_q_pts += 20.0
    elif trend == "Consolidation": lt_q_pts += 10.0

    lt_quality_score = round(min(100.0, max(0.0, lt_q_pts)), 1)

    # ── 2. LT ENTRY SCORE (0 - 100) ────────────────────────────────────────────
    lt_e_pts = 0.0
    if gtt_level and gtt_level > 0 and ltp > 0:
        dist_gtt_pct = ((ltp - gtt_level) / gtt_level) * 100.0
        if dist_gtt_pct <= 1.0: lt_e_pts += 35.0
        elif dist_gtt_pct <= 5.0: lt_e_pts += 25.0
        elif dist_gtt_pct <= 10.0: lt_e_pts += 15.0
        else: lt_e_pts += 5.0
    else:
        lt_e_pts += 15.0

    ma50 = float(scored.get("ma50") or 0)
    if ma50 > 0 and ltp > 0:
        dist_ma50 = abs((ltp - ma50) / ma50) * 100.0
        if dist_ma50 <= 5.0: lt_e_pts += 25.0
        elif dist_ma50 <= 12.0: lt_e_pts += 15.0
        else: lt_e_pts += 5.0
    else:
        lt_e_pts += 15.0

    if rsi is not None:
        if 40 <= rsi <= 62: lt_e_pts += 25.0
        elif 62 < rsi <= 72: lt_e_pts += 15.0
        else: lt_e_pts += 5.0

    if is_reversal_up or day_chg >= -0.3: lt_e_pts += 15.0

    lt_entry_score = round(min(100.0, max(0.0, lt_e_pts)), 1)

    # ── 3. ACTION MAPPING ──────────────────────────────────────────────────────
    if holding and int(holding.get("qty", 0)) > 0:
        return {
            "status": "BOUGHT",
            "badge": f"🟢 BOUGHT ({holding.get('qty')})",
            "badge_class": "badge-green",
            "reason": f"Holding active ({holding.get('qty')} sh @ ₹{holding.get('avg_price', 0):.2f}) · Quality: {lt_quality_score:.0f}/100",
            "lt_quality_score": lt_quality_score,
            "lt_entry_score": lt_entry_score
        }

    if lt_quality_score >= 70:
        if lt_entry_score >= 65:
            status = "BUY_NOW"
            badge = "🟢 BUY NOW (ACCUMULATE)"
            badge_class = "badge-green"
            reason = f"High conviction compounder ({lt_quality_score:.0f}/100) in prime accumulation zone ({lt_entry_score:.0f}/100 entry)"
        else:
            status = "ACCUMULATE_ON_DIP"
            badge = "🟢 ACCUMULATE ON DIP"
            badge_class = "badge-green"
            reason = f"Top quality business ({lt_quality_score:.0f}/100) — extended entry ({lt_entry_score:.0f}/100); set GTT near ₹{gtt_level:.2f}" if gtt_level else f"Top quality business ({lt_quality_score:.0f}/100) — set GTT near support"
    elif lt_quality_score >= 45:
        status = "WAIT"
        badge = "🔵 HOLD / MONITOR"
        badge_class = "badge-purple"
        reason = f"Moderate quality ({lt_quality_score:.0f}/100) — monitor for improved valuation/trend"
    else:
        status = "WATCHLIST"
        badge = "⚪ DE-PRIORITIZE"
        badge_class = "badge-gray"
        reason = f"Low fundamental quality score ({lt_quality_score:.0f}/100)"

    return {
        "status": status,
        "badge": badge,
        "badge_class": badge_class,
        "reason": reason,
        "lt_quality_score": lt_quality_score,
        "lt_entry_score": lt_entry_score
    }



def calculate_ema_crossover_15m(df_15m: pd.DataFrame) -> dict:
    """
    Computes 15 EMA vs 20 EMA on 15-minute candles.
    Detects:
      - BUY: 15 EMA crosses above 20 EMA (Fresh Golden Cross)
      - SELL: 15 EMA crosses below 20 EMA (Fresh Death Cross)
      - BULLISH HOLD: 15 EMA > 20 EMA (Upward Trend continuation)
      - BEARISH HOLD: 15 EMA < 20 EMA (Downward Trend continuation)
    """
    if df_15m is None or len(df_15m) < 25 or "Close" not in df_15m.columns:
        return {
            "signal": "NO_DATA",
            "badge": "⚪ NO DATA",
            "badge_cls": "badge-gray",
            "ema15": None,
            "ema20": None,
            "curr_price": None,
            "diff_pct": 0.0,
            "last_time": ""
        }
    
    close = df_15m["Close"].dropna()
    if len(close) < 25:
        return {
            "signal": "NO_DATA",
            "badge": "⚪ NO DATA",
            "badge_cls": "badge-gray",
            "ema15": None,
            "ema20": None,
            "curr_price": None,
            "diff_pct": 0.0,
            "last_time": ""
        }

    ema15 = close.ewm(span=15, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()

    curr_ema15 = float(ema15.iloc[-1])
    curr_ema20 = float(ema20.iloc[-1])
    prev_ema15 = float(ema15.iloc[-2])
    prev_ema20 = float(ema20.iloc[-2])

    curr_close = float(close.iloc[-1])
    last_time = str(close.index[-1])

    # Check crossovers
    if prev_ema15 <= prev_ema20 and curr_ema15 > curr_ema20:
        signal = "BUY"
        badge = "🟢 BUY (15m Golden Cross)"
        badge_cls = "badge-green"
    elif prev_ema15 >= prev_ema20 and curr_ema15 < curr_ema20:
        signal = "SELL"
        badge = "🔴 SELL (15m Death Cross)"
        badge_cls = "badge-red"
    elif curr_ema15 > curr_ema20:
        signal = "BULLISH_HOLD"
        badge = "🔵 BULLISH (15 EMA > 20 EMA)"
        badge_cls = "badge-purple"
    else:
        signal = "BEARISH_HOLD"
        badge = "🟠 BEARISH (15 EMA < 20 EMA)"
        badge_cls = "badge-yellow"

    diff_pct = round(((curr_ema15 - curr_ema20) / curr_ema20) * 100, 2)

    return {
        "signal": signal,
        "badge": badge,
        "badge_cls": badge_cls,
        "ema15": round(curr_ema15, 2),
        "ema20": round(curr_ema20, 2),
        "curr_price": round(curr_close, 2),
        "diff_pct": diff_pct,
        "last_time": last_time
    }


def find_best_swing_candidate(screener_results: list[dict]) -> dict:
    """
    Selects the optimal swing trade candidate based on swing_score (technical setup quality),
    not total_score (which is fundamentals-heavy). Filters by RSI zone, MA proximity, and regime.
    Uses MA-anchored SL logic consistent with compute_swing_setup().
    """
    if not screener_results:
        return {}

    candidates = []
    for s in screener_results:
        ltp = s.get("ltp", 0)
        rsi = s.get("rsi") or 50
        vol_spike = s.get("volume_spike") or 1.0
        beta = s.get("beta") or 1.0
        ma50 = s.get("ma50") or ltp

        dist_ma50_pct = ((ltp - ma50) / ma50) * 100 if ma50 > 0 else 0

        # Filter out overextended or extreme overbought stocks
        if rsi > 72 or rsi < 38:
            continue
        if dist_ma50_pct > 15 or dist_ma50_pct < -10:
            continue
        # Skip stocks already in market-correction avoid mode
        if s.get("nifty_regime_status") == "CORRECTION" and s.get("rs_rating", 50) < 75:
            continue

        # Rank by swing_score (technical setup) — not total_score (fundamentals)
        base = s.get("swing_score", s.get("total_score", 0))
        # Small tiebreaker bonuses
        if 50 <= rsi <= 63:
            base += 5
        if vol_spike >= 1.5:
            base += 5
        if 1.0 <= beta <= 1.6:
            base += 3

        candidates.append((base, s))

    if not candidates:
        # Fallback: best swing_score across all qualified
        candidates = [(s.get("swing_score", s.get("total_score", 0)), s) for s in screener_results if s.get("qualified")]
        if not candidates:
            candidates = [(s.get("swing_score", s.get("total_score", 0)), s) for s in screener_results]

    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]

    ltp = best.get("ltp", 0)
    ma50 = best.get("ma50") or (ltp * 0.96)

    # Stop Loss: MA-anchored (consistent with compute_swing_setup)
    if ma50 and (ltp * 0.94 <= ma50 <= ltp * 0.99):
        sl_price = round(ma50 * 0.985, 2)
    else:
        sl_price = round(ltp * 0.965, 2)

    risk = round(ltp - sl_price, 2)
    if risk <= 0 or (risk / ltp) < 0.02:
        risk = round(ltp * 0.035, 2)
        sl_price = round(ltp - risk, 2)
    elif (risk / ltp) > 0.07:
        risk = round(ltp * 0.05, 2)
        sl_price = round(ltp - risk, 2)

    target1 = round(ltp + (1.5 * risk), 2)   # Realistic 3-7d exit
    target2 = round(ltp + (2.5 * risk), 2)   # Runner target
    target1_pct = round(((target1 - ltp) / ltp) * 100, 1)
    target2_pct = round(((target2 - ltp) / ltp) * 100, 1)
    sl_pct = round(((sl_price - ltp) / ltp) * 100, 1)

    swing_score = best.get("swing_score", best.get("total_score", 0))

    return {
        "symbol": best.get("symbol"),
        "ticker": best.get("ticker"),
        "name": best.get("name"),
        "sector": best.get("sector"),
        "swing_score": swing_score,
        "total_score": best.get("total_score"),
        "strength": best.get("strength"),
        "value": best.get("value"),
        "momentum": best.get("momentum"),
        "ltp": ltp,
        "rsi": best.get("rsi"),
        "volume_spike": best.get("volume_spike"),
        "beta": best.get("beta"),
        "ma50": best.get("ma50"),
        "ma200": best.get("ma200"),
        "swing_badge": best.get("swing_badge", ""),
        "swing_reason": best.get("swing_reason", ""),
        "tech_rating": best.get("tech_rating", "🟡 Consolidation"),
        "stop_loss": sl_price,
        "stop_loss_pct": sl_pct,
        "target1": target1,
        "target1_pct": target1_pct,
        "target2": target2,
        "target2_pct": target2_pct,
        "risk_amount": risk,
        "risk_reward_ratio": "1 : 1.5 (T1) / 1 : 2.5 (T2)",
        "timeframe": "3 to 7 Trading Days",
        "rationale": f"Swing score {swing_score}/100 — RSI {best.get('rsi')} in momentum zone, {best.get('volume_spike')}x volume, RS {best.get('rs_rating')}."
    }


# ─── F&O Options Signal Engine ────────────────────────────────────────────────

def get_nse_monthly_expiry() -> tuple:
    """Return (days_to_expiry, expiry_date_str) for the active NSE monthly
    stock options contract (expires last Thursday of each month).
    Rolls over to next month if fewer than 4 days remain."""
    import datetime as _dt
    today = _dt.date.today()

    def last_thursday(year: int, month: int) -> _dt.date:
        if month == 12:
            last_day = _dt.date(year + 1, 1, 1) - _dt.timedelta(days=1)
        else:
            last_day = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1)
        offset = (last_day.weekday() - 3) % 7   # 3 = Thursday
        return last_day - _dt.timedelta(days=offset)

    expiry = last_thursday(today.year, today.month)
    days   = (expiry - today).days
    if days < 4:
        m, y = today.month + 1, today.year
        if m > 12:
            m, y = 1, y + 1
        expiry = last_thursday(y, m)
        days   = (expiry - today).days
    return days, expiry.strftime("%d %b %Y")


def compute_fno_signal(scored: dict, fno_cfg: dict) -> dict:
    """Compute F&O weekly OTM options signal (CE / PE / NEUTRAL).

    Strategy: Buy OTM CE or PE, hold ~1 week within the active NSE
    monthly contract.  Returns strikes, underlying SL/T1/T2, and
    a 0-100 conviction score.

    NSE-verified lot sizes (Aug 2026):
      MARUTI=50  RELIANCE=500  BAJAJ-AUTO=75
      ULTRACEMCO=50  APOLLOHOSP=125  TCS=225
    """
    import math as _math

    ltp       = scored.get("ltp", 0)
    rsi       = float(scored.get("rsi") or 50)
    ma50      = scored.get("ma50")
    ma200     = scored.get("ma200")
    vol_spike = float(scored.get("volume_spike") or 1.0)
    beta      = float(scored.get("beta") or 1.0)
    wk52_ret  = float(scored.get("wk52_return_pct") or 0)

    strike_iv = float(fno_cfg.get("strike_interval") or 50)
    if strike_iv <= 0:
        strike_iv = 50.0
    lot_size  = int(fno_cfg.get("lot_size") or 50)
    if lot_size <= 0:
        lot_size = 50

    if ltp <= 0:
        return {
            "signal": "NO_DATA", "symbol": scored.get("symbol"),
            "name": scored.get("name"), "ltp": 0, "conviction": 0,
            "lot_size": lot_size, "strike_interval": strike_iv,
        }

    above_ma50  = bool(ma50  and ltp >= ma50)
    above_ma200 = bool(ma200 and ltp >= ma200)

    # ── Intraday direction (today's % change from previous close) ─────────────
    prev_close = scored.get("prev_close") or ltp
    day_chg_pct = ((ltp - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

    # ── Direction (multi-factor: RSI + MA + intraday all must agree) ──────────
    # CE requires: strong RSI + above MA50 + NOT declining today (>-0.5%)
    # PE requires: weak RSI OR below MA50 + declining today (<+0.5%)
    # Tightened thresholds so large-cap uptrend stocks don't auto-trigger CE

    ce_rsi_ok  = rsi >= 57
    pe_rsi_ok  = rsi <= 43
    day_up     = day_chg_pct >= -0.3    # not meaningfully down
    day_down   = day_chg_pct <= 0.3     # not meaningfully up

    # Strong CE: all three bullish
    if ce_rsi_ok and above_ma50 and day_up:
        direction = "CE"
    # Strong PE: all three bearish
    elif pe_rsi_ok and not above_ma50 and day_down:
        direction = "PE"
    # Moderate CE: good RSI + above both MAs + slight down day OK
    elif rsi >= 60 and above_ma50 and above_ma200 and day_chg_pct >= -0.8:
        direction = "CE"
    # Moderate PE: weak RSI + below MA50 + today red
    elif rsi <= 46 and not above_ma50 and day_chg_pct <= 0.5:
        direction = "PE"
    # Intraday override — strong down day even if RSI/MA not fully bearish
    elif day_chg_pct <= -1.0 and not above_ma200:
        direction = "PE"
    # Intraday override — strong up day even if RSI/MA not fully bullish
    elif day_chg_pct >= 1.0 and above_ma200:
        direction = "CE"
    else:
        direction = "NEUTRAL"

    # ── Conviction Score (0–100) ───────────────────────────────────────────────
    conviction = 0
    # 1. RSI quality (20 pts)
    if direction == "CE":
        conviction += 20 if rsi >= 62 else 15 if rsi >= 58 else 10 if rsi >= 55 else 5
    elif direction == "PE":
        conviction += 20 if rsi <= 38 else 15 if rsi <= 42 else 10 if rsi <= 46 else 5
    else:
        conviction += 3
    # 2. MA alignment (20 pts)
    if direction == "CE":
        conviction += 20 if (above_ma50 and above_ma200) else 12 if above_ma50 else 5 if above_ma200 else 0
    elif direction == "PE":
        conviction += 20 if (not above_ma50 and not above_ma200) else 12 if not above_ma50 else 5 if not above_ma200 else 0
    else:
        conviction += 3
    # 3. Intraday alignment with signal (20 pts) — key for weekly options
    if direction == "CE":
        conviction += 20 if day_chg_pct >= 1.5 else 14 if day_chg_pct >= 0.5 else 8 if day_chg_pct >= 0 else 2 if day_chg_pct >= -0.5 else 0
    elif direction == "PE":
        conviction += 20 if day_chg_pct <= -1.5 else 14 if day_chg_pct <= -0.5 else 8 if day_chg_pct <= 0 else 2 if day_chg_pct <= 0.5 else 0
    else:
        conviction += 3
    # 4. Volume (15 pts)
    conviction += 15 if vol_spike >= 2.0 else 11 if vol_spike >= 1.5 else 7 if vol_spike >= 1.2 else 3 if vol_spike >= 0.9 else 0
    # 5. Beta suitability (15 pts)
    conviction += 15 if (0.9 <= beta <= 1.6) else 10 if (0.7 <= beta < 0.9 or 1.6 < beta <= 2.0) else 5 if (0.5 <= beta < 0.7) else 0
    # 6. 52-week momentum alignment (10 pts)
    if direction == "CE":
        conviction += 10 if wk52_ret >= 25 else 7 if wk52_ret >= 10 else 4 if wk52_ret >= 0 else 0
    elif direction == "PE":
        conviction += 10 if wk52_ret <= -15 else 7 if wk52_ret <= -5 else 4 if wk52_ret < 0 else 0
    else:
        conviction += 2
    conviction = min(100, max(0, conviction))

    # ── Strike Selection ───────────────────────────────────────────────────────
    ce_base     = int(_math.ceil(ltp / strike_iv) * strike_iv)
    ce_strike_1 = ce_base + strike_iv
    ce_strike_2 = ce_base + 2 * strike_iv
    pe_base     = int(_math.floor(ltp / strike_iv) * strike_iv)
    pe_strike_1 = pe_base - strike_iv
    pe_strike_2 = pe_base - 2 * strike_iv

    ce_otm_pct_1 = round(((ce_strike_1 - ltp) / ltp) * 100, 1)
    ce_otm_pct_2 = round(((ce_strike_2 - ltp) / ltp) * 100, 1)
    pe_otm_pct_1 = round(((ltp - pe_strike_1) / ltp) * 100, 1)
    pe_otm_pct_2 = round(((ltp - pe_strike_2) / ltp) * 100, 1)

    # ── Underlying R/R levels ──────────────────────────────────────────────────
    sl_pct, t1_pct, t2_pct = 2.0, 3.5, 6.0
    if direction in ("CE", "NEUTRAL"):
        sl_price = round(ltp * (1 - sl_pct / 100), 2)
        t1_price = round(ltp * (1 + t1_pct / 100), 2)
        t2_price = round(ltp * (1 + t2_pct / 100), 2)
    else:
        sl_price = round(ltp * (1 + sl_pct / 100), 2)
        t1_price = round(ltp * (1 - t1_pct / 100), 2)
        t2_price = round(ltp * (1 - t2_pct / 100), 2)

    days_to_expiry, expiry_str = get_nse_monthly_expiry()

    return {
        "symbol": scored.get("symbol"), "ticker": scored.get("ticker"),
        "name": scored.get("name"), "sector": scored.get("sector"),
        "ltp": round(ltp, 2), "prev_close": scored.get("prev_close"),
        "day_chg_pct": round(day_chg_pct, 2),
        "rsi": round(rsi, 1), "ma50": ma50, "ma200": ma200,
        "vol_spike": round(vol_spike, 2), "beta": round(beta, 2),
        "above_ma50": above_ma50, "above_ma200": above_ma200,
        "wk52_return_pct": round(wk52_ret, 1),
        "week_high_52": scored.get("week_high_52"),
        "week_low_52":  scored.get("week_low_52"),
        "signal": direction, "conviction": conviction,
        "lot_size": lot_size, "strike_interval": strike_iv,
        "ce_strike_1": ce_strike_1, "ce_strike_2": ce_strike_2,
        "ce_otm_pct_1": ce_otm_pct_1, "ce_otm_pct_2": ce_otm_pct_2,
        "pe_strike_1": pe_strike_1, "pe_strike_2": pe_strike_2,
        "pe_otm_pct_1": pe_otm_pct_1, "pe_otm_pct_2": pe_otm_pct_2,
        "sl_price": sl_price, "sl_pct": sl_pct,
        "t1_price": t1_price, "t1_pct": t1_pct,
        "t2_price": t2_price, "t2_pct": t2_pct,
        "days_to_expiry": days_to_expiry, "expiry_str": expiry_str,
        "total_score": scored.get("total_score"),
        "strength": scored.get("strength"),
        "momentum": scored.get("momentum"),
        "pa_score": scored.get("pa_score", 50.0),
        "cmf": scored.get("cmf", 0.0),
        "clv": scored.get("clv", 0.5),
        "market_structure": scored.get("market_structure", "Neutral"),
        "pa_pattern": scored.get("pa_pattern", "None"),
        "pa_badge": scored.get("pa_badge", "⚪ Neutral Order Flow"),
        "pa_class": scored.get("pa_class", "badge-gray"),
    }


def calc_indmoney_charges(trade_value: float, trade_type: str = "BUY") -> dict:
    """
    Calculates exact INDmoney Delivery Charges for Indian Equity:
    - Brokerage: 0.05% or ₹20 (whichever is lower).
    - STT (Securities Transaction Tax): 0.1% on Buy value & 0.1% on Sell value.
    - Exchange Turnover Fee (NSE): 0.00297% of trade value.
    - Stamp Duty: 0.015% on Buy value (0% on Sell).
    - GST: 18% on (Brokerage + Exchange Turnover Fee).
    - DP Charges (Depository Participant): ₹15.93 flat per sell order (CDSL/INDmoney).
    - SEBI Turnover Fee: 0.0001% of trade value.
    """
    trade_val = float(trade_value)
    if trade_val <= 0:
        return {
            "gross_value": 0.0, "total_charges": 0.0, "net_value": 0.0,
            "brokerage": 0.0, "stt": 0.0, "stamp_duty": 0.0,
            "exchange_fee": 0.0, "gst": 0.0, "dp_charges": 0.0, "sebi_fee": 0.0
        }

    # 1. Brokerage: 0.05% or ₹20 (whichever is lower)
    brokerage = min(20.0, trade_val * 0.0005)
    
    # 2. STT: 0.1% on Buy & Sell
    stt = trade_val * 0.001
    
    # 3. Exchange Turnover Fee (NSE): 0.00297%
    exchange_fee = trade_val * 0.0000297
    
    # 4. Stamp Duty: 0.015% on Buy only
    stamp_duty = (trade_val * 0.00015) if trade_type.upper() == "BUY" else 0.0
    
    # 5. GST: 18% on (Brokerage + Exchange Fee)
    gst = (brokerage + exchange_fee) * 0.18
    
    # 6. DP Charges: ₹15.93 flat per Sell order
    dp_charges = 15.93 if trade_type.upper() == "SELL" else 0.0
    
    # 7. SEBI Fee: 0.0001%
    sebi_fee = trade_val * 0.000001

    total_charges = round(brokerage + stt + exchange_fee + stamp_duty + gst + dp_charges + sebi_fee, 2)
    
    if trade_type.upper() == "BUY":
        net_value = round(trade_val + total_charges, 2)
    else:
        net_value = round(max(0.0, trade_val - total_charges), 2)

    return {
        "gross_value": round(trade_val, 2),
        "total_charges": total_charges,
        "net_value": net_value,
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "stamp_duty": round(stamp_duty, 2),
        "exchange_fee": round(exchange_fee, 2),
        "gst": round(gst, 2),
        "dp_charges": round(dp_charges, 2),
        "sebi_fee": round(sebi_fee, 2)
    }


def compute_quality_penny_stocks(screener_results: list[dict], top_n: int = 20, monthly_sip: float = 200.0) -> list[dict]:
    """
    Decoupled Quality Penny / Micro-Cap Engine:
    Separates Wealth-Builder Durability (Debt-free status, ROE, Margin) 
    from SIP Entry Timing (Distance from GTT / EMA20 support).
    """
    if not screener_results:
        return []

    qualified = []
    for s in screener_results:
        ltp = float(s.get("ltp") or 0.0)
        mc = float(s.get("market_cap") or 0.0)
        roe = float(s.get("roe_pct") if s.get("roe_pct") is not None else 0.0)
        npm = float(s.get("npm_pct") if s.get("npm_pct") is not None else 0.0)
        de = float(s.get("de_ratio") if s.get("de_ratio") is not None else 1.0)
        vol = float(s.get("avg_volume_10d") or s.get("today_volume") or 0.0)
        total_score = float(s.get("total_score") or 0.0)

        # Gate 1: Price Range (₹5 to ₹75)
        if not (5.0 <= ltp <= 75.0): continue
        # Gate 2: Market Cap Floor (>= ₹50 Cr)
        if mc > 0 and mc < 500000000: continue
        # Gate 3: Solvency (D/E <= 1.0)
        if de > 1.0: continue
        # Gate 4: Profitability (ROE >= 6% and Margin > 0%)
        if roe < 6.0 or npm <= 0.0: continue
        # Gate 5: Liquidity (Avg Volume >= 20,000)
        if vol > 0 and vol < 20000: continue
        # Gate 6: Minimum Quality Score (>= 45)
        if total_score < 45.0: continue

        # ── 1. PENNY QUALITY SCORE (0 - 100) ────────────────────────────────────
        q_pts = 0.0
        if de <= 0.15: q_pts += 25.0
        elif de <= 0.50: q_pts += 18.0
        elif de <= 1.0: q_pts += 10.0

        if roe >= 20.0: q_pts += 25.0
        elif roe >= 12.0: q_pts += 18.0
        elif roe >= 6.0: q_pts += 10.0

        if npm >= 10.0: q_pts += 20.0
        elif npm > 0.0: q_pts += 10.0

        q_pts += min(20.0, (total_score / 100.0) * 20.0)
        if vol >= 50000: q_pts += 10.0
        else: q_pts += 5.0

        penny_quality_score = round(min(100.0, max(0.0, q_pts)), 1)

        # ── 2. PENNY ENTRY SCORE (0 - 100) ──────────────────────────────────────
        e_pts = 0.0
        ema20 = float(s.get("ema20") or 0)
        sr_sup = float(s.get("sup_level") or 0)
        low20 = float(s.get("low20") or 0)
        ma50 = float(s.get("ma50") or 0)

        auto_gtt = ema20 if (0 < ema20 < ltp) else sr_sup if (0 < sr_sup < ltp) else low20 if (0 < low20 < ltp) else ma50 if (0 < ma50 < ltp) else ltp

        if auto_gtt > 0 and ltp > 0:
            dist_gtt_pct = ((ltp - auto_gtt) / auto_gtt) * 100.0
            if dist_gtt_pct <= 3.0: e_pts += 35.0
            elif dist_gtt_pct <= 8.0: e_pts += 22.0
            elif dist_gtt_pct <= 15.0: e_pts += 12.0
            else: e_pts += 5.0
        else:
            e_pts += 15.0

        if ema20 > 0 and ltp > 0:
            dist_ema = abs((ltp - ema20) / ema20) * 100.0
            if dist_ema <= 4.0: e_pts += 30.0
            elif dist_ema <= 10.0: e_pts += 18.0
            else: e_pts += 8.0
        else:
            e_pts += 15.0

        rsi = float(s.get("rsi") or 50.0)
        if 40 <= rsi <= 60: e_pts += 25.0
        elif 60 < rsi <= 70: e_pts += 15.0
        else: e_pts += 5.0

        day_chg = float(s.get("day_chg_pct") or 0.0)
        if day_chg >= -0.35: e_pts += 10.0

        penny_entry_score = round(min(100.0, max(0.0, e_pts)), 1)

        # ── 3. COMBINED PENNY RANK SCORE & ACTION ──────────────────────────────
        penny_rank_score = round((penny_quality_score * 0.65) + (penny_entry_score * 0.35), 1)

        if penny_quality_score >= 70:
            if penny_entry_score >= 60:
                status_badge = "🟢 START SIP NOW"
                status_badge_class = "badge-green"
                status_reason = f"High durability wealth-builder ({penny_quality_score:.0f}/100) at ideal SIP entry ({penny_entry_score:.0f}/100 entry)"
            else:
                status_badge = "🟢 SIP ON DIP / RETEST"
                status_badge_class = "badge-green"
                status_reason = f"Top quality micro-cap ({penny_quality_score:.0f}/100) — start initial tranche & accumulate on dips to GTT ₹{auto_gtt:.2f}"
        elif penny_quality_score >= 50:
            status_badge = "🟡 WATCHLIST"
            status_badge_class = "badge-yellow"
            status_reason = f"Developing micro-cap ({penny_quality_score:.0f}/100) — monitor earnings growth"
        else:
            status_badge = "🔴 REJECT"
            status_badge_class = "badge-gray"
            status_reason = "Fails micro-cap durability requirements"

        # SIP qty
        sip_qty = max(1, int(monthly_sip / ltp)) if ltp > 0 else 1
        sip_cost = round(sip_qty * ltp, 2)

        if de <= 0.15: durability_tag = "💎 Virtually Debt-Free"
        elif roe >= 20.0: durability_tag = "🔥 High ROE Compounder"
        elif total_score >= 60.0: durability_tag = "⚡ Quality Growth Penny"
        else: durability_tag = "📈 Undervalued Micro-Cap"

        dist_from_gtt_pct = round(((ltp - auto_gtt) / auto_gtt) * 100, 1) if auto_gtt > 0 else 0.0

        item = dict(s)
        item["penny_quality_score"] = penny_quality_score
        item["penny_entry_score"] = penny_entry_score
        item["penny_rank_score"] = penny_rank_score
        item["monthly_sip_qty"] = sip_qty
        item["monthly_sip_cost"] = sip_cost
        item["durability_tag"] = durability_tag
        item["durability_class"] = "badge-green" if penny_quality_score >= 70 else "badge-yellow"
        item["status_badge"] = status_badge
        item["status_badge_class"] = status_badge_class
        item["status_reason"] = status_reason
        item["auto_gtt"] = auto_gtt
        item["dist_from_gtt_pct"] = dist_from_gtt_pct
        qualified.append(item)

    qualified.sort(key=lambda x: x["penny_quality_score"], reverse=True)
    return qualified[:top_n]


