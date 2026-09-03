"""
screener_engine.py
Scores each stock on Strength, Value, Momentum (0-100 each).
All inputs come from yfinance .info dict + price history DataFrame.
No mock data — if a metric is missing, it is skipped and score is partial.
"""

import bisect
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

def classify_incumbent(info: dict) -> str:
    """
    Classifies stock into 5 status buckets based on fundamental trends:
    'GROWTH_CULT', 'MATURE_VALUE', 'TURNAROUND', 'DISTRESSED', 'STAGNANT'
    """
    roe = to_float(info.get("returnOnEquity")) or 0
    npm = to_float(info.get("profitMargins")) or 0
    growth = to_float(info.get("revenueGrowth")) or 0
    
    if growth > 0.15 and roe > 0.15: return "GROWTH_CULT"
    if roe > 0.15 and growth <= 0.15: return "MATURE_VALUE"
    if growth > 0 and roe <= 0: return "TURNAROUND"
    if growth < 0 and roe < 0.05: return "DISTRESSED"
    return "STAGNANT"

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

    if not avg_vol_20d and len(history) >= 20 and "Volume" in history.columns:
        avg_vol_20d = float(history["Volume"].tail(20).mean())
    elif not avg_vol_20d and len(history) >= 10 and "Volume" in history.columns:
        avg_vol_20d = float(history["Volume"].tail(10).mean())

    if not vol and len(history) >= 1 and "Volume" in history.columns:
        vol = float(history["Volume"].iloc[-1])

    vol_spike = 0.0
    vol_pts = 0

    if vol > 0 and avg_vol_20d > 0:
        vol_pace = vol
        try:
            import datetime
            ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
            now_dt = datetime.datetime.now(ist_offset)
            if now_dt.weekday() < 5:
                now_t = now_dt.time()
                market_open_t = datetime.time(9, 15)
                market_close_t = datetime.time(15, 30)
                if market_open_t <= now_t <= market_close_t:
                    mins_elapsed = (now_t.hour * 60 + now_t.minute) - (9 * 60 + 15)
                    if mins_elapsed > 15:
                        progress = min(1.0, max(0.08, mins_elapsed / 375.0))
                        vol_pace = vol / progress
        except Exception:
            pass

        vol_spike = round(vol_pace / avg_vol_20d, 2)
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

    valid_s = sum(1 for k, v in s_break.items() if not k.endswith("_pts") and v is not None)
    valid_v = sum(1 for k, v in v_break.items() if not k.endswith("_pts") and v is not None)

    total_s_metrics = 3.0
    total_v_metrics = 2.0
    s_completeness = min(1.0, valid_s / total_s_metrics)
    v_completeness = min(1.0, valid_v / total_v_metrics)

    # Proportional confidence scaling: fundamental weight scales smoothly with data completeness
    eff_s_weight = 0.40 * s_completeness
    eff_v_weight = 0.35 * v_completeness
    fund_weight = eff_s_weight + eff_v_weight
    tech_weight = max(0.0, 1.0 - fund_weight)

    if fund_weight >= 0.50:
        mkt_momentum_w = tech_weight * 0.70
        pa_w = tech_weight * 0.30
    else:
        mkt_momentum_w = tech_weight * 0.60
        pa_w = tech_weight * 0.40

    total = round((strength * eff_s_weight) + (value * eff_v_weight) + (momentum * mkt_momentum_w) + (pa_score * pa_w), 1)

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

    # Rank into 1-99 percentile with deterministic tie-breakers (None-safe)
    raw_scores.sort(key=lambda x: (x[0], x[1].get("wk52_return_pct") or 0, x[1].get("total_score") or 0, x[1].get("symbol") or ""))
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


def detect_rsi_divergence(history: pd.DataFrame, rsi_period: int = 14, lookback: int = 15) -> dict:
    """
    Detects Bullish RSI Divergence:
    Price forms a Lower Low (or Equal Low) over the last 15 bars,
    while RSI forms a Higher Low (indicating underlying accumulation/momentum reversal).
    """
    if history is None or history.empty or len(history) < rsi_period + lookback or "Close" not in history.columns:
        return {"has_rsi_div": False, "rsi_div_badge": "", "rsi_div_pts": 0.0}

    try:
        close = history["Close"]
        low = history["Low"] if "Low" in history.columns else close

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta.clip(upper=0))
        avg_gain = gain.ewm(alpha=1/rsi_period, min_periods=rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/rsi_period, min_periods=rsi_period, adjust=False).mean()
        
        rs = avg_gain / avg_loss.replace(0, 1e-6)
        rsi_series = 100.0 - (100.0 / (1.0 + rs))

        sub_lows = low.iloc[-lookback:]
        sub_rsi = rsi_series.iloc[-lookback:]

        mid = lookback // 2
        l1_idx = sub_lows.iloc[:mid].idxmin()
        l2_idx = sub_lows.iloc[mid:].idxmin()

        if l1_idx is None or l2_idx is None:
            return {"has_rsi_div": False, "rsi_div_badge": "", "rsi_div_pts": 0.0}

        price_l1 = float(sub_lows.loc[l1_idx])
        price_l2 = float(sub_lows.loc[l2_idx])

        rsi_l1 = float(sub_rsi.loc[l1_idx])
        rsi_l2 = float(sub_rsi.loc[l2_idx])

        if price_l2 <= price_l1 * 1.002 and rsi_l2 >= rsi_l1 + 2.0 and rsi_l2 <= 58.0:
            return {
                "has_rsi_div": True,
                "rsi_div_badge": f"📈 Bullish RSI Div ({rsi_l1:.0f}➔{rsi_l2:.0f})",
                "rsi_div_pts": 10.0
            }
    except Exception:
        pass

    return {"has_rsi_div": False, "rsi_div_badge": "", "rsi_div_pts": 0.0}


def compute_fibonacci_levels(history: pd.DataFrame, ltp: float = None) -> dict:
    """
    Computes Fibonacci Retracement levels from the recent swing high/low over 20-50 bars.
    Levels: 38.2%, 50.0%, 61.8%.
    Exclusion/Penalty Rule: If retracement exceeds 61.8%, the uptrend structure is broken (-25 penalty).
    """
    if history is None or history.empty or len(history) < 10 or "High" not in history.columns or "Low" not in history.columns:
        return {
            "fib_high": None, "fib_low": None, "fib_382": None, "fib_500": None, "fib_618": None,
            "fib_retrace_pct": None, "fib_status": "NONE", "fib_badge": "⚪ Fib N/A", "fib_pts": 0.0
        }

    high_series = history["High"].dropna()
    low_series = history["Low"].dropna()
    close_series = history["Close"].dropna()

    lookback = min(50, len(high_series))
    recent_highs = high_series.iloc[-lookback:]
    recent_lows = low_series.iloc[-lookback:]

    swing_high = float(recent_highs.max())
    swing_low = float(recent_lows.min())

    if ltp is None or ltp <= 0:
        ltp = float(close_series.iloc[-1]) if not close_series.empty else swing_high

    rng = swing_high - swing_low
    if rng <= 0 or swing_high <= 0:
        return {
            "fib_high": None, "fib_low": None, "fib_382": None, "fib_500": None, "fib_618": None,
            "fib_retrace_pct": None, "fib_status": "NONE", "fib_badge": "⚪ Fib N/A", "fib_pts": 0.0
        }

    fib_382 = round(swing_high - (0.382 * rng), 2)
    fib_500 = round(swing_high - (0.500 * rng), 2)
    fib_618 = round(swing_high - (0.618 * rng), 2)

    retrace_pct = round(((swing_high - ltp) / rng) * 100.0, 1)

    if retrace_pct > 61.8:
        fib_status = "FIB_618_EXCEEDED"
        fib_badge = f"⚠️ Fib 61.8% Broken ({retrace_pct:.1f}% retrace)"
        fib_pts = -25.0  # Severe penalty for trend breakdown
    elif 42.0 <= retrace_pct <= 61.8:
        fib_status = "FIB_500_ZONE"
        fib_badge = f"📐 Fib 50% Support (₹{fib_500})"
        fib_pts = 12.0
    elif 28.0 <= retrace_pct < 42.0:
        fib_status = "FIB_382_ZONE"
        fib_badge = f"📐 Fib 38.2% Support (₹{fib_382})"
        fib_pts = 15.0  # Prime swing entry zone
    elif retrace_pct < 28.0:
        fib_status = "FIB_SHALLOW"
        fib_badge = f"📐 Shallow Retrace ({retrace_pct:.1f}%)"
        fib_pts = 4.0
    else:
        fib_status = "NONE"
        fib_badge = "⚪ Fib N/A"
        fib_pts = 0.0

    return {
        "fib_high": round(swing_high, 2),
        "fib_low": round(swing_low, 2),
        "fib_382": fib_382,
        "fib_500": fib_500,
        "fib_618": fib_618,
        "fib_retrace_pct": retrace_pct,
        "fib_status": fib_status,
        "fib_badge": fib_badge,
        "fib_pts": fib_pts
    }


def compute_anchored_vwap(history: pd.DataFrame, ltp: float = None) -> dict:
    """
    Computes Anchored VWAP (AVWAP) from a high-volume catalyst/gap bar or key swing low in the last 30 bars.
    Detects when price retraces to test the AVWAP line for a low-risk swing entry.
    """
    if history is None or history.empty or len(history) < 5 or "Volume" not in history.columns or "High" not in history.columns:
        return {
            "avwap": None, "dist_avwap_pct": None, "avwap_status": "NONE",
            "avwap_badge": "⚓ AVWAP N/A", "avwap_pts": 0.0
        }

    lookback = min(30, len(history))
    sub = history.iloc[-lookback:].copy()

    highs = sub["High"]
    lows = sub["Low"]
    closes = sub["Close"]
    vols = sub["Volume"]

    if ltp is None or ltp <= 0:
        ltp = float(closes.iloc[-1])

    anchor_idx = 0
    max_vol = -1.0
    for i in range(len(sub)):
        v_i = float(vols.iloc[i])
        if v_i > max_vol:
            max_vol = v_i
            anchor_idx = i

    typ_prices = (highs.iloc[anchor_idx:] + lows.iloc[anchor_idx:] + closes.iloc[anchor_idx:]) / 3.0
    vols_sub = vols.iloc[anchor_idx:]

    cum_vol = vols_sub.sum()
    if cum_vol > 0:
        avwap_val = float((typ_prices * vols_sub).sum() / cum_vol)
    else:
        avwap_val = float(typ_prices.mean())

    avwap_val = round(avwap_val, 2)
    dist_avwap_pct = round(((ltp - avwap_val) / avwap_val) * 100.0, 1) if avwap_val > 0 else 0.0

    if -1.8 <= dist_avwap_pct <= 2.5:
        avwap_status = "AVWAP_TEST_BOUNCE"
        avwap_badge = f"⚓ AVWAP Bounce Support (₹{avwap_val})"
        avwap_pts = 15.0  # High-conviction entry at AVWAP support
    elif 2.5 < dist_avwap_pct <= 7.0:
        avwap_status = "ABOVE_AVWAP"
        avwap_badge = f"⚓ Above AVWAP (+{dist_avwap_pct:.1f}%)"
        avwap_pts = 8.0
    elif dist_avwap_pct > 7.0:
        avwap_status = "EXTENDED_FROM_AVWAP"
        avwap_badge = f"⚓ Extended from AVWAP (+{dist_avwap_pct:.1f}%)"
        avwap_pts = 2.0
    else:
        avwap_status = "BELOW_AVWAP"
        avwap_badge = f"⚓ Below AVWAP ({dist_avwap_pct:.1f}%)"
        avwap_pts = -5.0

    return {
        "avwap": avwap_val,
        "dist_avwap_pct": dist_avwap_pct,
        "avwap_status": avwap_status,
        "avwap_badge": avwap_badge,
        "avwap_pts": avwap_pts
    }


def compute_swing_setup(scored: dict, history: pd.DataFrame = None) -> dict:
    """
    Decoupled Swing Trade Engine:
    Separates SETUP QUALITY (is this a high-conviction swing candidate?) 
    from ENTRY QUALITY (is now a low-risk entry point?).

    Includes Fibonacci Retracement & Anchored VWAP (AVWAP) engines.
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

    # ── Fibonacci, Anchored VWAP & Bullish RSI Divergence ──
    fib_info = compute_fibonacci_levels(history, ltp) if history is not None else {
        "fib_high": scored.get("fib_high"), "fib_low": scored.get("fib_low"),
        "fib_382": scored.get("fib_382"), "fib_500": scored.get("fib_500"), "fib_618": scored.get("fib_618"),
        "fib_retrace_pct": scored.get("fib_retrace_pct"), "fib_status": scored.get("fib_status", "NONE"),
        "fib_badge": scored.get("fib_badge", "⚪ Fib N/A"), "fib_pts": float(scored.get("fib_pts") or 0.0)
    }

    avwap_info = compute_anchored_vwap(history, ltp) if history is not None else {
        "avwap": scored.get("avwap"), "dist_avwap_pct": scored.get("dist_avwap_pct"),
        "avwap_status": scored.get("avwap_status", "NONE"),
        "avwap_badge": scored.get("avwap_badge", "⚓ AVWAP N/A"), "avwap_pts": float(scored.get("avwap_pts") or 0.0)
    }

    rsi_div_info = detect_rsi_divergence(history) if history is not None else {
        "has_rsi_div": scored.get("has_rsi_div", False),
        "rsi_div_badge": scored.get("rsi_div_badge", ""),
        "rsi_div_pts": float(scored.get("rsi_div_pts") or 0.0)
    }

    # 1H S/R Breakout & Retest signals
    sr_type = scored.get("sr_type") or "NONE"
    is_break_res = scored.get("is_break_res", False) or (sr_type == "BREAK_RES")
    is_retest_buy = scored.get("is_retest_buy", False) or (sr_type == "RETEST_BUY")
    dist_from_res_pct = scored.get("dist_from_res_pct")

    dist_ma50_pct = round(((ltp - ma50) / ma50) * 100, 1) if (ma50 and ltp and ma50 > 0) else None
    dist_ema20_pct = round(((ltp - ema20) / ema20) * 100, 1) if (ema20 and ltp and ema20 > 0) else None

    # ── 1. SETUP QUALITY SCORE (Max 70 raw points → 0-100 scale) ──────────────
    setup_pts = 0.0

    # Fibonacci Retracement Score & Rejection Penalty
    setup_pts += fib_info.get("fib_pts", 0.0)

    # Bullish RSI Divergence Bonus
    setup_pts += rsi_div_info.get("rsi_div_pts", 0.0)

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

    # Anchored VWAP Support Score
    entry_pts += avwap_info.get("avwap_pts", 0.0)

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

    # 61.8% Fib Breakdown Rule: Severe penalty if pullback went too deep
    if fib_info.get("fib_status") == "FIB_618_EXCEEDED":
        combined_score = max(0.0, combined_score - 30.0)

    if ltp > 0 and ltp < 50.0:
        combined_score = max(0.0, combined_score - 25.0)

    swing_score = round(min(100.0, max(0.0, combined_score)), 1)


    # ── 4. ACTION LABEL & BADGE ASSIGNMENT ─────────────────────────────────────
    if fib_info.get("fib_status") == "FIB_618_EXCEEDED":
        swing_action = "REJECT — FIB 61.8% BROKEN"
        swing_badge = "⚠️ REJECT — FIB 61.8% BROKEN"
        swing_class = "badge-red"
        swing_reason = f"Pullback too deep ({fib_info.get('fib_retrace_pct', 0):.1f}% retrace) — uptrend structure broken"
    elif nifty_regime == "CORRECTION" and setup_score < 60:
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
        "risk_reward": "1 : 1.5 / 1 : 2.5",
        "fib_high": fib_info.get("fib_high"),
        "fib_low": fib_info.get("fib_low"),
        "fib_382": fib_info.get("fib_382"),
        "fib_500": fib_info.get("fib_500"),
        "fib_618": fib_info.get("fib_618"),
        "fib_retrace_pct": fib_info.get("fib_retrace_pct"),
        "fib_status": fib_info.get("fib_status"),
        "fib_badge": fib_info.get("fib_badge"),
        "avwap": avwap_info.get("avwap"),
        "dist_avwap_pct": avwap_info.get("dist_avwap_pct"),
        "avwap_status": avwap_info.get("avwap_status"),
        "avwap_badge": avwap_badge if 'avwap_badge' in locals() else avwap_info.get("avwap_badge"),
        "has_rsi_div": rsi_div_info.get("has_rsi_div", False),
        "rsi_div_badge": rsi_div_info.get("rsi_div_badge", "")
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


# ── TREND STATES ────────────────────────────────────────────────────────────
# Single source of truth for trend classification. Every consumer -- the scoring
# gates, the HTML filter dropdown, the JS badge rendering -- derives from this
# table instead of repeating string literals.
#
# This exists because repeating them silently broke the BUY_NOW gate: the
# classifier emitted trend "Uptrend" while carrying the badge "Strong Uptrend",
# and the gate compared trend against the literal "Strong Uptrend". That is
# always False, so BUY_NOW became unreachable with nothing to indicate it.
# Comparing against a name makes that class of mismatch a NameError, not silence.
TREND_STRONG_UPTREND = "Strong Uptrend"
TREND_UPTREND        = "Uptrend"
TREND_ACCUMULATION   = "Accumulation"
TREND_DISTRIBUTION   = "Distribution"
TREND_CONSOLIDATION  = "Consolidation"
TREND_DOWNTREND      = "Downtrend"

# Ordered strongest -> weakest. The frontend builds its filter dropdown from
# this, so adding a state here surfaces it in the UI with no further changes.
TREND_STATES: dict = {
    TREND_STRONG_UPTREND: {"badge": "🟢 Strong Uptrend",      "class": "badge-green"},
    TREND_UPTREND:        {"badge": "🟢 Uptrend",             "class": "badge-green"},
    TREND_ACCUMULATION:   {"badge": "🔵 Accumulation Phase",  "class": "badge-purple"},
    TREND_CONSOLIDATION:  {"badge": "🟡 Consolidation Phase", "class": "badge-yellow"},
    TREND_DISTRIBUTION:   {"badge": "🟠 Distribution Phase",  "class": "badge-yellow"},
    TREND_DOWNTREND:      {"badge": "🔴 Downtrend",           "class": "badge-red"},
}

# Trend states that represent constructive price structure.
UPTREND_STATES = (TREND_UPTREND, TREND_ACCUMULATION, TREND_STRONG_UPTREND)


def trend_result(state: str) -> dict:
    """Build a classification result from the TREND_STATES table.

    Keeping trend/badge/class together here means a state can never again ship
    with a badge that disagrees with the value the gates compare against.
    """
    meta = TREND_STATES[state]
    return {"trend": state, "badge": meta["badge"], "class": meta["class"]}


def compute_trend_classification(scored: dict) -> dict:
    """
    Evaluates market trend, returning one of TREND_STATES.
    See that table for the full set and their badges.
    """
    ltp = scored.get("ltp", 0)
    ema20 = scored.get("ema20")
    ma50 = scored.get("ma50")
    ma200 = scored.get("ma200")
    rsi = scored.get("rsi")
    vol_spike = scored.get("volume_spike", 1.0)
    wk52_h = scored.get("week_high_52")

    if ltp <= 0:
        return trend_result(TREND_CONSOLIDATION)

    above_20 = (ema20 is not None and ltp >= ema20)
    above_50 = (ma50 is not None and ltp >= ma50)
    above_200 = (ma200 is not None and ltp >= ma200) if ma200 else (above_20 or above_50)
    dist_52h_pct = ((ltp - wk52_h) / wk52_h * 100) if (wk52_h and wk52_h > 0) else -100

    # Price below 20-EMA, 50-MA, and 200-MA
    if not above_20 and not above_50 and (ma200 is None or not above_200):
        return trend_result(TREND_DOWNTREND)

    # Near 52W High (within 10%) or above 50MA, but volume spike >= 1.2x & weakening RSI (<48)
    if (dist_52h_pct >= -10 or above_50) and vol_spike >= 1.2 and (rsi is not None and rsi < 48):
        return trend_result(TREND_DISTRIBUTION)

    # Price above 200MA or 20-EMA, volume spike >= 1.2x, healthy RSI (45-58)
    if (above_200 or above_20) and vol_spike >= 1.2 and (rsi is not None and 45 <= rsi <= 58):
        return trend_result(TREND_ACCUMULATION)

    # Price > 20-EMA and > 50-MA (or 200-MA) with healthy RSI — full trend structure
    if above_20 and (ma50 is None or above_50) and (rsi is None or rsi >= 48):
        return trend_result(TREND_STRONG_UPTREND)

    # Above the 20-EMA only — constructive but a weaker structure than the above
    if above_20:
        return trend_result(TREND_UPTREND)

    # Consolidating near moving averages
    return trend_result(TREND_CONSOLIDATION)


def classify_stock_sector_group(sector: str, industry: str) -> str:
    sec_str = f"{sector or ''} {industry or ''}".lower()
    if any(k in sec_str for k in ["bank", "financial", "insurance", "capital markets", "nbfc", "credit"]):
        return "BFSI"
    elif any(k in sec_str for k in ["metal", "steel", "mining", "aluminum", "copper", "oil", "gas", "petroleum", "chemical"]):
        return "COMMODITY"
    elif any(k in sec_str for k in ["utility", "power", "electric", "infrastructure", "construction", "real estate"]):
        return "UTILITIES_INFRA"
    elif any(k in sec_str for k in ["industrial", "manufacturing", "capital goods", "machinery", "auto"]):
        return "MANUFACTURING"
    else:
        return "QUALITY_GROWTH"


def compute_fundamental_trend_score(scored: dict) -> dict:
    """
    Computes a Fundamental Trend Score (0-100) evaluating underlying operational trajectory:
    revenue trend, profit margin trend, ROE trend, cash flow trend, and balance sheet leverage trend.
    Excludes share-price momentum so momentum does not inflate fundamental trend.
    """
    roe = float(scored.get("roe_pct") if scored.get("roe_pct") is not None else 0.0)
    de = float(scored.get("de_ratio") if scored.get("de_ratio") is not None else 0.0)
    npm = float(scored.get("npm_pct") if scored.get("npm_pct") is not None else 0.0)
    rev_growth = float(scored.get("rev_growth_pct") if scored.get("rev_growth_pct") is not None else 0.0)
    cmf = float(scored.get("cmf") or 0.0)
    clv = float(scored.get("clv") or 0.5)

    trend_pts = 0.0
    # 1. Revenue Growth & Acceleration (max 25)
    if rev_growth >= 20.0: trend_pts += 25.0
    elif rev_growth >= 10.0: trend_pts += 18.0
    elif rev_growth > 0.0: trend_pts += 10.0
    else: trend_pts += 2.0

    # 2. Profit Margin Trend (max 25)
    if npm >= 12.0: trend_pts += 25.0
    elif npm >= 6.0: trend_pts += 18.0
    elif npm > 0.0: trend_pts += 10.0

    # 3. ROE Return Trend (max 25)
    if roe >= 18.0: trend_pts += 25.0
    elif roe >= 12.0: trend_pts += 18.0
    elif roe >= 6.0: trend_pts += 10.0

    # 4. FCF & Cash Accumulation Trend (max 15)
    if cmf >= 0.05 and clv >= 0.50: trend_pts += 15.0
    elif cmf >= 0.0: trend_pts += 8.0

    # 5. Debt / De-leveraging Trend (max 10)
    if de <= 0.3: trend_pts += 10.0
    elif de <= 0.8: trend_pts += 5.0

    fundamental_trend_score = round(min(100.0, max(0.0, trend_pts)), 1)
    if fundamental_trend_score >= 70: trend_rating = "STRONG_IMPROVING"
    elif fundamental_trend_score >= 45: trend_rating = "STABLE_NEUTRAL"
    else: trend_rating = "DETERIORATING"

    return {
        "fundamental_trend_score": fundamental_trend_score,
        "fundamental_trend_rating": trend_rating
    }


def compute_cyclicality_and_normalization(scored: dict, sec_group: str, lt_quality_score: float, trend_score: float) -> dict:
    """
    Computes Cyclicality & Earnings Normalization metrics:
    - cyclicality_flag: LOW / MODERATE / HIGH
    - cycle_position: RECOVERY / MID_CYCLE / PEAK_RISK / DOWNTURN / STABLE_NON_CYCLICAL
    - normalized_earnings_quality: 0-100 (through-cycle earnings durability vs peak profitability)
    - trend_driver: STRUCTURAL / CYCLE_DRIVEN / MIXED / UNKNOWN
    """
    rev_growth = float(scored.get("rev_growth_pct") if scored.get("rev_growth_pct") is not None else 0.0)
    ret_3m = float(scored.get("ret_3m") or 0.0)
    roe = float(scored.get("roe_pct") if scored.get("roe_pct") is not None else 0.0)
    de = float(scored.get("de_ratio") if scored.get("de_ratio") is not None else 0.0)

    # 1. Cyclicality Flag
    if sec_group in ("COMMODITY", "UTILITIES_INFRA"):
        cyclicality_flag = "HIGH"
    elif sec_group == "MANUFACTURING":
        cyclicality_flag = "MODERATE"
    else:
        cyclicality_flag = "LOW"

    # 2. Cycle Position
    if cyclicality_flag in ("HIGH", "MODERATE"):
        if rev_growth >= 25.0 or ret_3m >= 30.0:
            cycle_position = "PEAK_RISK" if roe >= 25.0 else "MID_CYCLE"
        elif rev_growth >= 10.0 or ret_3m >= 10.0:
            cycle_position = "MID_CYCLE"
        elif rev_growth > 0.0 or ret_3m >= -5.0:
            cycle_position = "RECOVERY"
        else:
            cycle_position = "DOWNTURN"
    else:
        cycle_position = "STABLE_NON_CYCLICAL"

    # 3. Normalized Earnings Quality (0 - 100)
    norm_pts = lt_quality_score * 0.7
    if de <= 0.2: norm_pts += 15.0
    elif de <= 0.5: norm_pts += 10.0
    if roe >= 15.0: norm_pts += 15.0
    elif roe >= 10.0: norm_pts += 8.0

    normalized_earnings_quality = round(min(100.0, max(0.0, norm_pts)), 1)

    # 4. Trend Driver
    if lt_quality_score >= 70.0 and de <= 0.3:
        trend_driver = "STRUCTURAL"
    elif cyclicality_flag in ("HIGH", "MODERATE") and (rev_growth >= 15.0 or ret_3m >= 20.0):
        trend_driver = "CYCLE_DRIVEN"
    elif lt_quality_score >= 55.0:
        trend_driver = "MIXED"
    else:
        trend_driver = "UNKNOWN"

    return {
        "cyclicality_flag": cyclicality_flag,
        "cycle_position": cycle_position,
        "normalized_earnings_quality": normalized_earnings_quality,
        "trend_driver": trend_driver
    }


def compute_sector_aware_lt_quality(scored: dict) -> dict:
    """
    Computes a 50/25/25 Sector-Aware Long-Term Business Quality Score (0-100),
    Fundamental Trend Score (0-100), Cyclicality Normalization metrics,
    independent Valuation rating, and Risk level.
    """
    sector = scored.get("sector") or ""
    industry = scored.get("industry") or ""
    sec_group = classify_stock_sector_group(sector, industry)

    roe = float(scored.get("roe_pct") if scored.get("roe_pct") is not None else 0.0)
    de = float(scored.get("de_ratio") if scored.get("de_ratio") is not None else 0.0)
    npm = float(scored.get("npm_pct") if scored.get("npm_pct") is not None else 0.0)
    rev_growth = float(scored.get("rev_growth_pct") if scored.get("rev_growth_pct") is not None else 0.0)
    total_score = float(scored.get("total_score") or 50.0)
    strength = float(scored.get("strength") or 50.0)
    pe = scored.get("pe")
    pb = scored.get("pb")
    trend = scored.get("trend") or TREND_CONSOLIDATION

    # ── 1. BUSINESS QUALITY & GOVERNANCE (50% max = 50 pts) ─────────────────
    bq_pts = 0.0
    if sec_group == "BFSI":
        if roe >= 18.0: bq_pts += 20.0
        elif roe >= 14.0: bq_pts += 15.0
        elif roe >= 10.0: bq_pts += 10.0
        bq_pts += min(15.0, (strength / 100.0) * 15.0)
        if npm >= 15.0: bq_pts += 15.0
        elif npm >= 10.0: bq_pts += 10.0
        else: bq_pts += 5.0
    elif sec_group == "COMMODITY":
        if roe >= 15.0: bq_pts += 18.0
        elif roe >= 10.0: bq_pts += 12.0
        elif roe >= 5.0: bq_pts += 8.0
        if de <= 0.15: bq_pts += 20.0
        elif de <= 0.40: bq_pts += 14.0
        elif de <= 0.80: bq_pts += 8.0
        if npm >= 10.0: bq_pts += 12.0
        elif npm > 0: bq_pts += 6.0
    elif sec_group == "UTILITIES_INFRA":
        if de <= 0.8: bq_pts += 18.0
        elif de <= 1.5: bq_pts += 12.0
        if roe >= 12.0: bq_pts += 18.0
        elif roe >= 8.0: bq_pts += 12.0
        bq_pts += min(14.0, (strength / 100.0) * 14.0)
    else:  # MANUFACTURING & QUALITY_GROWTH
        if roe >= 20.0: bq_pts += 20.0
        elif roe >= 14.0: bq_pts += 14.0
        elif roe >= 8.0: bq_pts += 8.0
        if de <= 0.15: bq_pts += 18.0
        elif de <= 0.40: bq_pts += 12.0
        elif de <= 1.0: bq_pts += 6.0
        if npm >= 12.0: bq_pts += 12.0
        elif npm >= 6.0: bq_pts += 8.0

    lt_business_quality = round(min(50.0, max(0.0, bq_pts)), 1)

    # ── 2. GROWTH (25% max = 25 pts) — PURE FUNDAMENTAL (No Price Momentum) ──
    g_pts = 0.0
    if rev_growth >= 20.0: g_pts += 15.0
    elif rev_growth >= 10.0: g_pts += 10.0
    elif rev_growth > 0.0: g_pts += 5.0

    if trend in UPTREND_STATES: g_pts += 10.0
    elif trend == TREND_CONSOLIDATION: g_pts += 5.0

    lt_growth_score = round(min(25.0, max(0.0, g_pts)), 1)

    # ── 3. PROFITABILITY & SUSTAINABILITY (25% max = 25 pts) ────────────────
    s_pts = 0.0
    s_pts += min(15.0, (total_score / 100.0) * 15.0)
    cmf = float(scored.get("cmf") or 0.0)
    clv = float(scored.get("clv") or 0.5)
    if cmf >= 0.05 and clv >= 0.55: s_pts += 10.0
    elif cmf >= 0.0 or clv >= 0.45: s_pts += 5.0

    lt_sustainability_score = round(min(25.0, max(0.0, s_pts)), 1)
    lt_quality_score = round(lt_business_quality + lt_growth_score + lt_sustainability_score, 1)

    trend_res = compute_fundamental_trend_score(scored)
    cycle_res = compute_cyclicality_and_normalization(scored, sec_group, lt_quality_score, trend_res["fundamental_trend_score"])

    # ── 4. INDEPENDENT VALUATION SCORE & STATUS (0 - 100) ────────────────────
    v_pts = 0.0
    if pe is not None and pe > 0:
        if pe <= 18.0: v_pts += 40.0
        elif pe <= 30.0: v_pts += 28.0
        elif pe <= 45.0: v_pts += 15.0
        else: v_pts += 5.0
    else:
        v_pts += 20.0

    if pb is not None and pb > 0:
        if pb <= 2.5: v_pts += 35.0
        elif pb <= 5.0: v_pts += 22.0
        else: v_pts += 8.0
    else:
        v_pts += 20.0

    div_yield = float(scored.get("div_yield_pct") or 0.0)
    if div_yield >= 1.5: v_pts += 25.0
    elif div_yield >= 0.5: v_pts += 15.0
    else: v_pts += 5.0

    lt_valuation_score = round(min(100.0, max(0.0, v_pts)), 1)
    if lt_valuation_score >= 70: lt_val_status = "UNDERVALUED"
    elif lt_valuation_score >= 45: lt_val_status = "FAIRLY_VALUED"
    else: lt_val_status = "EXTENDED"

    if de <= 0.3 and roe >= 14.0: lt_risk = "LOW"
    elif de <= 0.8: lt_risk = "MODERATE"
    else: lt_risk = "HIGH"

    return {
        "sector_group": sec_group,
        "lt_quality_score": lt_quality_score,
        "lt_business_quality": lt_business_quality,
        "lt_growth_score": lt_growth_score,
        "lt_sustainability_score": lt_sustainability_score,
        "lt_valuation_score": lt_valuation_score,
        "lt_valuation_status": lt_val_status,
        "lt_risk_level": lt_risk,
        **trend_res,
        **cycle_res
    }


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
    # UPTREND_STATES is the module-level constant defined with TREND_STATES.
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

    # Calculate sector-aware fundamental quality metrics
    eval_res = compute_sector_aware_lt_quality(scored)
    lt_quality_score = eval_res["lt_quality_score"]

    # ── LT ENTRY SCORE (0 - 100) ────────────────────────────────────────────
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

    # ── ACTION MAPPING ──────────────────────────────────────────────────────
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
        # BUY_NOW only for Strong Uptrend + GTT triggered (price at/near support)
        gtt_triggered = (gtt_level and gtt_level > 0 and ltp > 0 and
                        ((ltp - gtt_level) / gtt_level) * 100.0 <= 2.0)
        if lt_entry_score >= 65 and trend == TREND_STRONG_UPTREND and gtt_triggered:
            status = "BUY_NOW"
            badge = "🟢 BUY NOW (ACCUMULATE)"
            badge_class = "badge-green"
            reason = f"High conviction compounder ({lt_quality_score:.0f}/100) in prime accumulation zone ({lt_entry_score:.0f}/100 entry) · Strong Uptrend + GTT Triggered"
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


def compute_intraday_picks(screener_results: list[dict], top_n: int = 5) -> dict:
    """
    Selects intraday MIS buy (long) and sell (short) candidates for same-day
    square-off trades. Distinct from find_best_swing_candidate (3-7 day holds):
    intraday setups require today's price action + volume to already confirm
    direction, use much tighter stop-loss/target distances than a swing trade,
    and enforce a stricter liquidity floor since MIS positions must be exited
    the same day without excessive slippage.

    Buy (long): positive day move already underway on above-average volume,
    RSI in a bullish-but-not-yet-overbought zone, price holding above its
    50-day MA (trend intact).

    Sell (short): mirror conditions — negative day move on above-average
    volume, RSI in a bearish-but-not-yet-oversold zone, price below its
    50-day MA (trend broken). Assumes MIS intraday short-selling in the cash
    segment (standard with Indian discount brokers), not F&O — the separate
    F&O Options tab already covers options-based bearish plays.

    Returns {"buy": [...up to top_n...], "sell": [...up to top_n...]}, ranked
    by a composite of today's move size, volume confirmation, and RSI extension.
    """
    if not screener_results:
        return {"buy": [], "sell": []}

    # ── LIQUIDITY & CIRCUIT-TRAP GATES ──────────────────────────────────────
    # An MIS position has to be exitable the same day. Two things prevent that:
    # too little money changing hands, and the stock locking at a circuit band.
    #
    # Liquidity is measured in RUPEES TRADED, not share count. A share-count
    # floor is blind to price: against this scan set, 48 stocks clear 200,000
    # shares/day while trading under ₹2 Cr — PRIMO passes on 214,198 shares that
    # come to just ₹0.45 Cr. A meaningful position cannot be exited in that
    # without moving the price against you, which is the slippage a liquidity
    # floor exists to prevent. ₹5 Cr/day sits near the 10th percentile of names
    # that cleared the old gate, so this tightens the thin tail without gutting
    # the candidate pool.
    MIN_TRADED_VALUE = 5_00_00_000
    MIN_PRICE = 20.0

    # NSE circuit bands cluster at 5 / 10 / 20%. A stock pinned just under a band
    # is about to lock, and a locked stock cannot be exited at any price — the
    # trap this gate exists to avoid. A move that has already gone *past* a band
    # is evidence the stock does not have that band, so only the approach zone is
    # rejected, not everything above it.
    CIRCUIT_BANDS = (5.0, 10.0, 20.0)
    CIRCUIT_APPROACH_PCT = 0.5

    def is_near_circuit(move_pct: float) -> bool:
        """True when today's move sits in the approach zone below a circuit band."""
        m = abs(move_pct)
        return any(band - CIRCUIT_APPROACH_PCT <= m <= band for band in CIRCUIT_BANDS)

    def is_circuit_safe_class(s: dict) -> bool:
        """True for stocks that are not prone to locking at a circuit in the first place.

        Gating on today's move alone was the wrong instrument: it treats a symptom
        and lets a stock through the moment it moves past a band. BODALCHEM is the
        worked example -- a ₹1,249 Cr small cap, not MTF-approved, which the
        day-move rule admitted at +5.31% simply because 5.31 > 5.0, even though its
        circuit exposure had not changed at all. Its ₹50 Cr turnover that day was
        also a 4.15x volume spike, not its normal ~₹12 Cr.

        Stock class is the durable signal:
          - MTF-approved: the broker funds margin against it, which they do not do
            for names that gap and lock.
          - Large/mid cap: institutional depth, and dynamic rather than hard bands.
        A small cap outside both carries fixed 5/10/20% bands and can lock with no
        exit at any price -- precisely the trap an MIS position cannot survive.
        """
        return bool(s.get("is_mtf") or s.get("is_large_cap") or s.get("is_mid_cap"))

    buy_candidates = []
    sell_candidates = []

    for s in screener_results:
        ltp = s.get("ltp") or 0
        if ltp < MIN_PRICE:
            continue

        # Circuit exposure is a property of the stock, not of today's move.
        if not is_circuit_safe_class(s):
            continue

        liquidity_shares = s.get("avg_volume_10d") or s.get("today_volume") or 0
        if ltp * liquidity_shares < MIN_TRADED_VALUE:
            continue

        # prev_close comes from yfinance's `.info` dict upstream (score_stock），
        # which is known to silently return incomplete data / get rate-limited —
        # it's frequently None even when every other technical field is fine. Only
        # gate on today's move when we actually have it; otherwise fall through to
        # RSI + volume + trend alone rather than silently excluding everything
        # (a hard "prev_close required" gate would zero out both lists on any scan
        # where yfinance's .info degraded, which defeats the whole tab).
        raw_prev_close = s.get("prev_close")
        has_day_move = raw_prev_close is not None and raw_prev_close > 0
        day_chg_pct = ((ltp - raw_prev_close) / raw_prev_close) * 100 if has_day_move else 0.0

        rsi = s.get("rsi") or 50
        vol_spike = s.get("volume_spike") or 1.0
        ma50 = s.get("ma50") or ltp
        dist_ma50_pct = ((ltp - ma50) / ma50) * 100 if ma50 > 0 else 0
        momentum = s.get("momentum") or 0
        rs_rating = s.get("rs_rating") or 50

        # A stock already pinned just under a circuit band is the trap this tab
        # must not walk into: once it locks there is no exit at any price, and an
        # MIS position has to be closed the same day.
        if has_day_move and is_near_circuit(day_chg_pct):
            continue

        day_move_bullish = has_day_move and (0.4 <= day_chg_pct <= 7.0)
        day_move_bearish = has_day_move and (-7.0 <= day_chg_pct <= -0.4)

        # Buy (long): today's up-move confirmed by volume (when known), RSI
        # building but not yet overbought, trend intact.
        if (day_move_bullish and vol_spike >= 1.3
                and 54 <= rsi <= 74 and dist_ma50_pct >= -1.0):
            score = (min(day_chg_pct, 5) * 4 + min(vol_spike, 3) * 8
                      + (rsi - 50) * 0.6 + momentum * 0.3 + (rs_rating - 50) * 0.2)
            buy_candidates.append((score, s, day_chg_pct, dist_ma50_pct, has_day_move))

        # Sell (short): today's down-move confirmed by volume (when known), RSI
        # breaking down but not yet oversold-exhausted, trend broken.
        if (day_move_bearish and vol_spike >= 1.3
                and 26 <= rsi <= 46 and dist_ma50_pct <= 1.0):
            score = (min(abs(day_chg_pct), 5) * 4 + min(vol_spike, 3) * 8
                      + (50 - rsi) * 0.6 + (-momentum) * 0.3 + (50 - rs_rating) * 0.2)
            sell_candidates.append((score, s, day_chg_pct, dist_ma50_pct, has_day_move))

    buy_candidates.sort(key=lambda x: x[0], reverse=True)
    sell_candidates.sort(key=lambda x: x[0], reverse=True)

    def _build_pick(entry, direction):
        _, s, day_chg_pct, dist_ma50_pct, has_day_move = entry
        ltp = s.get("ltp") or 0
        raw_prev_close = s.get("prev_close")
        # Much tighter risk sizing than a swing trade — MIS is same-day only.
        risk_pct = 1.0
        if direction == "BUY":
            stop_loss = round(ltp * (1 - risk_pct / 100), 2)
            target1 = round(ltp * (1 + 1.5 * risk_pct / 100), 2)
            target2 = round(ltp * (1 + 2.5 * risk_pct / 100), 2)
        else:
            stop_loss = round(ltp * (1 + risk_pct / 100), 2)
            target1 = round(ltp * (1 - 1.5 * risk_pct / 100), 2)
            target2 = round(ltp * (1 - 2.5 * risk_pct / 100), 2)

        return {
            "symbol": s.get("symbol"),
            "ticker": s.get("ticker"),
            "name": s.get("name"),
            "sector": s.get("sector"),
            "direction": direction,
            "ltp": ltp,
            "prev_close": raw_prev_close,
            "day_chg_pct": round(day_chg_pct, 2) if has_day_move else None,
            "has_day_move": has_day_move,
            "rsi": s.get("rsi"),
            "volume_spike": s.get("volume_spike"),
            "dist_ma50_pct": round(dist_ma50_pct, 2),
            "rs_rating": s.get("rs_rating"),
            "total_score": s.get("total_score"),
            "stop_loss": stop_loss,
            "stop_loss_pct": risk_pct if direction == "SELL" else -risk_pct,
            "target1": target1,
            "target1_pct": 1.5 * risk_pct if direction == "BUY" else -1.5 * risk_pct,
            "target2": target2,
            "target2_pct": 2.5 * risk_pct if direction == "BUY" else -2.5 * risk_pct,
            "timeframe": "Intraday (MIS — square off by 3:20 PM)",
            "rationale": (
                (f"Up {day_chg_pct:.1f}% today on " if has_day_move and direction == "BUY"
                 else f"Down {abs(day_chg_pct):.1f}% today on " if has_day_move
                 else "")
                + f"{s.get('volume_spike')}x volume, RSI {s.get('rsi')}, "
                f"{'above' if direction == 'BUY' else 'below'} 50DMA ({dist_ma50_pct:+.1f}%)."
            ),
        }

    return {
        "buy": [_build_pick(e, "BUY") for e in buy_candidates[:top_n]],
        "sell": [_build_pick(e, "SELL") for e in sell_candidates[:top_n]],
    }


# ─── F&O Options Signal Engine ────────────────────────────────────────────────

def get_nse_monthly_expiry() -> tuple:
    """Return (days_to_expiry, expiry_date_str) for the active NSE monthly
    stock options contract (expires last Tuesday of each month per NSE rules).
    Rolls over to next month if fewer than 4 days remain."""
    import datetime as _dt
    today = _dt.date.today()

    def last_tuesday(year: int, month: int) -> _dt.date:
        if month == 12:
            last_day = _dt.date(year + 1, 1, 1) - _dt.timedelta(days=1)
        else:
            last_day = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1)
        offset = (last_day.weekday() - 1) % 7   # 1 = Tuesday
        return last_day - _dt.timedelta(days=offset)

    expiry = last_tuesday(today.year, today.month)
    days   = (expiry - today).days
    if days < 4:
        m, y = today.month + 1, today.year
        if m > 12:
            m, y = 1, y + 1
        expiry = last_tuesday(y, m)
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
    ce_strike_1 = ce_base
    ce_strike_2 = ce_base + strike_iv
    pe_base     = int(_math.floor(ltp / strike_iv) * strike_iv)
    pe_strike_1 = pe_base
    pe_strike_2 = pe_base - strike_iv

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


# Validity bounds for the raw fundamentals feed. These are NOT scoring
# thresholds -- they mark values that cannot be real: npm_pct arrives as high as
# 75,825% and roe_pct as low as -4,016% for some symbols. A value outside these
# bounds is treated as MISSING rather than clamped, because a corrupt figure is
# not a small figure, and clamping would silently admit it to the ranking.
PENNY_SANE_BOUNDS = {
    "roe_pct":   (-100.0, 100.0),
    "npm_pct":   (-100.0, 100.0),
    "de_ratio":  (0.0, 50.0),
    # A P/E below ~3 on a profitable company is nearly always an artifact -- a
    # one-off gain inflating EPS, or stale earnings against a re-rated price --
    # rather than genuine value. Left in, these dominate the cheapness percentile
    # and pull the whole list toward value traps (RELINFRA screened at P/E 0.8).
    # Treated as unmeasurable, consistent with the other bounds here.
    "pe":        (3.0, 300.0),
}


def sane_metric(row: dict, field: str):
    """Return row[field] as a float when it is real and within validity bounds, else None."""
    value = row.get(field)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):   # NaN / +-inf
        return None
    lo, hi = PENNY_SANE_BOUNDS.get(field, (float("-inf"), float("inf")))
    return v if lo <= v <= hi else None


def percentile_rank(sorted_values: list, value: float) -> float:
    """Fraction of `sorted_values` at or below `value`, in 0.0-1.0."""
    if not sorted_values:
        return 0.5
    return bisect.bisect_right(sorted_values, value) / len(sorted_values)


def compute_quality_penny_stocks(screener_results: list[dict], top_n: int = 20, monthly_sip: float = 200.0) -> list[dict]:
    """
    Quality + Value Penny / Micro-Cap Engine.

    Separates three independent judgements:
      - Durability : debt-free status, ROE, margin  (is the business sound?)
      - Value      : P/E and quality-adjusted P/E   (is it cheap for what it is?)
      - Entry      : distance from GTT / EMA20      (is now the moment?)

    Valuation is scored by PERCENTILE within the qualifying penny universe rather
    than against fixed P/E cut-offs. A "cheap" multiple is only meaningful
    relative to what else is available, and percentiles re-baseline themselves as
    the market moves instead of hardcoding a number that silently goes stale.

    A usable P/E is required: judging a stock "undervalued" without a valuation
    measure would be an unsupported claim, so unmeasurable stocks are excluded
    rather than admitted on durability alone.
    """
    if not screener_results:
        return []

    # ── PASS 1: hard gates, and collect the universe used for percentiles ──────
    candidates = []
    for s in screener_results:
        ltp = float(s.get("ltp") or 0.0)
        mc = float(s.get("market_cap") or 0.0)
        vol = float(s.get("avg_volume_10d") or s.get("today_volume") or 0.0)
        total_score = float(s.get("total_score") or 0.0)

        roe = sane_metric(s, "roe_pct")
        npm = sane_metric(s, "npm_pct")
        de  = sane_metric(s, "de_ratio")
        pe  = sane_metric(s, "pe")

        # Gate 1: Price Range (₹5 to ₹75)
        if not (5.0 <= ltp <= 75.0): continue
        # Gate 2: Market Cap Floor (>= ₹50 Cr)
        if mc > 0 and mc < 500000000: continue
        # Gate 3: Solvency — a missing/implausible D/E is disqualifying, not assumed safe
        if de is None or de > 1.0: continue
        # Gate 4: Profitability (ROE >= 6% and positive margin)
        if roe is None or npm is None or roe < 6.0 or npm <= 0.0: continue
        # Gate 5: Liquidity (Avg Volume >= 20,000)
        if vol > 0 and vol < 20000: continue
        # Gate 6: Minimum Quality Score (>= 45)
        if total_score < 45.0: continue
        # Gate 7: Valuation must be measurable and positive. A negative or absent
        # P/E means loss-making or unreported earnings — neither can be called
        # undervalued, which is a stated requirement of this list.
        if pe is None or pe <= 0.0: continue

        candidates.append((s, ltp, mc, roe, npm, de, pe, vol, total_score))

    if not candidates:
        return []

    # Universe distributions for percentile scoring. pe_by_quality is a PEG-style
    # measure: the multiple paid per unit of return on equity, so a high-ROE
    # business on a moderate multiple ranks ahead of a mediocre one on a low
    # multiple -- which is what separates genuine value from a value trap.
    pe_universe = sorted(c[6] for c in candidates)
    peg_universe = sorted((c[6] / c[3]) for c in candidates if c[3] > 0)

    qualified = []
    for s, ltp, mc, roe, npm, de, pe, vol, total_score in candidates:
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

        # ── 2. STRICT PENNY ENTRY SCORE (0 - 100) ──────────────────────────────────────
        e_pts = 0.0
        ema20 = float(s.get("ema20") or 0)
        sr_sup = float(s.get("sup_level") or 0)
        low20 = float(s.get("low20") or 0)
        ma50 = float(s.get("ma50") or 0)

        auto_gtt = ema20 if (0 < ema20 < ltp) else sr_sup if (0 < sr_sup < ltp) else low20 if (0 < low20 < ltp) else ma50 if (0 < ma50 < ltp) else ltp
        dist_gtt_pct = ((ltp - auto_gtt) / auto_gtt) * 100.0 if (auto_gtt > 0 and ltp > 0) else 99.0
        dist_ema = abs((ltp - ema20) / ema20) * 100.0 if (ema20 > 0 and ltp > 0) else 99.0

        # Strict GTT Proximity (Max 40 pts) - Only award high points if within 3.5% of GTT support
        if dist_gtt_pct <= 1.5: e_pts += 40.0
        elif dist_gtt_pct <= 3.5: e_pts += 30.0
        elif dist_gtt_pct <= 6.0: e_pts += 15.0
        else: e_pts += 0.0

        # Strict EMA20 Proximity (Max 30 pts)
        if dist_ema <= 2.0: e_pts += 30.0
        elif dist_ema <= 4.0: e_pts += 20.0
        elif dist_ema <= 7.0: e_pts += 10.0
        else: e_pts += 0.0

        # RSI Sweet Spot 45-60 (Max 20 pts)
        rsi = float(s.get("rsi") or 50.0)
        if 45 <= rsi <= 58: e_pts += 20.0
        elif 40 <= rsi <= 65: e_pts += 10.0
        else: e_pts += 0.0

        # Intraday Inflow (Max 10 pts)
        cmf = float(s.get("cmf") or 0.0)
        if cmf > 0.05: e_pts += 10.0

        penny_entry_score = round(min(100.0, max(0.0, e_pts)), 1)

        # ── 3. PENNY VALUE SCORE (0 - 100) ─────────────────────────────────────
        # Scored by rank within this scan's qualifying universe, not against fixed
        # multiples: "cheap" only means anything relative to what else is on offer,
        # and a percentile re-baselines itself as the market re-rates.
        pe_rank = percentile_rank(pe_universe, pe)            # 0 = cheapest
        v_pts = (1.0 - pe_rank) * 60.0

        # Quality-adjusted multiple (P/E per unit of ROE). This is what separates a
        # genuinely cheap good business from a value trap -- a low multiple earned
        # by weak returns scores no better than a fair multiple on strong ones.
        if roe > 0:
            peg_rank = percentile_rank(peg_universe, pe / roe)
            v_pts += (1.0 - peg_rank) * 40.0
        else:
            v_pts += 20.0                                     # neutral, not rewarded

        penny_value_score = round(min(100.0, max(0.0, v_pts)), 1)

        # ── 4. COMBINED PENNY RANK SCORE & ACTION ──────────────────────────────
        # Durability leads, value is the second voice, entry timing only breaks ties
        # -- a well-timed entry into a poor business should never outrank a sound one.
        penny_rank_score = round(
            (penny_quality_score * 0.45) + (penny_value_score * 0.30) + (penny_entry_score * 0.25), 1
        )

        if penny_quality_score >= 70:
            # Strict Buy Now Gate: Entry Score >= 70 AND price within 3.5% of GTT support
            if penny_entry_score >= 70.0 and dist_gtt_pct <= 3.5:
                status = "BUY_NOW"
                status_badge = "🟢 START SIP NOW"
                status_badge_class = "badge-green"
                status_reason = f"High durability ({penny_quality_score:.0f}/100) at strict GTT entry ({dist_gtt_pct:.1f}% from GTT ₹{auto_gtt:.2f})"
            else:
                status = "WAIT"
                status_badge = "🟢 SIP ON DIP / RETEST"
                status_badge_class = "badge-green"
                status_reason = f"Top quality micro-cap ({penny_quality_score:.0f}/100) — currently +{dist_gtt_pct:.1f}% above GTT. Wait for dip to ₹{auto_gtt:.2f}"
        elif penny_quality_score >= 50:
            status = "WATCHING"
            status_badge = "🟡 WATCHLIST"
            status_badge_class = "badge-yellow"
            status_reason = f"Developing micro-cap ({penny_quality_score:.0f}/100) — monitor earnings growth"
        else:
            status = "REJECT"
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
        item["penny_value_score"] = penny_value_score
        item["penny_rank_score"] = penny_rank_score
        item["pe"] = pe
        item["pe_percentile"] = round(pe_rank * 100, 1)
        item["monthly_sip_qty"] = sip_qty
        item["monthly_sip_cost"] = sip_cost
        item["durability_tag"] = durability_tag
        item["durability_class"] = "badge-green" if penny_quality_score >= 70 else "badge-yellow"
        item["status_badge"] = status_badge
        item["status_badge_class"] = status_badge_class
        item["status_reason"] = status_reason
        item["status"] = status
        item["auto_gtt"] = auto_gtt
        item["dist_from_gtt_pct"] = dist_from_gtt_pct
        qualified.append(item)

    # Rank on the combined score so valuation actually influences selection; sorting
    # on quality alone would have made the new value component decorative.
    qualified.sort(key=lambda x: x["penny_rank_score"], reverse=True)
    return qualified[:top_n]


def evaluate_incumbent_status(scored_match: dict) -> dict:
    """
    Evaluates an incumbent stock's status based on 7 Output Actions from the Final Implementation Brief:
    - KEEP_QUALIFIED: Business quality & trend meet ownership standards.
    - IMPROVING_MONITOR: Fundamentals improving, but durability/risk needs monitoring.
    - CYCLICAL_OPPORTUNITY: Favorable cycle/trend & valuation in cyclical sector.
    - FUNDAMENTAL_REVIEW: Weak/uncertain quality, but no confirmed deterioration.
    - REPLACE_CANDIDATE: Weak Structural Quality AND deteriorating Fundamental Trend, or severe leverage.
    - WAIT_DO_NOT_CHASE: Strong business but extended valuation.
    - WATCHLIST: Attractive valuation but insufficient quality/trend confirmation.
    """
    q_score = scored_match["lt_quality_score"]
    t_score = scored_match.get("fundamental_trend_score", 50.0)
    sec_group = scored_match.get("sector_group", "QUALITY_GROWTH")
    val_status = scored_match.get("lt_valuation_status", "FAIRLY_VALUED")
    cyc_flag = scored_match.get("cyclicality_flag", "LOW")
    cyc_pos = scored_match.get("cycle_position", "STABLE_NON_CYCLICAL")
    trend_drv = scored_match.get("trend_driver", "STRUCTURAL")
    de = float(scored_match.get("de_ratio") if scored_match.get("de_ratio") is not None else 0.0)

    if q_score >= 75.0 and t_score >= 45.0:
        if val_status == "EXTENDED":
            inc_status = "WAIT_DO_NOT_CHASE"
            badge = "🟠 WAIT / DO NOT CHASE"
            badge_class = "badge-orange"
            reason = f"Top quality business ({q_score:.0f}/100) — extended valuation ({val_status}); wait for dip"
        else:
            inc_status = "KEEP_QUALIFIED"
            badge = "🟢 KEEP / QUALIFIED"
            badge_class = "badge-green"
            reason = f"Maintains top structural quality ({q_score:.0f}/100) & stable trend ({t_score:.0f}/100)"
    elif q_score >= 50.0 and t_score >= 65.0:
        inc_status = "IMPROVING_MONITOR"
        badge = "🟢 IMPROVING / MONITOR"
        badge_class = "badge-green"
        reason = f"Improving fundamental trend ({t_score:.0f}/100) with moderate quality ({q_score:.0f}/100)"
    elif cyc_flag in ("HIGH", "MODERATE") and t_score >= 50.0 and val_status in ("UNDERVALUED", "FAIRLY_VALUED"):
        inc_status = "CYCLICAL_OPPORTUNITY"
        badge = "🟡 CYCLICAL OPPORTUNITY"
        badge_class = "badge-yellow"
        reason = f"Cyclical opportunity ({sec_group}, {cyc_pos}) — trend: {t_score:.0f}/100 ({trend_drv}), valuation: {val_status}"
    elif (q_score < 55.0 and t_score < 45.0) or (sec_group != "BFSI" and de > 1.8):
        inc_status = "REPLACE_CANDIDATE"
        badge = "🔴 REPLACE CANDIDATE"
        badge_class = "badge-red"
        reason = f"Deteriorating fundamentals (Trend: {t_score:.0f}/100, Quality: {q_score:.0f}/100) — material weakness confirmed"
    elif val_status == "UNDERVALUED" and q_score < 50.0:
        inc_status = "WATCHLIST"
        badge = "⚪ WATCHLIST"
        badge_class = "badge-gray"
        reason = f"Attractive valuation ({val_status}) but insufficient quality confirmation ({q_score:.0f}/100)"
    else:
        inc_status = "FUNDAMENTAL_REVIEW"
        badge = "🟡 FUNDAMENTAL REVIEW"
        badge_class = "badge-yellow"
        reason = f"Structural quality ({q_score:.0f}/100) — fundamental trend stable ({t_score:.0f}/100); hold for review"

    return {
        "incumbent_status": inc_status,
        "incumbent_badge": badge,
        "incumbent_badge_class": badge_class,
        "incumbent_reason": reason
    }


def run_lt_universe_discovery_pipeline(screener_results: list[dict], watchlist_items: list[dict]) -> dict:
    """
    Executes the 4-Stage LT Discovery & Incumbent Audit Pipeline across all 2,414 NSE stocks.
    Incumbents compete side-by-side on the exact same objective, sector-aware criteria as new candidates.
    """
    if not screener_results:
        return {"incumbents_audit": [], "top_challengers": []}

    incumbent_symbols = {w.get("symbol") for w in watchlist_items if isinstance(w, dict) and w.get("symbol")} if watchlist_items else set()

    all_eval = []
    for s in screener_results:
        if isinstance(s, dict) and s.get("symbol"):
            eval_res = compute_sector_aware_lt_quality(s)
            item = dict(s)
            item.update(eval_res)
            all_eval.append(item)

    all_eval.sort(key=lambda x: x.get("lt_quality_score", 0), reverse=True)

    # Incumbent Audit & Classification using 7-status output actions from Final Brief
    incumbents_audit = []
    for w in (watchlist_items or []):
        sym = w.get("symbol")
        if not sym:
            continue
        scored_match = next((x for x in all_eval if x.get("symbol") == sym), None)
        if scored_match:
            rank = all_eval.index(scored_match) + 1
            audit_res = evaluate_incumbent_status(scored_match)

            item = dict(w)
            item.update(scored_match)
            item.update(audit_res)
            item["universe_rank"] = rank
            incumbents_audit.append(item)

    # Top New Universe Challengers (Non-incumbents)
    top_challengers = []
    for x in all_eval:
        if x.get("symbol") not in incumbent_symbols and x.get("lt_quality_score", 0) >= 75.0:
            rank = all_eval.index(x) + 1
            item = dict(x)
            item["incumbent_status"] = "NEW_DISCOVERY"
            item["incumbent_badge"] = "⚡ NEW QUALITY DISCOVERY"
            item["incumbent_badge_class"] = "badge-purple"
            item["incumbent_reason"] = f"Discovered from 2,414 NSE universe — Rank #{rank} (Quality: {x['lt_quality_score']:.0f}/100)"
            item["universe_rank"] = rank
            top_challengers.append(item)
            if len(top_challengers) >= 15:
                break

    return {
        "incumbents_audit": incumbents_audit,
        "top_challengers": top_challengers,
        "all_ranked_count": len(all_eval)
    }


def select_monthly_lt_watchlist_additions(screener_results: list[dict], existing_symbols: set,
                                           top_n: int = 15, max_price: float = 600.0) -> list[dict]:
    """
    Selects top_n stocks to be ADDED as real LT watchlist entries for a locked
    monthly cohort — these become actual lt_watchlist.json entries and flow
    through the exact same get_lt_watchlist_status() BUY_NOW / ACCUMULATE_ON_DIP
    / WAIT / WATCHLIST gate as every other tracked stock (auto GTT trailing,
    entry-timing score, the works). This function only decides WHICH stocks
    join the watchlist, not how they're subsequently classified — that's
    already handled by the existing gate logic, unchanged.

    Ranks by a 70/30 blend of fundamental quality (compute_sector_aware_lt_
    quality's lt_quality_score) and momentum (score_stock's existing momentum
    sub-score) — quality leads since this is a long-term hold, momentum breaks
    ties and favors names already showing price strength. Requires
    lt_quality_score >= 70, matching the same threshold get_lt_watchlist_status
    itself uses to grant BUY_NOW/ACCUMULATE_ON_DIP eligibility, so nothing gets
    added that wouldn't already qualify once it's in the watchlist. Adds a
    liquidity floor (a high score on a thinly-traded microcap reflects noisy,
    sparse fundamentals, not real quality) and an LTP ceiling (max_price).
    Excludes symbols already tracked, since the point is fresh ideas.
    """
    if not screener_results:
        return []

    MIN_LIQUIDITY = 100_000  # lighter than the Intraday tab's traded-value floor —
                              # an LT hold doesn't need same-day exit liquidity, just
                              # enough to not be a delisting/manipulation risk.
    MIN_PRICE = 20.0

    candidates = []
    for s in screener_results:
        if not isinstance(s, dict):
            continue
        sym = s.get("symbol")
        if not sym or sym in existing_symbols:
            continue
        ltp = s.get("ltp") or 0
        if ltp < MIN_PRICE or ltp > max_price:
            continue
        liquidity = s.get("avg_volume_10d") or s.get("today_volume") or 0
        if liquidity < MIN_LIQUIDITY:
            continue

        eval_res = compute_sector_aware_lt_quality(s)
        quality = eval_res.get("lt_quality_score", 0)
        if quality < 70.0:
            continue

        momentum = float(s.get("momentum") or 0)
        item = dict(s)
        item.update(eval_res)
        item["combined_rank_score"] = round(quality * 0.7 + momentum * 0.3, 2)
        candidates.append(item)

    candidates.sort(key=lambda x: x["combined_rank_score"], reverse=True)
    return candidates[:top_n]


