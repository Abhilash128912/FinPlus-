"""
fundamental_engine.py - Genuine Indian Equity Fundamental Data Engine

Fetches and caches real corporate ratios (ROE, ROCE, P/E, P/B, Debt-to-Equity,
Net Profit Margin, Revenue Growth) for Indian NSE equities from Tickertape only:
reported ratios plus figures CALCULATED from Tickertape's annual financial statements.
screener.in is not used.

Features:
  - 30-day local disk caching in fundamentals_cache.json (financials update quarterly).
  - Rate-limit friendly: respectful throttling between web calls.
  - DuPont and balance sheet derived metrics where direct ratios are missing.
  - No built-in/hardcoded baselines: unknown fundamentals are reported as None.
"""

import json
import os
import re
import time
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "fundamentals_cache.json")
CACHE_TTL_SEC = 30 * 24 * 3600  # off-season refresh interval; see fundamentals_ttl_sec()


def fundamentals_ttl_sec() -> int:
    """How long a stored fundamentals record is treated as fresh. Indian companies publish
    quarterly results roughly 45 days after each quarter ends, so during those result
    seasons figures can change within days (refresh weekly); the rest of the year monthly
    is plenty."""
    from datetime import date
    d = date.today()
    seasons = (((7, 10), (8, 25)), ((10, 10), (11, 25)), ((1, 10), (2, 25)), ((4, 15), (6, 5)))
    for (m1, d1), (m2, d2) in seasons:
        if (m1, d1) <= (d.month, d.day) <= (m2, d2):
            return 7 * 24 * 3600
    return CACHE_TTL_SEC

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# Sources that are NOT real fundamentals: a hardcoded per-stock table and a
# generic "neutral" template (ROE 14 / ROCE 16 / D-E 0.5 / durability 57) that
# once filled the cache for ~1,000 stocks and made unrelated companies look
# identical -- and "GOOD_DURABILITY". Anything with these sources is discarded.
PLACEHOLDER_SOURCES = {"default_neutral", "baseline"}


def _is_rejected_source(v: dict) -> bool:
    src = str((v or {}).get("source") or "")
    return src in PLACEHOLDER_SOURCES or "screener.in" in src


def _drop_placeholders(cache: dict) -> dict:
    return {k: v for k, v in cache.items() if not _is_rejected_source(v)}


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return _drop_placeholders(json.load(f))
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


# ── Tickertape-only fundamentals ─────────────────────────────────────────────
# Every figure here is either reported by Tickertape or CALCULATED from the company's
# own reported annual financial statements (income statement + balance sheet) served by
# Tickertape. screener.in is not used at all. A field that cannot be obtained or
# calculated is None ("not available") -- nothing is assumed.
_TT_BASE = "https://api.tickertape.in"
_TT_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
_FINANCIAL_SECTOR_WORDS = ("bank", "financ", "insur", "nbfc", "asset management", "capital markets", "broking")


def _tt_json(path: str, params: dict | None = None, retries: int = 2):
    """GET a Tickertape endpoint; returns the decoded JSON only when success is true."""
    for attempt in range(retries + 1):
        try:
            r = requests.get(f"{_TT_BASE}{path}", params=params, headers=_TT_HEADERS, timeout=12)
            if r.status_code == 200:
                j = r.json()
                return j if isinstance(j, dict) and j.get("success") else None
            if r.status_code in (403, 429):
                time.sleep(2.0 * (attempt + 1))      # rate limited: back off
            elif r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(0.4 * (attempt + 1))
    return None


def _tt_resolve(sym: str) -> dict | None:
    """Tickertape /stocks/info payload for exactly this NSE ticker, or None.

    Tickertape's internal ids do NOT always equal the NSE ticker (e.g. its id "BEL" is Bella
    Casa Fashion, while Bharat Electronics is "BAJE"), and the old lookup trusted whatever
    came back. The returned info.ticker must equal the requested symbol; a near-miss or a
    substring match is rejected."""
    sym = clean_symbol(sym)

    def _accept(data):
        return data if data and str((data.get("info") or {}).get("ticker") or "").upper() == sym else None

    from urllib.parse import quote
    j = _tt_json(f"/stocks/info/{quote(sym, safe='')}")
    got = _accept((j or {}).get("data"))
    if got:
        return got
    s = _tt_json("/stocks/search", {"text": sym})
    for res in (((s or {}).get("data") or {}).get("searchResults") or []):
        info = ((res.get("stock") or {}).get("info") or {})
        if str(info.get("ticker") or "").upper() == sym and res.get("sid"):
            j2 = _tt_json(f"/stocks/info/{res['sid']}")
            got = _accept((j2 or {}).get("data"))
            if got:
                return got
    return None


def _derive_from_statements(inc: list, bal: list, financial: bool, interim: list | None = None) -> dict:
    """Net margin, revenue growth, D/E and ROCE calculated from the latest reported fiscal
    year's statements. D/E and ROCE are not computed for banks/insurers/NBFCs (their
    balance sheets make those ratios meaningless)."""
    def fy_rows(rows):
        rows = [r for r in (rows or []) if r.get("endDate")]          # drops the TTM row
        return sorted(rows, key=lambda r: r["endDate"], reverse=True)

    inc_all = inc
    inc, bal = fy_rows(inc), fy_rows(bal)
    out: dict = {}
    if not inc:
        return out
    cur = inc[0]
    end = cur["endDate"]
    rev, ni, ebit = cur.get("incTrev"), cur.get("incNinc"), cur.get("incPbi")   # incPbi = profit before interest & tax
    if rev and rev > 0 and ni is not None:
        out["npm_pct"] = round(ni / rev * 100.0, 2)
    if len(inc) > 1 and rev is not None:
        prev = inc[1].get("incTrev")
        if prev and prev > 0:
            out["rev_growth_pct"] = round((rev / prev - 1.0) * 100.0, 2)
    b = next((x for x in bal if x.get("endDate") == end), None)         # same fiscal year only
    if b:
        teq, debt, ta, tcl = b.get("balTeq"), b.get("balTdeb"), b.get("balTota"), b.get("balTcl")
        if not financial:
            if teq and teq > 0 and debt is not None:
                out["de_ratio"] = round(debt / teq, 2)
            if ebit is not None and ta and tcl is not None and (ta - tcl) > 0:
                out["roce_pct"] = round(ebit / (ta - tcl) * 100.0, 2)
        if ni is not None and teq and teq > 0:
            out["roe_from_statements"] = round(ni / teq * 100.0, 2)
    out["fy"] = cur.get("displayPeriod")
    out["fy_end"] = end[:10]
    out["npm_basis"] = out["fy"]
    out["growth_basis"] = out["fy"]

    # More current figures where Tickertape has them: trailing-twelve-month net margin
    # (the row with no end date) and year-on-year growth of the latest reported quarter.
    ttm = next((r for r in (inc_all or []) if not r.get("endDate")), None)
    if ttm and ttm.get("incTrev") and ttm["incTrev"] > 0 and ttm.get("incNinc") is not None:
        out["npm_pct_fy"] = out.get("npm_pct")
        out["npm_pct"] = round(ttm["incNinc"] / ttm["incTrev"] * 100.0, 2)
        out["npm_basis"] = "TTM"
    qs = sorted([r for r in (interim or []) if r.get("endDate")], key=lambda r: r["endDate"], reverse=True)
    if len(qs) >= 5:
        latest, year_ago = qs[0], qs[4]
        lr, yr = latest.get("qIncTrev"), year_ago.get("qIncTrev")
        if lr is not None and yr and yr > 0:
            out["rev_growth_fy_pct"] = out.get("rev_growth_pct")
            out["rev_growth_pct"] = round((lr / yr - 1.0) * 100.0, 2)
            out["growth_basis"] = f"{latest.get('displayPeriod')} vs year earlier"
        ln, yn = latest.get("qIncNinc"), year_ago.get("qIncNinc")
        if ln is not None and yn and yn > 0:
            out["profit_growth_pct"] = round((ln / yn - 1.0) * 100.0, 2)
    if qs:
        out["as_of"] = qs[0].get("displayPeriod")
    return out


def _parse_tickertape_payload(symbol: str, data: dict) -> dict | None:
    """Ratios Tickertape reports directly (ROE, PE, P/B, beta, dividend yield, market cap,
    sector). Margin, growth, D/E and ROCE come from _derive_from_statements."""
    if not data:
        return None
    ratios = data.get("ratios", {}) or {}
    info = data.get("info", {}) or {}
    return {
        "symbol": symbol,
        "name": info.get("name") or symbol,
        "sector": info.get("sector") or "",
        "roe_pct": _parse_float(ratios.get("roe")),
        "roce_pct": None,
        "pe": _parse_float(ratios.get("pe") or ratios.get("ttmPe")),
        "pb": _parse_float(ratios.get("pb")),
        "de_ratio": None,
        "npm_pct": None,
        "rev_growth_pct": None,
        "div_yield": _parse_float(ratios.get("divYield")),
        "beta": _parse_float(ratios.get("beta")),
        "market_cap": _parse_float(ratios.get("marketCap")),
        "source": "tickertape",
        "updated_at": time.time(),
    }


def fetch_combined_fundamentals(symbol: str) -> dict | None:
    """Real fundamentals for one NSE symbol from Tickertape only (name kept for callers).
    Returns None when Tickertape has no exact-ticker match for the symbol."""
    sym = clean_symbol(symbol)
    data = _tt_resolve(sym)
    if not data:
        return None
    base = _parse_tickertape_payload(sym, data)
    sid = data.get("sid")
    financial = any(w in (base.get("sector") or "").lower() for w in _FINANCIAL_SECTOR_WORDS)
    inc = ((_tt_json(f"/stocks/financials/income/{sid}/annual/normal", {"count": 5}) or {}).get("data")) or []
    bal = ((_tt_json(f"/stocks/financials/balancesheet/{sid}/annual/normal", {"count": 5}) or {}).get("data")) or []
    inc_q = ((_tt_json(f"/stocks/financials/income/{sid}/interim/normal", {"count": 6}) or {}).get("data")) or []
    derived = _derive_from_statements(inc, bal, financial, inc_q)
    for k in ("roce_pct", "de_ratio", "npm_pct", "rev_growth_pct"):
        if derived.get(k) is not None:
            base[k] = derived[k]
    for k in ("fy", "fy_end", "npm_basis", "growth_basis", "as_of", "profit_growth_pct",
              "npm_pct_fy", "rev_growth_fy_pct"):
        if derived.get(k) is not None:
            base[k] = derived[k]
    if base.get("roe_pct") is None and derived.get("roe_from_statements") is not None:
        base["roe_pct"] = derived["roe_from_statements"]
    base["sid"] = sid

    # Data-quality flags (free, internal consistency checks; stocks carrying a blocking
    # flag are kept out of the pick lists rather than trusted).
    flags = []
    if not derived:
        flags.append("no_statements")
    else:
        try:
            from datetime import date
            fy_end = date.fromisoformat(derived["fy_end"])
            if (date.today() - fy_end).days > 550:
                flags.append("stale")
        except Exception:
            pass
        rs, rr = derived.get("roe_from_statements"), _parse_float(data.get("ratios", {}).get("roe"))
        if rs is not None and rr is not None and abs(rs - rr) > 15.0:
            flags.append("roe_mismatch")
    roe_now, npm_now = base.get("roe_pct"), base.get("npm_pct")
    growth_now = base.get("rev_growth_pct")
    if ((roe_now is not None and abs(roe_now) > 100) or (npm_now is not None and abs(npm_now) > 90)
            or (growth_now is not None and abs(growth_now) > 1000)):
        flags.append("outlier")     # e.g. growth measured from a near-zero base year
    base["data_flags"] = flags
    base["updated_at"] = time.time()
    base.update(compute_dvm_score(base))
    return base


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

    def _num(key):
        v = fund_data.get(key)
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    roe_v, de_v, beta_v, pe_v, pb_v = _num("roe_pct"), _num("de_ratio"), _num("beta"), _num("pe"), _num("pb")
    sector = (fund_data.get("sector") or "").lower()

    # Durability is built ONLY from the metrics that exist. A missing D/E, beta or
    # sector no longer earns assumed points (it used to be D/E 0.4, beta 1.1 and a flat
    # 15 "moat" points): its component is left out and the score is scaled to the
    # points that were actually available. Without ROE and enough other evidence the
    # score is None ("not available").
    earned, possible = 0.0, 0.0

    if roe_v is not None:                              # 1. Capital efficiency (40)
        roe = min(roe_v, ROE_ROCE_SANITY_CAP)
        pts = 40 if roe >= 25.0 else 35 if roe >= 20.0 else 28 if roe >= 15.0 else 16 if roe >= 10.0 else 8 if roe >= 6.0 else 2
        earned += pts
        possible += 40
    if de_v is not None:                               # 2a. Leverage (18)
        earned += 18 if de_v <= 0.2 else 14 if de_v <= 0.5 else 8 if de_v <= 1.0 else 0
        possible += 18
    if beta_v is not None:                             # 2b. Volatility (17)
        earned += 17 if beta_v <= 0.85 else 12 if beta_v <= 1.15 else 6 if beta_v <= 1.40 else 0
        possible += 17
    if sector:                                         # 3. Moat / predictability (25)
        cyclicals = ["textile", "spinning", "yarn", "sugar", "fertilizer", "gas distribution", "sponge iron", "commodity", "metals"]
        quality_sectors = ["it", "software", "pharma", "fmcg", "consumer", "auto parts", "auto ancillar", "defence", "private bank"]
        earned += 5 if any(k in sector for k in cyclicals) else 25 if any(k in sector for k in quality_sectors) else 15
        possible += 25

    if roe_v is None or possible < 58.0:
        durability_score = None
    else:
        durability_score = round(earned / possible * 100.0, 1)

    # Valuation score (0-100) from whichever of PE / P/B exists
    valuation_score = None
    if pe_v is not None or pb_v is not None:
        val_pts = 50
        if pe_v is not None:
            if 10.0 <= pe_v <= 25.0: val_pts += 25
            elif 25.0 < pe_v <= 40.0: val_pts += 10
            elif pe_v > 60.0: val_pts -= 20
            elif pe_v < 8.0 and roe_v is not None and roe_v < 10.0: val_pts -= 15  # value trap
        if pb_v is not None:
            if 1.0 <= pb_v <= 4.0: val_pts += 25
            elif pb_v > 8.0: val_pts -= 15
        valuation_score = max(5.0, min(100.0, round(val_pts, 1)))

    if durability_score is None:
        dvm_label = None
    elif durability_score >= 70.0:
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

    if cached and _is_rejected_source(cached):
        cached = None  # never serve placeholder or screener.in values
    # No-network reads keep serving a record for up to twice its refresh interval (the
    # background warm loop refreshes at 1x); beyond that it is "not available", not stale-trusted.
    if cached and (now - cached.get("updated_at", 0) < 2 * fundamentals_ttl_sec()):
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


def refresh_stale(symbols: list[str], pace_sec: float = 1.5, max_age_sec: float | None = None) -> int:
    """Synchronous, rate-limited pass over `symbols`: skips anything
    already fresh (real source, within max_age_sec), does a combined fetch
    for everything else, saves the cache periodically. Meant to be called
    from a background thread (see app.py's fundamentals warm loop), not
    inline during a scan -- a full pass over a few hundred symbols at this
    pace takes minutes, which is fine for a periodic warmer and wrong for
    an on-demand scoring call. Returns how many symbols were refreshed."""
    now = time.time()
    if max_age_sec is None:
        max_age_sec = fundamentals_ttl_sec()
    refreshed = 0
    for i, raw_sym in enumerate(symbols):
        sym = clean_symbol(raw_sym)
        cached = _MEM_CACHE.get(sym)
        is_real = cached and cached.get("source") not in (None, "unavailable")
        # Real entries are refreshed after max_age_sec; a symbol Tickertape has no exact
        # match for is only retried after 3 days, so the warm loop is not hammering it.
        if cached and (now - cached.get("updated_at", 0) < (max_age_sec if is_real else 3 * 86400)):
            continue
        try:
            combined = fetch_combined_fundamentals(sym)
            if combined:
                _MEM_CACHE[sym] = combined
                refreshed += 1
            else:
                _MEM_CACHE[sym] = {"symbol": sym, "source": "unavailable", "updated_at": time.time()}
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

