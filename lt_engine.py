"""
lt_engine.py - Long-Term Business Quality & 4-Stage Universe Discovery Pipeline

Implements:
  1. 50/25/25 Sector-Aware Long-Term Business Quality Score:
     - Business Quality & Governance (50 pts): ROE > 15-20%, low D/E, NPM > 10-15%
     - Fundamental Growth & Reinvestment (25 pts): 3Y revenue growth & ROCE durability
     - Valuation & Risk Normalization (25 pts): Sector P/E & Cyclicality adjustments
  2. Incumbent Audit: Audits long-term watchlist stocks against universe challengers.
  3. Top Challengers Discovery: Finds genuine high-ROCE compounders across NSE.
  4. Real Screener.in Fundamentals: No more missing ROE or 0-weight defaults.
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

LT_WATCHLIST_FILE = os.path.join(BASE_DIR, "lt_watchlist.json")
if not os.path.exists(LT_WATCHLIST_FILE):
    src_wl = os.path.join(SCREENER_APP_DIR, "lt_watchlist.json")
    if os.path.exists(src_wl):
        try:
            with open(src_wl, "r", encoding="utf-8") as f_in, open(LT_WATCHLIST_FILE, "w", encoding="utf-8") as f_out:
                f_out.write(f_in.read())
        except Exception:
            pass

EXCLUDED_SLOW_PSUS = {
    # PSU Banks
    'PNB', 'MAHABANK', 'CANBK', 'UNIONBANK', 'BANKBARODA', 'SBIN', 'INDIANB', 'IOB', 
    'UCOBANK', 'CENTRALBK', 'BANKINDIA', 'PSB',
    # PSU Oil & Gas, Mining, Metals
    'OIL', 'COALINDIA', 'NMDC', 'BPCL', 'IOC', 'ONGC', 'GAIL', 'SAIL', 'MOIL', 
    'MRPL', 'HINDPETRO', 'NATIONALUM', 'KIOCL',
    # PSU Power & Utilities
    'NHPC', 'BHEL', 'NTPC', 'POWERGRID', 'PFC', 'RECLTD', 'SJVN', 'IREDA', 'NLCINDIA',
    # PSU Rail & Infrastructure
    'IRFC', 'RVNL', 'IRCON', 'RITES', 'HUDCO', 'NBCC', 'ENGINERSIN',
    # PSU Defense & Shipbuilders
    'HAL', 'BDL', 'MAZDOCK', 'COCHINSHIP', 'GRSE', 'MIDHANI',
    # PSU Financials & Insurance
    'NIACL', 'GICRE', 'LICHSGFIN', 'LICI', 'IFCI', 'SBICARD', 'SBILIFE'
}

FUTURE_MEGATREND_MAP = {
    # Defense Electronics & Radar Systems
    'BEL': 'Defense Electronics & Radar Systems',
    
    # Solar & Clean Energy
    'ACMESOLAR': 'Solar & Clean Energy',
    'UTLSOLAR': 'Solar & Clean Energy',
    'JNPR': 'Solar & Clean Energy',
    'INOXWIND': 'Solar & Clean Energy',
    'GIPCL': 'Solar & Clean Energy',
    
    # Semiconductor & Advanced EMS
    'APOLLO': 'Semiconductor & Advanced EMS',
    'EXICOM': 'Semiconductor & Advanced EMS',
    'RIR': 'Semiconductor & Advanced EMS',
    'MOSCHIP': 'Semiconductor & Advanced EMS',
    'PCBL': 'Semiconductor & Advanced EMS',
    'EMIL': 'Semiconductor & Advanced EMS',
    'REMSONSIND': 'Semiconductor & Advanced EMS',
    
    # Precious Metals & Gold Jewellery
    'SENCO': 'Precious Metals & Gold',
    'MVGJL': 'Precious Metals & Gold',
    'SHANTIGOLD': 'Precious Metals & Gold',
    'RBZJEWEL': 'Precious Metals & Gold',
    'RADHIKAJWE': 'Precious Metals & Gold',
    'GOLDIAM': 'Precious Metals & Gold',
    
    # EV Electronics & Autonomous Cockpits
    'MOTHERSON': 'EV Electronics & Cockpits',
    'BELRISE': 'EV Electronics & Cockpits',
    'MARINE': 'EV Electronics & Cockpits',
    
    # Electric Mobility & Commercial Fleets
    'TMCV': 'Electric & Clean Mobility',
    'ASHOKLEY': 'Electric & Clean Mobility',
    'JAMNAAUTO': 'Electric & Clean Mobility',
    
    # Digital Wealth & FinTech Platform
    'ZAGGLE': 'Digital Wealth & FinTech',
    'MOBIKWIK': 'Digital Wealth & FinTech',
    
    # AAA Retail Housing Finance
    'BAJAJHFL': 'AAA Retail Housing Finance',
    
    # Digital NBFC & Enterprise Wealth
    'TATACAP': 'Digital NBFC & Enterprise Wealth',
    
    # Private Banking & Wealth
    'FEDERALBNK': 'Private Banking & Wealth',
    'IDFCFIRSTB': 'Private Banking & Wealth',
    
    # Green Ports & Modern Maritime Logistics
    'JSWINFRA': 'Green Ports & Modern Logistics',
    
    # 5G Telecom & Digital Infrastructure
    'INDUSTOWER': '5G Telecom & Digital Infrastructure',
    
    # Digital Consumer & E-Commerce
    'NYKAA': 'Digital Consumer & E-Commerce',
    'SWIGGY': 'Digital Consumer & E-Commerce',
}


def get_compounder_pillar(c: dict) -> str:
    sym = c.get('symbol', '')
    if sym in FUTURE_MEGATREND_MAP:
        return FUTURE_MEGATREND_MAP[sym]
    return c.get('sector') or 'General'


def load_lt_watchlist() -> list[dict]:
    if os.path.exists(LT_WATCHLIST_FILE):
        try:
            with open(LT_WATCHLIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def scan_lt_discovery(top_n: int = 20, update_live_quotes: bool = True) -> dict:
    """
    Executes the 4-stage Long Term Discovery Pipeline:
      - Audits watchlist incumbents with real fundamentals and live prices
      - Discovers top challengers across the universe
    """
    # Shared process-lifetime cache (equity_scan.load_screener_data) rather
    # than this engine's own independent read of the same 11MB file -- see
    # that function's docstring for why (the free-tier OOM this fixed).
    raw_data = equity_scan.load_screener_data()

    watchlist = load_lt_watchlist()
    watchlist_symbols = {w.get("symbol") for w in watchlist if w.get("symbol")}

    # Candidates: Filtered strictly between ₹75 and ₹500, strictly excluding slow PSUs
    candidates = [
        dict(row) for row in raw_data
        if row.get("symbol") and row.get("symbol") not in EXCLUDED_SLOW_PSUS and (
            row.get("symbol") in watchlist_symbols
            or (75.0 <= float(row.get("ltp") or 0.0) <= 500.0)
        )
    ]

    # Optional live quotes batch via INDmoney
    if update_live_quotes:
        try:
            sec_map = equity_scan.get_security_id_map()
            by_symbol = {c["symbol"]: c for c in candidates if c.get("symbol") in sec_map}
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
            print(f"[lt_engine] live quote update skipped: {exc}")

    # Enrich with genuine Screener.in fundamentals & compute LT quality
    for c in candidates:
        sym = c.get("symbol")
        fund = fundamental_engine.get_fundamentals(sym)
        c["roe_pct"] = fund.get("roe_pct")
        c["roce_pct"] = fund.get("roce_pct")
        c["de_ratio"] = fund.get("de_ratio")
        c["npm_pct"] = fund.get("npm_pct")
        c["rev_growth_pct"] = fund.get("rev_growth_pct")
        c["pe"] = fund.get("pe")
        c["pb"] = fund.get("pb")
        c["pillar"] = get_compounder_pillar(c)

        # Re-score LT quality and combined rank score
        eval_res = se.compute_sector_aware_lt_quality(c)
        c.update(eval_res)

    # Run Screener engine 4-stage discovery pipeline
    pipeline_res = se.run_lt_universe_discovery_pipeline(candidates, watchlist)

    scored_universe = pipeline_res.get("universe", candidates)
    by_symbol_scored = {s.get("symbol"): s for s in scored_universe if s.get("symbol")}

    # Update watchlist with latest metrics & live GTT trigger checks
    enriched_watchlist = []
    for w in watchlist:
        sym = w.get("symbol")
        item = dict(w)
        scored_data = by_symbol_scored.get(sym, {})
        item.update(scored_data)

        ltp = item.get("ltp")
        if ltp:
            ltp = float(ltp)
            item["ltp"] = ltp
            gtt = float(item.get("gtt_level") or (ltp * 0.95))
            item["gtt_level"] = round(gtt, 2)
            dist_pct = round(((ltp - gtt) / gtt) * 100, 1) if gtt > 0 else 0.0
            item["dist_from_gtt_pct"] = dist_pct

            if ltp <= gtt or dist_pct <= 3.5:
                item["status"] = "BUY_NOW"
                item["status_badge"] = "🚀 BUY NOW"
                item["status_badge_class"] = "badge-green"
                item["status_reason"] = f"At or below GTT dip level (₹{gtt:.2f})"
            else:
                item["status"] = "WAIT"
                item["status_badge"] = "⏳ WAIT"
                item["status_badge_class"] = "badge-gray"
                item["status_reason"] = f"+{dist_pct:.1f}% above GTT dip level (₹{gtt:.2f})"
        else:
            item["ltp"] = None
            item["status"] = "WAIT"
            item["status_badge"] = "⏳ WAIT"
            item["status_badge_class"] = "badge-gray"
        enriched_watchlist.append(item)

    # Monthly Featured Cohort: Top 10 High-Strength Future Picks (₹75 to ₹500)
    monthly_cohort = get_or_refresh_monthly_picks(raw_data, top_n=10, min_price=75.0, max_price=500.0)

    cohort_syms = {p["symbol"] for p in monthly_cohort.get("picks", [])}
    raw_challengers = pipeline_res.get("top_challengers", [])
    top_challengers = []
    seen_syms = set(cohort_syms) | set(watchlist_symbols)

    # 1. First pass: High-momentum future megatrend stocks (Precious Metals, Semi/EMS, Solar, EV Tech)
    megatrend_cands = [
        c for c in scored_universe
        if c.get("symbol") in FUTURE_MEGATREND_MAP
        and c.get("symbol") not in seen_syms
        and 75.0 <= float(c.get("ltp") or 0.0) <= 500.0
        and c.get("trend") in ("Strong Uptrend", "Uptrend", "Accumulation", "Consolidation")
    ]
    megatrend_cands.sort(key=lambda x: (
        0 if get_compounder_pillar(x) in ("Precious Metals & Gold", "Semiconductor & Advanced EMS", "Solar & Clean Energy") else 1,
        -float(x.get("combined_rank_score") or x.get("lt_quality_score") or 0.0)
    ))
    for c in megatrend_cands:
        c["pillar"] = get_compounder_pillar(c)
        c["sector_group"] = c["pillar"]
        top_challengers.append(c)
        seen_syms.add(c["symbol"])
        if len(top_challengers) >= top_n:
            break

    # 2. Second pass: Fill remainder with top pipeline challengers if needed
    if len(top_challengers) < top_n:
        for c in raw_challengers:
            sym = c.get("symbol")
            ltp = float(c.get("ltp") or 0.0)
            trend = c.get("trend") or ""
            if not sym or sym in EXCLUDED_SLOW_PSUS or sym in seen_syms or not (75.0 <= ltp <= 500.0) or trend in ("Downtrend", "Distribution"):
                continue
            c["pillar"] = get_compounder_pillar(c)
            c["sector_group"] = c["pillar"]
            top_challengers.append(c)
            seen_syms.add(sym)
            if len(top_challengers) >= top_n:
                break

    return {
        "monthly_cohort": monthly_cohort,
        "watchlist": enriched_watchlist,
        "top_challengers": top_challengers,
        "total_scanned": len(scored_universe),
        "updated_at": time.time(),
    }


LT_MONTHLY_PICKS_FILE = os.path.join(BASE_DIR, "lt_monthly_picks.json")


def get_or_refresh_monthly_picks(raw_universe: list[dict], top_n: int = 10,
                                 min_price: float = 75.0, max_price: float = 500.0) -> dict:
    """
    Selects top 10 stocks with highest fundamental strength and price between ₹75 and ₹500,
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
    if os.path.exists(LT_MONTHLY_PICKS_FILE):
        try:
            with open(LT_MONTHLY_PICKS_FILE, "r", encoding="utf-8") as f:
                saved_state = json.load(f)
        except Exception:
            saved_state = {}

    # Check if existing cohort is still locked for this month with 40/40/20 Future Compounders v6
    is_active_lock = (
        saved_state.get("locked_until") == locked_until_str
        and saved_state.get("cap_distribution") == "40_40_20_future_compounders_v7"
        and len(saved_state.get("picks") or []) == top_n
    )

    by_symbol_universe = {r.get("symbol"): r for r in raw_universe if r.get("symbol")}

    if is_active_lock:
        picks = saved_state["picks"]
        # Update live prices and re-evaluate GTT trigger status
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
            with open(LT_MONTHLY_PICKS_FILE, "w", encoding="utf-8") as f:
                json.dump(saved_state, f, indent=2)
        except Exception:
            pass
        return saved_state

    # Autosearch: Partition universe between min_price (₹75) and max_price (₹500)
    # Allocation: 40% Large Cap (4), 40% Mid Cap (4), 20% Small Cap (2)
    n_large = int(round(top_n * 0.40))
    n_mid = int(round(top_n * 0.40))
    n_small = top_n - n_large - n_mid

    candidates_by_cap = {"Large Cap": [], "Mid Cap": [], "Small Cap": []}
    for row in raw_universe:
        sym = row.get("symbol")
        ltp = float(row.get("ltp") or 0.0)
        trend = row.get("trend") or ""
        if not sym or not (min_price <= ltp <= max_price):
            continue
        if sym != "BEL" and (sym in EXCLUDED_SLOW_PSUS or trend in ("Downtrend", "Distribution")):
            continue
        if sym == "FEDERALBNK":
            cap = "Mid Cap"
        elif sym == "BEL":
            cap = "Large Cap"
        else:
            cap = row.get("cap_category") or "Small Cap"
        if cap in candidates_by_cap:
            candidates_by_cap[cap].append(dict(row))
        else:
            candidates_by_cap["Small Cap"].append(dict(row))

    # Enrich with genuine fundamentals + Trendlyne-style DVM Durability
    for cap, c_list in candidates_by_cap.items():
        for c in c_list:
            sym = c.get("symbol")
            fund = fundamental_engine.get_fundamentals(sym, allow_network=False)
            c["roe_pct"] = fund.get("roe_pct")
            c["roce_pct"] = fund.get("roce_pct")
            c["de_ratio"] = fund.get("de_ratio")
            c["npm_pct"] = fund.get("npm_pct")
            c["rev_growth_pct"] = fund.get("rev_growth_pct")
            c["pe"] = fund.get("pe")
            c["pb"] = fund.get("pb")
            c["durability_score"] = fund.get("durability_score", 50.0)
            c["dvm_label"] = fund.get("dvm_label", "AVERAGE")
            c["pillar"] = get_compounder_pillar(c)

    filtered_by_cap = {}
    for cap, c_list in candidates_by_cap.items():
        req_count = n_large if "Large" in cap else n_mid if "Mid" in cap else n_small
        growth_cands = [
            c for c in c_list
            if float(c.get("durability_score") or 0.0) >= 48.0
        ]
        if len(growth_cands) >= req_count:
            filtered_by_cap[cap] = growth_cands
        else:
            filtered_by_cap[cap] = c_list

    def _rank_and_pick_megatrends(pool, top_k, used_pillars, excluded_symbols=None):
        if excluded_symbols is None:
            excluded_symbols = set()
        candidates = [x for x in pool if x.get("symbol") not in excluded_symbols]
        scored = []
        for c in candidates:
            eval_res = se.compute_sector_aware_lt_quality(c)
            q = float(eval_res.get("lt_quality_score") or 0.0)
            dur = float(c.get("durability_score") or 50.0)
            roce = float(c.get("roce_pct") or 15.0)
            trend = c.get("trend") or "Uptrend"
            # Momentum bonus: Strong Uptrend gets +15, Accumulation gets +12, Uptrend +10
            mom_bonus = 15.0 if "Strong" in trend else 12.0 if "Accumulation" in trend else 10.0 if "Uptrend" in trend else 5.0
            pil = c["pillar"]
            # Future sunrise sector boost
            theme_boost = 20.0 if pil in ('Solar & Clean Energy', 'Semiconductor & Advanced EMS', 'Precious Metals & Gold', 'Defense Electronics & Radar Systems') else 12.0 if pil in ('EV Electronics & Cockpits', 'Digital Wealth & FinTech', 'AAA Retail Housing Finance', 'Green Ports & Modern Logistics', 'Digital NBFC & Enterprise Wealth', '5G Telecom & Digital Infrastructure', 'Private Banking & Wealth') else 0.0
            # Flag-bearer boost for user requested anchors
            semi_flag = 10.0 if c.get("symbol") in ("APOLLO", "BEL", "FEDERALBNK") else 0.0

            item = dict(c)
            item.update(eval_res)
            # Future Megatrend Score: 35% Durability + 25% ROCE + 25% Momentum + Theme Boost + Flag + 15% Quality
            item["combined_rank_score"] = round((dur * 0.35) + (min(roce, 40.0) * 1.5 * 0.25) + mom_bonus + theme_boost + semi_flag + (q * 0.15), 1)
            item["pillar"] = pil
            scored.append(item)
        scored.sort(key=lambda x: x["combined_rank_score"], reverse=True)

        picks = []
        for s in scored:
            pil = s["pillar"]
            if pil not in used_pillars and pil != "General":
                picks.append(s)
                used_pillars.add(pil)
                if len(picks) == top_k:
                    break
        # Fallback if pool exhausted
        if len(picks) < top_k:
            for s in scored:
                if s not in picks:
                    picks.append(s)
                    if len(picks) == top_k:
                        break
        return picks

    used_pillars = set()
    selected_large = _rank_and_pick_megatrends(filtered_by_cap["Large Cap"], n_large, used_pillars)
    ex_large = {x["symbol"] for x in selected_large}
    selected_mid = _rank_and_pick_megatrends(filtered_by_cap["Mid Cap"], n_mid, used_pillars, excluded_symbols=ex_large)
    ex_mid = ex_large | {x["symbol"] for x in selected_mid}
    selected_small = _rank_and_pick_megatrends(filtered_by_cap["Small Cap"], n_small, used_pillars, excluded_symbols=ex_mid)

    selected = selected_large + selected_mid + selected_small

    cohort_picks = []
    for p in selected:
        sym = p.get("symbol")
        ltp = float(p.get("ltp") or 0.0)

        # Set conservative GTT dip entry at 50 MA or 5% pullback
        ma50 = float(p.get("ma50") or 0.0)
        ema20 = float(p.get("ema20") or 0.0)
        if 0 < ma50 < ltp:
            gtt = round(ma50, 2)
        elif 0 < ema20 < ltp:
            gtt = round(ema20, 2)
        else:
            gtt = round(ltp * 0.95, 2)

        dist_pct = round(((ltp - gtt) / gtt) * 100, 1) if gtt > 0 else 0.0

        is_buy = ltp > 0 and (ltp <= gtt or dist_pct <= 3.5 or (p.get("trend") == "Accumulation" and dist_pct <= 5.0))
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

        cap_cat = "Mid Cap" if sym == "FEDERALBNK" else (p.get("cap_category") or "Small Cap")
        cohort_picks.append({
            "symbol": sym,
            "name": p.get("name") or sym,
            "sector": p.get("pillar") or p.get("sector") or "",
            "cap_category": cap_cat,
            "ltp": ltp,
            "gtt_level": gtt,
            "dist_from_gtt_pct": dist_pct,
            "status": status,
            "status_badge": badge,
            "status_badge_class": badge_cls,
            "status_reason": reason,
            "lt_quality_score": p.get("lt_quality_score"),
            "durability_score": p.get("durability_score", 50.0),
            "dvm_label": p.get("dvm_label", "AVERAGE"),
            "trend": p.get("trend") or "Uptrend",
            "combined_rank_score": p.get("combined_rank_score"),
            "sector_group": p.get("sector_group"),
            "roe_pct": p.get("roe_pct"),
            "roce_pct": p.get("roce_pct"),
            "de_ratio": p.get("de_ratio"),
            "npm_pct": p.get("npm_pct"),
            "pe": p.get("pe"),
        })

    cohort_data = {
        "month_label": month_label,
        "locked_until": locked_until_str,
        "cap_distribution": "40_40_20_future_compounders_v7",
        "min_price": min_price,
        "max_price": max_price,
        "picks": cohort_picks,
        "updated_at": time.time(),
    }

    try:
        with open(LT_MONTHLY_PICKS_FILE, "w", encoding="utf-8") as f:
            json.dump(cohort_data, f, indent=2)
    except Exception as e:
        print(f"[lt_engine] failed to save {LT_MONTHLY_PICKS_FILE}: {e}")

    return cohort_data


if __name__ == "__main__":
    res = scan_lt_discovery(top_n=5, update_live_quotes=False)
    print(f"LT Monthly Cohort: {res.get('monthly_cohort', {}).get('month_label')}")
    for p in res.get("monthly_cohort", {}).get("picks", []):
        print(f"  {p['symbol']:<12} LTP={p.get('ltp')} GTT={p.get('gtt_level')} Status={p.get('status')} Dist={p.get('dist_from_gtt_pct')}% ROE={p.get('roe_pct')}%")
