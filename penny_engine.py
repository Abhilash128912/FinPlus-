"""
penny_engine.py - Quality + Value Penny & Micro-Cap SIP Engine

Implements:
  1. Durability, Valuation, and GTT Entry Scoring:
     - Penny Quality Score (0-100): Debt-to-Equity <= 1.0, ROE >= 6-15%, positive net margins.
     - Penny Value Score (0-100): Percentile-ranked valuation & quality-adjusted P/E.
     - Penny Entry Score (0-100): Distance from GTT dip level and 20 EMA.
  2. Circuit & Trap Safety:
     - Price range: ₹5 to ₹75
     - Minimum market cap: ₹50 Cr
     - Minimum average volume: 20,000 shares
  3. Monthly SIP Allocation:
     - Calculates precise monthly shares for a ₹200/month budget per stock.
"""

import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENER_APP_DIR = os.environ.get("SCREENER_APP_DIR", BASE_DIR)
if SCREENER_APP_DIR not in sys.path:
    sys.path.insert(0, SCREENER_APP_DIR)

import screener_engine as se
import fundamental_engine
import equity_scan

def scan_penny_picks(top_n: int = 20, monthly_sip: float = 200.0, update_live_quotes: bool = True) -> dict:
    """
    Executes Quality + Value Penny Stock Screener:
      - Reads NSE universe
      - Enriches candidates with live INDmoney quotes & Screener.in fundamentals
      - Applies exact 7-gate safety filter and percentile ranking
      - Calculates SIP quantity
    """
    # Shared process-lifetime cache (equity_scan.load_screener_data) rather
    # than this engine's own independent read of the same 11MB file -- see
    # that function's docstring for why (the free-tier OOM this fixed).
    raw_data = equity_scan.load_screener_data()

    # Filter for micro-caps in the ₹5 to ₹75 window with positive momentum & liquidity.
    # 2026-09-12 audit: this used to let any symbol on the static DEBT_FREE_MICROCAPS
    # list skip the trend/volume gates below outright, on the theory a human had
    # already vetted those names. That list stopped being re-checked once written,
    # though -- KAMDHENU's hardcoded D/E (0.024) was 4x stale versus its actual
    # current cached D/E (0.43) by the time this was audited. One gate, applied the
    # same way to every candidate, live-computed every time: no more exceptions.
    penny_candidates = [
        dict(row) for row in raw_data
        if row.get("symbol")
        and (5.0 <= float(row.get("ltp") or 0.0) <= 75.0)
        and row.get("trend") not in ("Downtrend", "Distribution")
        and float(row.get("avg_volume_10d") or 0.0) >= 10000
    ]

    # Optional live quotes update via INDmoney
    if update_live_quotes:
        try:
            sec_map = equity_scan.get_security_id_map()
            by_symbol = {c["symbol"]: c for c in penny_candidates if c.get("symbol") in sec_map}
            scrip_to_symbol = {f"NSE_{sec_map[sym]}": sym for sym in by_symbol}
            all_codes = list(scrip_to_symbol.keys())

            live_by_code = {}
            for i in range(0, len(all_codes), equity_scan.QUOTES_BATCH_SIZE):
                batch = all_codes[i:i + equity_scan.QUOTES_BATCH_SIZE]
                try:
                    live_by_code.update(equity_scan.fetch_live_quotes_batch(batch))
                except Exception:
                    pass

            for code, sym in scrip_to_symbol.items():
                live = live_by_code.get(code)
                if live and live.get("ltp") is not None:
                    by_symbol[sym]["ltp"] = live["ltp"]
        except Exception as exc:
            print(f"[penny_engine] live quote update skipped: {exc}")

    # Enrich with genuine cached fundamentals & enforce strict debt-free gate (D/E <= 0.10)
    enriched = []
    for c in penny_candidates:
        sym = c.get("symbol")
        fund = fundamental_engine.get_fundamentals(sym, allow_network=False)
        c["roe_pct"] = fund.get("roe_pct")
        c["roce_pct"] = fund.get("roce_pct")
        c["de_ratio"] = fund.get("de_ratio")
        c["npm_pct"] = fund.get("npm_pct")
        c["rev_growth_pct"] = fund.get("rev_growth_pct")
        c["pe"] = fund.get("pe")
        c["pb"] = fund.get("pb")
        c["durability_score"] = fund.get("durability_score")  # None = not available
        c["dvm_label"] = fund.get("dvm_label")

        # Strict Debt-Free Gate: D/E must be <= 0.10, checked live every time -- no
        # hardcoded-list bypass (see the candidate filter above for why).
        de_val = fund.get("de_ratio")
        is_debt_free = de_val is not None and float(de_val) <= 0.10
        if not is_debt_free:
            continue

        # Re-score quality using screener_engine. score_strength/score_value
        # read raw yfinance .info field names (returnOnEquity, trailingPE,
        # debtToEquity...) -- fundamental_engine's schema uses different
        # names and units, so it has to go through the bridge or these
        # calls silently see nothing and return 0.0 regardless of how good
        # the real fetched data is (confirmed 2026-09-11).
        legacy = fundamental_engine.to_legacy_yfinance_shape(c)
        s_score, _ = se.score_strength(legacy)
        v_score, _ = se.score_value(legacy)
        c["strength"] = s_score
        c["value"] = v_score
        if c.get("momentum") is None:
            continue  # no real momentum reading -> cannot score (no assumed 50)
        c["total_score"] = round((s_score * 0.40) + (v_score * 0.35) + (float(c["momentum"]) * 0.25), 1)

        enriched.append(c)

    # Run screener_engine's compute_quality_penny_stocks with exact gates
    penny_picks = se.compute_quality_penny_stocks(enriched, top_n=top_n, monthly_sip=monthly_sip)

    # Monthly Featured Penny Cohort: Top 10 Debt-Free Micro-Caps (₹5 to ₹75).
    # Sourced from `enriched` -- the same live-fundamentals-checked, D/E<=0.10-gated
    # pool "All Qualified Micro-Caps" (penny_picks, above) is built from -- not the
    # raw pre-gate universe, so the monthly cohort can never include a name the live
    # debt-free gate would have rejected.
    monthly_cohort = get_or_refresh_penny_monthly_picks(enriched, top_n=10, monthly_sip=monthly_sip)

    return {
        "monthly_cohort": monthly_cohort,
        "picks": penny_picks,
        "total_evaluated": len(penny_candidates),
        "qualified_count": len(penny_picks),
        "monthly_sip_budget": monthly_sip,
        "updated_at": time.time(),
    }


PENNY_MONTHLY_PICKS_FILE = os.path.join(BASE_DIR, "penny_monthly_picks.json")


def get_or_refresh_penny_monthly_picks(raw_universe: list[dict], top_n: int = 10, monthly_sip: float = 200.0,
                                       min_price: float = 5.0, max_price: float = 75.0) -> dict:
    """
    Selects top 10 debt-free micro-caps with price <= ₹75 (₹5 to ₹75),
    locks them for the current calendar month, and triggers 'BUY NOW' when
    live LTP reaches or falls below the GTT dip accumulation level.
    """
    import calendar
    from datetime import date

    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    locked_until_str = f"{today.year:04d}-{today.month:02d}-{last_day:02d}"
    month_label = today.strftime("%B %Y")

    saved_state = {}
    if os.path.exists(PENNY_MONTHLY_PICKS_FILE):
        try:
            with open(PENNY_MONTHLY_PICKS_FILE, "r", encoding="utf-8") as f:
                saved_state = json.load(f)
        except Exception:
            saved_state = {}

    is_active_lock = (
        saved_state.get("locked_until") == locked_until_str
        and saved_state.get("method") == "live_debt_free_gate_v1"
        and len(saved_state.get("picks") or []) == top_n
    )

    by_symbol_universe = {r.get("symbol"): r for r in raw_universe if r.get("symbol")}

    if is_active_lock:
        picks = saved_state["picks"]
        for p in picks:
            sym = p.get("symbol")
            u_row = by_symbol_universe.get(sym)
            if u_row and u_row.get("ltp"):
                p["ltp"] = u_row["ltp"]

            ltp = float(p.get("ltp") or 0.0)
            gtt = float(p.get("gtt_level") or (ltp * 0.95))
            p["gtt_level"] = round(gtt, 2)

            dist_pct = round(((ltp - gtt) / gtt) * 100, 1) if gtt > 0 else 0.0
            p["dist_from_gtt_pct"] = dist_pct

            # Sizing for SIP
            if ltp > 0:
                p["monthly_shares"] = max(1, int(round(monthly_sip / ltp)))

            is_buy = ltp > 0 and (ltp <= gtt or dist_pct <= 3.5 or (p.get("trend") == "Accumulation" and dist_pct <= 5.0))
            if is_buy:
                p["status"] = "BUY_NOW"
                p["status_badge"] = "🚀 BUY NOW"
                p["status_badge_class"] = "badge-green"
                p["status_reason"] = f"At accumulation / GTT dip level (₹{gtt:.2f})"
            else:
                p["status"] = "WAIT"
                p["status_badge"] = f"⏳ WAIT FOR DIP ({dist_pct:+.1f}%)"
                p["status_badge_class"] = "badge-yellow"
                p["status_reason"] = f"+{dist_pct:.1f}% above GTT dip level (₹{gtt:.2f})"

        saved_state["picks"] = picks
        saved_state["updated_at"] = time.time()
        try:
            with open(PENNY_MONTHLY_PICKS_FILE, "w", encoding="utf-8") as f:
                json.dump(saved_state, f, indent=2)
        except Exception:
            pass
        return saved_state

    # Fresh selection: rank the already live-gated candidate pool (raw_universe is
    # `enriched` from scan_penny_picks -- every entry already cleared the D/E<=0.10
    # debt-free gate against CURRENT cached fundamentals) by quality, and lock in
    # the top N for the month.
    #
    # 2026-09-12 audit: this used to read the top N straight from a hardcoded
    # DEBT_FREE_MICROCAPS Python list instead, which meant a stock's real D/E was
    # never re-checked once written into that list. Confirmed stale in practice:
    # KAMDHENU's hardcoded de_ratio was 0.024 while its actual cached de_ratio had
    # drifted to 0.43 -- 4x over the 0.10 gate -- and the cohort kept showing it as
    # debt-free regardless. Selecting fresh from live data on every new lock period
    # means a name has to actually be debt-free right now to make the cut, and it
    # can't get "stuck" here indefinitely once it stops qualifying.
    def _rank_score(cand: dict) -> float:
        dur = float(cand.get("durability_score") if cand.get("durability_score") is not None else 65.0)
        roe_val = cand.get("roe_pct")
        pe_val = cand.get("pe")
        q = min(100.0, max(50.0, 60.0 + (float(roe_val if roe_val is not None else 12.0) * 1.5)))
        v = min(100.0, max(40.0, 90.0 - (float(pe_val if pe_val is not None else 20.0) * 0.8)))
        return (dur * 0.40) + (q * 0.35) + (v * 0.25)

    ranked_universe = sorted(raw_universe, key=_rank_score, reverse=True)

    cohort_picks = []
    for c in ranked_universe[:top_n]:
        sym = c.get("symbol")
        u_row = c  # raw_universe entries already carry live ltp/trend/etc.
        ltp = float(u_row.get("ltp") or c.get("ltp") or 0.0)
        trend = u_row.get("trend") or c.get("trend")  # None if unknown -- never assumed "Uptrend"

        # Set conservative GTT dip entry at auto_gtt, 50 MA, or 5% pullback
        auto_gtt = float(u_row.get("auto_gtt") or 0.0)
        ma50 = float(u_row.get("ma50") or 0.0)
        if 0 < auto_gtt < ltp:
            gtt = round(auto_gtt, 2)
        elif 0 < ma50 < ltp:
            gtt = round(ma50, 2)
        else:
            gtt = round(ltp * 0.95, 2)

        dist_pct = round(((ltp - gtt) / gtt) * 100, 1) if gtt > 0 else 0.0
        shares = max(1, int(round(monthly_sip / ltp))) if ltp > 0 else 1

        is_buy = ltp > 0 and (ltp <= gtt or dist_pct <= 3.5 or (trend == "Accumulation" and dist_pct <= 5.0))
        if is_buy:
            status = "BUY_NOW"
            badge = "🚀 BUY NOW"
            badge_cls = "badge-green"
            reason = f"At accumulation / GTT dip level (₹{gtt:.2f})"
        else:
            status = "WAIT"
            badge = f"⏳ WAIT FOR DIP ({dist_pct:+.1f}%)"
            badge_cls = "badge-yellow"
            reason = f"+{dist_pct:.1f}% above GTT dip level (₹{gtt:.2f})"

        # `or DEFAULT` treats a real 0.0 the same as missing data -- several
        # of the audited debt-free microcaps genuinely have roe_pct=0.0, and
        # `or 12.0` was silently inflating their rank score with a fake
        # positive ROE instead of scoring the real (weak) number.
        dur_val = c.get("durability_score")
        roe_val = c.get("roe_pct")
        pe_val = c.get("pe")
        dur = float(dur_val) if dur_val is not None else 65.0
        q = round(min(100.0, max(50.0, 60.0 + (float(roe_val if roe_val is not None else 12.0) * 1.5))), 1)
        v = round(min(100.0, max(40.0, 90.0 - (float(pe_val if pe_val is not None else 20.0) * 0.8))), 1)
        rank_s = round(_rank_score(c), 1)  # same formula that ranked/sliced ranked_universe above
        entry_s = round(max(10.0, 100.0 - (dist_pct * 3.0)), 1)

        cohort_picks.append({
            "symbol": sym,
            "name": c.get("name") or sym,
            "sector": c.get("sector") or "",
            "ltp": ltp,
            "gtt_level": gtt,
            "dist_from_gtt_pct": dist_pct,
            "status": status,
            "status_badge": badge,
            "status_badge_class": badge_cls,
            "status_reason": reason,
            "trend": trend,
            "durability_score": dur,
            "dvm_label": c.get("dvm_label", "GOOD"),
            "penny_rank_score": rank_s,
            "penny_quality_score": q,
            "penny_value_score": v,
            "penny_entry_score": entry_s,
            "monthly_shares": shares,
            "roe_pct": c.get("roe_pct"),
            "roce_pct": c.get("roce_pct"),
            "de_ratio": c.get("de_ratio"),
            "pe": c.get("pe"),
            "today_volume": u_row.get("today_volume") or u_row.get("avg_volume_10d"),
        })

    cohort_data = {
        "month_label": month_label,
        "locked_until": locked_until_str,
        "method": "live_debt_free_gate_v1",
        "min_price": min_price,
        "max_price": max_price,
        "monthly_sip_budget": monthly_sip,
        "picks": cohort_picks,
        "updated_at": time.time(),
    }

    try:
        with open(PENNY_MONTHLY_PICKS_FILE, "w", encoding="utf-8") as f:
            json.dump(cohort_data, f, indent=2)
    except Exception as e:
        print(f"[penny_engine] failed to save {PENNY_MONTHLY_PICKS_FILE}: {e}")

    return cohort_data


if __name__ == "__main__":
    res = scan_penny_picks(top_n=5, monthly_sip=200.0, update_live_quotes=False)
    print(f"Penny Monthly Cohort: {res.get('monthly_cohort', {}).get('month_label')}")
    for p in res.get("monthly_cohort", {}).get("picks", []):
        print(f"  {p['symbol']:<12} LTP={p.get('ltp')} GTT={p.get('gtt_level')} Status={p.get('status')} SIP_Qty={p.get('monthly_shares')} ROE={p.get('roe_pct')}%")
