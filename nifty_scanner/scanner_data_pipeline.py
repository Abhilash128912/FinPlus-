import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import time

from nifty_tickers import get_nifty500_tickers
from scanner_database import init_scanner_db, save_stock_to_cache

def compute_rsi(series: pd.Series, period: int = 14) -> float:
    """
    Computes standard Wilder's smoothed RSI (14-day) using pandas.
    """
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

def fetch_single_stock_metrics(ticker: str, nifty_df_3m: float) -> dict:
    """
    Queries yfinance for a single stock ticker to retrieve technical price series
    and fundamental balance sheet ratios, computing the composite 100-point score.
    """
    try:
        # Load ticker info
        stock = yf.Ticker(ticker)
        
        # 1. Technical Price History (Fetch 1 Year of daily prices)
        hist = stock.history(period="1y", interval="1d")
        if hist.empty or len(hist) < 30:
            return None
            
        last_price = float(hist["Close"].iloc[-1])
        
        # Compute technical moving averages
        series_close = hist["Close"]
        ema20 = float(series_close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(series_close.ewm(span=50, adjust=False).mean().iloc[-1])
        sma200 = float(series_close.rolling(window=min(200, len(series_close))).mean().iloc[-1]) if len(series_close) >= 200 else float(series_close.mean())
        
        # Computes % deviations
        price_vs_20ema = ((last_price - ema20) / ema20) * 100
        price_vs_50ema = ((last_price - ema50) / ema50) * 100
        price_vs_200sma = ((last_price - sma200) / sma200) * 100
        
        # Volume ratio (5d avg vs 20d avg)
        series_vol = hist["Volume"]
        vol_5d = float(series_vol.iloc[-5:].mean())
        vol_20d = float(series_vol.iloc[-20:].mean())
        vol_ratio = vol_5d / vol_20d if vol_20d > 0 else 1.0
        
        # 3-Month return relative to Nifty 50
        # Check if we have 3 months of historical close
        idx_3m = -min(63, len(series_close))  # 63 trading days is approx 3 months
        price_3m = float(series_close.iloc[idx_3m])
        stock_3m_ret = ((last_price - price_3m) / price_3m) * 100
        rel_strength_3m = stock_3m_ret - nifty_df_3m
        
        # RSI 14
        rsi = compute_rsi(series_close)
        
        # 2. Fundamental Ratios
        info = stock.info
        company_name = info.get("longName", ticker)
        sector = info.get("sector", "Other")
        
        # Market Cap in Crores (Divide by 10,000,000 to convert from Rupees to Crores)
        mcap = info.get("marketCap", 0.0)
        mcap_cr = (mcap / 10000000.0) if mcap else 0.0
        
        pe = info.get("trailingPE")
        pb = info.get("priceToBook")
        div_yield = info.get("dividendYield", 0.0)
        if div_yield:
            div_yield = div_yield * 100.0  # convert decimal to %
            
        debt_to_equity = info.get("debtToEquity")
        if debt_to_equity:
            debt_to_equity = debt_to_equity / 100.0  # yfinance returns debt to equity as % in some cases (e.g. 50 instead of 0.5)
            if debt_to_equity > 10.0:  # Safety guard check
                debt_to_equity = debt_to_equity / 10.0
        else:
            debt_to_equity = 0.0
            
        roe = info.get("returnOnEquity")
        if roe:
            roe = roe * 100.0  # convert to %
        else:
            roe = 0.0
            
        # ROCE - yfinance does not always provide ROCE, so we approximate using returnOnAssets or set similar to ROE
        roce = info.get("returnOnAssets")
        if roce:
            roce = roce * 120.0  # Approximate factor
        else:
            roce = roe * 0.9 if roe else 0.0
            
        eps_growth_yoy = info.get("earningsGrowth", 0.0)
        if eps_growth_yoy:
            eps_growth_yoy = eps_growth_yoy * 100.0  # convert to %
            
        # Industry PE lookup fallback
        industry_pe = info.get("trailingPegRatio")
        if industry_pe and pe:
            industry_pe = pe / industry_pe
        else:
            industry_pe = 25.0  # Standard index average fallback
            
        # 3. Computing 100-Point Composite Score
        
        # A. Fundamental Score (Max 50 Points)
        f_score = 0.0
        # 1. ROE (15 points)
        if roe >= 20.0: f_score += 15.0
        elif roe >= 15.0: f_score += 10.0
        elif roe >= 10.0: f_score += 5.0
        
        # 2. Debt to Equity (15 points)
        if debt_to_equity == 0.0: f_score += 15.0
        elif debt_to_equity <= 0.5: f_score += 10.0
        elif debt_to_equity <= 1.0: f_score += 5.0
        
        # 3. ROCE (10 points)
        if roce >= 18.0: f_score += 10.0
        elif roce >= 12.0: f_score += 5.0
        
        # 4. EPS Growth YoY (10 points)
        if eps_growth_yoy >= 15.0: f_score += 10.0
        elif eps_growth_yoy >= 5.0: f_score += 5.0
        
        # B. Momentum Score (Max 50 Points)
        m_score = 0.0
        # 1. Relative Strength vs Nifty 50 (15 points)
        if rel_strength_3m >= 15.0: m_score += 15.0
        elif rel_strength_3m >= 5.0: m_score += 10.0
        elif rel_strength_3m >= -5.0: m_score += 5.0
        
        # 2. RSI 14 (15 points)
        if 55.0 <= rsi <= 70.0: m_score += 15.0
        elif rsi > 70.0: m_score += 10.0
        elif 40.0 <= rsi < 55.0: m_score += 5.0
        
        # 3. Moving Average Alignments (10 points)
        if last_price > ema20 > ema50 > sma200:
            m_score += 10.0
        elif last_price > ema50 > sma200:
            m_score += 5.0
            
        # 4. Volume Support (10 points)
        if vol_ratio >= 1.5: m_score += 10.0
        elif vol_ratio >= 1.0: m_score += 5.0
        
        total_score = f_score + m_score
        
        return {
            "ticker": ticker,
            "company_name": company_name,
            "sector": sector,
            "last_price": round(last_price, 2),
            "market_cap_cr": round(mcap_cr, 2),
            "pe_ratio": round(pe, 2) if pe else None,
            "industry_pe": round(industry_pe, 2) if industry_pe else None,
            "pb_ratio": round(pb, 2) if pb else None,
            "dividend_yield": round(div_yield, 2),
            "debt_to_equity": round(debt_to_equity, 2),
            "roe": round(roe, 2),
            "roce": round(roce, 2),
            "eps_growth_yoy": round(eps_growth_yoy, 2),
            "rsi_14": round(rsi, 2),
            "price_vs_20ema": round(price_vs_20ema, 2),
            "price_vs_50ema": round(price_vs_50ema, 2),
            "price_vs_200sma": round(price_vs_200sma, 2),
            "rel_strength_3m": round(rel_strength_3m, 2),
            "vol_ratio_5d_20d": round(vol_ratio, 2),
            "avg_volume_5d": round(vol_5d, 2),
            "fundamental_score": f_score,
            "momentum_score": m_score,
            "total_score": total_score,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
    except Exception as e:
        # Silently skip errors on tickers with zero volumes or bad API fields
        return None

def run_nifty500_scanner_pipeline(progress_callback=None):
    """
    Runs the complete scanning pipeline for all tickers in the Nifty 500 space.
    Calculates Nifty 50 index benchmarks first, then iterates over stocks.
    """
    init_scanner_db()
    
    # 1. Fetch Nifty 50 Index 3-Month Performance Benchmark
    nifty_df_3m = 0.0
    try:
        nifty = yf.Ticker("^NSEI")
        nifty_hist = nifty.history(period="1y", interval="1d")
        if not nifty_hist.empty:
            close_now = nifty_hist["Close"].iloc[-1]
            close_3m = nifty_hist["Close"].iloc[-min(63, len(nifty_hist))]
            nifty_df_3m = ((close_now - close_3m) / close_3m) * 100
    except Exception:
        pass
        
    # 2. Get active Nifty 500 tickers
    tickers = get_nifty500_tickers()
    total_tickers = len(tickers)
    
    success_count = 0
    for idx, ticker in enumerate(tickers):
        # Trigger progress callback if present (for Streamlit progress updates)
        if progress_callback:
            progress_callback(idx + 1, total_tickers, ticker)
            
        stock_data = fetch_single_stock_metrics(ticker, nifty_df_3m)
        if stock_data:
            save_stock_to_cache(stock_data)
            success_count += 1
            
        # Tiny sleep to avoid aggressive API hammering blocks
        time.sleep(0.05)
        
    return success_count
