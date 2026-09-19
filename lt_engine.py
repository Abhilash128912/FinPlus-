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


# ── Best-10 long-term list ────────────────────────────────────────────────────
# The list is the 10 best stocks NOW, ranked on measurable, real-data criteria, and it
# changes whenever the data says a better stock exists. There is no calendar lock and
# no pinned symbol. To stop it reshuffling on every refresh, an incumbent is only
# replaced when a challenger beats it by SWAP_MARGIN points (or the incumbent stops
# qualifying).
LT_LIST_VERSION = "best10_real_data_v1"
LT_REFRESH_SEC = 30 * 60      # recompute at most every 30 minutes (inputs are daily data)
SWAP_MARGIN = 6.0             # score points a challenger must lead an incumbent by
MAX_PER_SECTOR_GROUP = 3      # diversification: max stocks per industry sector
MIN_DURABILITY = 55.0
MIN_ROE = 12.0
MIN_ROCE = 12.0               # non-financials; banks/NBFCs are judged on ROE only
MAX_DEBT_TO_EQUITY = 1.5      # non-financials, when D/E is known
BUY_NOW_DIST_PCT = 3.5        # % above the GTT dip level that still counts as "at" it
WATCH_DIST_PCT = 8.0          # further than this above the GTT level -> WATCH

TREND_STATE_POINTS = {"Strong Uptrend": 100.0, "Accumulation": 85.0, "Uptrend": 75.0, "Consolidation": 45.0}


def _gtt_level(p: dict, ltp: float) -> float:
    """Dip-entry level: the 50-day MA, else the 20-day EMA (when below price), else a
    5% pullback from the current price (a stated rule, not market data)."""
    ma50 = float(p.get("ma50") or 0.0)
    ema20 = float(p.get("ema20") or 0.0)
    if 0 < ma50 < ltp:
        return round(ma50, 2)
    if 0 < ema20 < ltp:
        return round(ema20, 2)
    return round(ltp * 0.95, 2)


def _status_for(trend, ltp: float, gtt: float) -> dict:
    """BUY_NOW / WAIT / WATCH from price vs the GTT dip level and the trend."""
    dist_pct = round(((ltp - gtt) / gtt) * 100, 1) if gtt > 0 else 0.0
    at_level = ltp > 0 and (ltp <= gtt or dist_pct <= BUY_NOW_DIST_PCT
                            or (trend == "Accumulation" and dist_pct <= 5.0))
    if at_level:
        return {"status": "BUY_NOW", "status_badge": "\U0001F680 BUY NOW", "status_badge_class": "badge-green",
                "status_reason": f"At accumulation / GTT dip level (\u20b9{gtt:.2f})", "dist_from_gtt_pct": dist_pct}
    if dist_pct <= WATCH_DIST_PCT:
        return {"status": "WAIT", "status_badge": f"\u23f3 WAIT FOR DIP ({dist_pct:+.1f}%)",
                "status_badge_class": "badge-yellow",
                "status_reason": f"+{dist_pct:.1f}% above GTT dip level (\u20b9{gtt:.2f})", "dist_from_gtt_pct": dist_pct}
    return {"status": "WATCH", "status_badge": f"\U0001F441 WATCH ({dist_pct:+.1f}%)",
            "status_badge_class": "badge-gray",
            "status_reason": f"Extended: +{dist_pct:.1f}% above GTT dip level (\u20b9{gtt:.2f}); wait for a pullback",
            "dist_from_gtt_pct": dist_pct}


def _score_candidate(c: dict, eval_res: dict, financial: bool) -> tuple[float, dict]:
    """0-100 score from REAL inputs only. A component with no data is dropped and the
    remaining weights renormalised -- nothing is assumed."""
    comps = {}
    comps["quality"] = float(c["durability_score"])
    prof_metric = c.get("roe_pct") if financial else (c.get("roce_pct") if c.get("roce_pct") is not None else c.get("roe_pct"))
    comps["profitability"] = min(max(float(prof_metric), 0.0), 40.0) / 40.0 * 100.0
    mom_parts = []
    if c.get("trend") in TREND_STATE_POINTS:
        mom_parts.append(TREND_STATE_POINTS[c["trend"]])
    if c.get("rs_rating") is not None:
        mom_parts.append(float(c["rs_rating"]))
    if mom_parts:
        comps["momentum"] = sum(mom_parts) / len(mom_parts)
    pe = c.get("pe")
    # A PE below ~4 is almost always a one-off gain distorting earnings, not a bargain:
    # the valuation part is left out instead of being scored as "very cheap".
    if pe is not None and float(pe) >= 4.0:
        pe = float(pe)
        comps["valuation"] = 100.0 if pe <= 25 else 70.0 if pe <= 40 else 40.0 if pe <= 60 else 10.0
    weights = {"quality": 0.40, "profitability": 0.25, "momentum": 0.25, "valuation": 0.10}
    total_w = sum(weights[k] for k in comps)
    score = sum(comps[k] * weights[k] for k in comps) / total_w
    return round(score, 1), {k: round(v, 1) for k, v in comps.items()}


# ── Fresh technicals from the broker's daily candles ─────────────────────────
# Trend, moving averages and momentum are computed here from INDstocks daily candles
# (the same feed the NIFTY/BANKNIFTY trend analyser uses), NOT read from the desktop scan
# snapshot, which can be days old. Cached per symbol for a few hours. If the candles cannot
# be fetched (e.g. expired token) the candidate falls back to the snapshot values and is
# marked technicals_fresh=False so the staleness is visible.
TECH_TTL_SEC = 6 * 3600
_TECH_CACHE: dict = {}
_HIST_CACHE: dict = {}      # symbol -> daily candle DataFrame (same TTL)


def fresh_history(symbol: str):
    """Daily candle DataFrame behind fresh_technicals (None if unavailable)."""
    if fresh_technicals(symbol, require_ma200=False) is None:
        return None
    return _HIST_CACHE.get(symbol)


def _tech_from_df(df) -> dict | None:
    """Trend / MAs / RSI / volume / returns from a daily candle frame (None if too short)."""
    import trend_engine
    if df is None or df.empty:
        return None
    m = trend_engine._metrics_from_daily(df, None)
    if not m:
        return None
    cls = se.compute_trend_classification(m)
    close = df["Close"]
    return {
        "trend": cls.get("trend"),
        "ltp": float(close.iloc[-1]),
        "ema20": m["ema20"], "ma50": m["ma50"], "ma200": m["ma200"],
        "rsi": m["rsi"], "volume_spike": m["volume_spike"],
        "ret_6m": (float(close.iloc[-1] / close.iloc[-126] - 1.0) * 100.0) if len(close) > 126 else None,
        "ret_1m": (float(close.iloc[-1] / close.iloc[-22] - 1.0) * 100.0) if len(close) > 22 else None,
        "ret_3m": (float(close.iloc[-1] / close.iloc[-64] - 1.0) * 100.0) if len(close) > 64 else None,
        # Average volume of the 10 sessions BEFORE the latest bar: "today's volume vs average"
        # must not have today in its own baseline (it understated the ratio, e.g. 3.25x vs 4.8x).
        "avg_volume_10d": float((df["Volume"].iloc[-11:-1] if len(df) > 11 else df["Volume"]).mean()),
        "bars": len(df),
        "last_bar": str(df.index[-1].date()),
    }


def fresh_momentum(symbol: str, ltp: float | None = None, volume: float | None = None):
    """Momentum score (0-100) from fresh candles using the screener's own score_momentum():
    200/50-day MA position, 52-week return, RSI, volume spike and beta. `ltp` / `volume` let a
    caller pass the LIVE price and volume; beta comes from Tickertape (may be None)."""
    df = fresh_history(symbol)
    if df is None or df.empty:
        return None
    last = float(df["Close"].iloc[-1])
    info = {"currentPrice": float(ltp) if ltp else last, "regularMarketPrice": float(ltp) if ltp else last,
            "volume": float(volume) if volume else float(df["Volume"].iloc[-1]),
            "beta": fundamental_engine.get_fundamentals(symbol, allow_network=False).get("beta")}
    try:
        score, _ = se.score_momentum(info, df)
        return score
    except Exception as exc:
        print(f"[lt_engine] fresh momentum failed for {symbol}: {exc}")
        return None


def prefetch_technicals(symbols: list) -> None:
    """Fill the technicals cache for many symbols at once: INDstocks daily candles, 5 stocks per
    request, paced under the API's rate limit (~5 requests/second) with back-off on HTTP 429.
    Symbols already cached (within TECH_TTL_SEC) are skipped."""
    import requests as _rq
    now = time.time()
    try:
        sec_map = equity_scan.get_security_id_map()
    except Exception as exc:
        print(f"[lt_engine] technicals prefetch skipped: {exc}")
        return
    todo = [s for s in dict.fromkeys(symbols)
            if s in sec_map and not ((_TECH_CACHE.get(s) or (0, None))[0] and now - _TECH_CACHE[s][0] < TECH_TTL_SEC)]
    for i in range(0, len(todo), 5):
        batch = todo[i:i + 5]
        code_to_sym = {f"NSE_{sec_map[s]}": s for s in batch}
        dfs = None
        for attempt in range(5):
            try:
                dfs = equity_scan.fetch_daily_candles_batch(list(code_to_sym))
                break
            except _rq.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                print(f"[lt_engine] candle batch failed: {exc}")
                break
            except Exception as exc:
                print(f"[lt_engine] candle batch failed: {exc}")
                break
        if dfs is None:
            continue
        for code, sym in code_to_sym.items():
            df = dfs.get(code)
            tech = _tech_from_df(df)
            if tech:
                _TECH_CACHE[sym] = (time.time(), tech)
                _HIST_CACHE[sym] = df
        time.sleep(0.2)


def fresh_technicals(symbol: str, require_ma200: bool = True) -> dict | None:
    hit = _TECH_CACHE.get(symbol)
    if not (hit and time.time() - hit[0] < TECH_TTL_SEC):
        prefetch_technicals([symbol])
        hit = _TECH_CACHE.get(symbol)
    if not hit:
        return None
    tech = hit[1]
    return tech if (tech.get("ma200") is not None or not require_ma200) else None


def _qualified_candidates(raw_universe: list, min_price: float, max_price: float) -> list:
    BLOCKING_FLAGS = {"no_statements", "stale", "roe_mismatch"}
    # Stage 1 -- fundamentals (cheap: local cache). Snapshot price is used only as a wide
    # pre-filter; the real price band and the trend are checked on fresh data below.
    stage1 = []
    for row in raw_universe:
        sym = row.get("symbol")
        snap_ltp = float(row.get("ltp") or 0.0)
        if not sym or sym in EXCLUDED_SLOW_PSUS or not (min_price * 0.7 <= snap_ltp <= max_price * 1.4):
            continue
        fund = fundamental_engine.get_fundamentals(sym, allow_network=False)
        if fund.get("durability_score") is None or fund.get("roe_pct") is None or fund.get("npm_pct") is None:
            continue  # no real fundamentals -> cannot be judged
        if BLOCKING_FLAGS & set(fund.get("data_flags") or []):
            continue  # statements stale / inconsistent / missing: not trusted
        if float(fund["npm_pct"]) <= 0 or float(fund["roe_pct"]) < MIN_ROE or float(fund["durability_score"]) < MIN_DURABILITY:
            continue
        c = dict(row)
        for k in ("roe_pct", "roce_pct", "de_ratio", "npm_pct", "rev_growth_pct", "profit_growth_pct", "pe", "pb",
                  "durability_score", "dvm_label", "fy", "as_of", "npm_basis", "growth_basis", "data_flags", "sector"):
            c[k] = fund.get(k)
        eval_res = se.compute_sector_aware_lt_quality(c)
        sector_group = eval_res.get("sector_group") or c.get("sector_group") or "General"
        financial = sector_group == "BFSI" or any(w in (c.get("sector") or "").lower() for w in ("bank", "financ", "insur"))
        if not financial:
            if c.get("roce_pct") is not None and float(c["roce_pct"]) < MIN_ROCE:
                continue
            if c.get("de_ratio") is not None and float(c["de_ratio"]) > MAX_DEBT_TO_EQUITY:
                continue
        stage1.append((c, eval_res, sector_group, financial))

    # Stage 2 -- fresh technicals for the survivors (batched: 5 stocks per INDstocks request)
    prefetch_technicals([c["symbol"] for c, *_ in stage1])
    staged = []
    for c, eval_res, sector_group, financial in stage1:
        tech = fresh_technicals(c["symbol"])
        if tech:
            for k in ("trend", "ltp", "ema20", "ma50", "ma200", "rsi", "volume_spike"):
                c[k] = tech[k]
            c["ret_6m"] = tech.get("ret_6m")
            c["technicals_fresh"] = True
            c["technicals_as_of"] = tech["last_bar"]
        else:
            if row_has_snapshot := (c.get("ma200") is not None and c.get("trend")):
                c["technicals_fresh"] = False      # snapshot fallback, flagged
                c["technicals_as_of"] = "scan snapshot"
            else:
                continue                            # no usable price history at all
        ltp = float(c.get("ltp") or 0.0)
        if not (min_price <= ltp <= max_price):
            continue
        if (c.get("trend") or "") in ("Downtrend", "Distribution"):
            continue
        staged.append((c, eval_res, sector_group, financial))

    # Relative strength: the universe-wide RS rating (1-99 vs NIFTY, fresh candles) when available;
    # otherwise the percentile of 6-month return among these candidates.
    import fresh_rs
    rets = sorted(c["ret_6m"] for c, *_ in staged if c.get("ret_6m") is not None)
    for c, *_ in staged:
        uni = fresh_rs.rs_rating(c["symbol"])
        if uni is not None:
            c["rs_rating"] = float(uni)
            c["rs_source"] = "fresh universe RS"
        elif c.get("ret_6m") is not None and len(rets) > 1:
            import bisect
            c["rs_rating"] = round(bisect.bisect_left(rets, c["ret_6m"]) / (len(rets) - 1) * 99.0, 1)
            c["rs_source"] = "candidate percentile (6M return)"
        else:
            c["rs_rating"] = None

    out = []
    for c, eval_res, sector_group, financial in staged:
        score, breakdown = _score_candidate(c, eval_res, financial)
        item = dict(c)
        item.update(eval_res)
        item["sector_group"] = sector_group
        item["combined_rank_score"] = score
        item["score_breakdown"] = breakdown
        out.append(item)
    out.sort(key=lambda x: x["combined_rank_score"], reverse=True)
    return out


def _div_key(c: dict) -> str:
    """Diversification bucket = the stock's real industry sector; a stock with no
    sector is its own bucket (never capped)."""
    return c.get("sector") or ("UNKNOWN:" + str(c.get("symbol")))


def _select_with_hysteresis(ranked: list, incumbents: list, top_n: int) -> list:
    by_sym = {c["symbol"]: c for c in ranked}
    selected = [by_sym[s] for s in incumbents if s in by_sym][:top_n]   # keep those still qualifying
    counts = {}

    def _count(c):
        g = _div_key(c)
        counts[g] = counts.get(g, 0) + 1

    def _room(c):
        return counts.get(_div_key(c), 0) < MAX_PER_SECTOR_GROUP

    kept = []
    for c in selected:
        if _room(c):
            kept.append(c)
            _count(c)
    selected = kept
    chosen = {c["symbol"] for c in selected}

    # fill empty slots with the best available
    for c in ranked:
        if len(selected) >= top_n:
            break
        if c["symbol"] not in chosen and _room(c):
            selected.append(c)
            chosen.add(c["symbol"])
            _count(c)

    # swap: a challenger replaces the weakest incumbent only if it leads by SWAP_MARGIN
    for c in ranked:
        if c["symbol"] in chosen:
            continue
        weakest = min(selected, key=lambda x: x["combined_rank_score"])
        if c["combined_rank_score"] - weakest["combined_rank_score"] < SWAP_MARGIN:
            break
        g_new, g_old = _div_key(c), _div_key(weakest)
        if g_new != g_old and counts.get(g_new, 0) >= MAX_PER_SECTOR_GROUP:
            continue
        selected.remove(weakest)
        chosen.discard(weakest["symbol"])
        counts[g_old] = counts.get(g_old, 1) - 1
        selected.append(c)
        chosen.add(c["symbol"])
        counts[g_new] = counts.get(g_new, 0) + 1
    selected.sort(key=lambda x: x["combined_rank_score"], reverse=True)
    return selected


def _pick_record(p: dict) -> dict:
    ltp = float(p.get("ltp") or 0.0)
    gtt = _gtt_level(p, ltp)
    rec = {
        "symbol": p.get("symbol"),
        "name": p.get("name") or p.get("symbol"),
        "sector": p.get("sector") or p.get("sector_group") or "",
        "cap_category": p.get("cap_category") or "Small Cap",
        "ltp": ltp,
        "gtt_level": gtt,
        "lt_quality_score": p.get("lt_quality_score"),
        "fundamentals_available": True,
        "durability_score": p.get("durability_score"),
        "dvm_label": p.get("dvm_label"),
        "trend": p.get("trend"),
        "combined_rank_score": p.get("combined_rank_score"),
        "score_breakdown": p.get("score_breakdown"),
        "sector_group": p.get("sector_group"),
        "roe_pct": p.get("roe_pct"),
        "roce_pct": p.get("roce_pct"),
        "de_ratio": p.get("de_ratio"),
        "npm_pct": p.get("npm_pct"),
        "pe": p.get("pe"),
        "ma50": p.get("ma50"),
        "ema20": p.get("ema20"),
        "rev_growth_pct": p.get("rev_growth_pct"),
        "profit_growth_pct": p.get("profit_growth_pct"),
        "fundamentals_as_of": p.get("as_of") or p.get("fy"),
        "fundamentals_basis": {"margin": p.get("npm_basis"), "growth": p.get("growth_basis")},
        "technicals_fresh": p.get("technicals_fresh"),
        "technicals_as_of": p.get("technicals_as_of"),
        "data_flags": p.get("data_flags") or [],
    }
    rec.update(_status_for(p.get("trend"), ltp, gtt))
    return rec


def refresh_live_status(cohort: dict) -> dict:
    """Overlays LIVE quotes (one batched INDmoney call for the picks) and recomputes each
    pick's BUY_NOW / WAIT / WATCH status. If live quotes are unavailable the prices stay at
    the last scan snapshot and the cohort says so (prices_live=False)."""
    picks = cohort.get("picks") or []
    live_ok = False
    try:
        sec_map = equity_scan.get_security_id_map()
        codes = {f"NSE_{sec_map[p['symbol']]}": p for p in picks if p.get("symbol") in sec_map}
        quotes = equity_scan.fetch_live_quotes_batch(list(codes)) if codes else {}
        for code, p in codes.items():
            q = quotes.get(code)
            if q and q.get("ltp"):
                p["ltp"] = float(q["ltp"])
                live_ok = True
    except Exception as exc:
        print(f"[lt_engine] live quote overlay skipped: {exc}")
    for p in picks:
        ltp = float(p.get("ltp") or 0.0)
        p.update(_status_for(p.get("trend"), ltp, _gtt_level(p, ltp)))
    cohort["prices_live"] = live_ok
    cohort["prices_as_of"] = time.time()
    return cohort


def get_or_refresh_monthly_picks(raw_universe: list[dict], top_n: int = 10,
                                 min_price: float = 75.0, max_price: float = 500.0) -> dict:
    """The best `top_n` long-term stocks right now (real fundamentals only), each with a
    BUY_NOW / WAIT / WATCH status from trend and GTT. (Function name kept for callers;
    there is no monthly lock any more -- see the block comment above.)"""
    from datetime import date

    today = date.today()
    now = time.time()
    saved = {}
    if os.path.exists(LT_MONTHLY_PICKS_FILE):
        try:
            with open(LT_MONTHLY_PICKS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            saved = {}
    same_version = saved.get("cap_distribution") == LT_LIST_VERSION
    by_symbol_universe = {r.get("symbol"): r for r in raw_universe if r.get("symbol")}

    fresh = (same_version and saved.get("picks")
             and saved.get("top_n") == top_n
             and (now - float(saved.get("computed_at") or 0)) < LT_REFRESH_SEC
             and all(p.get("fundamentals_available") is True for p in saved["picks"]))
    if fresh:
        # Same list; only refresh live prices and BUY_NOW / WAIT / WATCH status.
        for p in saved["picks"]:
            u_row = by_symbol_universe.get(p.get("symbol"))
            if u_row and u_row.get("ltp"):
                p["ltp"] = float(u_row["ltp"])
            p.update(_status_for(p.get("trend"), float(p.get("ltp") or 0.0),
                                 _gtt_level(p, float(p.get("ltp") or 0.0))))
        saved["updated_at"] = now
        try:
            with open(LT_MONTHLY_PICKS_FILE, "w", encoding="utf-8") as f:
                json.dump(saved, f, indent=2)
        except Exception:
            pass
        return saved

    ranked = _qualified_candidates(raw_universe, min_price, max_price)
    incumbents = [p.get("symbol") for p in (saved.get("picks") or [])] if same_version else []
    selected = _select_with_hysteresis(ranked, incumbents, top_n)
    chosen = {c["symbol"] for c in selected}
    bench = [{"symbol": c["symbol"], "name": c.get("name") or c["symbol"], "ltp": c.get("ltp"),
              "combined_rank_score": c["combined_rank_score"], "trend": c.get("trend")}
             for c in ranked if c["symbol"] not in chosen][:10]

    cohort_data = {
        "month_label": today.strftime("%d %B %Y"),
        "locked_until": today.isoformat(),
        "cap_distribution": LT_LIST_VERSION,
        "min_price": min_price,
        "max_price": max_price,
        "qualified_count": len(ranked),
        "top_n": top_n,
        "selection_rules": {
            "gates": f"durability>={MIN_DURABILITY:.0f}, ROE>={MIN_ROE:.0f}%, net margin>0, "
                     f"ROCE>={MIN_ROCE:.0f}% and D/E<={MAX_DEBT_TO_EQUITY} (banks/NBFCs: ROE only), "
                     "trend (fresh, from daily candles) not Downtrend/Distribution, 200+ days of price history, "
                     "real Tickertape fundamentals only, statements current and consistent",
            "score": "40% durability + 25% profitability + 25% trend/RS + 10% valuation (missing parts dropped)",
            "stability": f"an incumbent is replaced only when beaten by {SWAP_MARGIN:.0f}+ points; max {MAX_PER_SECTOR_GROUP} per industry sector",
        },
        "picks": [_pick_record(p) for p in selected],
        "bench": bench,
        "updated_at": now,
        "computed_at": now,
    }
    try:
        with open(LT_MONTHLY_PICKS_FILE, "w", encoding="utf-8") as f:
            json.dump(cohort_data, f, indent=2)
    except Exception:
        pass
    return cohort_data



if __name__ == "__main__":
    res = scan_lt_discovery(top_n=5, update_live_quotes=False)
    print(f"LT Monthly Cohort: {res.get('monthly_cohort', {}).get('month_label')}")
    for p in res.get("monthly_cohort", {}).get("picks", []):
        print(f"  {p['symbol']:<12} LTP={p.get('ltp')} GTT={p.get('gtt_level')} Status={p.get('status')} Dist={p.get('dist_from_gtt_pct')}% ROE={p.get('roe_pct')}%")
