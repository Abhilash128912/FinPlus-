"""
Daily-timeframe trend classification for all 4 instruments, reusing the
STOCK SCREENER APP's own compute_trend_classification() (screener_engine.py)
rather than inventing a second definition of "uptrend"/"downtrend" -- same
reuse pattern as intraday_candidate_gates_pass() and sr_volume.py elsewhere
in this app. That function needs daily ema20/ma50/ma200/rsi/volume_spike/
week_high_52, computed here from real daily history:

  - NIFTY/BANK NIFTY: the SPOT INDEX (not the futures contract) via
    INDmoney's 1day historical endpoint, up to its ~1-year cap. The spot
    index is used specifically because futures roll monthly, which would
    put a discontinuity in a 200-day moving average every ~20 trading days.
  - Crude Oil/Natural Gas: yfinance daily history on the NYMEX proxies
    (CL=F / NG=F), same "MCX tracks the NY price and we only need it for
    the general shape" reasoning already applied to the live signal cards,
    and already how the screener's own commodity panel computes its EMA
    crossover signal (fetch_commodity_signals() in fetch_and_build.py).

RSI here uses the exact same Wilder-smoothing formula as
detect_rsi_divergence() in screener_engine.py (ewm alpha=1/14), so a "RSI
48" here means the same thing it means on the equity screener.
"""
import sys

import pandas as pd
import yfinance as yf

SCREENER_APP_DIR = r"D:\STOCK SCREENER APP"

INDEX_SECURITY_IDS = {"NIFTY": "NSE_40000001", "BANKNIFTY": "NSE_40000003"}
COMMODITY_TICKERS = {"CRUDEOIL": "CL=F", "NATURALGAS": "NG=F"}


def _screener_engine():
    if SCREENER_APP_DIR not in sys.path:
        sys.path.insert(0, SCREENER_APP_DIR)
    import screener_engine as se
    return se


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-6)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    val = rsi_series.iloc[-1]
    return None if pd.isna(val) else float(val)


def _strip_zero_volume_tail(df: pd.DataFrame) -> pd.DataFrame:
    """Today's still-open daily bar often carries zero recorded volume --
    drop it so RSI/MA/volume-spike are judged on completed days only."""
    while len(df) > 1 and (df["Volume"].iloc[-1] or 0) <= 0:
        df = df.iloc[:-1]
    return df


def _metrics_from_daily(df: pd.DataFrame, live_ltp: float | None) -> dict | None:
    df = _strip_zero_volume_tail(df)
    if len(df) < 25:  # need at least enough for ema20 + a volume baseline to mean anything
        return None

    close = df["Close"]
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(df) >= 50 else None
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else None
    rsi = _rsi(close)
    vol_avg10 = float(df["Volume"].iloc[-10:].mean())
    vol_spike = float(df["Volume"].iloc[-1] / vol_avg10) if vol_avg10 > 0 else 1.0
    week_high_52 = float(df["High"].max())
    ltp = live_ltp if live_ltp is not None else float(close.iloc[-1])

    return {
        "ltp": ltp, "ema20": round(ema20, 2), "ma50": round(ma50, 2) if ma50 else None,
        "ma200": round(ma200, 2) if ma200 else None, "rsi": round(rsi, 1) if rsi is not None else None,
        "volume_spike": round(vol_spike, 2), "week_high_52": round(week_high_52, 2),
        "days_available": len(df),
    }


def get_index_trend(underlying: str, live_ltp: float | None = None) -> dict:
    """underlying: 'NIFTY' or 'BANKNIFTY'."""
    import indmoney_feed
    df = indmoney_feed.get_daily_candles(INDEX_SECURITY_IDS[underlying])
    if df.empty:
        return {"available": False, "reason": "no daily history returned"}

    metrics = _metrics_from_daily(df, live_ltp)
    if metrics is None:
        return {"available": False, "reason": "not enough completed daily bars"}

    se = _screener_engine()
    result = se.compute_trend_classification(metrics)
    return {"available": True, **result, **metrics}


def get_commodity_trend(mcx_symbol: str, live_ltp_usd: float | None = None) -> dict:
    """mcx_symbol: 'CRUDEOIL' or 'NATURALGAS'. live_ltp_usd, if given, should
    be the NYMEX-quoted price (not the MCX INR price) -- this trend view
    runs entirely on the NYMEX proxy series, so mixing in an INR price
    would silently misclassify every level."""
    ticker = COMMODITY_TICKERS[mcx_symbol]
    df = yf.Ticker(ticker).history(period="2y", interval="1d")
    if df.empty:
        return {"available": False, "reason": f"yfinance returned no daily data for {ticker}"}

    metrics = _metrics_from_daily(df, live_ltp_usd)
    if metrics is None:
        return {"available": False, "reason": "not enough completed daily bars"}

    se = _screener_engine()
    result = se.compute_trend_classification(metrics)
    return {"available": True, **result, **metrics}


def get_equity_trend(symbol: str, live_ltp: float | None = None) -> dict:
    """symbol: e.g. 'RELIANCE'."""
    sym = symbol.upper().strip()
    import indmoney_feed
    scrip = "NSE_2885" if sym == "RELIANCE" else f"NSE_{indmoney_feed._get_equity_security_id(sym)}"
    df = indmoney_feed.get_daily_candles(scrip)
    if df.empty:
        df = yf.Ticker(f"{sym}.NS").history(period="2y", interval="1d")
        if df.empty:
            return {"available": False, "reason": f"no daily history returned for {sym}"}

    metrics = _metrics_from_daily(df, live_ltp)
    if metrics is None:
        return {"available": False, "reason": "not enough completed daily bars"}

    se = _screener_engine()
    result = se.compute_trend_classification(metrics)
    return {"available": True, **result, **metrics}


if __name__ == "__main__":
    with open("indmoney.env", encoding="utf-8") as f:
        for line in f:
            if line.startswith("INDMONEY_ACCESS_TOKEN="):
                import os
                os.environ["INDMONEY_ACCESS_TOKEN"] = line.strip().split("=", 1)[1]

    for u in ("NIFTY", "BANKNIFTY"):
        print(u, get_index_trend(u))
    for c in ("CRUDEOIL", "NATURALGAS"):
        print(c, get_commodity_trend(c))
    print("RELIANCE", get_equity_trend("RELIANCE"))
