import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import os
import time

from nifty_tickers import get_nifty500_tickers
from scanner_database import init_scanner_db, save_stock_to_cache


# ─────────────────────────────────────────────────────────────────────────────
# Technical Indicator Functions
# ─────────────────────────────────────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = 14) -> float:
    """Wilder's smoothed RSI."""
    if len(series) < period + 1:
        return 50.0
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ema_up / ema_down
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def compute_adx(hist: pd.DataFrame, period: int = 14) -> tuple:
    """
    Average Directional Index (ADX) with +DI / -DI.
    ADX > 25 = trending market.  ADX < 20 = choppy / sideways.
    Returns (adx, plus_di, minus_di).
    """
    try:
        high  = hist["High"]
        low   = hist["Low"]
        close = hist["Close"]

        if len(close) < period * 2:
            return 20.0, 25.0, 25.0

        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high  - prev_close).abs(),
            (low   - prev_close).abs()
        ], axis=1).max(axis=1)

        up_move   = high.diff()
        down_move = -low.diff()
        plus_dm   = pd.Series(
            np.where((up_move > down_move)   & (up_move   > 0), up_move,   0.0),
            index=close.index)
        minus_dm  = pd.Series(
            np.where((down_move > up_move)   & (down_move > 0), down_move, 0.0),
            index=close.index)

        alpha = 1 / period
        atr_s    = tr.ewm(alpha=alpha, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s
        minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_s

        dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.fillna(0).ewm(alpha=alpha, adjust=False).mean()

        return float(adx.iloc[-1]), float(plus_di.iloc[-1]), float(minus_di.iloc[-1])
    except Exception:
        return 20.0, 25.0, 25.0


def compute_macd(close: pd.Series,
                 fast: int = 12, slow: int = 26, signal_period: int = 9) -> tuple:
    """
    MACD line, signal line, histogram and crossover label.
    Returns (macd_val, signal_val, histogram, signal_label).
    Labels: 'Bullish Crossover' | 'Bullish' | 'Bearish Crossover' | 'Bearish'
    """
    try:
        if len(close) < slow + signal_period:
            return 0.0, 0.0, 0.0, "Neutral"

        ema_fast    = close.ewm(span=fast,   adjust=False).mean()
        ema_slow    = close.ewm(span=slow,   adjust=False).mean()
        macd_line   = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram   = macd_line - signal_line

        curr_hist = float(histogram.iloc[-1])
        prev_hist = float(histogram.iloc[-2]) if len(histogram) >= 2 else 0.0

        if prev_hist <= 0 and curr_hist > 0:
            label = "Bullish Crossover"
        elif prev_hist >= 0 and curr_hist < 0:
            label = "Bearish Crossover"
        elif curr_hist > 0:
            label = "Bullish"
        else:
            label = "Bearish"

        return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), curr_hist, label
    except Exception:
        return 0.0, 0.0, 0.0, "Neutral"


def compute_atr(hist: pd.DataFrame, period: int = 14) -> float:
    """Average True Range — raw rupee volatility per bar."""
    try:
        high  = hist["High"]
        low   = hist["Low"]
        close = hist["Close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high  - prev_close).abs(),
            (low   - prev_close).abs()
        ], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        return float(atr.iloc[-1])
    except Exception:
        return 0.0


def compute_piotroski_score(info: dict) -> int:
    """
    Modified 9-point Piotroski F-Score using yfinance info dict.
    7–9 = High quality  |  0–3 = Deteriorating / avoid.
    """
    score = 0
    try:
        # ── Profitability ────────────────────────────────────────────────────
        roa = float(info.get("returnOnAssets") or 0)
        if roa > 0:
            score += 1                               # P1: ROA positive

        ocf = float(info.get("operatingCashflow") or 0)
        if ocf > 0:
            score += 1                               # P2: OCF positive

        earnings_growth = float(info.get("earningsGrowth") or 0)
        if earnings_growth > 0:
            score += 1                               # P3: ROA improving (proxy)

        # P4: Accrual quality — OCF / Assets > ROA
        total_assets = float(info.get("totalAssets") or 1) or 1
        if total_assets > 0 and (ocf / total_assets) > roa:
            score += 1

        # ── Leverage / Liquidity ─────────────────────────────────────────────
        de = float(info.get("debtToEquity") or 100)  # yfinance returns %, e.g. 50 = 0.5x
        if de < 50:                                  # < 0.5x real ratio
            score += 1                               # P5: Low leverage

        cr = float(info.get("currentRatio") or 0)
        if cr > 1.2:
            score += 1                               # P6: Healthy liquidity

        # P7: No dilution proxy — revenue growing means no distress issuance
        rev_growth = float(info.get("revenueGrowth") or 0)
        if rev_growth > 0:
            score += 1

        # ── Operating Efficiency ─────────────────────────────────────────────
        gross_margin = float(info.get("grossMargins") or 0)
        if gross_margin > 0.15:
            score += 1                               # P8: Margin quality

        if rev_growth > 0.05:
            score += 1                               # P9: Asset turnover improving

    except Exception:
        pass

    return min(score, 9)


def compute_bollinger_squeeze(close: pd.Series, period: int = 20) -> tuple:
    """
    Detects Bollinger Band squeeze — compressed volatility precedes large moves.
    Returns (is_squeeze: bool, bb_width_pct: float).
    """
    try:
        if len(close) < period * 3:
            return False, 5.0

        roll_mean = close.rolling(period).mean()
        roll_std  = close.rolling(period).std()
        bb_width  = ((roll_mean + 2 * roll_std - (roll_mean - 2 * roll_std))
                     / roll_mean * 100).dropna()

        if len(bb_width) < 2:
            return False, 5.0

        curr_width  = float(bb_width.iloc[-1])
        lookback    = min(126, len(bb_width))
        min_6m      = float(bb_width.iloc[-lookback:].min())
        is_squeeze  = curr_width < min_6m * 1.15   # within 15% of 6m low width

        return is_squeeze, round(curr_width, 2)
    except Exception:
        return False, 5.0


# ─────────────────────────────────────────────────────────────────────────────
# Main Per-Ticker Metrics Function
# ─────────────────────────────────────────────────────────────────────────────

def fetch_single_stock_metrics(ticker: str, nifty_df_3m: float) -> dict:
    """
    Fetches and computes the full enhanced metric set for one ticker:
    - RSI, EMA, SMA, Volume Ratio (existing)
    - ADX, MACD, ATR, Bollinger Squeeze (new)
    - Piotroski F-Score (new)
    - Breakout detection (new)
    - ATR-based trade signal: Entry / Stop Loss / T1 / T2 / R:R (new)
    - Enhanced 100-pt composite score with ADX gate (new)
    - Conviction label (new)
    """
    try:
        stock = yf.Ticker(ticker)

        # ── Price History ───────────────────────────────────────────────────
        hist = stock.history(period="1y", interval="1d")
        if hist.empty or len(hist) < 30:
            return None

        last_price   = float(hist["Close"].iloc[-1])
        series_close = hist["Close"]

        ema20  = float(series_close.ewm(span=20,  adjust=False).mean().iloc[-1])
        ema50  = float(series_close.ewm(span=50,  adjust=False).mean().iloc[-1])
        sma200 = (float(series_close.rolling(window=min(200, len(series_close))).mean().iloc[-1])
                  if len(series_close) >= 200 else float(series_close.mean()))

        price_vs_20ema  = ((last_price - ema20)  / ema20)  * 100
        price_vs_50ema  = ((last_price - ema50)  / ema50)  * 100
        price_vs_200sma = ((last_price - sma200) / sma200) * 100

        series_vol = hist["Volume"]
        vol_5d     = float(series_vol.iloc[-5:].mean())
        vol_20d    = float(series_vol.iloc[-20:].mean())
        vol_ratio  = vol_5d / vol_20d if vol_20d > 0 else 1.0

        idx_3m        = -min(63, len(series_close))
        price_3m      = float(series_close.iloc[idx_3m])
        stock_3m_ret  = ((last_price - price_3m) / price_3m) * 100
        rel_strength_3m = stock_3m_ret - nifty_df_3m

        rsi = compute_rsi(series_close)

        # ── New Technical Indicators ────────────────────────────────────────
        adx, plus_di, minus_di = compute_adx(hist)
        macd_val, macd_sig_val, macd_hist, macd_signal = compute_macd(series_close)
        atr = compute_atr(hist)

        high_52w  = float(hist["High"].max())
        low_52w   = float(hist["Low"].min())
        proximity_52w_high_pct = ((last_price - high_52w) / high_52w) * 100

        # Breakout: price within 3% of 52-week high AND volume surge ≥ 1.8×
        is_breakout = (proximity_52w_high_pct >= -3.0) and (vol_ratio >= 1.8)

        bb_squeeze, bb_width_pct = compute_bollinger_squeeze(series_close)

        # ── Fundamentals ────────────────────────────────────────────────────
        info = stock.info
        company_name = info.get("longName", ticker)
        sector       = info.get("sector", "Other")

        mcap    = info.get("marketCap", 0.0)
        mcap_cr = (mcap / 10_000_000.0) if mcap else 0.0

        pe  = info.get("trailingPE")
        pb  = info.get("priceToBook")
        div_yield = info.get("dividendYield", 0.0)
        if div_yield:
            div_yield *= 100.0

        debt_to_equity = info.get("debtToEquity")
        if debt_to_equity:
            debt_to_equity = debt_to_equity / 100.0
            if debt_to_equity > 10.0:
                debt_to_equity /= 10.0
        else:
            debt_to_equity = 0.0

        roe = info.get("returnOnEquity")
        roe = (roe * 100.0) if roe else 0.0

        roce = info.get("returnOnAssets")
        roce = (roce * 120.0) if roce else (roe * 0.9 if roe else 0.0)

        eps_growth_yoy = info.get("earningsGrowth", 0.0)
        if eps_growth_yoy:
            eps_growth_yoy *= 100.0

        industry_pe = info.get("trailingPegRatio")
        if industry_pe and pe:
            industry_pe = pe / industry_pe
        else:
            industry_pe = 25.0

        piotroski = compute_piotroski_score(info)

        # ── Enhanced Composite Score ─────────────────────────────────────────
        # Fundamental (max 50 pts)
        f_score = 0.0

        if roe >= 20.0:    f_score += 12.0
        elif roe >= 15.0:  f_score += 8.0
        elif roe >= 10.0:  f_score += 4.0

        if debt_to_equity == 0.0:      f_score += 12.0
        elif debt_to_equity <= 0.5:    f_score += 8.0
        elif debt_to_equity <= 1.0:    f_score += 4.0

        if roce >= 18.0:   f_score += 8.0
        elif roce >= 12.0: f_score += 4.0

        if eps_growth_yoy >= 15.0:  f_score += 8.0
        elif eps_growth_yoy >= 5.0: f_score += 4.0

        if piotroski >= 7:   f_score += 10.0
        elif piotroski >= 5: f_score +=  6.0
        elif piotroski >= 3: f_score +=  3.0

        # Momentum (max 50 pts, before ADX gate)
        m_score = 0.0

        if rel_strength_3m >= 15.0:   m_score += 13.0
        elif rel_strength_3m >= 5.0:  m_score +=  9.0
        elif rel_strength_3m >= -5.0: m_score +=  4.0

        if 55.0 <= rsi <= 70.0: m_score += 12.0
        elif rsi > 70.0:        m_score +=  8.0
        elif 40.0 <= rsi < 55.0:m_score +=  4.0

        if last_price > ema20 > ema50 > sma200: m_score += 9.0
        elif last_price > ema50 > sma200:        m_score += 5.0

        if vol_ratio >= 1.5: m_score += 10.0
        elif vol_ratio >= 1.0:m_score += 5.0

        # MACD bonus (max 6 pts)
        if macd_signal   == "Bullish Crossover": m_score += 6.0
        elif macd_signal == "Bullish":            m_score += 4.0
        # Bearish Crossover / Bearish → 0 pts (no negative — just no bonus)

        # ADX Trend Strength Gate
        if adx < 20.0:
            m_score *= 0.70          # −30% in choppy/sideways markets
        elif adx >= 25.0:
            m_score = min(50.0, m_score * 1.05)   # +5% bonus in strong trend

        total_score = f_score + m_score

        # ── ATR-Based Trade Signal ────────────────────────────────────────────
        if atr > 0 and last_price > 0:
            entry_price = round(last_price, 2)
            sl_ema      = ema20 * 0.99             # 1% below 20 EMA
            sl_hard     = last_price * 0.93        # 7% hard stop
            stop_loss   = round(max(sl_ema, sl_hard), 2) if sl_ema < last_price else round(sl_hard, 2)
            target_1    = round(last_price + 2.0 * atr, 2)   # 1:2 R:R
            target_2    = round(last_price + 3.0 * atr, 2)   # 1:3 R:R
            risk_amt    = last_price - stop_loss
            reward_amt  = target_1 - last_price
            rr_ratio    = round(reward_amt / risk_amt, 2) if risk_amt > 0 else 0.0
        else:
            entry_price = round(last_price, 2)
            stop_loss   = round(last_price * 0.93, 2)
            target_1    = round(last_price * 1.05, 2)
            target_2    = round(last_price * 1.08, 2)
            rr_ratio    = 1.5

        # ── Conviction Label ─────────────────────────────────────────────────
        if total_score >= 82:   conviction_label = "Strong Buy"
        elif total_score >= 68: conviction_label = "Buy"
        elif total_score >= 52: conviction_label = "Watch"
        elif total_score >= 36: conviction_label = "Neutral"
        else:                   conviction_label = "Avoid"

        return {
            # Core
            "ticker":            ticker,
            "company_name":      company_name,
            "sector":            sector,
            "last_price":        round(last_price, 2),
            "market_cap_cr":     round(mcap_cr, 2),
            "pe_ratio":          round(pe, 2) if pe else None,
            "industry_pe":       round(industry_pe, 2) if industry_pe else None,
            "pb_ratio":          round(pb, 2) if pb else None,
            "dividend_yield":    round(div_yield, 2),
            "debt_to_equity":    round(debt_to_equity, 2),
            "roe":               round(roe, 2),
            "roce":              round(roce, 2),
            "eps_growth_yoy":    round(eps_growth_yoy, 2),
            "rsi_14":            round(rsi, 2),
            "price_vs_20ema":    round(price_vs_20ema, 2),
            "price_vs_50ema":    round(price_vs_50ema, 2),
            "price_vs_200sma":   round(price_vs_200sma, 2),
            "rel_strength_3m":   round(rel_strength_3m, 2),
            "vol_ratio_5d_20d":  round(vol_ratio, 2),
            "avg_volume_5d":     round(vol_5d, 2),
            # New indicators
            "adx_14":            round(adx, 2),
            "macd_signal":       macd_signal,
            "macd_histogram":    round(macd_hist, 4),
            "piotroski_score":   piotroski,
            "breakout_signal":   1 if is_breakout else 0,
            "proximity_52w_high_pct": round(proximity_52w_high_pct, 2),
            "atr_14":            round(atr, 2),
            "entry_price":       entry_price,
            "stop_loss":         stop_loss,
            "target_1":          target_1,
            "target_2":          target_2,
            "rr_ratio":          rr_ratio,
            "bb_squeeze":        1 if bb_squeeze else 0,
            "bb_width_pct":      bb_width_pct,
            "conviction_label":  conviction_label,
            # Scores
            "fundamental_score": round(f_score, 2),
            "momentum_score":    round(m_score, 2),
            "total_score":       round(total_score, 2),
            "last_updated":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_nifty500_scanner_pipeline(progress_callback=None):
    """
    Runs the full enhanced pipeline for all Nifty 500 tickers.
    """
    init_scanner_db()

    # Nifty 50 3-month benchmark
    nifty_df_3m = 0.0
    try:
        nifty_hist = yf.Ticker("^NSEI").history(period="1y", interval="1d")
        if not nifty_hist.empty:
            close_now = nifty_hist["Close"].iloc[-1]
            close_3m  = nifty_hist["Close"].iloc[-min(63, len(nifty_hist))]
            nifty_df_3m = ((close_now - close_3m) / close_3m) * 100
    except Exception:
        pass

    tickers      = get_nifty500_tickers()
    total_tickers = len(tickers)
    success_count = 0

    for idx, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(idx + 1, total_tickers, ticker)

        stock_data = fetch_single_stock_metrics(ticker, nifty_df_3m)
        if stock_data:
            save_stock_to_cache(stock_data)
            success_count += 1

        time.sleep(0.05)

    return success_count
