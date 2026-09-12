"""
screener_views.py - Terminal Views Matching the Dashboard Design System

Uses the exact same typography, palette, card elevations, glowing section bars,
meta pills, stat tiles, and list tables as the Dashboard and Intraday screens.
"""

def _fmt(val, decimals=2):
    if val is None:
        return "—"
    try:
        f = float(val)
        if decimals == 0:
            return f"{int(round(f)):,}"
        return f"{f:,.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


def _dvm_badge(p: dict) -> tuple[str, str, str]:
    """(label_text, badge_css_class, title_attr) for a pick's DVM badge.

    durability_score/dvm_label are None when fundamental_engine has no real
    data for this symbol yet (source == "unavailable") -- previously this
    silently fell back to "50" / "GOOD", a confident-looking score with
    nothing real behind it. Shows an honest "No data" badge instead until
    the background fundamentals warmer (app.py) actually populates real
    numbers for the symbol."""
    score = p.get("durability_score")
    if score is None:
        return "No data", "call-none", "Fundamentals not yet fetched for this symbol"
    label = (p.get("dvm_label") or "AVERAGE").replace("_", " ")
    cls = "badge-green" if "HIGH" in label else "badge-purple" if "GOOD" in label else "badge-yellow"
    return f"DVM {_fmt(score, 0)}", cls, f"{label.title()} · source: {p.get('source', 'unknown')}"


FILTER_CSS = """
    .filter-bar {
      display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end;
      background: rgba(26, 31, 46, 0.75); border: 1px solid var(--border); border-radius: 10px;
      padding: 12px 16px; margin-bottom: 14px;
    }
    .filter-group { display: flex; flex-direction: column; gap: 4px; }
    .filter-group label { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
    .filter-group select, .filter-group input {
      background: var(--panel); border: 1px solid var(--border); color: var(--text);
      padding: 7px 11px; border-radius: 6px; font-size: 12.5px; outline: none; font-family: inherit;
    }
    .filter-group select:focus, .filter-group input:focus { border-color: #6366f1; }
    .filter-reset {
      background: rgba(99, 102, 241, 0.12); border: 1px solid var(--border); color: #818cf8;
      padding: 7px 14px; border-radius: 6px; font-size: 12.5px; font-weight: 600; cursor: pointer;
      transition: all 0.15s; height: 33px;
    }
    .filter-reset:hover { background: rgba(99, 102, 241, 0.25); color: #fff; }
    th.sortable { cursor: pointer; user-select: none; transition: background 0.15s, color 0.15s; }
    th.sortable:hover { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
    th.sortable .sort-arrow { font-size: 10.5px; margin-left: 4px; opacity: 0.5; }
    th.sort-active { color: #818cf8 !important; }
    th.sort-active .sort-arrow { opacity: 1; color: #a5b4fc; }
"""

FILTER_JS = """
<script>
function initTableFeatures(targetId) {
  const table = document.getElementById(targetId);
  const bar = document.querySelector('.filter-bar[data-target="' + targetId + '"]');
  if (!table || !bar) return;

  // 1. Populate 'Filter by Title / Column' dropdown with exact table headers
  const colSelect = bar.querySelector('.f-col');
  const headers = table.querySelectorAll('thead th');
  if (colSelect && colSelect.options.length <= 1) {
    headers.forEach((th, idx) => {
      const title = th.innerText.replace(/[▲▼⇅]/g, '').trim();
      if (title && title !== '#') {
        const opt = document.createElement('option');
        opt.value = idx;
        opt.textContent = title;
        colSelect.appendChild(opt);
      }
    });
  }

  // 2. Populate Sector dropdown dynamically from table
  const secSelect = bar.querySelector('.f-sector');
  if (secSelect && secSelect.options.length <= 1) {
    const sectors = new Set();
    table.querySelectorAll('tbody tr').forEach(r => {
      const s = r.getAttribute('data-sector') || '';
      if (s && s !== '—') sectors.add(s);
    });
    Array.from(sectors).sort().forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s;
      secSelect.appendChild(opt);
    });
    if (sectors.size === 0 && secSelect.parentElement) {
      secSelect.parentElement.style.display = 'none';
    }
  }

  // 3. Make all headers clickable to sort by that Title
  headers.forEach((th, colIdx) => {
    if (!th.classList.contains('sortable')) {
      th.classList.add('sortable');
      const arrow = document.createElement('span');
      arrow.className = 'sort-arrow';
      arrow.textContent = ' ⇅';
      th.appendChild(arrow);
      th.addEventListener('click', () => sortTableByColumn(targetId, colIdx));
    }
  });

  applyMultiFilter(targetId);
}

function applyMultiFilter(targetId) {
  const bar = document.querySelector('.filter-bar[data-target="' + targetId + '"]');
  const table = document.getElementById(targetId);
  if (!bar || !table) return;

  const search = (bar.querySelector('.f-search') ? bar.querySelector('.f-search').value : '').toLowerCase().trim();
  const colFilter = bar.querySelector('.f-col') ? bar.querySelector('.f-col').value : 'all';
  const trend = bar.querySelector('.f-trend') ? bar.querySelector('.f-trend').value : 'all';
  const cap = bar.querySelector('.f-cap') ? bar.querySelector('.f-cap').value : 'all';
  const signal = bar.querySelector('.f-signal') ? bar.querySelector('.f-signal').value : 'all';
  const sector = bar.querySelector('.f-sector') ? bar.querySelector('.f-sector').value : 'all';
  const priceRange = bar.querySelector('.f-price') ? bar.querySelector('.f-price').value : 'all';

  const rows = table.querySelectorAll('tbody tr');
  let visible = 0;

  rows.forEach(r => {
    const rTrend = r.getAttribute('data-trend') || '';
    const rCap = r.getAttribute('data-cap') || '';
    const rSignal = r.getAttribute('data-signal') || '';
    const rSearch = r.getAttribute('data-search') || '';
    const rSector = r.getAttribute('data-sector') || '';
    const rPrice = parseFloat(r.getAttribute('data-price') || '0');

    let ok = true;

    // Search by title/column or all titles
    if (search) {
      if (colFilter === 'all') {
        if (!rSearch.toLowerCase().includes(search) && !r.innerText.toLowerCase().includes(search)) {
          ok = false;
        }
      } else {
        const cell = r.cells[parseInt(colFilter)];
        if (!cell || !cell.innerText.toLowerCase().includes(search)) {
          ok = false;
        }
      }
    }

    if (trend !== 'all' && !rTrend.includes(trend)) ok = false;
    if (cap !== 'all' && !rCap.toLowerCase().includes(cap.toLowerCase())) ok = false;
    if (signal !== 'all' && !rSignal.includes(signal)) ok = false;
    if (sector !== 'all' && rSector !== sector) ok = false;

    if (priceRange === 'u50' && !(rPrice < 50)) ok = false;
    else if (priceRange === '50-100' && !(rPrice >= 50 && rPrice <= 100)) ok = false;
    else if (priceRange === '100-250' && !(rPrice > 100 && rPrice <= 250)) ok = false;
    else if (priceRange === '250-500' && !(rPrice > 250 && rPrice <= 500)) ok = false;
    else if (priceRange === 'a500' && !(rPrice > 500)) ok = false;

    r.style.display = ok ? '' : 'none';
    if (ok) visible++;
  });

  const countEl = bar.querySelector('.f-count');
  if (countEl) {
    countEl.textContent = 'Showing ' + visible + ' of ' + rows.length + ' stocks';
  }
}

let sortDirections = {};
function sortTableByColumn(targetId, colIdx) {
  const table = document.getElementById(targetId);
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const key = targetId + '_' + colIdx;
  const asc = !sortDirections[key];
  sortDirections[key] = asc;

  // Clear other active headers
  table.querySelectorAll('thead th').forEach((th, idx) => {
    th.classList.remove('sort-active');
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = ' ⇅';
    if (idx === colIdx) {
      th.classList.add('sort-active');
      if (arrow) arrow.textContent = asc ? ' ▲' : ' ▼';
    }
  });

  rows.sort((a, b) => {
    const valA = (a.cells[colIdx] ? a.cells[colIdx].innerText : '').trim();
    const valB = (b.cells[colIdx] ? b.cells[colIdx].innerText : '').trim();

    // Clean numbers
    const cleanNum = s => parseFloat(s.replace(/[₹,%\s+]/g, ''));
    const numA = cleanNum(valA);
    const numB = cleanNum(valB);

    if (!isNaN(numA) && !isNaN(numB)) {
      return asc ? numA - numB : numB - numA;
    }
    return asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
  });

  rows.forEach(r => tbody.appendChild(r));
}

function resetMultiFilter(targetId) {
  const bar = document.querySelector('.filter-bar[data-target="' + targetId + '"]');
  if (!bar) return;
  const s = bar.querySelector('.f-search'); if (s) s.value = '';
  const col = bar.querySelector('.f-col'); if (col) col.value = 'all';
  const t = bar.querySelector('.f-trend'); if (t) t.value = 'all';
  const c = bar.querySelector('.f-cap'); if (c) c.value = 'all';
  const sig = bar.querySelector('.f-signal'); if (sig) sig.value = 'all';
  const sec = bar.querySelector('.f-sector'); if (sec) sec.value = 'all';
  const pr = bar.querySelector('.f-price'); if (pr) pr.value = 'all';
  applyMultiFilter(targetId);
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.filter-bar').forEach(bar => {
    const target = bar.getAttribute('data-target');
    if (target) initTableFeatures(target);
  });
});
</script>
"""

def _render_filter_bar(target_id: str, show_trend: bool = True, show_cap: bool = True, show_signal: bool = True, show_sector: bool = True, show_price: bool = True) -> str:
    trend_opts = f'''
      <div class="filter-group">
        <label>Trend Phase</label>
        <select class="f-trend" onchange="applyMultiFilter('{target_id}')">
          <option value="all">All Trends</option>
          <option value="Strong Uptrend">🚀 Strong Uptrend</option>
          <option value="Uptrend">📈 Uptrend</option>
          <option value="Accumulation">🟢 Accumulation Phase</option>
          <option value="Consolidation">🟡 Consolidation Phase</option>
          <option value="Distribution">🟠 Distribution Phase</option>
          <option value="Downtrend">🔻 Downtrend</option>
        </select>
      </div>
    ''' if show_trend else ''

    cap_opts = f'''
      <div class="filter-group">
        <label>Market Cap</label>
        <select class="f-cap" onchange="applyMultiFilter('{target_id}')">
          <option value="all">All Caps</option>
          <option value="Large">Large Cap</option>
          <option value="Mid">Mid Cap</option>
          <option value="Small">Small Cap</option>
        </select>
      </div>
    ''' if show_cap else ''

    sig_opts = f'''
      <div class="filter-group">
        <label>Signal</label>
        <select class="f-signal" onchange="applyMultiFilter('{target_id}')">
          <option value="all">All Signals</option>
          <option value="BUY">🚀 BUY NOW / DIP</option>
          <option value="WAIT">⏳ WAIT</option>
        </select>
      </div>
    ''' if show_signal else ''

    sec_opts = f'''
      <div class="filter-group">
        <label>Sector</label>
        <select class="f-sector" onchange="applyMultiFilter('{target_id}')">
          <option value="all">All Sectors</option>
        </select>
      </div>
    ''' if show_sector else ''

    price_opts = f'''
      <div class="filter-group">
        <label>Price Range</label>
        <select class="f-price" onchange="applyMultiFilter('{target_id}')">
          <option value="all">All Prices</option>
          <option value="u50">&lt; ₹50</option>
          <option value="50-100">₹50 – ₹100</option>
          <option value="100-250">₹100 – ₹250</option>
          <option value="250-500">₹250 – ₹500</option>
          <option value="a500">&gt; ₹500</option>
        </select>
      </div>
    ''' if show_price else ''

    return f'''
    <div class="filter-bar" data-target="{target_id}">
      <div class="filter-group">
        <label>Filter By Title / Column</label>
        <select class="f-col" onchange="applyMultiFilter('{target_id}')">
          <option value="all">🔍 All Titles / Columns</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Search Query</label>
        <input type="text" class="f-search" placeholder="Type to filter..." oninput="applyMultiFilter('{target_id}')">
      </div>
      {trend_opts}
      {cap_opts}
      {sig_opts}
      {sec_opts}
      {price_opts}
      <button class="filter-reset" onclick="resetMultiFilter('{target_id}')">↺ Reset</button>
      <span class="f-count" style="margin-left:auto;font-size:12.5px;color:var(--muted);align-self:center"></span>
    </div>
    '''


# ---------------- SWING VIEW ----------------
def render_swing_page(state: dict, nav_bar_fn, style_css: str) -> str:
    result = state.get("result") or {}
    picks = result.get("picks") or []
    updated_at = state.get("updated_at")
    running = state.get("running")

    updated_str = updated_at.strftime('%H:%M:%S UTC') if updated_at else "Computing..."
    buy_now_count = sum(1 for p in picks if "BUY" in (p.get("status") or p.get("swing_action") or ""))
    avg_roe = (
        round(sum(float(p.get("roe_pct") or 0) for p in picks) / len(picks), 1)
        if picks else 0.0
    )

    stats = [
        ("CANDIDATE UNIVERSE", result.get("total_candidates", 0), "var(--muted)"),
        ("QUALIFIED SETUPS", result.get("qualified_count", 0), "var(--green)"),
        ("BUY NOW / DIP", buy_now_count, "#818cf8"),
        ("AVG ROE (SCREENER.IN)", f"{avg_roe}%", "var(--amber)"),
    ]

    stat_html = "".join(
        f'<div class="stat-tile"><div class="n" style="color:{c}">{n}</div><div class="l">{lbl}</div></div>'
        for lbl, n, c in stats
    )

    # Top Conviction Cards (top 4 picks)
    top_cards = []
    for p in picks[:4]:
        sym = p.get("symbol")
        ltp = _fmt(p.get("ltp"))
        action = p.get("swing_action") or p.get("status") or "WAIT"
        badge_cls = "badge-green" if "BUY" in action else "badge-purple" if "BREAKOUT" in action else "badge-yellow"
        badge_txt = p.get("status_badge") or action

        score = _fmt(p.get("swing_score"), 0)
        setup_q = _fmt(p.get("setup_score"), 0)
        entry_q = _fmt(p.get("entry_score"), 0)

        sl = _fmt(p.get("swing_sl"))
        t1 = _fmt(p.get("swing_t1"))
        t2 = _fmt(p.get("swing_t2"))
        rr = _fmt(p.get("risk_reward"), 1)

        roe = _fmt(p.get("roe_pct"), 1)
        roce = _fmt(p.get("roce_pct"), 1)
        de = _fmt(p.get("de_ratio"), 2)
        pe = _fmt(p.get("pe"), 1)
        fib = p.get("fib_badge") or "—"
        rs = _fmt(p.get("rs_rating"), 0)

        top_cards.append(f"""
        <div class="card">
          <div class="card-top">
            <span class="card-title"><span class="live-dot"></span>{sym}</span>
            <span class="badge {badge_cls}">{badge_txt}</span>
          </div>
          <div style="font-size:12.5px;color:var(--muted);margin-top:2px">{p.get('sector') or p.get('name', '')}</div>
          <div class="ltp-head">
            <div class="ltp">₹{ltp}</div>
            <div style="text-align:right">
              <span class="badge badge-green" style="padding:4px 10px;font-size:12.5px">Score {score}</span>
            </div>
          </div>
          <div style="display:flex;gap:6px;margin:6px 0 10px">
            <span class="badge badge-purple" style="padding:3px 8px;font-size:11.5px">Setup {setup_q}</span>
            <span class="badge badge-yellow" style="padding:3px 8px;font-size:11.5px">Entry {entry_q}</span>
            <span class="badge call-none" style="padding:3px 8px;font-size:11.5px">RS {rs}</span>
          </div>
          <table class="kv">
            <tr><td>Stop Loss (ATR)</td><td style="color:var(--red)">₹{sl}</td></tr>
            <tr><td>Target 1</td><td style="color:var(--green)">₹{t1}</td></tr>
            <tr><td>Target 2</td><td style="color:#38bdf8">₹{t2}</td></tr>
            <tr><td>Risk : Reward</td><td>1 : {rr}</td></tr>
            <tr><td>Fibonacci Level</td><td style="font-size:12.5px;color:var(--muted)">{fib}</td></tr>
            <tr><td>ROE / ROCE</td><td style="color:var(--green)">{roe}% / {roce}%</td></tr>
            <tr><td>Debt-to-Equity / P/E</td><td>{de} / {pe}</td></tr>
          </table>
        </div>""")

    # Table rows
    rows = []
    for p in picks:
        sym = p.get("symbol")
        ltp = _fmt(p.get("ltp"))
        score = _fmt(p.get("swing_score"), 0)
        action = p.get("swing_action") or p.get("status") or "WAIT"
        badge_cls = "badge-green" if "BUY" in action else "badge-purple" if "BREAKOUT" in action else "badge-yellow"
        badge_txt = p.get("status_badge") or action

        sl = _fmt(p.get("swing_sl"))
        t1 = _fmt(p.get("swing_t1"))
        t2 = _fmt(p.get("swing_t2"))
        rr = _fmt(p.get("risk_reward"), 1)
        fib = p.get("fib_badge") or "—"
        roe = _fmt(p.get("roe_pct"), 1)
        roce = _fmt(p.get("roce_pct"), 1)
        de = _fmt(p.get("de_ratio"), 2)
        pe = _fmt(p.get("pe"), 1)

        trend = p.get("trend") or "Uptrend"
        trend_cls = "badge-green" if "Strong" in trend else "badge-blue" if "Uptrend" in trend else "badge-yellow" if "Accumulation" in trend else "call-none"
        cap = p.get("cap_category") or "Small Cap"

        rows.append(f"""
        <tr data-trend="{trend}" data-cap="{cap}" data-signal="{action}" data-sector="{p.get('sector','')}" data-price="{p.get('ltp') or 0}" data-search="{sym} {p.get('name','')} {p.get('sector','')}">
          <td class="sym">{sym}</td>
          <td><span class="badge {trend_cls}" style="padding:3px 8px;font-size:11.5px">{trend}</span></td>
          <td><span class="badge {badge_cls}" style="padding:4px 10px;font-size:12px">{badge_txt}</span></td>
          <td>₹{ltp}</td>
          <td style="font-weight:700;color:var(--green)">{score}</td>
          <td style="color:var(--red)">₹{sl}</td>
          <td style="color:var(--green)">₹{t1}</td>
          <td style="color:#38bdf8">{t2}</td>
          <td>1 : {rr}</td>
          <td class="reason-cell">{fib}</td>
          <td style="color:var(--green)">{roe}%</td>
          <td style="color:#38bdf8">{roce}%</td>
          <td>{de}</td>
          <td>{pe}</td>
        </tr>""")

    body_html = "".join(rows) if rows else '<tr><td colspan="14" style="text-align:center;padding:32px;color:var(--muted)">No swing setups currently qualifying.</td></tr>'

    return f"""<!DOCTYPE html>
<html><head>
  <meta charset="utf-8"><meta http-equiv="refresh" content="180">
  <title>Swing Trading Screen — INDmoney &amp; Screener.in</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    {style_css}
    {FILTER_CSS}
  </style>
</head>
<body>
  {nav_bar_fn("swing")}
  <div class="header">
    <h1>High-Conviction Swing Trading Screen</h1>
    <p>Decoupled Setup Quality vs Entry Quality (Fibonacci 38.2/50/61.8%, Anchored VWAP, Bullish RSI Divergence, 1M/3M RS vs Nifty) &middot; Live INDmoney broker execution prices &middot; Real Screener.in fundamental ratios.</p>
    <div class="meta-row">
      <span class="meta-pill"><span class="pulse"></span>Refreshed {updated_str}</span>
      <span class="meta-pill">Rescans every 10 min</span>
      <span class="meta-pill">Qualified: {len(picks)} setups</span>
      {f'<span class="meta-pill meta-pill-warn">Rescan in progress…</span>' if running else ''}
    </div>
  </div>

  <div class="section">
    <div class="section-head">
      <span class="section-bar"></span>
      <h2>Top High-Conviction Setups</h2>
    </div>
    <p class="desc">Leading candidates ranked by composite Swing Score with optimal risk-to-reward ratios and confirmed momentum.</p>
    <div class="stat-strip">{stat_html}</div>
    {f'<div class="card-grid" style="margin-top:16px">{ "".join(top_cards) }</div>' if top_cards else ''}
  </div>

  <div class="section">
    <div class="section-head">
      <span class="section-bar"></span>
      <h2>All Qualified Swing Setups ({len(picks)})</h2>
    </div>
    <p class="desc">Complete list of stocks clearing the strict SWING_GATES filter (price &ge; ₹50, Large/Mid Cap or MTF margin list, valid ATR stop).</p>
    {_render_filter_bar("swingTable")}
    <div class="table-wrap" style="margin-top:14px">
      <table class="list" id="swingTable">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Trend</th>
            <th>Signal</th>
            <th>LTP</th>
            <th>Swing Score</th>
            <th>Stop Loss</th>
            <th>Target 1</th>
            <th>Target 2</th>
            <th>R : R</th>
            <th>Fibonacci Level</th>
            <th>ROE</th>
            <th>ROCE</th>
            <th>D/E</th>
            <th>P/E</th>
          </tr>
        </thead>
        <tbody>
          {body_html}
        </tbody>
      </table>
    </div>
  </div>

  {FILTER_JS}
</body></html>"""


# ---------------- LONG TERM VIEW ----------------
def render_lt_page(state: dict, nav_bar_fn, style_css: str) -> str:
    result = state.get("result") or {}
    monthly_cohort = result.get("monthly_cohort") or {}
    cohort_picks = monthly_cohort.get("picks") or []
    month_label = monthly_cohort.get("month_label") or "Current Month"
    locked_until = monthly_cohort.get("locked_until") or "Month End"

    watchlist = result.get("watchlist") or []
    challengers = result.get("top_challengers") or []
    updated_at = state.get("updated_at")

    updated_str = updated_at.strftime('%H:%M:%S UTC') if updated_at else "Computing..."
    buy_dip_count = sum(1 for w in watchlist if w.get("status") == "BUY_NOW")
    cohort_buy_now = sum(1 for p in cohort_picks if p.get("status") == "BUY_NOW")

    stats = [
        ("MONTHLY COHORT (< ₹500)", len(cohort_picks), "#818cf8"),
        ("COHORT 'BUY NOW' ACTIVE", cohort_buy_now, "var(--green)"),
        ("WATCHLIST INCUMBENTS", len(watchlist), "var(--muted)"),
        ("UNIVERSE CHALLENGERS", len(challengers), "var(--amber)"),
    ]

    stat_html = "".join(
        f'<div class="stat-tile"><div class="n" style="color:{c}">{n}</div><div class="l">{lbl}</div></div>'
        for lbl, n, c in stats
    )

    # Monthly Cohort Rows
    cohort_rows = []
    for idx, p in enumerate(cohort_picks, 1):
        sym = p.get("symbol")
        ltp = _fmt(p.get("ltp"))
        gtt = _fmt(p.get("gtt_level"))
        dist = _fmt(p.get("dist_from_gtt_pct"), 1)
        status = p.get("status") or "WAIT"
        badge_cls = "badge-green" if status == "BUY_NOW" else "badge-yellow"
        badge_txt = p.get("status_badge") or status
        reason = p.get("status_reason") or ""
        q_score = _fmt(p.get("lt_quality_score"), 1)
        roe = _fmt(p.get("roe_pct"), 1)
        roce = _fmt(p.get("roce_pct"), 1)
        de = _fmt(p.get("de_ratio"), 2)
        pe = _fmt(p.get("pe"), 1)

        cap = p.get("cap_category") or "Small Cap"
        cap_cls = "badge-purple" if "Large" in cap else "badge-blue" if "Mid" in cap else "call-none"
        trend = p.get("trend") or "Uptrend"
        trend_cls = "badge-green" if "Strong" in trend else "badge-blue" if "Uptrend" in trend else "badge-yellow" if "Accumulation" in trend else "call-none"
        dvm_text, dvm_cls, dvm_title = _dvm_badge(p)

        cohort_rows.append(f"""
        <tr data-trend="{trend}" data-cap="{cap}" data-signal="{status}" data-sector="{p.get('sector','')}" data-price="{p.get('ltp') or 0}" data-search="{sym} {p.get('name','')} {p.get('sector','')}">
          <td style="color:var(--dim);font-weight:700">#{idx}</td>
          <td class="sym">{sym}</td>
          <td><span class="badge {cap_cls}" style="padding:3px 8px;font-size:11.5px">{cap}</span></td>
          <td><span class="badge {trend_cls}" style="padding:3px 8px;font-size:11.5px">{trend}</span></td>
          <td><span class="badge {dvm_cls}" style="padding:3px 8px;font-size:11.5px" title="{dvm_title}">{dvm_text}</span></td>
          <td class="reason-cell">{p.get('sector','')}</td>
          <td><span class="badge {badge_cls}" style="padding:4px 10px;font-size:12px">{badge_txt}</span></td>
          <td>₹{ltp}</td>
          <td style="color:var(--amber);font-weight:700">₹{gtt}</td>
          <td style="color:{'var(--green)' if float(p.get('dist_from_gtt_pct') or 0) <= 3.5 else 'var(--muted)'}">{dist}%</td>
          <td style="font-weight:700;color:var(--green)">{q_score}</td>
          <td style="color:var(--green)">{roe}%</td>
          <td style="color:#38bdf8">{roce}%</td>
          <td>{de}</td>
          <td>{pe}</td>
          <td class="reason-cell">{reason}</td>
        </tr>""")

    wl_rows = []
    for w in watchlist:
        sym = w.get("symbol")
        ltp = _fmt(w.get("ltp"))
        q_score = _fmt(w.get("lt_quality_score"), 1)
        role = w.get("portfolio_role") or w.get("type", "Core")
        status = w.get("status") or "WAIT"
        badge_cls = "badge-green" if status == "BUY_NOW" else "call-none"
        badge_txt = w.get("status_badge") or status
        reason = w.get("status_reason") or ""
        trend = w.get("trend") or "Uptrend"
        trend_cls = "badge-green" if "Strong" in trend else "badge-blue" if "Uptrend" in trend else "badge-yellow" if "Accumulation" in trend else "call-none"

        gtt = _fmt(w.get("gtt_level"))
        dist = _fmt(w.get("dist_from_gtt_pct"), 1)

        roe = _fmt(w.get("roe_pct"), 1)
        roce = _fmt(w.get("roce_pct"), 1)
        de = _fmt(w.get("de_ratio"), 2)
        pe = _fmt(w.get("pe"), 1)

        wl_rows.append(f"""
        <tr data-trend="{trend}" data-cap="all" data-signal="{status}" data-sector="{w.get('sector','')}" data-price="{w.get('ltp') or 0}" data-search="{sym} {w.get('name','')} {w.get('sector','')}">
          <td class="sym">{sym}</td>
          <td class="reason-cell">{w.get('sector','')}</td>
          <td><span class="badge badge-purple" style="padding:4px 10px;font-size:12px">{role}</span></td>
          <td><span class="badge {trend_cls}" style="padding:3px 8px;font-size:11.5px">{trend}</span></td>
          <td style="font-weight:700;color:var(--green)">{q_score}</td>
          <td>₹{ltp}</td>
          <td style="color:var(--amber)">₹{gtt}</td>
          <td>{dist}%</td>
          <td><span class="badge {badge_cls}" style="padding:4px 10px;font-size:12px">{badge_txt}</span></td>
          <td class="reason-cell">{reason}</td>
          <td style="color:var(--green)">{roe}%</td>
          <td style="color:#38bdf8">{roce}%</td>
          <td>{de}</td>
          <td>{pe}</td>
        </tr>""")

    ch_rows = []
    for idx, c in enumerate(challengers, 1):
        sym = c.get("symbol")
        ltp = _fmt(c.get("ltp"))
        q_score = _fmt(c.get("lt_quality_score"), 1)
        sec_group = c.get("sector_group", "General").replace("_", " ")
        trend = c.get("trend") or c.get("fundamental_trend_rating", "STABLE").replace("_", " ")
        trend_cls = "badge-green" if "Strong" in trend else "badge-blue" if "Uptrend" in trend else "badge-yellow" if "Accumulation" in trend else "call-none"
        risk = c.get("lt_risk_level", "MODERATE")
        risk_cls = "badge-green" if risk == "LOW" else "badge-yellow" if risk == "MODERATE" else "badge-red"
        cap = c.get("cap_category") or "Mid Cap"

        roe = _fmt(c.get("roe_pct"), 1)
        roce = _fmt(c.get("roce_pct"), 1)
        de = _fmt(c.get("de_ratio"), 2)
        npm = _fmt(c.get("npm_pct"), 1)
        pe = _fmt(c.get("pe"), 1)

        ch_rows.append(f"""
        <tr data-trend="{trend}" data-cap="{cap}" data-signal="all" data-sector="{sec_group}" data-price="{c.get('ltp') or 0}" data-search="{sym} {c.get('name','')} {sec_group}">
          <td style="color:var(--dim);font-weight:700">#{idx}</td>
          <td class="sym">{sym}</td>
          <td><span class="badge call-none" style="padding:3px 8px;font-size:11.5px">{sec_group}</span></td>
          <td><span class="badge {trend_cls}" style="padding:3px 8px;font-size:11.5px">{trend}</span></td>
          <td style="font-weight:700;color:var(--green)">{q_score}</td>
          <td><span class="badge {risk_cls}" style="padding:3px 8px;font-size:11.5px">{risk}</span></td>
          <td>₹{ltp}</td>
          <td style="color:var(--green)">{roe}%</td>
          <td style="color:#38bdf8">{roce}%</td>
          <td>{de}</td>
          <td>{npm}%</td>
          <td>{pe}</td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html><head>
  <meta charset="utf-8"><meta http-equiv="refresh" content="300">
  <title>Long-Term Quality &amp; Universe Discovery — INDmoney &amp; Screener.in</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    {style_css}
    {FILTER_CSS}
  </style>
</head>
<body>
  {nav_bar_fn("lt")}
  <div class="header">
    <h1>Long-Term Quality &amp; 4-Stage Universe Discovery</h1>
    <p>40% Large / 40% Mid / 20% Small Cap Allocation &middot; Price strictly ₹75–₹500 &middot; Curated Watchlist Audit &middot; Genuine Screener.in &amp; Tickertape Fundamentals &middot; Trendlyne DVM Durability.</p>
    <div class="meta-row">
      <span class="meta-pill"><span class="pulse"></span>Refreshed {updated_str}</span>
      <span class="meta-pill">Cohort Lock: {month_label} (until {locked_until})</span>
      <span class="meta-pill">Allocation: 40% Large (4) / 40% Mid (4) / 20% Small (2)</span>
      <span class="meta-pill">Watchlist: {len(watchlist)} incumbents</span>
    </div>
  </div>

  <div class="section">
    <div class="section-head">
      <span class="section-bar"></span>
      <h2>⭐ Monthly Featured Cohort: Top 10 High-Strength Picks (₹75 to ₹500 &middot; 40% Large / 40% Mid / 20% Small)</h2>
    </div>
    <p class="desc">Autosearched across the universe strictly between ₹75 and ₹500 with a balanced 40% Large Cap (4), 40% Mid Cap (4), and 20% Small Cap (2) allocation. Screened for <b>Trendlyne DVM Durability &ge; 55</b> and healthy trend phases (excluding commodity cyclicals). Automatically triggers <b>BUY NOW</b> when price enters the institutional accumulation / GTT dip zone.</p>
    <div class="stat-strip">{stat_html}</div>
    {_render_filter_bar("ltCohortTable")}
    <div class="table-wrap" style="margin-top:14px">
      <table class="list" id="ltCohortTable">
        <thead>
          <tr>
            <th>#</th>
            <th>Symbol</th>
            <th>Cap</th>
            <th>Trend</th>
            <th>DVM Durability</th>
            <th>Sector</th>
            <th>Signal</th>
            <th>LTP</th>
            <th>GTT Dip</th>
            <th>Distance</th>
            <th>Quality</th>
            <th>ROE</th>
            <th>ROCE</th>
            <th>D/E</th>
            <th>P/E</th>
            <th>Execution Note</th>
          </tr>
        </thead>
        <tbody>
          {"".join(cohort_rows)}
        </tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="section-head">
      <span class="section-bar"></span>
      <h2>Curated Watchlist Incumbents ({len(watchlist)})</h2>
    </div>
    <p class="desc">High-conviction core portfolio holdings monitored continuously against GTT dip accumulation levels.</p>
    {_render_filter_bar("ltWatchlistTable", show_cap=False)}
    <div class="table-wrap" style="margin-top:14px">
      <table class="list" id="ltWatchlistTable">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Sector</th>
            <th>Role</th>
            <th>Trend</th>
            <th>Quality</th>
            <th>LTP</th>
            <th>GTT Dip</th>
            <th>Distance</th>
            <th>Signal</th>
            <th>Reason</th>
            <th>ROE</th>
            <th>ROCE</th>
            <th>D/E</th>
            <th>P/E</th>
          </tr>
        </thead>
        <tbody>
          {"".join(wl_rows)}
        </tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="section-head">
      <span class="section-bar"></span>
      <h2>Universe Discovery: Top High-Quality Compounders ({len(challengers)})</h2>
    </div>
    <p class="desc">Challengers across the NSE universe outranking the market on return on capital, balance sheet durability, and structural growth.</p>
    {_render_filter_bar("ltChallengersTable")}
    <div class="table-wrap" style="margin-top:14px">
      <table class="list" id="ltChallengersTable">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Symbol</th>
            <th>Sector Group</th>
            <th>Trend</th>
            <th>Quality Score</th>
            <th>Risk</th>
            <th>LTP</th>
            <th>ROE</th>
            <th>ROCE</th>
            <th>D/E</th>
            <th>Net Margin</th>
            <th>P/E</th>
          </tr>
        </thead>
        <tbody>
          {"".join(ch_rows)}
        </tbody>
      </table>
    </div>
  </div>

  {FILTER_JS}
</body></html>"""


# ---------------- PENNY VIEW ----------------
def render_penny_page(state: dict, nav_bar_fn, style_css: str) -> str:
    result = state.get("result") or {}
    monthly_cohort = result.get("monthly_cohort") or {}
    cohort_picks = monthly_cohort.get("picks") or []
    month_label = monthly_cohort.get("month_label") or "Current Month"
    locked_until = monthly_cohort.get("locked_until") or "Month End"

    picks = result.get("picks") or []
    updated_at = state.get("updated_at")

    updated_str = updated_at.strftime('%H:%M:%S UTC') if updated_at else "Computing..."
    cohort_buy_now = sum(1 for p in cohort_picks if p.get("status") == "BUY_NOW")

    stats = [
        ("DEBT-FREE COHORT (₹5 to ₹75)", len(cohort_picks), "#818cf8"),
        ("COHORT 'BUY NOW' ACTIVE", cohort_buy_now, "var(--green)"),
        ("MAX D/E (DEBT-FREE GATE)", "0.10", "var(--green)"),
        ("SIP ALLOCATION", f"₹{result.get('monthly_sip_budget', 200):.0f} / mo", "var(--amber)"),
    ]

    stat_html = "".join(
        f'<div class="stat-tile"><div class="n" style="color:{c}">{n}</div><div class="l">{lbl}</div></div>'
        for lbl, n, c in stats
    )

    # Monthly Cohort Rows for Penny
    cohort_rows = []
    for idx, p in enumerate(cohort_picks, 1):
        sym = p.get("symbol")
        ltp = _fmt(p.get("ltp"))
        gtt = _fmt(p.get("gtt_level"))
        dist = _fmt(p.get("dist_from_gtt_pct"), 1)
        status = p.get("status") or "WAIT"
        badge_cls = "badge-green" if status == "BUY_NOW" else "badge-yellow"
        badge_txt = p.get("status_badge") or status
        reason = p.get("status_reason") or ""
        rank_s = _fmt(p.get("penny_rank_score"), 1)
        qual_s = _fmt(p.get("penny_quality_score"), 1)
        entry_s = _fmt(p.get("penny_entry_score"), 1)
        shares = p.get("monthly_shares")
        sip_txt = f"{shares} shares" if shares else "—"
        roe = _fmt(p.get("roe_pct"), 1)
        de_val = float(p.get("de_ratio") or 0.0)
        if de_val <= 0.01:
            de_badge = '<span class="badge badge-green" style="padding:2px 6px;font-size:11px">0.00 (Zero Debt)</span>'
        else:
            de_badge = f'<span style="color:var(--green);font-weight:700">{de_val:.2f}</span>'
        pe = _fmt(p.get("pe"), 1)

        trend = p.get("trend") or "Uptrend"
        trend_cls = "badge-green" if "Strong" in trend else "badge-blue" if "Uptrend" in trend else "badge-yellow" if "Accumulation" in trend else "call-none"
        dvm_text, dvm_cls, dvm_title = _dvm_badge(p)

        cohort_rows.append(f"""
        <tr data-trend="{trend}" data-cap="Micro Cap" data-signal="{status}" data-sector="{p.get('sector','')}" data-price="{p.get('ltp') or 0}" data-search="{sym} {p.get('name','')} {p.get('sector','')}">
          <td style="color:var(--dim);font-weight:700">#{idx}</td>
          <td class="sym">{sym}</td>
          <td><span class="badge {trend_cls}" style="padding:3px 8px;font-size:11.5px">{trend}</span></td>
          <td><span class="badge {dvm_cls}" style="padding:3px 8px;font-size:11.5px" title="{dvm_title}">{dvm_text}</span></td>
          <td><span class="badge {badge_cls}" style="padding:4px 10px;font-size:12px">{badge_txt}</span></td>
          <td>₹{ltp}</td>
          <td style="color:var(--amber);font-weight:700">₹{gtt}</td>
          <td style="color:{'var(--green)' if float(p.get('dist_from_gtt_pct') or 0) <= 3.5 else 'var(--muted)'}">{dist}%</td>
          <td style="font-weight:700;color:#a855f7">{sip_txt}</td>
          <td style="font-weight:700;color:var(--green)">{rank_s}</td>
          <td style="color:var(--green)">{qual_s}</td>
          <td style="color:var(--amber)">{entry_s}</td>
          <td style="color:var(--green)">{roe}%</td>
          <td>{de_badge}</td>
          <td>{pe}</td>
          <td class="reason-cell">{reason}</td>
        </tr>""")

    rows = []
    for p in picks:
        sym = p.get("symbol")
        ltp = _fmt(p.get("ltp"))
        rank_s = _fmt(p.get("penny_rank_score"), 1)
        qual_s = _fmt(p.get("penny_quality_score"), 1)
        val_s = _fmt(p.get("penny_value_score"), 1)
        entry_s = _fmt(p.get("penny_entry_score"), 1)

        shares = p.get("monthly_shares")
        sip_txt = f"{shares} shares" if shares else "—"

        status = p.get("status") or "WAIT"
        badge_cls = "badge-green" if "BUY" in status else "call-none"
        reason = p.get("status_reason") or ""
        trend = p.get("trend") or "Uptrend"
        trend_cls = "badge-green" if "Strong" in trend else "badge-blue" if "Uptrend" in trend else "badge-yellow" if "Accumulation" in trend else "call-none"
        dvm_text, dvm_cls, dvm_title = _dvm_badge(p)

        roe = _fmt(p.get("roe_pct"), 1)
        de = _fmt(p.get("de_ratio"), 2)
        pe = _fmt(p.get("pe"), 1)
        vol = _fmt(p.get("avg_volume_10d") or p.get("today_volume"), 0)

        rows.append(f"""
        <tr data-trend="{trend}" data-cap="Small Cap" data-signal="{status}" data-sector="{p.get('sector','')}" data-price="{p.get('ltp') or 0}" data-search="{sym} {p.get('name','')} {p.get('sector','')}">
          <td class="sym">{sym}</td>
          <td><span class="badge {trend_cls}" style="padding:3px 8px;font-size:11.5px">{trend}</span></td>
          <td><span class="badge {dvm_cls}" style="padding:3px 8px;font-size:11.5px" title="{dvm_title}">{dvm_text}</span></td>
          <td><span class="badge {badge_cls}" style="padding:4px 10px;font-size:12px">{status}</span></td>
          <td>₹{ltp}</td>
          <td style="font-weight:700;color:var(--green)">{rank_s}</td>
          <td style="color:var(--green)">{qual_s}</td>
          <td style="color:#38bdf8">{val_s}</td>
          <td style="color:var(--amber)">{entry_s}</td>
          <td style="font-weight:700;color:#a855f7">{sip_txt}</td>
          <td style="color:var(--green)">{roe}%</td>
          <td>{de}</td>
          <td>{pe}</td>
          <td style="font-size:12px;color:var(--muted)">{vol}</td>
          <td class="reason-cell">{reason}</td>
        </tr>""")

    body_html = "".join(rows) if rows else '<tr><td colspan="15" style="text-align:center;padding:32px;color:var(--muted)">No penny stocks currently meeting strict solvency &amp; durability gates.</td></tr>'

    return f"""<!DOCTYPE html>
<html><head>
  <meta charset="utf-8"><meta http-equiv="refresh" content="300">
  <title>Quality Penny &amp; Micro-Cap SIP — INDmoney &amp; Screener.in</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    {style_css}
    {FILTER_CSS}
  </style>
</head>
<body>
  {nav_bar_fn("penny")}
  <div class="header">
    <h1>Quality Debt-Free Micro-Cap &amp; Penny SIP Screen</h1>
    <p>Strict Debt-Free Micro-Cap Filter (Price ₹5–₹75 &middot; D/E &le; 0.10 &middot; Zero Debt &amp; Net-Cash Positive &middot; Positive Margins &middot; Trendlyne DVM Durability &middot; Monthly 10-Stock Featured Cohort with GTT Triggers &middot; ₹200 SIP Sizing).</p>
    <div class="meta-row">
      <span class="meta-pill"><span class="pulse"></span>Refreshed {updated_str}</span>
      <span class="meta-pill">Cohort Lock: {month_label} (until {locked_until})</span>
      <span class="meta-pill">Budget: ₹200 / stock / month</span>
    </div>
  </div>

  <div class="section">
    <div class="section-head">
      <span class="section-bar"></span>
      <h2>⭐ Monthly Featured Penny Cohort: Top 10 Debt-Free Micro-Caps (₹5 to ₹75)</h2>
    </div>
    <p class="desc">Strictly screened across micro-caps (₹5 to ₹75) for <b>Zero-Debt &amp; Net-Cash Positive</b> businesses (D/E &le; 0.10, Total Debt &asymp; 0, Cash &gt; Debt) with active positive momentum, scored with <b>Trendlyne DVM Durability</b>. Locked for {month_label}. Suggests <b>BUY NOW</b> when price dips into the GTT accumulation zone.</p>
    <div class="stat-strip">{stat_html}</div>
    {_render_filter_bar("pennyCohortTable", show_cap=False)}
    <div class="table-wrap" style="margin-top:14px">
      <table class="list" id="pennyCohortTable">
        <thead>
          <tr>
            <th>#</th>
            <th>Symbol</th>
            <th>Trend</th>
            <th>DVM Durability</th>
            <th>Signal</th>
            <th>LTP</th>
            <th>GTT Dip</th>
            <th>Distance</th>
            <th>₹200 SIP Qty</th>
            <th>Penny Rank</th>
            <th>Quality</th>
            <th>Entry</th>
            <th>ROE</th>
            <th>D/E</th>
            <th>P/E</th>
            <th>Execution Note</th>
          </tr>
        </thead>
        <tbody>
          {"".join(cohort_rows)}
        </tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <div class="section-head">
      <span class="section-bar"></span>
      <h2>All Qualified Micro-Caps ({len(picks)})</h2>
    </div>
    <p class="desc">Only fundamentally durable micro-caps with clean debt profiles and measurable positive earnings qualify for this list.</p>
    {_render_filter_bar("pennyTable", show_cap=False)}
    <div class="table-wrap" style="margin-top:14px">
      <table class="list" id="pennyTable">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Trend</th>
            <th>DVM Durability</th>
            <th>Signal</th>
            <th>LTP</th>
            <th>Rank</th>
            <th>Quality</th>
            <th>Value</th>
            <th>Entry</th>
            <th>₹200 SIP Qty</th>
            <th>ROE</th>
            <th>D/E</th>
            <th>P/E</th>
            <th>Volume</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {body_html}
        </tbody>
      </table>
    </div>
  </div>

  {FILTER_JS}
</body></html>"""
