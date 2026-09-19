"""
data_health.py -- a standing, automatic answer to "is the data on screen real and current?".

Runs independent checks against what the apps are serving right now and against an outside source,
and reports OK / WARN / FAIL per check plus an overall status:

  * every list is populated, has unique symbols, finite scores in 0-100 and a positive price
  * picks are computed on FRESH candles (technicals_fresh), not the desktop-scan snapshot
  * candle dates are current for the last trading session
  * universe RS coverage
  * the broker token is live
  * a sample of prices is cross-checked against Yahoo Finance (an independent free source)

It cannot prove a number is "right" -- only that it is present, current, internally sane and
consistent with a second source. A mismatch is reported, never hidden.
"""
from __future__ import annotations

import datetime
import math
import time

import requests

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
PRICE_TOLERANCE_PCT = 1.5
LIST_MIN = {"swing": 1, "lt": 5, "penny": 1, "momentum_buy": 1, "momentum_sell": 1}
_STATUS_RANK = {"OK": 0, "SKIPPED": 0, "WARN": 1, "FAIL": 2}


def last_session_date(now: datetime.datetime | None = None) -> datetime.date:
    """Most recent NSE trading day whose session has started (weekends only; exchange holidays are
    not modelled, so a holiday can only make a check stricter than necessary, never looser)."""
    now = (now or datetime.datetime.now(IST)).astimezone(IST)
    d = now.date()
    if now.weekday() < 5 and now.time() < datetime.time(9, 15):
        d -= datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


def _business_days_between(a: datetime.date, b: datetime.date) -> int:
    """Whole business days from a to b (b later); 0 when equal."""
    n, cur = 0, a
    while cur < b:
        cur += datetime.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def _picks(payload: dict, name: str) -> list[dict]:
    node = (payload or {}).get(name) or {}
    if name == "momentum_buy":
        node = ((payload or {}).get("momentum") or {}).get("buy") or []
        return [p for p in node if isinstance(p, dict)]
    if name == "momentum_sell":
        node = ((payload or {}).get("momentum") or {}).get("sell") or []
        return [p for p in node if isinstance(p, dict)]
    return [p for p in (node.get("picks") or []) if isinstance(p, dict)]


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def evaluate_payload(payload: dict, now: datetime.datetime | None = None) -> list[dict]:
    """Pure checks on the served lists (no network) -- unit-testable."""
    checks: list[dict] = []
    lists = {n: _picks(payload, n) for n in LIST_MIN}

    empty = [n for n, mn in LIST_MIN.items() if len(lists[n]) < mn]
    checks.append(_check("lists_populated", "FAIL" if empty else "OK",
                         ("empty or too short: " + ", ".join(empty)) if empty else
                         ", ".join(f"{n}={len(v)}" for n, v in lists.items())))

    dups = []
    for n, v in lists.items():
        syms = [p.get("symbol") for p in v]
        if len(syms) != len(set(syms)):
            dups.append(n)
    checks.append(_check("unique_symbols", "FAIL" if dups else "OK",
                         ("duplicate symbols in: " + ", ".join(dups)) if dups else "no duplicates within any list"))

    bad = []
    for n, v in lists.items():
        for p in v:
            ltp = p.get("ltp")
            if ltp is None or not isinstance(ltp, (int, float)) or not math.isfinite(ltp) or ltp <= 0:
                bad.append(f"{n}:{p.get('symbol')} price")
            for k in ("swing_score", "total_score", "combined_rank_score", "momentum_score", "score"):
                v_ = p.get(k)
                if v_ is not None and (not isinstance(v_, (int, float)) or not math.isfinite(v_) or not (0 <= v_ <= 100)):
                    bad.append(f"{n}:{p.get('symbol')} {k}={v_}")
    checks.append(_check("values_sane", "FAIL" if bad else "OK",
                         ("; ".join(bad[:6]) + (" ..." if len(bad) > 6 else "")) if bad else
                         "prices positive and scores finite within 0-100"))

    total = stale = 0
    for n, v in lists.items():
        for p in v:
            if "technicals_fresh" in p:
                total += 1
                stale += 0 if p.get("technicals_fresh") else 1
    checks.append(_check("fresh_technicals", "OK" if stale == 0 else "WARN",
                         f"{total - stale}/{total} picks computed on fresh candles" if total else "no picks report freshness"))

    expected = last_session_date(now)
    old = []
    for n, v in lists.items():
        for p in v:
            asof = p.get("technicals_as_of")
            try:
                d = datetime.date.fromisoformat(str(asof)[:10])
            except ValueError:
                continue
            if _business_days_between(d, expected) > 1:
                old.append(f"{n}:{p.get('symbol')} {d}")
    checks.append(_check("candles_current", "WARN" if old else "OK",
                         ("older than the last session (" + str(expected) + "): " + ", ".join(old[:5])) if old else
                         f"candle dates current for the last session ({expected})"))
    return checks


def price_cross_check(payload: dict, sample: int = 6, timeout: float = 6.0) -> dict:
    """Compare served prices with Yahoo Finance for a sample of picks (an independent free source)."""
    picks: list[dict] = []
    for n in ("momentum_buy", "swing", "lt", "penny"):
        picks += _picks(payload, n)[:2]
    seen, rows = set(), []
    for p in picks:
        s = p.get("symbol")
        if s and s not in seen and isinstance(p.get("ltp"), (int, float)):
            seen.add(s)
            rows.append((s, float(p["ltp"])))
        if len(rows) >= sample:
            break
    if not rows:
        return _check("price_cross_check", "SKIPPED", "no priced picks to compare")
    diffs, unreachable = [], 0
    for sym, ours in rows:
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS",
                             params={"range": "5d", "interval": "1d"},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
            theirs = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
            diffs.append((sym, ours, float(theirs), abs(ours - float(theirs)) / float(theirs) * 100.0))
        except Exception:
            unreachable += 1
    if not diffs:
        return _check("price_cross_check", "SKIPPED", "Yahoo Finance not reachable from this server")
    worst = max(diffs, key=lambda d: d[3])
    off = [d for d in diffs if d[3] > PRICE_TOLERANCE_PCT]
    detail = (f"{len(diffs) - len(off)}/{len(diffs)} within {PRICE_TOLERANCE_PCT}% of Yahoo; worst {worst[0]} "
              f"{worst[1]:.2f} vs {worst[2]:.2f} ({worst[3]:.2f}%)")
    return _check("price_cross_check", "WARN" if off else "OK", detail + (f"; {unreachable} unreachable" if unreachable else ""))


def system_checks() -> list[dict]:
    """Checks on the running system itself (token, RS coverage)."""
    out: list[dict] = []
    try:
        import token_manager
        st = token_manager.get_token_status()
        ok = bool(st.get("has_token")) and not st.get("is_expired")
        out.append(_check("broker_token", "OK" if ok else "FAIL", "INDstocks token live" if ok else "token missing or expired"))
    except Exception as exc:
        out.append(_check("broker_token", "WARN", f"could not read token status: {exc}"))
    try:
        import fresh_rs
        cov, uni, at = fresh_rs._RS.get("coverage", 0), fresh_rs._RS.get("universe", 0), fresh_rs._RS.get("at", 0)
        if not at:
            out.append(_check("rs_coverage", "WARN", "universe RS not computed yet (first refresh runs after start-up)"))
        else:
            pct = 100.0 * cov / uni if uni else 0.0
            age_h = (time.time() - at) / 3600.0
            status = "OK" if pct >= 80 and age_h < 12 else "WARN"
            out.append(_check("rs_coverage", status, f"{cov}/{uni} stocks ({pct:.0f}%), computed {age_h:.1f}h ago"))
    except Exception as exc:
        out.append(_check("rs_coverage", "WARN", f"could not read RS state: {exc}"))
    try:
        import signal_journal
        s = signal_journal.stats()
        out.append(_check("signal_journal", "OK",
                          f"{s['raw_records']} records = {s['raw_records'] - s['duplicates_collapsed']} independent trials "
                          f"({s['wins']}W/{s['losses']}L resolved)"))
    except Exception as exc:
        out.append(_check("signal_journal", "WARN", f"could not read journal: {exc}"))
    return out


def run(payload: dict, network: bool = True) -> dict:
    checks = evaluate_payload(payload) + system_checks()
    if network:
        checks.append(price_cross_check(payload))
    worst = max(checks, key=lambda c: _STATUS_RANK[c["status"]])["status"]
    overall = "FAIL" if worst == "FAIL" else "WARN" if worst == "WARN" else "OK"
    problems = [c for c in checks if c["status"] in ("WARN", "FAIL")]
    return {
        "overall": overall,
        "summary": ("All checks passed" if overall == "OK"
                    else f"{len(problems)} check(s) need attention: " + ", ".join(c["name"] for c in problems)),
        "checked_at": datetime.datetime.now(IST).isoformat(timespec="seconds"),
        "checks": checks,
    }
