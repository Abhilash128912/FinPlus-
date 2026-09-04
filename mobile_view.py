"""Suggestions-only page for the Capacitor app.

The desktop page is built for a screen that can hold a 2,568-row table: it ships
a 176KB document and then fetches the ~10MB scan payload so the browser can
filter it (the swing tab alone filters all of it to find its 441 candidates).
On a phone that download is the whole of the app's sluggishness, and none of it
buys anything -- the four things worth looking at on a phone are the suggestion
sets, and three of the four are already chosen server-side before the page is
built.

So this view ships the picks and nothing else: four tabs, every row slimmed to
the fields actually rendered, no scan payload, and live polling scoped to the
active tab -- so no single price request exceeds TAB_SYMBOL_BUDGET, which is what
keeps /api/ltp responsive.
"""

import json

# The server warms recently-requested symbols in one bounded batch, so a request
# wide enough to overflow it pushes the rows on screen out of the warm set and
# serves them stale. Polling is scoped to the visible tab, so the number that
# actually reaches /api/ltp is the largest single tab -- not the page total, which
# is only ever spread across four separate requests.
#
# Enforced at build time rather than trusted: an upstream top_n that grows would
# otherwise quietly reintroduce the wide-request problem.
TAB_SYMBOL_BUDGET = 50

# Only what the cards render. Penny rows in particular arrive as full scan rows
# of ~130 fields; shipping those whole would undo the point of this page.
SLIM_FIELDS = {
    "intraday": (
        "symbol", "ticker", "name", "ltp", "prev_close", "day_chg_pct", "direction",
        "stop_loss", "stop_loss_pct", "target1", "target1_pct", "target2",
        "target2_pct", "rsi", "volume_spike", "rs_rating", "rationale", "sector",
    ),
    "swing": (
        "symbol", "ticker", "name", "ltp", "swing_score", "setup_score", "swing_sl",
        "swing_sl_pct", "swing_t1", "swing_t1_pct", "swing_t2", "swing_t2_pct",
        "swing_badge", "swing_class", "swing_reason", "rs_rating", "trend",
        "trend_class", "cap_category", "sector",
    ),
    "penny": (
        "symbol", "ticker", "name", "ltp", "status", "status_badge",
        "status_badge_class", "status_reason", "auto_gtt", "dist_from_gtt_pct",
        "penny_quality_score", "penny_entry_score", "monthly_sip_qty",
        "monthly_sip_cost", "trend", "trend_class", "rsi", "sector",
    ),
    "lt": (
        "symbol", "ticker", "ltp", "status", "status_badge", "status_badge_class",
        "status_reason", "auto_gtt", "gtt_level", "is_auto_gtt",
        "dist_from_gtt_pct", "lt_quality_score", "lt_entry_score", "trend",
        "trend_badge", "sector", "portfolio_role", "day_chg_pct",
    ),
}

TAB_ORDER = (
    ("intraday", "Intraday"),
    ("swing", "Swing"),
    ("penny", "Penny"),
    ("lt", "Long Term"),
)


def _slim(rows, kind):
    fields = SLIM_FIELDS[kind]
    return [{k: r.get(k) for k in fields if r.get(k) is not None} for r in (rows or [])]


def build_mobile_payload(intraday, swing, penny, lt_watchlist, mkt_info, run_time):
    """Slim the four suggestion sets into what the mobile page renders.

    Returns (payload, symbols, per_tab). `symbols` is every unique ticker the page
    can ask /api/ltp about; `per_tab` is the count each tab would request on its
    own, which is what the budget is actually about.
    """
    payload = {
        "run_time": run_time,
        "market": {
            "badge": (mkt_info or {}).get("badge", ""),
            "is_equity_open": bool((mkt_info or {}).get("is_equity_open")),
            "time_str": (mkt_info or {}).get("time_str", ""),
        },
        "tabs": {
            "intraday": {
                "buy": _slim((intraday or {}).get("buy"), "intraday"),
                "sell": _slim((intraday or {}).get("sell"), "intraday"),
            },
            "swing": _slim(swing, "swing"),
            "penny": _slim(penny, "penny"),
            "lt": _slim(lt_watchlist, "lt"),
        },
    }

    symbols = {}
    def note(rows):
        out = []
        for r in rows:
            sym = r.get("symbol")
            if sym:
                symbols[sym] = r.get("ticker") or (sym + ".NS")
                out.append(sym)
        return out

    # Per tab, because that is the unit a single /api/ltp request is built from.
    per_tab = {
        "intraday": len(set(note(payload["tabs"]["intraday"]["buy"]) +
                            note(payload["tabs"]["intraday"]["sell"]))),
        "swing": len(set(note(payload["tabs"]["swing"]))),
        "penny": len(set(note(payload["tabs"]["penny"]))),
        "lt": len(set(note(payload["tabs"]["lt"]))),
    }

    payload["symbols"] = symbols
    return payload, symbols, per_tab


_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Stock Screener — Suggestions</title>
<style>
  :root {
    --bg:#0b0f14; --card:#131a22; --card2:#1a232e; --line:#22303d;
    --fg:#e6edf3; --muted:#8b9bab; --green:#34d399; --red:#f87171;
    --amber:#fbbf24; --accent:#60a5fa;
  }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         padding-bottom:env(safe-area-inset-bottom); }
  header { position:sticky; top:0; z-index:5; background:var(--bg);
           border-bottom:1px solid var(--line); padding:10px 12px 0;
           padding-top:calc(10px + env(safe-area-inset-top)); }
  .hrow { display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }
  .title { font-weight:700; font-size:16px; letter-spacing:.2px; }
  .mkt { font-size:11px; color:var(--muted); }
  .meta { font-size:11px; color:var(--muted); margin:4px 0 8px; }
  .dot { display:inline-block; width:7px; height:7px; border-radius:50%;
         background:var(--muted); margin-right:5px; vertical-align:1px; }
  .dot.live { background:var(--green); }
  .dot.err  { background:var(--red); }
  nav { display:flex; gap:4px; overflow-x:auto; scrollbar-width:none; }
  nav::-webkit-scrollbar { display:none; }
  nav button { flex:0 0 auto; background:none; border:none; color:var(--muted);
               font:600 13px/1 inherit; padding:10px 12px; border-bottom:2px solid transparent; }
  nav button[aria-selected="true"] { color:var(--fg); border-bottom-color:var(--accent); }
  nav button .n { font-weight:400; opacity:.7; font-size:11px; }
  main { padding:10px 12px 24px; }
  .sub { font-size:11px; text-transform:uppercase; letter-spacing:.6px;
         color:var(--muted); margin:14px 2px 6px; }
  .sub:first-child { margin-top:2px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:10px 11px; margin-bottom:8px; }
  .r1 { display:flex; align-items:baseline; gap:8px; }
  .sym { font-weight:700; font-size:15px; }
  .nm { color:var(--muted); font-size:11px; overflow:hidden; text-overflow:ellipsis;
        white-space:nowrap; flex:1; min-width:0; }
  .px { margin-left:auto; font-weight:700; font-variant-numeric:tabular-nums; }
  .chg { font-size:11px; font-variant-numeric:tabular-nums; }
  .up { color:var(--green); } .dn { color:var(--red); }
  .badge { display:inline-block; font-size:10px; font-weight:700; padding:2px 6px;
           border-radius:4px; background:var(--card2); color:var(--muted); }
  .badge.g { background:rgba(52,211,153,.14); color:var(--green); }
  .badge.r { background:rgba(248,113,113,.14); color:var(--red); }
  .badge.a { background:rgba(251,191,36,.14); color:var(--amber); }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(72px,1fr));
          gap:6px; margin-top:8px; }
  .kv { background:var(--card2); border-radius:6px; padding:5px 6px; }
  .kv b { display:block; font-size:12px; font-variant-numeric:tabular-nums; }
  .kv span { font-size:9px; text-transform:uppercase; letter-spacing:.4px; color:var(--muted); }
  .why { font-size:11px; color:var(--muted); margin-top:7px; }
  .empty { color:var(--muted); font-size:12px; padding:18px 2px; }
  .stale { color:var(--amber); }
</style>
</head><body>
<header>
  <div class="hrow">
    <span class="title">Stock Screener</span>
    <span class="mkt" id="mkt"></span>
  </div>
  <div class="meta"><span class="dot" id="dot"></span><span id="status">Loading prices…</span>
    &nbsp;·&nbsp; Last scan: <span id="runtime"></span></div>
  <nav id="tabs"></nav>
</header>
<main id="view"></main>
<script>
var DATA = __MOBILE_PAYLOAD__;
var TABS = __TAB_ORDER__;

var live = {};      // symbol -> price
var staleSet = {};  // symbol -> true
var active = TABS[0][0];

function n(v, d) { var x = parseFloat(v); return isFinite(x) ? x.toFixed(d === undefined ? 2 : d) : '—'; }
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
  return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]; }); }
function px(row) { var p = live[row.symbol]; return p != null ? p : row.ltp; }

function chgPct(row) {
  var p = px(row), pc = parseFloat(row.prev_close);
  if (p != null && isFinite(pc) && pc > 0) return ((p - pc) / pc) * 100;
  if (row.day_chg_pct != null) return parseFloat(row.day_chg_pct);
  return null;
}

function cls(v) { return v > 0 ? 'up' : v < 0 ? 'dn' : ''; }

function badgeClass(s) {
  s = String(s || '');
  if (/BUY_NOW|ACCUMULATE|green/i.test(s)) return 'g';
  if (/AVOID|EXIT|red/i.test(s)) return 'r';
  if (/WAIT|WATCH|amber|yellow/i.test(s)) return 'a';
  return '';
}

function head(row, extra) {
  var c = chgPct(row);
  var p = px(row);
  var mark = staleSet[row.symbol] ? ' <span class="stale" title="price not fresh">·</span>' : '';
  return '<div class="r1"><span class="sym">' + esc(row.symbol) + '</span>' +
    (extra || '') +
    '<span class="nm">' + esc(row.name || row.sector || '') + '</span>' +
    '<span class="px">₹' + n(p) + mark + '</span></div>' +
    (c == null ? '' : '<div class="chg ' + cls(c) + '">' + (c >= 0 ? '+' : '') + n(c, 2) + '% today</div>');
}

function kv(items) {
  var out = items.filter(function (i) { return i[1] !== '—' && i[1] != null; })
    .map(function (i) { return '<div class="kv"><b>' + i[1] + '</b><span>' + i[0] + '</span></div>'; });
  return out.length ? '<div class="grid">' + out.join('') + '</div>' : '';
}

function cardIntraday(row) {
  return '<div class="card">' + head(row) +
    kv([['Stop', '₹' + n(row.stop_loss)], ['T1', '₹' + n(row.target1)],
        ['T2', '₹' + n(row.target2)], ['RSI', n(row.rsi, 1)],
        ['Vol×', n(row.volume_spike, 2)], ['RS', row.rs_rating != null ? row.rs_rating : '—']]) +
    (row.rationale ? '<div class="why">' + esc(row.rationale) + '</div>' : '') +
    '</div>';
}

function cardSwing(row) {
  var b = row.swing_badge ? '<span class="badge ' + badgeClass(row.swing_class || row.swing_badge) +
    '">' + esc(row.swing_badge) + '</span>' : '';
  return '<div class="card">' + head(row, b) +
    kv([['Setup', n(row.setup_score, 0)], ['Swing', n(row.swing_score, 0)],
        ['Stop', '₹' + n(row.swing_sl)], ['T1', '₹' + n(row.swing_t1)],
        ['T2', '₹' + n(row.swing_t2)], ['RS', row.rs_rating != null ? row.rs_rating : '—']]) +
    (row.swing_reason ? '<div class="why">' + esc(row.swing_reason) + '</div>' : '') +
    '</div>';
}

function cardPenny(row) {
  var b = row.status_badge ? '<span class="badge ' + badgeClass(row.status_badge_class || row.status) +
    '">' + esc(row.status_badge) + '</span>' : '';
  return '<div class="card">' + head(row, b) +
    kv([['Quality', n(row.penny_quality_score, 0)], ['Entry', n(row.penny_entry_score, 0)],
        ['GTT', '₹' + n(row.auto_gtt)], ['From GTT', n(row.dist_from_gtt_pct, 1) + '%'],
        ['SIP qty', row.monthly_sip_qty != null ? row.monthly_sip_qty : '—']]) +
    (row.status_reason ? '<div class="why">' + esc(row.status_reason) + '</div>' : '') +
    '</div>';
}

function cardLt(row) {
  var b = row.status_badge ? '<span class="badge ' + badgeClass(row.status_badge_class || row.status) +
    '">' + esc(row.status_badge) + '</span>' : '';
  var gtt = row.auto_gtt != null ? row.auto_gtt : row.gtt_level;
  return '<div class="card">' + head(row, b) +
    kv([['Quality', n(row.lt_quality_score, 0)], ['Entry', n(row.lt_entry_score, 0)],
        ['GTT', '₹' + n(gtt)], ['From GTT', n(row.dist_from_gtt_pct, 1) + '%'],
        ['Trend', esc(row.trend || '—')]]) +
    (row.status_reason ? '<div class="why">' + esc(row.status_reason) + '</div>' : '') +
    '</div>';
}

function tabCount(key) {
  var t = DATA.tabs[key];
  if (key === 'intraday') return (t.buy || []).length + (t.sell || []).length;
  return (t || []).length;
}

function renderTabs() {
  document.getElementById('tabs').innerHTML = TABS.map(function (t) {
    return '<button role="tab" data-k="' + t[0] + '" aria-selected="' + (t[0] === active) + '">' +
      t[1] + ' <span class="n">' + tabCount(t[0]) + '</span></button>';
  }).join('');
}

function render() {
  renderTabs();
  var t = DATA.tabs[active], html = '';
  if (active === 'intraday') {
    var buy = t.buy || [], sell = t.sell || [];
    html += '<div class="sub">Buy · long</div>' +
      (buy.length ? buy.map(cardIntraday).join('') : '<div class="empty">No long setups cleared the gates today.</div>');
    html += '<div class="sub">Sell · short</div>' +
      (sell.length ? sell.map(cardIntraday).join('') : '<div class="empty">No short setups cleared the gates today.</div>');
  } else {
    var rows = t || [];
    var card = active === 'swing' ? cardSwing : active === 'penny' ? cardPenny : cardLt;
    html = rows.length ? rows.map(card).join('') : '<div class="empty">Nothing here right now.</div>';
  }
  document.getElementById('view').innerHTML = html;
}

// Only the visible tab's symbols, plus nothing else. The whole page knows under
// 100; a single tab is 10-40, which is what keeps the server's warm batch useful.
function activeSymbols() {
  var t = DATA.tabs[active], rows;
  if (active === 'intraday') rows = (t.buy || []).concat(t.sell || []);
  else rows = t || [];
  return rows.map(function (r) { return DATA.symbols[r.symbol] || (r.symbol + '.NS'); });
}

function setStatus(txt, kind) {
  document.getElementById('status').textContent = txt;
  var d = document.getElementById('dot');
  d.className = 'dot' + (kind ? ' ' + kind : '');
}

async function poll() {
  var tickers = activeSymbols();
  if (!tickers.length) { setStatus('No rows to price'); return; }
  setStatus('Updating ' + tickers.length + ' prices…');
  try {
    var res = await fetch('/api/ltp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: tickers })
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var j = await res.json();
    var map = j.ltps || j.prices || {};
    var got = 0;
    Object.keys(DATA.symbols).forEach(function (sym) {
      var tk = DATA.symbols[sym];
      var p = map[tk] != null ? map[tk] : map[sym];
      if (p != null) { live[sym] = p; got++; }
      if (j.stale) staleSet[sym] = !!(j.stale[tk] || j.stale[sym]);
    });
    render();
    setStatus(got + ' live · ' + new Date().toLocaleTimeString('en-IN', { hour12: true }),
      got ? 'live' : 'err');
  } catch (e) {
    setStatus('Prices unavailable — showing scan values', 'err');
  }
}

document.getElementById('tabs').addEventListener('click', function (e) {
  var b = e.target.closest('button[data-k]');
  if (!b) return;
  active = b.dataset.k;
  render();
  poll();
});

document.getElementById('runtime').textContent = DATA.run_time || '—';
document.getElementById('mkt').textContent = DATA.market.badge || '';
render();
poll();
setInterval(poll, 30000);
document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });
</script>
</body></html>
"""


def render_mobile_html(payload: dict) -> str:
    """Inline the payload into the page. No external CSS/JS/data fetches."""
    return (
        _PAGE
        .replace("__MOBILE_PAYLOAD__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        .replace("__TAB_ORDER__", json.dumps([list(t) for t in TAB_ORDER]))
    )
