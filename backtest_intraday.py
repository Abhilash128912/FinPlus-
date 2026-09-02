"""
backtest_intraday.py
=====================
Walk-forward backtest of the Intraday MIS buy/sell selection logic
(screener_engine.compute_intraday_picks) using the 1-year daily OHLCV
history already cached per ticker in cache/*.json — no network calls.

Replicates the exact live selection formulas (screener_engine.py):
  - RSI-14 via Wilder's smoothing (ewm alpha=1/14), matching TradingView/Zerodha
  - volume_spike = today's volume / 20-day average volume
  - ma50 = simple mean of the last 50 closes
  - day_chg_pct = (entry - prior close) / prior close * 100

Simulated trade mechanics: enter at day D's open once the selection
criteria are met (RSI/50DMA evaluated through day D-1's close, volume/day
move using day D's own bar), then walk day D's High/Low range to see
whether the 1% stop-loss or the 1.5%/2.5% targets (same numbers as the
live app) were touched, exiting at the day's close otherwise (approximating
the mandatory MIS same-day square-off).

LIMITATION, stated explicitly: this is a DAILY-BAR backtest, not a tick-
level intraday one — the cached history has no intraday path, so when a
day's High-Low range touches both the stop and a target, we can't know
which happened first. This script resolves that ambiguity by assuming the
stop was hit first, which UNDERSTATES (never overstates) the strategy's
real win rate. Treat results as a directional sanity check on the
selection logic, not a precise expectancy figure.
"""
import glob
import json
import time

import pandas as pd

MIN_LIQUIDITY = 200_000
MIN_PRICE = 20.0
LOOKBACK_MIN = 60  # warm-up so RSI-14 / 50MA / 20d-vol-avg have stabilized
RISK_PCT = 1.0      # same 1% stop / 1.5x / 2.5x targets as compute_intraday_picks


def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(100)


def simulate_ticker(symbol: str, df: pd.DataFrame) -> list[dict]:
    trades = []
    if len(df) < LOOKBACK_MIN + 2:
        return trades

    df = df.reset_index(drop=True)
    closes = df["close"]
    rsi = compute_rsi(closes)
    ma50 = closes.rolling(window=50, min_periods=1).mean()
    vol20 = df["volume"].rolling(window=20, min_periods=1).mean()

    for i in range(LOOKBACK_MIN, len(df)):
        prev_close = closes.iloc[i - 1]
        today_open = df["open"].iloc[i]
        today_high = df["high"].iloc[i]
        today_low = df["low"].iloc[i]
        today_close = closes.iloc[i]
        today_vol = df["volume"].iloc[i]
        avg_vol = vol20.iloc[i - 1]
        r = rsi.iloc[i - 1]
        ma = ma50.iloc[i - 1]

        if pd.isna(r) or pd.isna(ma) or pd.isna(avg_vol) or avg_vol <= 0 or prev_close <= 0:
            continue
        if today_open < MIN_PRICE or avg_vol < MIN_LIQUIDITY:
            continue

        vol_spike = today_vol / avg_vol
        day_chg_pct = (today_open - prev_close) / prev_close * 100
        dist_ma50_pct = (today_open - ma) / ma * 100 if ma > 0 else 0

        direction = None
        if 0.4 <= day_chg_pct <= 7.0 and vol_spike >= 1.3 and 54 <= r <= 74 and dist_ma50_pct >= -1.0:
            direction = "BUY"
        elif -7.0 <= day_chg_pct <= -0.4 and vol_spike >= 1.3 and 26 <= r <= 46 and dist_ma50_pct <= 1.0:
            direction = "SELL"
        if direction is None:
            continue

        entry = today_open
        if direction == "BUY":
            stop = entry * (1 - RISK_PCT / 100)
            t1 = entry * (1 + 1.5 * RISK_PCT / 100)
            t2 = entry * (1 + 2.5 * RISK_PCT / 100)
            if today_low <= stop:
                exit_price, outcome = stop, "stop"
            elif today_high >= t2:
                exit_price, outcome = t2, "target2"
            elif today_high >= t1:
                exit_price, outcome = t1, "target1"
            else:
                exit_price, outcome = today_close, "eod"
            ret_pct = (exit_price - entry) / entry * 100
        else:
            stop = entry * (1 + RISK_PCT / 100)
            t1 = entry * (1 - 1.5 * RISK_PCT / 100)
            t2 = entry * (1 - 2.5 * RISK_PCT / 100)
            if today_high >= stop:
                exit_price, outcome = stop, "stop"
            elif today_low <= t2:
                exit_price, outcome = t2, "target2"
            elif today_low <= t1:
                exit_price, outcome = t1, "target1"
            else:
                exit_price, outcome = today_close, "eod"
            ret_pct = (entry - exit_price) / entry * 100

        trades.append({
            "symbol": symbol, "date": df["date"].iloc[i], "direction": direction,
            "entry": round(entry, 2), "exit": round(exit_price, 2),
            "outcome": outcome, "ret_pct": round(ret_pct, 3),
        })
    return trades


def main():
    files = glob.glob("cache/*.json")
    print(f"Backtesting across {len(files)} cached tickers (1y daily history each)...")
    t0 = time.time()
    all_trades = []
    processed = 0
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
            hist = d.get("history_close", [])
            symbol = (d.get("ticker") or "").replace(".NS", "")
            if not hist or not symbol:
                continue
            df = pd.DataFrame(hist)
            if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
                continue
            trades = simulate_ticker(symbol, df)
            all_trades.extend(trades)
            processed += 1
        except Exception:
            continue

    elapsed = time.time() - t0
    print(f"Processed {processed} tickers with usable history in {elapsed:.1f}s")
    print(f"Total simulated trades: {len(all_trades)}\n")

    if not all_trades:
        print("No trades generated — criteria may be too strict for the cached history window.")
        return

    trades_df = pd.DataFrame(all_trades)

    def report(label, sub):
        n = len(sub)
        if n == 0:
            print(f"{label}: no trades")
            return
        wins = sub[sub["ret_pct"] > 0]
        losses = sub[sub["ret_pct"] <= 0]
        win_rate = len(wins) / n * 100
        avg_ret = sub["ret_pct"].mean()
        avg_win = wins["ret_pct"].mean() if len(wins) else 0
        avg_loss = losses["ret_pct"].mean() if len(losses) else 0
        total_ret = sub["ret_pct"].sum()
        expectancy = avg_ret
        print(f"--- {label} ({n} trades) ---")
        print(f"  Win rate:        {win_rate:.1f}%")
        print(f"  Avg return/trade:{avg_ret:+.3f}%")
        print(f"  Avg win:         {avg_win:+.3f}%   Avg loss: {avg_loss:+.3f}%")
        print(f"  Sum of returns:  {total_ret:+.2f}% (naive, no compounding/position sizing)")
        print(f"  Outcome mix:     {sub['outcome'].value_counts().to_dict()}")
        print(f"  Expectancy/trade:{expectancy:+.3f}%")
        print()

    report("ALL TRADES", trades_df)
    report("BUY (long)", trades_df[trades_df["direction"] == "BUY"])
    report("SELL (short)", trades_df[trades_df["direction"] == "SELL"])

    # Save full trade log for inspection
    trades_df.to_csv("backtest_intraday_trades.csv", index=False)
    print("Full trade log saved to backtest_intraday_trades.csv")


if __name__ == "__main__":
    main()
