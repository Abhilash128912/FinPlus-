"""
fundamental_engine.py - Genuine Indian Equity Fundamental Data Engine

Fetches and caches real corporate ratios (ROE, ROCE, P/E, P/B, Debt-to-Equity,
Net Profit Margin, Revenue Growth) directly from Screener.in for Indian NSE
equities, replacing broken Yahoo Finance data.

Features:
  - 30-day local disk caching in fundamentals_cache.json (financials update quarterly).
  - Rate-limit friendly: respectful throttling between web calls.
  - DuPont and balance sheet derived metrics where direct ratios are missing.
  - Built-in fallback baselines for offline/resilient startup.
"""

import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "fundamentals_cache.json")
CACHE_TTL_SEC = 30 * 24 * 3600  # 30 days - fundamentals change quarterly

# Pre-seeded baseline values for resilience
PORTFOLIO_FALLBACKS = {
    "RELIANCE": {"roe_pct": 8.91, "roce_pct": 10.3, "pe": 22.8, "pb": 1.88, "de_ratio": 0.42, "npm_pct": 8.2, "rev_growth_pct": 11.2, "div_yield": 0.48},
    "TCS": {"roe_pct": 48.2, "roce_pct": 62.4, "pe": 27.5, "pb": 13.2, "de_ratio": 0.08, "npm_pct": 19.5, "rev_growth_pct": 8.4, "div_yield": 1.45},
    "INFY": {"roe_pct": 31.9, "roce_pct": 40.0, "pe": 13.6, "pb": 4.61, "de_ratio": 0.10, "npm_pct": 16.4, "rev_growth_pct": 6.8, "div_yield": 4.63},
    "HDFCBANK": {"roe_pct": 16.8, "roce_pct": 17.5, "pe": 18.2, "pb": 2.75, "de_ratio": 0.0, "npm_pct": 21.0, "rev_growth_pct": 15.6, "div_yield": 1.15},
    "ICICIBANK": {"roe_pct": 18.5, "roce_pct": 19.2, "pe": 17.4, "pb": 3.10, "de_ratio": 0.0, "npm_pct": 24.5, "rev_growth_pct": 18.2, "div_yield": 0.85},
    "ITC": {"roe_pct": 29.3, "roce_pct": 38.9, "pe": 16.5, "pb": 4.50, "de_ratio": 0.0, "npm_pct": 28.5, "rev_growth_pct": 7.5, "div_yield": 5.58},
    "TATASTEEL": {"roe_pct": 11.7, "roce_pct": 12.5, "pe": 19.4, "pb": 2.24, "de_ratio": 0.85, "npm_pct": 6.2, "rev_growth_pct": 5.2, "div_yield": 2.19},
    "TATAMOTORS": {"roe_pct": 28.4, "roce_pct": 21.2, "pe": 9.8, "pb": 3.45, "de_ratio": 0.72, "npm_pct": 7.1, "rev_growth_pct": 14.5, "div_yield": 0.65},
    "SBIN": {"roe_pct": 16.2, "roce_pct": 16.8, "pe": 10.5, "pb": 1.45, "de_ratio": 0.0, "npm_pct": 18.2, "rev_growth_pct": 14.0, "div_yield": 1.65},
    "BHARTIARTL": {"roe_pct": 15.8, "roce_pct": 14.5, "pe": 42.0, "pb": 7.80, "de_ratio": 1.35, "npm_pct": 9.4, "rev_growth_pct": 12.8, "div_yield": 0.60},
    "BEL": {"roe_pct": 26.5, "roce_pct": 35.2, "pe": 44.5, "pb": 10.8, "de_ratio": 0.0, "npm_pct": 21.4, "rev_growth_pct": 16.5, "div_yield": 0.85},
    "ASHOKLEY": {"roe_pct": 24.2, "roce_pct": 22.8, "pe": 26.5, "pb": 5.60, "de_ratio": 0.35, "npm_pct": 7.5, "rev_growth_pct": 12.0, "div_yield": 2.10},
    "TATAPOWER": {"roe_pct": 14.2, "roce_pct": 13.5, "pe": 31.0, "pb": 3.85, "de_ratio": 1.20, "npm_pct": 9.2, "rev_growth_pct": 10.5, "div_yield": 0.50},
    "NMDC": {"roe_pct": 27.5, "roce_pct": 36.2, "pe": 11.2, "pb": 2.45, "de_ratio": 0.0, "npm_pct": 31.5, "rev_growth_pct": 14.2, "div_yield": 3.85},
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"[fundamental_engine] cache save error: {e}")


_MEM_CACHE = _load_cache()


def clean_symbol(sym: str) -> str:
    s = sym.strip().upper()
    if s.endswith(".NS") or s.endswith(".BO"):
        s = s[:-3]
    return s


def _parse_float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        clean = re.sub(r"[^\d.-]", "", str(val))
        return float(clean) if clean else None
    except Exception:
        return None


def fetch_screener_data(symbol: str) -> dict | None:
    """Fetches key financial ratios for an NSE equity from Screener.in."""
    sym = clean_symbol(symbol)
    urls = [
        f"https://www.screener.in/company/{sym}/consolidated/",
        f"https://www.screener.in/company/{sym}/",
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=8)
            if resp.status_code == 200 and len(resp.text) > 10000:
                soup = BeautifulSoup(resp.text, "html.parser")
                ratios = {}
                for li in soup.select("#top-ratios li"):
                    name_el = li.select_one(".name")
                    val_el = li.select_one(".number")
                    if name_el and val_el:
                        name = name_el.get_text(strip=True)
                        val = val_el.get_text(strip=True).replace(",", "")
                        ratios[name] = val

                roe = _parse_float(ratios.get("ROE"))
                roce = _parse_float(ratios.get("ROCE"))
                pe = _parse_float(ratios.get("Stock P/E"))
                pb = _parse_float(ratios.get("Book Value"))
                market_cap = _parse_float(ratios.get("Market Cap"))
                current_price = _parse_float(ratios.get("Current Price"))
                div_yield = _parse_float(ratios.get("Dividend Yield"))

                # Estimate P/B ratio from Current Price / Book Value if Book Value was returned
                pb_ratio = None
                if current_price and pb and pb > 0:
                    pb_ratio = round(current_price / pb, 2)

                # Search for Debt to equity or Borrowings in Balance Sheet
                de_ratio = None
                npm_pct = None
                rev_growth_pct = None

                # Extract Net Profit Margin & Revenue Growth from Quarterly / P&L tables if present
                try:
                    tables = soup.select("section#profit-loss table.data-table, section#quarters table.data-table")
                    for tbl in tables:
                        rows = tbl.select("tr")
                        sales_row, np_row, opm_row = None, None, None
                        for row in rows:
                            text = row.get_text()
                            if "Sales" in text and not sales_row:
                                sales_row = [td.get_text(strip=True).replace(",", "") for td in row.select("td")]
                            elif "Net Profit" in text and not np_row:
                                np_row = [td.get_text(strip=True).replace(",", "") for td in row.select("td")]
                            elif "OPM %" in text and not opm_row:
                                opm_row = [td.get_text(strip=True).replace(",", "").replace("%", "") for td in row.select("td")]

                        if opm_row and len(opm_row) > 1:
                            val = _parse_float(opm_row[-1])
                            if val is not None:
                                npm_pct = val
                        elif sales_row and np_row and len(sales_row) > 1 and len(np_row) > 1:
                            s_last = _parse_float(sales_row[-1])
                            np_last = _parse_float(np_row[-1])
                            if s_last and np_last and s_last > 0:
                                npm_pct = round((np_last / s_last) * 100, 2)

                        if sales_row and len(sales_row) >= 3:
                            s_curr = _parse_float(sales_row[-1])
                            s_prev = _parse_float(sales_row[-2])
                            if s_curr and s_prev and s_prev > 0:
                                rev_growth_pct = round(((s_curr - s_prev) / s_prev) * 100, 2)
                        if npm_pct is not None:
                            break
                except Exception:
                    pass

                # Parse Borrowings / Equity from Balance sheet for D/E
                try:
                    bs_table = soup.select_one("section#balance-sheet table.data-table")
                    if bs_table:
                        eq_row, res_row, bor_row = None, None, None
                        for row in bs_table.select("tr"):
                            txt = row.get_text()
                            if "Equity Capital" in txt:
                                eq_row = [_parse_float(td.get_text(strip=True).replace(",", "")) for td in row.select("td")]
                            elif "Reserves" in txt:
                                res_row = [_parse_float(td.get_text(strip=True).replace(",", "")) for td in row.select("td")]
                            elif "Borrowings" in txt:
                                bor_row = [_parse_float(td.get_text(strip=True).replace(",", "")) for td in row.select("td")]
                        if bor_row and len(bor_row) > 1:
                            bor = bor_row[-1] or 0.0
                            eq = (eq_row[-1] if eq_row and len(eq_row) > 1 else 0.0) or 0.0
                            res = (res_row[-1] if res_row and len(res_row) > 1 else 0.0) or 0.0
                            net_worth = eq + res
                            if net_worth > 0:
                                de_ratio = round(bor / net_worth, 2)
                            else:
                                de_ratio = 0.0 if bor == 0 else 2.0
                except Exception:
                    pass

                # de_ratio/npm_pct/rev_growth_pct: None when the balance-sheet or
                # P&L table parse didn't find a value, not a guessed number --
                # a heuristic guess here previously produced e.g. de_ratio=0.0
                # ("debt-free") for stocks whose balance sheet was never
                # actually read, which is exactly backwards for a metric that
                # gates real stock picks (see penny_engine's debt-free gate).
                out = {
                    "symbol": sym,
                    "roe_pct": roe,
                    "roce_pct": roce,
                    "pe": pe,
                    "pb": pb_ratio,
                    "de_ratio": de_ratio,
                    "npm_pct": npm_pct,
                    "rev_growth_pct": rev_growth_pct,
                    "div_yield": div_yield,
                    "market_cap": market_cap,
                    "source": "screener.in",
                    "updated_at": time.time(),
                }
                return out
            elif resp.status_code == 404:
                continue
        except Exception:
            continue
    return None


def fetch_tickertape_data(symbol: str) -> dict | None:
    """Fetches real corporate fundamentals, ratios, and risk metrics from Tickertape API."""
    sym = clean_symbol(symbol)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    # 1. Direct ticker lookup
    try:
        url = f"https://api.tickertape.in/stocks/info/{sym}"
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            res = r.json()
            if res.get("success") and res.get("data"):
                return _parse_tickertape_payload(sym, res["data"])
    except Exception:
        pass

    # 2. Search fallback to resolve Tickertape SID (e.g. BEL -> BAJE, FILATEX -> FLTX)
    try:
        s_url = f"https://api.tickertape.in/search?text={sym}"
        sr = requests.get(s_url, headers=headers, timeout=5)
        if sr.status_code == 200:
            sdata = sr.json().get("data", {})
            stocks = sdata.get("stocks", [])
            for st in stocks:
                ticker = (st.get("ticker") or "").upper()
                name = (st.get("name") or "").upper()
                sid = st.get("sid")
                if sid and (ticker == sym or sym in name or (st.get("slug") and sym in st.get("slug", "").upper())):
                    r2 = requests.get(f"https://api.tickertape.in/stocks/info/{sid}", headers=headers, timeout=5)
                    if r2.status_code == 200 and r2.json().get("success"):
                        return _parse_tickertape_payload(sym, r2.json().get("data"))
    except Exception:
        pass

    return None


def _parse_tickertape_payload(symbol: str, data: dict) -> dict | None:
    """Tickertape's /stocks/info ratios object does NOT include net profit
    margin, revenue growth, ROCE, or debt-to-equity at all (confirmed
    2026-09-11 against the live response: only roe/pe/pb/beta/divYield/
    marketCap/eps/bps etc. are present) -- those four fields are left None
    here rather than guessed, so a real value from a second source (see
    fetch_combined_fundamentals) can fill them in, and so a field that's
    genuinely unknown reads as unknown, not as a confident-looking number
    that happens to be wrong for every stock it's applied to."""
    if not data:
        return None
    ratios = data.get("ratios", {}) or {}
    info = data.get("info", {}) or {}

    roe = _parse_float(ratios.get("roe"))
    pe = _parse_float(ratios.get("pe") or ratios.get("ttmPe"))
    pb = _parse_float(ratios.get("pb"))
    div_yield = _parse_float(ratios.get("divYield"))
    beta = _parse_float(ratios.get("beta"))
    market_cap = _parse_float(ratios.get("marketCap"))
    sector = info.get("sector") or ""
    name = info.get("name") or symbol

    return {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "roe_pct": roe,
        "roce_pct": None,   # not in this endpoint's payload
        "pe": pe,
        "pb": pb,
        "de_ratio": None,   # not in this endpoint's payload
        "npm_pct": None,    # not in this endpoint's payload
        "rev_growth_pct": None,  # not in this endpoint's payload
        "div_yield": div_yield,
        "beta": beta,
        "market_cap": market_cap,
        "source": "tickertape",
        "updated_at": time.time(),
    }


def fetch_combined_fundamentals(symbol: str) -> dict | None:
    """Tickertape first (fast JSON, reliable for roe/pe/pb/beta/div_yield),
    then screener.in to fill in whatever Tickertape doesn't carry (npm_pct,
    rev_growth_pct, de_ratio, roce_pct). Merges rather than picking one
    source, since neither alone covers the full field set. A field still
    None after both is genuinely unavailable, not fabricated. Returns None
    only if BOTH sources fail outright."""
    tt = fetch_tickertape_data(symbol)
    time.sleep(0.15)
    sc = fetch_screener_data(symbol)

    if tt is None and sc is None:
        return None

    merged = dict(sc) if sc else {}
    if tt:
        for k, v in tt.items():
            if v is not None or k not in merged:
                merged[k] = v
    # Whichever source had it; screener.in is the only source for these three.
    if sc:
        for k in ("npm_pct", "rev_growth_pct", "de_ratio", "roce_pct"):
            if merged.get(k) is None and sc.get(k) is not None:
                merged[k] = sc[k]

    sources = [s for s in (("tickertape" if tt else None), ("screener.in" if sc else None)) if s]
    merged["symbol"] = clean_symbol(symbol)
    merged["source"] = "+".join(sources)
    merged["updated_at"] = time.time()

    dvm = compute_dvm_score(merged)
    merged.update(dvm)
    return merged


def compute_dvm_score(fund_data: dict) -> dict:
    """
    Computes an internal, Trendlyne-DVM-*inspired* durability/valuation score
    (not Trendlyne's actual proprietary score -- an approximation built from
    public ratios; callers displaying this should label it as such):
      - Durability Score (0-100): Capital Efficiency (ROE/ROCE 40%), Solvency & Volatility (35%), Moat & Sector (25%).
      - Valuation Score (0-100): P/E and P/B percentile sanity.

    ROE/ROCE are capped at ROE_ROCE_SANITY_CAP before scoring: a genuine
    reported figure can still be a corporate-action artifact rather than a
    business-quality signal -- Raymond showed 168% ROE on screener.in as of
    2026-09-11, a post-demerger equity-base effect, not 168% actual return
    on capital. Capping it keeps one distorted ratio from maxing out the
    capital-efficiency score. The raw, uncapped value is left untouched
    everywhere else (this function's output, not the stored fundamentals
    record) so the real number is still visible to anyone who looks.
    """
    ROE_ROCE_SANITY_CAP = 60.0

    roe_raw = float(fund_data.get("roe_pct") or 0.0)
    roce_raw = float(fund_data.get("roce_pct") or (roe_raw * 1.2 if roe_raw > 0 else 0.0))
    roe = min(roe_raw, ROE_ROCE_SANITY_CAP)
    roce = min(roce_raw, ROE_ROCE_SANITY_CAP)
    de = float(fund_data.get("de_ratio") or 0.4)
    beta = float(fund_data.get("beta") or 1.1)
    pe = float(fund_data.get("pe") or 25.0)
    pb = float(fund_data.get("pb") or 3.0)
    sector = (fund_data.get("sector") or "").lower()

    # 1. Capital Efficiency (40 pts)
    cap_pts = 0
    if roe >= 25.0: cap_pts = 40
    elif roe >= 20.0: cap_pts = 35
    elif roe >= 15.0: cap_pts = 28
    elif roe >= 10.0: cap_pts = 16
    elif roe >= 6.0: cap_pts = 8
    else: cap_pts = 2

    # 2. Solvency & Volatility Risk (35 pts)
    solv_pts = 0
    if de <= 0.2: solv_pts += 18
    elif de <= 0.5: solv_pts += 14
    elif de <= 1.0: solv_pts += 8
    else: solv_pts += 0

    if beta <= 0.85: solv_pts += 17
    elif beta <= 1.15: solv_pts += 12
    elif beta <= 1.40: solv_pts += 6
    else: solv_pts += 0

    # 3. Moat & Business Predictability (25 pts)
    moat_pts = 15
    cyclicals = ["textile", "spinning", "yarn", "sugar", "fertilizer", "gas distribution", "sponge iron", "commodity", "metals"]
    quality_sectors = ["it", "software", "pharma", "fmcg", "consumer", "auto parts", "auto ancillar", "defence", "private bank"]
    if any(k in sector for k in cyclicals):
        moat_pts = 5  # Severe discount for pure commodity/cyclical margins
    elif any(k in sector for k in quality_sectors):
        moat_pts = 25  # Premium for pricing power and repeat business

    durability_score = round(cap_pts + solv_pts + moat_pts, 1)

    # Valuation Score (0-100)
    val_pts = 50
    if 10.0 <= pe <= 25.0: val_pts += 25
    elif 25.0 < pe <= 40.0: val_pts += 10
    elif pe > 60.0: val_pts -= 20
    elif pe < 8.0 and roe < 10.0: val_pts -= 15  # Value trap

    if 1.0 <= pb <= 4.0: val_pts += 25
    elif pb > 8.0: val_pts -= 15
    valuation_score = max(5.0, min(100.0, round(val_pts, 1)))

    if durability_score >= 70.0:
        dvm_label = "HIGH_DURABILITY"
    elif durability_score >= 55.0:
        dvm_label = "GOOD_DURABILITY"
    elif durability_score >= 40.0:
        dvm_label = "AVERAGE"
    else:
        dvm_label = "LOW_DURABILITY"

    return {
        "durability_score": durability_score,
        "valuation_score": valuation_score,
        "dvm_label": dvm_label,
    }


def get_fundamentals(symbol: str, allow_network: bool = False) -> dict:
    """Returns fundamental metrics for a symbol, cache-first.

    allow_network=False (the default, used by on-demand scoring calls during
    a scan) never blocks on a network call -- it only reads whatever's
    already cached. Real data gets into the cache via the background
    warmer (see refresh_stale / app.py's warm loop), not via this call.
    allow_network=True does a synchronous combined fetch when nothing
    usable is cached yet -- used by the warmer itself and any caller that
    can afford to wait.

    A symbol with no real data anywhere gets source="unavailable" and every
    numeric field None -- never a confident-looking fabricated number.
    compute_sector_aware_lt_quality() and the penny debt-free gate already
    treat None as "unknown, don't assume," which is the correct behavior
    for a metric that gates real stock picks.
    """
    sym = clean_symbol(symbol)
    cached = _MEM_CACHE.get(sym)
    now = time.time()

    if cached and (now - cached.get("updated_at", 0) < CACHE_TTL_SEC):
        if "durability_score" not in cached:
            dvm = compute_dvm_score(cached)
            cached.update(dvm)
            _MEM_CACHE[sym] = cached
        return cached

    if allow_network:
        combined = fetch_combined_fundamentals(sym)
        if combined:
            _MEM_CACHE[sym] = combined
            _save_cache(_MEM_CACHE)
            return combined

    # Fallback to portfolio baselines -- a real, if static, known-good
    # number for a small set of well-known large caps.
    fb = PORTFOLIO_FALLBACKS.get(sym)
    if fb:
        res = {"symbol": sym, **fb, "source": "baseline", "updated_at": now}
        dvm = compute_dvm_score(res)
        res.update(dvm)
        _MEM_CACHE[sym] = res
        return res

    unavailable = {
        "symbol": sym,
        "roe_pct": None,
        "roce_pct": None,
        "pe": None,
        "pb": None,
        "de_ratio": None,
        "npm_pct": None,
        "rev_growth_pct": None,
        "div_yield": None,
        "beta": None,
        "durability_score": None,
        "valuation_score": None,
        "dvm_label": None,
        "source": "unavailable",
        "updated_at": now,
    }
    _MEM_CACHE[sym] = unavailable
    return unavailable


def to_legacy_yfinance_shape(fund: dict) -> dict:
    """Bridges this module's field names/units to the raw yfinance .info
    names and units that screener_engine.score_strength()/score_value()
    read. Those two functions predate this module and expect
    returnOnEquity/trailingPE/priceToBook/debtToEquity/profitMargins/
    revenueGrowth -- calling them with roe_pct/pe/pb/de_ratio/npm_pct/
    rev_growth_pct silently reads as all-missing (confirmed 2026-09-11:
    penny_engine's score_strength/score_value both returned 0.0 for a
    stock with real roe_pct=8.91/pe=22.8/de_ratio=0.45/npm_pct=15.0 on
    file, because none of those keys exist under yfinance's names). Units
    also differ: debtToEquity is a *percentage* in yfinance (divided by
    100 downstream) while de_ratio here is already a ratio; profitMargins/
    revenueGrowth are *ratios* in yfinance (multiplied by 100 downstream)
    while npm_pct/rev_growth_pct here are already percentages. roe is the
    one field score_strength auto-detects (treats anything > 1.5 as
    already-percentage), so it needs no unit conversion, only the rename.
    """
    out = dict(fund)
    if fund.get("roe_pct") is not None:
        out["returnOnEquity"] = fund["roe_pct"]
    if fund.get("pe") is not None:
        out["trailingPE"] = fund["pe"]
    if fund.get("pb") is not None:
        out["priceToBook"] = fund["pb"]
    if fund.get("de_ratio") is not None:
        out["debtToEquity"] = fund["de_ratio"] * 100.0
    if fund.get("npm_pct") is not None:
        out["profitMargins"] = fund["npm_pct"] / 100.0
    if fund.get("rev_growth_pct") is not None:
        out["revenueGrowth"] = fund["rev_growth_pct"] / 100.0
    if fund.get("div_yield") is not None:
        out["dividendYield"] = fund["div_yield"] / 100.0
    return out


def refresh_stale(symbols: list[str], pace_sec: float = 1.5, max_age_sec: float = CACHE_TTL_SEC) -> int:
    """Synchronous, rate-limited pass over `symbols`: skips anything
    already fresh (real source, within max_age_sec), does a combined fetch
    for everything else, saves the cache periodically. Meant to be called
    from a background thread (see app.py's fundamentals warm loop), not
    inline during a scan -- a full pass over a few hundred symbols at this
    pace takes minutes, which is fine for a periodic warmer and wrong for
    an on-demand scoring call. Returns how many symbols were refreshed."""
    now = time.time()
    refreshed = 0
    for i, raw_sym in enumerate(symbols):
        sym = clean_symbol(raw_sym)
        cached = _MEM_CACHE.get(sym)
        is_real = cached and cached.get("source") not in (None, "unavailable")
        if is_real and (now - cached.get("updated_at", 0) < max_age_sec):
            continue
        try:
            combined = fetch_combined_fundamentals(sym)
            if combined:
                _MEM_CACHE[sym] = combined
                refreshed += 1
        except Exception as e:
            print(f"[fundamental_engine] refresh failed for {sym}: {e}")
        time.sleep(pace_sec)
        if refreshed and refreshed % 20 == 0:
            _save_cache(_MEM_CACHE)
    if refreshed:
        _save_cache(_MEM_CACHE)
    return refreshed


if __name__ == "__main__":
    for test_sym in ["ITC", "BEL", "GAIL", "FILATEX", "JAMNAAUTO", "TCS"]:
        res = get_fundamentals(test_sym, allow_network=True)
        print(f"[{test_sym}] ROE={res.get('roe_pct')}% PE={res.get('pe')} Durability={res.get('durability_score')} ({res.get('dvm_label')}) Source={res.get('source')}")

