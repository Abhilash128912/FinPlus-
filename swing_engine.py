"""
swing_engine.py - High-Conviction Swing Trading Engine

Combines:
  1. screener_engine's Decoupled Swing Engine (Setup Quality vs Entry Quality,
     Fibonacci Retracement 38.2/50/61.8, Anchored VWAP, Bullish RSI Divergence,
     1M/3M Relative Strength vs NIFTY, Auto-GTT trigger, ATR stops & targets).
  2. Live INDmoney broker quotes (real-time tick prices, avoiding delayed Yahoo data).
  3. Genuine Indian fundamental analysis (Screener.in ROE, ROCE, D/E, NPM, P/E)
     via fundamental_engine.py to restore authentic Business Strength & Value scoring.
"""

import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENER_APP_DIR = os.environ.get("SCREENER_APP_DIR", BASE_DIR)
if SCREENER_APP_DIR not in sys.path:
    sys.path.insert(0, SCREENER_APP_DIR)

import screener_engine as se
import equity_scan
import fundamental_engine


def _load_base_scan_data() -> list[dict]:
    # Shared process-lifetime cache (equity_scan.load_screener_data) so this
    # doesn't hold its own independent copy of the 11MB scan file alongside
    # equity_scan/lt_engine/penny_engine's copies -- see that function's
    # docstring for why (the free-tier OOM this fixed).
    return equity_scan.load_screener_data()


def scan_swing_candidates(top_n: int = 15, update_live_quotes: bool = True) -> dict:
    """
    Executes full swing pipeline across liquid universe:
      - Reads candidate pool
      - Enriches with live INDmoney quotes
      - Enriches with genuine Screener.in fundamentals (ROE, ROCE, D/E, NPM, P/E)
      - Evaluates setup quality, entry timing, and GTT trigger levels
      - Enforces exact SWING_GATES
    """
    raw_data = _load_base_scan_data()
    if not raw_data:
        return {"picks": [], "total_candidates": 0, "qualified_count": 0}

    # Filter for candidates passing general liquid / cap gates first
    candidates = [
        dict(row) for row in raw_data
        if (row.get("cap_category") in ("Large Cap", "Mid Cap") or row.get("is_mtf") in (True, "true"))
        and (row.get("ltp") or 0) >= 50.0
    ]

    # Live quotes via INDmoney if requested and available
    if update_live_quotes:
        try:
            sec_map = equity_scan.get_security_id_map()
            by_symbol = {c["symbol"]: c for c in candidates if c.get("symbol") in sec_map}
            scrip_to_symbol = {f"NSE_{sec_map[sym]}": sym for sym in by_symbol}
            all_codes = list(scrip_to_symbol.keys())

            live_by_code = equity_scan.fetch_live_quotes_resilient(all_codes)

            for code, sym in scrip_to_symbol.items():
                live = live_by_code.get(code)
                if live and live.get("ltp") is not None:
                    row = by_symbol[sym]
                    row["ltp"] = live["ltp"]
                    row["_live"] = True
                    avg_vol = row.get("avg_volume_10d") or 0
                    if avg_vol > 0 and live.get("volume") is not None:
                        row["volume_spike"] = round(live["volume"] / avg_vol, 2)
                        row["today_volume"] = live["volume"]
        except Exception as exc:
            print(f"[swing_engine] live quote update skipped: {exc}")

    # Enrich with genuine Screener.in fundamentals & recompute scores
    enriched = []
    for c in candidates:
        sym = c.get("symbol")
        if not sym:
            continue

        # Pull authentic fundamentals
        fund = fundamental_engine.get_fundamentals(sym)
        c["roe_pct"] = fund.get("roe_pct")
        c["roce_pct"] = fund.get("roce_pct")
        c["de_ratio"] = fund.get("de_ratio")
        c["npm_pct"] = fund.get("npm_pct")
        c["rev_growth_pct"] = fund.get("rev_growth_pct")
        c["pe"] = fund.get("pe")
        c["pb"] = fund.get("pb")

        # Re-score fundamental Strength (0-100) and Value (0-100) using screener_engine logic.
        # score_strength/score_value read raw yfinance .info field names --
        # bridge fundamental_engine's schema/units first or these silently
        # see nothing and return 0.0 regardless of real data on file.
        legacy = fundamental_engine.to_legacy_yfinance_shape(c)
        s_score, s_break = se.score_strength(legacy)
        v_score, v_break = se.score_value(legacy)
        c["strength"] = s_score
        c["strength_score"] = s_score
        c["strength_breakdown"] = s_break
        c["value"] = v_score
        c["value_score"] = v_score
        c["value_breakdown"] = v_break

        # Genuine fundamental weight
        c["fund_weight_pct"] = 40.0
        c["tech_weight_pct"] = 60.0

        # Compute swing setup metrics
        setup = se.compute_swing_setup(c)
        c.update(setup)

        # Confirm GTT entry status against current live price
        ltp = float(c.get("ltp") or 0.0)
        gtt_breakout = float(c.get("gtt_breakout_level") or 0.0)
        gtt_pullback = float(c.get("gtt_pullback_level") or 0.0)

        # Realistic GTT trigger detection
        status = c.get("status") or "WAIT"
        action = c.get("swing_action") or "WATCH"
        badge = "⏳ WAIT"
        badge_class = "badge-gray"

        if gtt_breakout > 0 and ltp >= gtt_breakout:
            status = "BUY_NOW"
            action = "BUY BREAKOUT"
            badge = "🚀 BUY NOW"
            badge_class = "badge-green"
        elif gtt_pullback > 0 and abs(ltp - gtt_pullback) / gtt_pullback <= 0.015:
            status = "BUY_NOW"
            action = "BUY PULLBACK"
            badge = "🎯 BUY DIP"
            badge_class = "badge-green"
        elif gtt_pullback > 0 and ltp > gtt_pullback:
            status = "WAIT"
            action = "WAIT FOR PULLBACK"
            badge = "⏳ PULLBACK"
            badge_class = "badge-amber"
        elif gtt_breakout > 0 and ltp < gtt_breakout:
            status = "WAIT"
            action = "WAIT FOR BREAKOUT"
            badge = "⏳ BREAKOUT"
            badge_class = "badge-blue"

        c["status"] = status
        c["swing_action"] = action
        c["status_badge"] = badge
        c["status_badge_class"] = badge_class

        # Check exact SWING_GATES
        if se.swing_candidate_gates_pass(c):
            enriched.append(c)

    def _rank(rows):
        rows.sort(key=lambda s: (se.sane_metric(s, "swing_score") or 0.0,
                                 se.sane_metric(s, "total_score") or 0.0), reverse=True)
        return rows

    # First pass (snapshot technicals) only picks a wide shortlist. The shortlisted stocks are
    # then RE-EVALUATED on fresh INDstocks daily candles -- trend, RSI, moving averages, 1M/3M
    # returns, volume vs average and the Fibonacci / anchored-VWAP / divergence setup all
    # recomputed from the candles -- because the scan snapshot can be days old (GRANULES was
    # scored on RSI 66.8 when its real RSI was 53).
    _rank(enriched)
    if update_live_quotes:
        import lt_engine
        lt_engine.prefetch_technicals([c["symbol"] for c in enriched[:60]])   # batched INDstocks candles
        refreshed = []
        for c in enriched[:60]:
            df = lt_engine.fresh_history(c["symbol"])
            tech = lt_engine.fresh_technicals(c["symbol"], require_ma200=False)
            if df is None or not tech:
                c["technicals_fresh"] = False
                refreshed.append(c)
                continue
            c = dict(c)
            if not c.get("_live"):
                c["ltp"] = tech["ltp"]          # no live quote: the last daily close, not a snapshot price
            c.update({"trend": tech["trend"], "rsi": tech["rsi"], "ema20": tech["ema20"], "ma50": tech["ma50"],
                      "ma200": tech["ma200"]})
            if tech.get("ret_1m") is not None:
                c["ret_1m"] = round(tech["ret_1m"], 2)
            if tech.get("ret_3m") is not None:
                c["ret_3m"] = round(tech["ret_3m"], 2)
            avg_vol = tech["avg_volume_10d"]
            if avg_vol > 0 and c.get("today_volume"):
                c["volume_spike"] = round(float(c["today_volume"]) / avg_vol, 2)
            c["avg_volume_10d"] = avg_vol
            c["technicals_fresh"] = True
            c["technicals_as_of"] = tech["last_bar"]
            # Momentum, RS and the order-flow inputs (CMF, CLV, market structure, price-action
            # pattern) recomputed from the fresh candles instead of read from the scan snapshot.
            m = lt_engine.fresh_momentum(c["symbol"], ltp=c.get("ltp"), volume=c.get("today_volume"))
            if m is not None:
                c["momentum"] = m
            c["momentum_fresh"] = m is not None
            import fresh_rs
            rs = fresh_rs.rs_rating(c["symbol"])
            if rs is not None:
                c["rs_rating"] = rs
            c["rs_fresh"] = rs is not None
            try:
                pa_score, pa = se.score_price_action_and_order_flow(df)
                c["pa_score"] = pa_score
                c.update({k: pa[k] for k in ("cmf", "clv", "market_structure", "pa_pattern", "pa_badge", "pa_class") if k in pa})
            except Exception as exc:
                print(f"[swing_engine] order-flow recompute failed for {c['symbol']}: {exc}")
            c.update(se.compute_swing_setup(c, history=df))
            ltp = float(c.get("ltp") or 0.0)
            gb = float(c.get("gtt_breakout_level") or 0.0)
            gp = float(c.get("gtt_pullback_level") or 0.0)
            if gb > 0 and ltp >= gb:
                c.update(status="BUY_NOW", swing_action="BUY BREAKOUT", status_badge="\U0001F680 BUY NOW", status_badge_class="badge-green")
            elif gp > 0 and abs(ltp - gp) / gp <= 0.015:
                c.update(status="BUY_NOW", swing_action="BUY PULLBACK", status_badge="\U0001F3AF BUY DIP", status_badge_class="badge-green")
            elif gp > 0 and ltp > gp:
                c.update(status="WAIT", swing_action="WAIT FOR PULLBACK", status_badge="\u23f3 PULLBACK", status_badge_class="badge-amber")
            elif gb > 0 and ltp < gb:
                c.update(status="WAIT", swing_action="WAIT FOR BREAKOUT", status_badge="\u23f3 BREAKOUT", status_badge_class="badge-blue")
            if se.swing_candidate_gates_pass(c):
                refreshed.append(c)
        enriched = _rank(refreshed)

    top_picks = enriched[:top_n]
    return {
        "picks": top_picks,
        "total_candidates": len(candidates),
        "qualified_count": len(enriched),
        "updated_at": time.time(),
    }


if __name__ == "__main__":
    res = scan_swing_candidates(top_n=5, update_live_quotes=False)
    print(f"Swing Candidates: {res['qualified_count']} qualified out of {res['total_candidates']}")
    for p in res["picks"]:
        print(f"  {p['symbol']:<12} LTP={p.get('ltp')} SwingScore={p.get('swing_score')} SetupQ={p.get('setup_quality')} EntryQ={p.get('entry_quality')} Status={p.get('swing_action')} SL={p.get('swing_sl')} T1={p.get('swing_t1')} ROE={p.get('roe_pct')}%")
