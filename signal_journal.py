"""
Signal outcome journal for the commodity signals.

Every gate value in sr_volume.py is hand-tuned against a handful of named
examples, and the model's accuracy has, until now, been *asserted* rather
than *measured*. This module closes that loop: it records each BUY/SELL the
model fires for crude and natural gas, then -- as later bars arrive -- scores
whether price reached Target 1 before the stop, and reports a rolling
hit-rate and expectancy per instrument and per setup type.

That number is the only honest answer to "is it accurate?". It also feeds
back into the product: a setup type running a poor hit-rate can be
down-weighted or shown with a health warning, rather than presented with the
same confidence as one that works.

Persistence is a single JSON file, written atomically (tmp + os.replace)
like mcx_bars.json. Records are deduped so the 60-second refresh loop logs
one entry per distinct setup, not sixty copies of the same open trade.
Evaluation is idempotent -- re-running it over the same bars can only move a
record from "open" to a terminal outcome, never flip a decided one.
"""
from __future__ import annotations

import datetime
import json
import os

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOURNAL_FILE = os.path.join(BASE_DIR, "signal_journal.json")

# Cap the journal so it can't grow without bound; keep the most recent N.
MAX_RECORDS = 2000
# A new signal for a symbol is "the same setup still standing" if its entry
# is within this fraction of the previously logged open one. Prevents the
# refresh loop from logging a fresh record every minute for one live signal.
DEDUP_ENTRY_PCT = 0.15


def _load() -> list[dict]:
    try:
        with open(JOURNAL_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(records: list[dict]) -> None:
    if len(records) > MAX_RECORDS:
        records = records[-MAX_RECORDS:]
    tmp = JOURNAL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, separators=(",", ":"))
    os.replace(tmp, JOURNAL_FILE)


def _last_open(records: list[dict], symbol: str) -> dict | None:
    for r in reversed(records):
        if r["symbol"] == symbol and r["outcome"] == "open":
            return r
    return None


def log_signal(symbol: str, sig: dict, now: datetime.datetime | None = None) -> None:
    """Record a fresh BUY/SELL if it is a genuinely new setup.

    A record is only opened when the signal has a direction and a stop and a
    target to be scored against, and when it differs from the currently open
    record for this symbol (different direction, or an entry more than
    DEDUP_ENTRY_PCT away). NONE/NO_DATA signals are not logged.
    """
    direction = sig.get("srv_signal")
    if direction not in ("BUY", "SELL"):
        return
    entry, stop, t1 = sig.get("srv_entry"), sig.get("srv_stop"), sig.get("srv_target1")
    if entry is None or stop is None or t1 is None:
        return

    now = now or datetime.datetime.now(datetime.timezone.utc)
    records = _load()
    open_rec = _last_open(records, symbol)
    if open_rec and open_rec["direction"] == direction and open_rec["entry"]:
        if abs(entry - open_rec["entry"]) / open_rec["entry"] * 100.0 <= DEDUP_ENTRY_PCT:
            return  # same setup still live -- don't double-log

    records.append({
        "symbol": symbol,
        "direction": direction,
        "setup": sig.get("srv_setup", "level_bounce"),
        "entry": round(float(entry), 2),
        "stop": round(float(stop), 2),
        "target1": round(float(t1), 2),
        "target2": sig.get("srv_target2"),
        "strength": sig.get("srv_strength"),
        "rr": sig.get("srv_rr"),
        "opened_at": now.isoformat(),
        "outcome": "open",
        "closed_at": None,
        "bars_to_resolve": None,
    })
    _save(records)


def evaluate(symbol: str, bars_df: pd.DataFrame | None,
             now: datetime.datetime | None = None) -> None:
    """Score this symbol's open records against bars printed after entry.

    For a long: walk the post-entry bars in time order; the first bar to
    trade at or below the stop is a loss, the first to trade at or above
    Target 1 is a win. A bar that spans both in a single candle is scored a
    loss -- the conservative reading, since we can't see intrabar order and
    a stop you can't prove you survived should not be counted a win.
    """
    if bars_df is None or bars_df.empty:
        return
    now = now or datetime.datetime.now(datetime.timezone.utc)
    records = _load()
    changed = False

    # Bars indexed by timestamp; tolerate tz-naive index.
    idx = pd.to_datetime(bars_df.index)
    highs = bars_df["High"].values.astype(float)
    lows = bars_df["Low"].values.astype(float)

    for r in records:
        if r["symbol"] != symbol or r["outcome"] != "open":
            continue
        try:
            opened = pd.Timestamp(r["opened_at"])
        except Exception:
            continue
        opened_cmp = opened.tz_localize(None) if opened.tzinfo else opened
        idx_cmp = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx

        long = r["direction"] == "BUY"
        stop, t1 = r["stop"], r["target1"]
        resolved, bars_seen = None, 0
        for i in range(len(idx_cmp)):
            if idx_cmp[i] <= opened_cmp:
                continue
            bars_seen += 1
            hit_stop = lows[i] <= stop if long else highs[i] >= stop
            hit_t1 = highs[i] >= t1 if long else lows[i] <= t1
            if hit_stop and hit_t1:
                resolved = "stop"  # conservative: can't prove target came first
                break
            if hit_stop:
                resolved = "stop"
                break
            if hit_t1:
                resolved = "target"
                break
        if resolved:
            r["outcome"] = resolved
            r["closed_at"] = now.isoformat()
            r["bars_to_resolve"] = bars_seen
            changed = True

    if changed:
        _save(records)


def stats(symbol: str | None = None) -> dict:
    """Rolling performance. With `symbol`, that instrument only; without, all.

    Reports resolved-trade counts, win rate (target hit before stop), and
    expectancy in R multiples -- a win is +rr R (its own reward:risk), a loss
    is -1 R -- which is the figure that actually says whether following the
    signals makes money, not just whether they're "often right".
    """
    records = _load()
    resolved = [r for r in records
                if r["outcome"] in ("target", "stop")
                and (symbol is None or r["symbol"] == symbol)]
    open_ct = sum(1 for r in records
                  if r["outcome"] == "open" and (symbol is None or r["symbol"] == symbol))
    if not resolved:
        return {"resolved": 0, "open": open_ct, "wins": 0, "losses": 0,
                "win_rate": None, "expectancy_r": None}

    wins = [r for r in resolved if r["outcome"] == "target"]
    losses = [r for r in resolved if r["outcome"] == "stop"]
    r_sum = 0.0
    for r in wins:
        r_sum += float(r.get("rr") or 1.0)
    r_sum += -1.0 * len(losses)
    return {
        "resolved": len(resolved),
        "open": open_ct,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(100.0 * len(wins) / len(resolved), 1),
        "expectancy_r": round(r_sum / len(resolved), 2),
    }


def stats_by_setup(symbol: str | None = None) -> dict:
    """Win rate broken out by setup type (level_bounce / PDH_BREAK / PDL_BREAK)."""
    records = _load()
    out: dict[str, dict] = {}
    for r in records:
        if r["outcome"] not in ("target", "stop"):
            continue
        if symbol is not None and r["symbol"] != symbol:
            continue
        s = out.setdefault(r["setup"], {"wins": 0, "losses": 0})
        s["wins" if r["outcome"] == "target" else "losses"] += 1
    for s, v in out.items():
        tot = v["wins"] + v["losses"]
        v["win_rate"] = round(100.0 * v["wins"] / tot, 1) if tot else None
    return out


if __name__ == "__main__":
    for sym in ("CRUDEOIL", "NATURALGAS"):
        print(sym, stats(sym), stats_by_setup(sym))
