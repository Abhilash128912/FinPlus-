"""
screener_engine.py
Scores each stock on Strength, Value, Momentum (0-100 each).
All inputs come from yfinance .info dict + price history DataFrame.
No mock data — if a metric is missing, it is skipped and score is partial.
"""

import pandas as pd


def score_strength(info: dict) -> tuple[float, dict]:
    """
    Strength Score (0-100): Is the business fundamentally healthy?
    Returns (score, breakdown_dict)
    """
    breakdown = {}
    score = 0.0

    # 1. ROE > 15% → up to 25 pts
    roe = to_float(info.get("returnOnEquity"))
    if roe is not None:
        roe_pct = roe * 100
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
    wk52_pts = 0
    if wk52 is not None:
        wk52_pct = wk52 * 100
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

    # 4. RSI (14-day) between 40–70 → up to 15 pts
    rsi_pts = 0
    rsi_val = None
    if len(history) >= 15:
        delta = history["Close"].diff()
        gain = delta.clip(lower=0).tail(14).mean()
        loss = (-delta.clip(upper=0)).tail(14).mean()
        if loss and loss > 0:
            rs = gain / loss
            rsi_val = round(100 - (100 / (1 + rs)), 1)
            if 50 <= rsi_val <= 65:   rsi_pts = 15
            elif 45 <= rsi_val <= 70: rsi_pts = 12
            elif 40 <= rsi_val <= 75: rsi_pts = 6
            elif rsi_val > 75:        rsi_pts = 2
            else:                     rsi_pts = 2
    score += rsi_pts
    breakdown["rsi"] = rsi_val
    breakdown["rsi_pts"] = rsi_pts

    # 5. Volume Spike Ratio → up to 15 pts
    vol = info.get("volume") or info.get("regularMarketVolume") or 0
    avg_vol_10d = info.get("averageVolume10days") or info.get("averageDailyVolume10Day") or 0
    vol_spike = 0.0
    vol_pts = 0

    if vol > 0 and avg_vol_10d > 0:
        vol_spike = round(vol / avg_vol_10d, 2)
        if vol_spike >= 2.5:   vol_pts = 15
        elif vol_spike >= 1.8: vol_pts = 12
        elif vol_spike >= 1.2: vol_pts = 8
        elif vol_spike >= 0.9: vol_pts = 4
        else:                  vol_pts = 0
    
    score += vol_pts
    breakdown["volume_spike"] = vol_spike
    breakdown["volume_pts"] = vol_pts
    breakdown["today_volume"] = vol
    breakdown["avg_volume_10d"] = avg_vol_10d

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

    total = round((strength * 0.40) + (value * 0.35) + (momentum * 0.25), 1)

    current_price = (
        info.get("currentPrice") or
        info.get("regularMarketPrice") or
        info.get("previousClose") or 0
    )
    open_price = info.get("open") or info.get("regularMarketOpen")
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

    return {
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
        "ma50": m_break.get("ma50"),
        "ma200": m_break.get("ma200"),
        "wk52_return_pct": m_break.get("wk52_return_pct"),
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
    ma50 = scored.get("ma50")
    ma200 = scored.get("ma200")
    rsi = scored.get("rsi")
    vol_spike = scored.get("volume_spike", 1.0)
    wk52_h = scored.get("week_high_52")

    if ltp <= 0 or not ma200:
        return {"trend": "Consolidation", "badge": "🟡 Consolidation Phase", "class": "badge-yellow"}

    above_50 = (ma50 is not None and ltp >= ma50)
    above_200 = (ltp >= ma200)
    dist_52h_pct = ((ltp - wk52_h) / wk52_h * 100) if (wk52_h and wk52_h > 0) else -100

    # 🔴 Downtrend: Price below both 50MA and 200MA
    if not above_50 and not above_200:
        return {"trend": "Downtrend", "badge": "🔴 Downtrend", "class": "badge-red"}

    # 🟠 Distribution Phase: Near 52W High (within 10%) or above 50MA, but volume spike >= 1.2x & weakening RSI (<48)
    if (dist_52h_pct >= -10 or above_50) and vol_spike >= 1.2 and (rsi is not None and rsi < 48):
        return {"trend": "Distribution", "badge": "🟠 Distribution Phase", "class": "badge-yellow"}

    # 🔵 Accumulation Phase: Price above 200MA, volume spike >= 1.2x, healthy RSI (45-58)
    if above_200 and vol_spike >= 1.2 and (rsi is not None and 45 <= rsi <= 58):
        return {"trend": "Accumulation", "badge": "🔵 Accumulation Phase", "class": "badge-purple"}

    # 🟢 Strong Uptrend: Price > 50MA and Price > 200MA with strong RSI (>=50)
    if above_50 and above_200 and (rsi is None or rsi >= 50):
        return {"trend": "Uptrend", "badge": "🟢 Strong Uptrend", "class": "badge-green"}

    # 🟡 Consolidation Phase: Price consolidating near moving averages
    return {"trend": "Consolidation", "badge": "🟡 Consolidation Phase", "class": "badge-yellow"}


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
    Selects the optimal 7-day swing trade candidate based on:
    - Fundamental Quality (Score >= 55, qualified == True)
    - RSI Sweet Spot (45 - 65)
    - Volume Spike (>= 1.0)
    - Relative Strength Beta (0.8 - 1.8)
    - Moving Average Support (within 8% of 50 MA)
    Calculates automated Stop-Loss (SL), Target 1 (1:2 R:R), Target 2 (1:3 R:R).
    """
    if not screener_results:
        return {}

    candidates = []
    for s in screener_results:
        if not s.get("qualified") and s.get("total_score", 0) < 55:
            continue

        ltp = s.get("ltp", 0)
        rsi = s.get("rsi") or 50
        vol_spike = s.get("volume_spike") or 1.0
        beta = s.get("beta") or 1.0
        ma50 = s.get("ma50") or ltp

        dist_ma50_pct = ((ltp - ma50) / ma50) * 100 if ma50 > 0 else 0

        # Filter out overextended or extreme overbought stocks
        if rsi > 72 or rsi < 40:
            continue
        if dist_ma50_pct > 15 or dist_ma50_pct < -10:
            continue

        # Swing Scoring Bonus
        swing_score = s.get("total_score", 0)
        if 50 <= rsi <= 63:
            swing_score += 10
        if vol_spike >= 1.2:
            swing_score += 10
        if 1.0 <= beta <= 1.6:
            swing_score += 8

        candidates.append((swing_score, s))

    if not candidates:
        # Fallback to highest total score if strict criteria matches none
        candidates = [(s.get("total_score", 0), s) for s in screener_results if s.get("qualified")]
        if not candidates:
            candidates = [(s.get("total_score", 0), s) for s in screener_results]

    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]

    ltp = best.get("ltp", 0)
    ma50 = best.get("ma50") or (ltp * 0.96)

    # Stop Loss calculation: 4% below LTP or 2% below 50 MA (whichever is closer/safer)
    sl_price = round(max(ltp * 0.96, ma50 * 0.98), 2)
    risk = round(ltp - sl_price, 2)
    if risk <= 0:
        risk = round(ltp * 0.04, 2)
        sl_price = round(ltp - risk, 2)

    target1 = round(ltp + (2.0 * risk), 2)
    target2 = round(ltp + (3.0 * risk), 2)
    target1_pct = round(((target1 - ltp) / ltp) * 100, 1)
    target2_pct = round(((target2 - ltp) / ltp) * 100, 1)
    sl_pct = round(((sl_price - ltp) / ltp) * 100, 1)

    return {
        "symbol": best.get("symbol"),
        "ticker": best.get("ticker"),
        "name": best.get("name"),
        "sector": best.get("sector"),
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
        "tech_rating": best.get("tech_rating", "🟡 Consolidation"),
        "stop_loss": sl_price,
        "stop_loss_pct": sl_pct,
        "target1": target1,
        "target1_pct": target1_pct,
        "target2": target2,
        "target2_pct": target2_pct,
        "risk_amount": risk,
        "risk_reward_ratio": "1 : 2.0 (T1) / 1 : 3.0 (T2)",
        "timeframe": "3 to 7 Trading Days",
        "rationale": f"High quality ({best.get('total_score')}/100) with RSI {best.get('rsi')} in momentum accumulation zone, volume spike {best.get('volume_spike')}x, and Beta {best.get('beta')} relative strength."
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

    strike_iv = fno_cfg.get("strike_interval", 50)
    lot_size  = fno_cfg.get("lot_size", 50)

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
