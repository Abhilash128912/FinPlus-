"""
NYMEX intraday proxy history for the two MCX energy contracts.

The accuracy ceiling on the live crude/natgas signal was never the model --
it was the data feeding it. MCX publishes no intraday history at all, so
mcx_feed.py builds bars by sampling the live snapshot every few minutes and
folding them into hourly candles itself. That series starts thin (a seed of
~63 bars) and grows slowly, and sr_volume's pivot scan needs 20 bars either
side of a pivot: for the first several trading days the model can barely
find one qualifying level, so it stays silent or fires off a single stale
pivot.

yfinance, meanwhile, serves *real* intraday history for the NYMEX proxies
CL=F (WTI crude) and NG=F (Henry Hub gas) -- 60 days of 1h candles with
genuine traded volume. MCX crude is quoted in ₹/barrel and tracks WTI, MCX
natgas in ₹/mmBtu tracking Henry Hub; the units already match, so the only
conversion between the NYMEX price and the MCX price is USD/INR (plus a
small, slow-moving basis). trend_engine.py already relies on exactly this
proxy relationship for the daily trend. Scaling the deep NYMEX intraday
series by the live USD/INR rate gives the level model hundreds of real bars
to work from on day one instead of waiting a week to accumulate them.

This module never touches the MCX *price* shown to the user or used for
execution -- that stays the real, tradeable mcx_feed price. It only supplies
a richer bar series for finding levels, and a second-timeframe confluence
check, both clearly labelled as proxy-derived wherever they surface.
"""
from __future__ import annotations

import time

import pandas as pd
import yfinance as yf

PROXY_TICKERS = {"CRUDEOIL": "CL=F", "NATURALGAS": "NG=F"}

_FX_CACHE = {"rate": None, "at": 0.0}
_FX_TTL_SEC = 300.0
_FX_FALLBACK = 88.0


def get_usdinr_rate() -> float:
    """USD/INR, cached 5 min. Used only to scale the USD proxy series to an
    INR-comparable level -- never to price a trade -- so a stale-by-minutes
    rate or the conservative fallback is acceptable; what matters is not
    fetching FX on every signal pass. Mirrors app._get_usdinr_rate() rather
    than importing the Flask app into the engine layer."""
    now = time.time()
    if _FX_CACHE["rate"] is not None and (now - _FX_CACHE["at"]) < _FX_TTL_SEC:
        return _FX_CACHE["rate"]
    try:
        hist = yf.Ticker("USDINR=X").history(period="1d", interval="1m")
        rate = float(hist["Close"].iloc[-1]) if hist is not None and not hist.empty else _FX_FALLBACK
    except Exception:
        rate = _FX_CACHE["rate"] or _FX_FALLBACK
    _FX_CACHE["rate"] = rate
    _FX_CACHE["at"] = now
    return rate

# yfinance intraday cache. The frame is ~60 days of hourly bars (~1000 rows)
# and refetching it per signal pass is wasteful -- it only gains one new bar
# an hour. Cache per (ticker, interval) for a few minutes.
_CACHE: dict[tuple[str, str], dict] = {}
_TTL_SEC = 300.0


def _fetch(ticker: str, period: str, interval: str) -> pd.DataFrame | None:
    key = (ticker, interval)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached["at"]) < _TTL_SEC and cached["df"] is not None:
        return cached["df"]
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval)
        if df is None or df.empty:
            df = None
        else:
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "High", "Low", "Close"])
        _CACHE[key] = {"at": now, "df": df}
        return df
    except Exception as e:
        print(f"  [warn] yfinance intraday unavailable for {ticker} {interval}: {e}")
        return cached["df"] if cached else None


def proxy_bars_inr(mcx_symbol: str, usdinr_rate: float, interval: str = "60m",
                   period: str = "60d") -> pd.DataFrame | None:
    """Deep NYMEX intraday history for `mcx_symbol`, price-scaled to INR.

    Returns an OHLCV frame directly consumable by sr_volume.compute_signal,
    or None when the proxy feed is unavailable (caller must degrade to the
    MCX-only series, never invent bars). Volume is the proxy's real traded
    volume -- left unscaled, since sr_volume only ever compares volume to its
    own rolling average, so absolute units don't matter.
    """
    ticker = PROXY_TICKERS.get(mcx_symbol)
    if not ticker or not usdinr_rate or usdinr_rate <= 0:
        return None
    df = _fetch(ticker, period, interval)
    if df is None or df.empty:
        return None
    out = df.copy()
    for col in ("Open", "High", "Low", "Close"):
        out[col] = out[col] * float(usdinr_rate)
    return out


def day_change_pct(mcx_symbol: str) -> float | None:
    """The NYMEX proxy's latest daily % change (last close vs the prior day's
    close). This is the *commodity's* own day move in USD terms -- percentage
    change is scale-invariant, so it equals the move in INR before any FX
    drift, which is exactly what's needed to separate a real barrel/gas move
    from a rupee move. Returns None when daily history is unavailable."""
    ticker = PROXY_TICKERS.get(mcx_symbol)
    if not ticker:
        return None
    daily = _fetch(ticker, "5d", "1d")
    if daily is None or len(daily) < 2:
        return None
    closes = daily["Close"].dropna()
    if len(closes) < 2:
        return None
    prev, last = float(closes.iloc[-2]), float(closes.iloc[-1])
    return round((last - prev) / prev * 100.0, 2) if prev else None


def _basis(mcx_price: float | None, proxy_inr_last: float | None) -> float | None:
    """The residual gap between the real MCX price and the INR-scaled proxy
    close -- carry, expiry basis, and any FX staleness rolled together. Small
    and slow; reported so a level derived from the proxy can be nudged onto
    the MCX price scale rather than sitting a few rupees off."""
    if mcx_price is None or proxy_inr_last is None or proxy_inr_last <= 0:
        return None
    return float(mcx_price) - float(proxy_inr_last)


def enriched_bars(mcx_symbol: str, usdinr_rate: float, mcx_price: float | None,
                  interval: str = "60m") -> dict:
    """Proxy bar frame plus the basis needed to align it to the MCX price.

    Returns {"df": frame|None, "basis": float|None, "source": str}. When a
    basis is available every price column is shifted by it, so levels found
    on this frame land on the same scale as the live MCX quote the user
    trades against.
    """
    df = proxy_bars_inr(mcx_symbol, usdinr_rate, interval=interval)
    if df is None or df.empty:
        return {"df": None, "basis": None, "source": "unavailable"}
    proxy_last = float(df["Close"].iloc[-1])
    basis = _basis(mcx_price, proxy_last)
    if basis is not None:
        for col in ("Open", "High", "Low", "Close"):
            df[col] = df[col] + basis
    return {"df": df, "basis": basis, "source": f"NYMEX {PROXY_TICKERS[mcx_symbol]} @ {usdinr_rate:.2f} INR"}


def confluence(mcx_symbol: str, usdinr_rate: float, mcx_price: float | None,
               level: float | None, tolerance_pct: float = 0.4) -> dict:
    """Does a level found on the primary timeframe also show up on a higher
    NYMEX timeframe? A support/resistance that appears on both 1h and daily
    is defended by more participants and holds more often than a level only
    one timeframe sees.

    Checks the given `level` (already on the MCX price scale) against daily
    proxy swing highs/lows converted to INR. Returns a small dict with a
    boolean and the nearest higher-timeframe level, for strength weighting
    and display. Never fabricates confirmation when the proxy is unavailable
    -- it returns confirmed=False with reason, and the caller leaves the
    base strength untouched.
    """
    if level is None or not usdinr_rate:
        return {"confirmed": False, "reason": "no level or FX"}
    ticker = PROXY_TICKERS.get(mcx_symbol)
    if not ticker:
        return {"confirmed": False, "reason": "unknown symbol"}
    daily = _fetch(ticker, "6mo", "1d")
    if daily is None or len(daily) < 20:
        return {"confirmed": False, "reason": "no daily proxy history"}

    basis = _basis(mcx_price, float(daily["Close"].iloc[-1]) * usdinr_rate)
    shift = basis if basis is not None else 0.0

    # Simple swing points: local highs/lows over a 5-bar window on the daily.
    highs, lows = [], []
    h = daily["High"].values
    l = daily["Low"].values
    for i in range(3, len(daily) - 3):
        if h[i] == max(h[i - 3:i + 4]):
            highs.append(float(h[i]) * usdinr_rate + shift)
        if l[i] == min(l[i - 3:i + 4]):
            lows.append(float(l[i]) * usdinr_rate + shift)

    tol = abs(level) * tolerance_pct / 100.0
    all_levels = highs + lows
    near = [lv for lv in all_levels if abs(lv - level) <= tol]
    if near:
        nearest = min(near, key=lambda lv: abs(lv - level))
        return {"confirmed": True, "daily_level": round(nearest, 2),
                "tolerance_pct": tolerance_pct}
    return {"confirmed": False, "reason": "no matching daily level"}


if __name__ == "__main__":
    import trend_engine  # only for a manual smoke test
    rate = 88.0
    for sym in ("CRUDEOIL", "NATURALGAS"):
        info = enriched_bars(sym, rate, None)
        df = info["df"]
        print(f"{sym}: source={info['source']} bars={0 if df is None else len(df)} "
              f"last_close={None if df is None else round(float(df['Close'].iloc[-1]), 2)}")
