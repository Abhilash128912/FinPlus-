"""
options_views.py - Dedicated Option Trading Terminal & Strategy Desk View

A standalone, ultra-premium derivatives workspace providing:
  - Real-time underlying selection (NIFTY 50, BANK NIFTY, and permanent RELIANCE integration).
  - Top 10 Intraday Options Screener (5 CE and 5 PE stocks based on stock screener intraday logic).
  - Live expiry selection and auto-refreshing 17-column Option Chain ladder.
  - Institutional OI distribution, Max Pain, and Call/Put walls.
  - Algorithmic trade selection engine (Directional Momentum, Hedged Spreads, Theta Harvesting).
  - Full Greeks matrix (Delta, Theta, Gamma, IV) and risk/reward parameters.
"""

from typing import Any, Callable, Dict, List, Optional
import option_strategy_engine


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


def _fmt_oi(val):
    if val is None:
        return "—"
    try:
        n = float(val)
        if n >= 10000000:
            return f"{n/10000000:.2f} Cr"
        if n >= 100000:
            return f"{n/100000:.2f} L"
        if n >= 1000:
            return f"{n/1000:.1f} k"
        return f"{int(n)}"
    except (ValueError, TypeError):
        return str(val)


OPTIONS_CSS = """
    /* Options Terminal Specific Styles */
    .opt-header-bar {
      display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center;
      gap: 16px; margin-bottom: 20px; padding: 20px 24px;
      background: linear-gradient(135deg, rgba(26, 31, 46, 0.95) 0%, rgba(17, 21, 33, 0.95) 100%);
      border: 1px solid var(--border); border-radius: 12px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    }
    .opt-title-box h1 {
      margin: 0 0 6px 0; font-size: 22px; font-weight: 800;
      background: linear-gradient(135deg, #fff 0%, #cbd5e1 100%);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      letter-spacing: -0.02em; display: flex; align-items: center; gap: 10px;
    }
    .opt-title-box p {
      margin: 0; font-size: 13px; color: var(--muted); line-height: 1.4;
    }

    /* Underlying Selector Pills */
    .underlying-selector-wrap {
      margin-bottom: 22px;
    }
    .underlying-selector-label {
      font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
      color: var(--muted); margin-bottom: 8px; display: flex; align-items: center; gap: 8px;
    }
    .underlying-selector {
      display: flex; flex-wrap: wrap; gap: 8px;
    }
    .underlying-btn {
      padding: 8px 14px; border-radius: 8px; font-size: 12.5px; font-weight: 700;
      border: 1px solid var(--border); background: var(--card-bg); color: var(--text);
      cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
      text-decoration: none; transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .underlying-btn:hover {
      border-color: var(--accent); background: rgba(59, 130, 246, 0.1);
      transform: translateY(-1px);
    }
    .underlying-btn.active {
      background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
      border-color: #3b82f6; color: #ffffff;
      box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
    }
    .underlying-btn .perm-badge {
      font-size: 9.5px; font-weight: 800; padding: 1px 5px; border-radius: 3px;
      background: rgba(234, 179, 8, 0.25); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.4);
      letter-spacing: 0.04em; text-transform: uppercase;
    }

    /* Top 10 Screened Stock Options Board */
    .picks-board-section {
      margin-bottom: 28px;
    }
    .picks-board-head {
      display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;
    }
    .picks-dual-grid {
      display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
    }
    @media (max-width: 1024px) {
      .picks-dual-grid { grid-template-columns: 1fr; }
    }
    .picks-cohort-col {
      background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px;
      padding: 16px; display: flex; flex-direction: column; gap: 10px;
    }
    .cohort-header {
      display: flex; justify-content: space-between; align-items: center;
      padding-bottom: 10px; border-bottom: 1px solid rgba(255,255,255,0.06); margin-bottom: 4px;
    }
    .cohort-title {
      font-size: 14px; font-weight: 800; display: flex; align-items: center; gap: 8px;
    }
    .cohort-title.ce { color: var(--green); }
    .cohort-title.pe { color: var(--red); }
    
    .pick-card-item {
      background: #0f131d; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px;
      padding: 12px 14px; display: flex; flex-direction: column; gap: 8px;
      transition: all 0.2s; position: relative; text-decoration: none; color: inherit;
    }
    .pick-card-item:hover {
      border-color: var(--accent); background: #131926; transform: translateY(-2px);
      box-shadow: 0 6px 18px rgba(0,0,0,0.35);
    }
    .pick-card-item.selected {
      border-color: #3b82f6; background: rgba(59, 130, 246, 0.08);
      outline: 2px solid rgba(59, 130, 246, 0.5); outline-offset: -1px;
    }
    .pick-row-top {
      display: flex; justify-content: space-between; align-items: center;
    }
    .pick-sym-group {
      display: flex; align-items: center; gap: 8px;
    }
    .pick-sym {
      font-size: 15px; font-weight: 800; color: #ffffff;
    }
    .pick-sec {
      font-size: 11px; color: var(--muted);
    }
    .pick-row-mid {
      display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px 10px;
      background: rgba(255,255,255,0.02); padding: 8px; border-radius: 6px;
      font-size: 11.5px;
    }
    .pick-stat-lbl { color: var(--muted); font-size: 10px; text-transform: uppercase; }
    .pick-stat-val { font-weight: 700; color: #ffffff; margin-top: 2px; }
    .pick-row-foot {
      display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--muted);
    }
    .pick-chain-btn {
      font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 4px;
      background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3);
      cursor: pointer; display: inline-flex; align-items: center; gap: 4px; text-decoration: none;
    }
    .pick-chain-btn:hover {
      background: #2563eb; color: #ffffff;
    }

    /* Sector Heatmap */
    .heatmap-section { margin-bottom: 28px; }
    .heatmap-sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
    .heatmap-sector { margin-bottom: 14px; }
    .heatmap-sector-title {
      font-size: 12px; font-weight: 700; color: var(--text); margin-bottom: 6px;
      display: flex; align-items: center; gap: 8px;
    }
    .heatmap-sector-title .count { color: var(--muted); font-weight: 500; }
    .heatmap-tiles {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); gap: 6px;
    }
    .heatmap-tile {
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      gap: 3px; padding: 10px 6px; border-radius: 8px; text-decoration: none;
      border: 1px solid rgba(255,255,255,0.08); transition: transform 0.15s, border-color 0.15s;
    }
    .heatmap-tile:hover { transform: translateY(-2px); border-color: #fff; }
    .heatmap-tile .tile-sym { font-size: 12px; font-weight: 800; color: #fff; }
    .heatmap-tile .tile-chg { font-size: 11px; font-weight: 700; color: #fff; }

    /* Control Controls Row */
    .controls-row {
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    }
    .opt-select {
      background: #0f131d; color: var(--text); border: 1px solid var(--border);
      border-radius: 6px; padding: 8px 14px; font-size: 13px; font-weight: 600;
      cursor: pointer; outline: none; transition: border-color 0.2s;
    }
    .opt-select:focus { border-color: var(--accent); }
    .btn-refresh {
      background: #1e293b; color: var(--text); border: 1px solid var(--border);
      border-radius: 6px; padding: 8px 14px; font-size: 13px; font-weight: 600;
      cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
      transition: all 0.2s;
    }
    .btn-refresh:hover { background: #334155; border-color: var(--muted); }

    /* Overview Stat Cards Grid */
    .opt-stat-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 14px; margin-bottom: 24px;
    }
    .opt-stat-card {
      background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px;
      padding: 16px; position: relative; overflow: hidden;
    }
    .opt-stat-card::before {
      content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
      background: var(--stat-bar, #3b82f6);
    }
    .opt-stat-title {
      font-size: 11.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
      color: var(--muted); margin-bottom: 8px; display: flex; justify-content: space-between;
    }
    .opt-stat-value {
      font-size: 22px; font-weight: 800; color: #ffffff; letter-spacing: -0.02em;
    }
    .opt-stat-sub {
      font-size: 12px; color: var(--muted); margin-top: 6px; line-height: 1.4;
    }

    /* Strategy Desk / Window */
    .strategy-desk-card {
      background: linear-gradient(135deg, rgba(26, 31, 46, 0.98) 0%, rgba(17, 21, 33, 0.98) 100%);
      border: 1px solid var(--border); border-radius: 12px; padding: 22px;
      margin-bottom: 28px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }
    .strategy-desk-head {
      display: flex; justify-content: space-between; align-items: center;
      padding-bottom: 16px; margin-bottom: 20px; border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .strategy-desk-title {
      font-size: 17px; font-weight: 800; color: #fff; display: flex; align-items: center; gap: 10px;
    }
    .strategy-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px;
    }
    .strat-item {
      background: #0f131d; border: 1px solid var(--border); border-radius: 10px;
      padding: 18px; position: relative; transition: border-color 0.2s;
    }
    .strat-item:hover { border-color: rgba(59, 130, 246, 0.5); }
    .strat-top {
      display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;
    }
    .strat-name {
      font-size: 16px; font-weight: 800; color: #fff; margin-bottom: 4px;
    }
    .strat-leg {
      font-size: 12px; font-family: monospace; color: var(--accent);
    }
    .strat-metrics-row {
      display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px;
      background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05);
      border-radius: 6px; padding: 10px; margin-bottom: 14px; text-align: center;
    }
    .strat-m-label { font-size: 11px; color: var(--muted); text-transform: uppercase; }
    .strat-m-val { font-size: 15px; font-weight: 800; color: #fff; margin-top: 3px; }

    .strat-greeks-row {
      display: flex; justify-content: space-around; gap: 8px;
      padding: 8px 10px; background: rgba(0,0,0,0.25); border-radius: 6px;
      font-size: 11.5px; margin-bottom: 14px;
    }
    .strat-greeks-row span { color: var(--muted); }
    .strat-greeks-row b { color: #fff; }

    .strat-rationale {
      font-size: 12px; color: #94a3b8; line-height: 1.5; padding: 10px 12px;
      background: rgba(30, 41, 59, 0.4); border-left: 3px solid var(--accent);
      border-radius: 4px;
    }

    /* Option Chain Ladder Table */
    .oc-container {
      background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px;
      overflow: hidden; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
    }
    .oc-table-scroll {
      max-height: 680px; overflow-y: auto; overflow-x: auto;
    }
    .oc-table {
      width: 100%; border-collapse: collapse; font-size: 12.5px; font-variant-numeric: tabular-nums;
    }
    .oc-table th {
      position: sticky; top: 0; z-index: 10; background: #0f131d;
      padding: 10px 8px; font-weight: 700; border-bottom: 1px solid var(--border);
      text-align: right;
    }
    .oc-table th.th-grp-call {
      background: #112218; color: var(--green); text-align: center; border-right: 1px solid var(--border);
      letter-spacing: 0.05em;
    }
    .oc-table th.th-grp-strike {
      background: #1a1e2b; color: #cbd5e1; text-align: center; min-width: 90px;
    }
    .oc-table th.th-grp-put {
      background: #251214; color: var(--red); text-align: center; border-left: 1px solid var(--border);
      letter-spacing: 0.05em;
    }
    .oc-table td {
      padding: 8px 8px; border-bottom: 1px solid rgba(255,255,255,0.04); text-align: right;
    }
    .oc-table td.td-strike {
      text-align: center; font-weight: 800; font-size: 13.5px; background: #131722;
      border-left: 1px solid var(--border); border-right: 1px solid var(--border);
      position: relative;
    }

    /* ITM and ATM Highlight */
    .itm-call { background: rgba(34, 197, 94, 0.06); }
    .itm-put { background: rgba(239, 68, 68, 0.06); }
    .tr-atm {
      background: rgba(234, 179, 8, 0.12) !important;
      outline: 2px solid rgba(234, 179, 8, 0.6); outline-offset: -2px;
    }
    .tr-atm td.td-strike {
      background: #242111 !important; color: #facc15;
    }
    .atm-pill {
      font-size: 9.5px; font-weight: 800; padding: 1px 5px; border-radius: 3px;
      background: #eab308; color: #000; margin-left: 6px; vertical-align: middle;
    }

    /* Visual OI distribution bar */
    .oi-cell {
      position: relative; overflow: hidden;
    }
    .oi-bar-call {
      position: absolute; top: 2px; bottom: 2px; right: 0;
      background: rgba(34, 197, 94, 0.18); border-radius: 2px; z-index: 1;
      pointer-events: none;
    }
    .oi-bar-put {
      position: absolute; top: 2px; bottom: 2px; left: 0;
      background: rgba(239, 68, 68, 0.18); border-radius: 2px; z-index: 1;
      pointer-events: none;
    }
    .oi-txt { position: relative; z-index: 2; }
"""


def render_options_page(
    underlying: str,
    chain_data: Dict[str, Any],
    expiries: List[str],
    signal_dict: Optional[Dict[str, Any]],
    trend_dict: Optional[Dict[str, Any]],
    nav_bar_fn: Callable[[str], str],
    base_style: str,
) -> str:
    """Renders the comprehensive, standalone Option Trading Terminal with 10 Intraday Screened Stocks."""
    underlying = underlying.upper().strip()
    analysis = option_strategy_engine.analyze_option_derivatives(chain_data, signal_dict, trend_dict)

    # Fetch Top 10 Screened Stocks (5 CE + 5 PE, Reliance always included!)
    options_scan = option_strategy_engine.scan_top_options_stocks()
    ce_picks = options_scan.get("ce_picks") or []
    pe_picks = options_scan.get("pe_picks") or []

    spot_ltp = chain_data.get("underlying_ltp") or 0.0
    atm_strike = chain_data.get("atm_strike") or 0.0
    pcr = float(chain_data.get("pcr") or 1.0)
    pcr_sent = chain_data.get("pcr_sentiment") or "NEUTRAL"
    current_expiry = chain_data.get("expiry") or (expiries[0] if expiries else "")

    pcr_cls = "badge-green" if pcr_sent == "BULLISH" else "badge-red" if pcr_sent == "BEARISH" else "badge-yellow"
    regime = analysis.get("regime", "NEUTRAL")
    regime_cls = "badge-green" if regime == "BULLISH" else "badge-red" if regime == "BEARISH" else "badge-yellow"

    # Underlying Pill Buttons (Core + Screened Stocks)
    base_underlyings = [
        {"key": "NIFTY", "name": "NIFTY 50", "icon": "📈", "tag": "Index"},
        {"key": "BANKNIFTY", "name": "BANK NIFTY", "icon": "🏦", "tag": "Index"},
        {"key": "RELIANCE", "name": "RELIANCE", "icon": "👑", "tag": "Always Active", "permanent": True},
    ]

    # Add any active underlying that is not in base
    existing_keys = {u["key"] for u in base_underlyings}
    if underlying not in existing_keys:
        base_underlyings.append({"key": underlying, "name": underlying, "icon": "🎯", "tag": "Active Stock"})

    pills_html = []
    for item in base_underlyings:
        is_active = item["key"] == underlying
        cls = "underlying-btn active" if is_active else "underlying-btn"
        perm_badge = '<span class="perm-badge">Always Active</span>' if item.get("permanent") else ""
        pills_html.append(
            f'<a href="/options?underlying={item["key"]}" class="{cls}">'
            f'{item["icon"]} <span>{item["name"]}</span> {perm_badge}</a>'
        )

    # Quick pills for the Top CE & PE picks
    ce_pills = []
    for p in ce_picks:
        k = p["symbol"]
        is_act = k == underlying
        c_cls = "underlying-btn active" if is_act else "underlying-btn"
        ce_pills.append(f'<a href="/options?underlying={k}" class="{c_cls}" title="{p["name"]}">{k}</a>')

    pe_pills = []
    for p in pe_picks:
        k = p["symbol"]
        is_act = k == underlying
        c_cls = "underlying-btn active" if is_act else "underlying-btn"
        rel_flag = ' 👑' if p.get("is_reliance") else ''
        pe_pills.append(f'<a href="/options?underlying={k}" class="{c_cls}" title="{p["name"]}">{k}{rel_flag}</a>')

    pills_bar = f"""
    <div class="underlying-selector-wrap">
      <div class="underlying-selector-label"><span>Core Watchlist &middot; Derivatives Hub</span></div>
      <div class="underlying-selector" style="margin-bottom:10px">{"".join(pills_html)}</div>
      <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span style="font-size:11px;font-weight:700;color:var(--green)">🟢 TOP CE:</span>
          {"".join(ce_pills)}
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span style="font-size:11px;font-weight:700;color:var(--red)">🔴 TOP PE:</span>
          {"".join(pe_pills)}
        </div>
      </div>
    </div>"""

    # Expiry dropdown options
    expiry_options = []
    for idx, exp in enumerate(expiries):
        selected = 'selected="selected"' if exp == current_expiry else ""
        label = f"{exp} (Current Expiry)" if idx == 0 else exp
        expiry_options.append(f'<option value="{exp}" {selected}>{label}</option>')
    expiry_select_html = "".join(expiry_options)

    # Stat Card Metrics
    straddle_prem = analysis.get("straddle_premium", 0.0)
    upper_be = analysis.get("upper_breakeven", 0.0)
    lower_be = analysis.get("lower_breakeven", 0.0)
    max_pain = analysis.get("max_pain", atm_strike)
    high_call_k = analysis.get("highest_call_strike", atm_strike)
    high_call_oi = analysis.get("highest_call_oi", 0)
    high_put_k = analysis.get("highest_put_strike", atm_strike)
    high_put_oi = analysis.get("highest_put_oi", 0)
    total_ce_oi = chain_data.get("total_ce_oi", 0)
    total_pe_oi = chain_data.get("total_pe_oi", 0)
    avg_iv = analysis.get("avg_iv")

    # ─── Top 10 Screened Stock Options Board HTML ─────────────────────────────
    def _render_pick_item(p: dict) -> str:
        sym = p["symbol"]
        is_sel = sym == underlying
        sel_cls = "selected" if is_sel else ""
        chg = p["day_chg_pct"]
        chg_col = "var(--green)" if chg >= 0 else "var(--red)"
        sign = "+" if chg >= 0 else ""
        rel_badge = '<span class="perm-badge" style="margin-left:4px">Always Active</span>' if p.get("is_reliance") else ""

        pcr_val = p.get("pcr")
        pcr_sent = p.get("pcr_sentiment")
        pcr_col = "var(--green)" if pcr_sent == "BULLISH" else "var(--red)" if pcr_sent == "BEARISH" else "#ffffff"

        return f"""
        <div class="pick-card-item {sel_cls}">
          <div class="pick-row-top">
            <div class="pick-sym-group">
              <span class="pick-sym">{sym}</span>
              {rel_badge}
              <span class="pick-sec">{p['sector']}</span>
            </div>
            <span class="badge {p['badge_class']}">{p['rec_option']}</span>
          </div>
          <div class="pick-row-mid">
            <div>
              <div class="pick-stat-lbl">Spot Price</div>
              <div class="pick-stat-val">₹{_fmt(p['spot_ltp'])}</div>
            </div>
            <div>
              <div class="pick-stat-lbl">Day Move</div>
              <div class="pick-stat-val" style="color:{chg_col}">{sign}{chg:.2f}%</div>
            </div>
            <div>
              <div class="pick-stat-lbl">Volume Spike</div>
              <div class="pick-stat-val">{p['volume_spike']:.2f}x</div>
            </div>
            <div>
              <div class="pick-stat-lbl">Total OI</div>
              <div class="pick-stat-val">{_fmt_oi(p.get('total_oi'))}</div>
            </div>
            <div>
              <div class="pick-stat-lbl">PCR</div>
              <div class="pick-stat-val" style="color:{pcr_col}">{_fmt(pcr_val, 2)}</div>
            </div>
            <div>
              <div class="pick-stat-lbl">Intraday Score</div>
              <div class="pick-stat-val" style="color:var(--lime)">{p['intraday_score']:.1f}</div>
            </div>
          </div>
          <div class="pick-row-foot">
            <span>RSI: <b style="color:#fff">{p['rsi']}</b> &middot; Prem Est: <b style="color:#fff">₹{_fmt(p['premium'])}</b></span>
            <a href="/options?underlying={sym}" class="pick-chain-btn">
              <span>📊 View Chain &rarr;</span>
            </a>
          </div>
        </div>"""

    ce_items_html = "".join([_render_pick_item(p) for p in ce_picks])
    pe_items_html = "".join([_render_pick_item(p) for p in pe_picks])

    top_picks_board_html = f"""
    <div class="picks-board-section">
      <div class="section-head" style="margin-bottom:14px">
        <span class="section-bar"></span>
        <h2>⚡ TOP 10 INTRADAY OPTION PICKS &mdash; Stock Screener Algorithm</h2>
        <span style="font-size:12px;color:var(--muted)">5 Bullish CE &middot; 5 Bearish PE &middot; Reliance Permanently Integrated</span>
      </div>
      <div class="picks-dual-grid">
        <div class="picks-cohort-col">
          <div class="cohort-header">
            <div class="cohort-title ce">
              <span>🟢 TOP 5 CALL (CE) MOMENTUM PICKS</span>
            </div>
            <span class="badge badge-green">BULLISH BREAKOUT</span>
          </div>
          {ce_items_html}
        </div>
        <div class="picks-cohort-col">
          <div class="cohort-header">
            <div class="cohort-title pe">
              <span>🔴 TOP 5 PUT (PE) BREAKDOWN PICKS</span>
            </div>
            <span class="badge badge-red">BEARISH BREAKDOWN</span>
          </div>
          {pe_items_html}
        </div>
      </div>
    </div>"""

    # ─── Sector Heatmap (options-eligible universe: LTP > ₹1,000, lot < 500,
    # RELIANCE exempt) ──────────────────────────────────────────────────────
    heatmap = option_strategy_engine.build_sector_heatmap()

    def _heatmap_tile_color(chg: float) -> str:
        t = max(-5.0, min(5.0, chg)) / 5.0
        if t >= 0:
            alpha = 0.12 + 0.60 * t
            return f"rgba(34,197,94,{alpha:.2f})"
        alpha = 0.12 + 0.60 * (-t)
        return f"rgba(239,68,68,{alpha:.2f})"

    def _render_heatmap_tile(t: dict) -> str:
        chg = t["day_chg_pct"]
        sign = "+" if chg >= 0 else ""
        is_sel = t["symbol"] == underlying
        border = "border:2px solid #fff;" if is_sel else ""
        return (
            f'<a href="/options?underlying={t["symbol"]}" class="heatmap-tile" '
            f'style="background:{_heatmap_tile_color(chg)};{border}" title="{t["name"]} &middot; RSI {t["rsi"]} &middot; {t["volume_spike"]:.1f}x vol">'
            f'<span class="tile-sym">{t["symbol"]}</span>'
            f'<span class="tile-chg">{sign}{chg:.2f}%</span>'
            f'</a>'
        )

    heatmap_sectors_html = []
    for sec in heatmap.get("sectors") or []:
        tiles_html = "".join(_render_heatmap_tile(t) for t in sec["tiles"])
        avg = sec["avg_chg_pct"]
        avg_col = "var(--green)" if avg >= 0 else "var(--red)"
        heatmap_sectors_html.append(f"""
        <div class="heatmap-sector">
          <div class="heatmap-sector-title">
            <span>{sec['name']}</span>
            <span class="count">({len(sec['tiles'])} stocks &middot; avg <b style="color:{avg_col}">{'+' if avg >= 0 else ''}{avg:.2f}%</b>)</span>
          </div>
          <div class="heatmap-tiles">{tiles_html}</div>
        </div>""")

    heatmap_html = f"""
    <div class="section heatmap-section">
      <div class="section-head" style="margin-bottom:4px">
        <span class="section-bar"></span>
        <h2>🗺️ Sector Heatmap &mdash; Options-Eligible Universe</h2>
      </div>
      <div class="heatmap-sub" style="margin-bottom:14px">
        {heatmap.get('total_stocks', 0)} stocks &middot; LTP &gt; ₹1,000 &middot; Lot Size &lt; 500 &middot; RELIANCE exempt from both &middot; colored by today's move
      </div>
      {"".join(heatmap_sectors_html) if heatmap_sectors_html else '<div style="color:var(--muted);font-size:13px">No stocks in the filtered universe have live day-move data yet.</div>'}
    </div>"""

    # Strategy Desk HTML
    strategies = analysis.get("strategies") or []
    strat_cards_html = []
    for s in strategies:
        strat_cards_html.append(f"""
        <div class="strat-item">
          <div class="strat-top">
            <div>
              <div class="strat-name">{s['name']}</div>
              <div class="strat-leg">{s['leg']}</div>
            </div>
            <span class="badge {s['badge_class']}">{s['style']}</span>
          </div>
          <div class="strat-metrics-row">
            <div>
              <div class="strat-m-label">Entry Price</div>
              <div class="strat-m-val" style="color:var(--text)">₹{_fmt(s['entry'])}</div>
            </div>
            <div>
              <div class="strat-m-label">Target 1</div>
              <div class="strat-m-val" style="color:var(--green)">₹{_fmt(s['target1'])}</div>
            </div>
            <div>
              <div class="strat-m-label">Stop Loss</div>
              <div class="strat-m-val" style="color:var(--red)">₹{_fmt(s['stop_loss'])}</div>
            </div>
          </div>
          <div class="strat-greeks-row">
            <div><span>Delta &Delta;:</span> <b>{_fmt(s.get('delta'), 2)}</b></div>
            <div><span>Theta &Theta;:</span> <b style="color:var(--amber)">{_fmt(s.get('theta'), 1)}/d</b></div>
            <div><span>IV:</span> <b>{_fmt(s.get('iv'), 1)}%</b></div>
            <div><span>R:R:</span> <b style="color:var(--lime)">1:{_fmt(s.get('rr'), 2)}</b></div>
          </div>
          <div class="strat-rationale">{s['rationale']}</div>
        </div>""")

    strategy_desk_html = f"""
    <div class="strategy-desk-card">
      <div class="strategy-desk-head">
        <div class="strategy-desk-title">
          <span>⚡ ALGORITHMIC OPTION STRATEGY DESK</span>
          <span class="badge {regime_cls}">{regime} SETUP</span>
        </div>
        <div style="font-size:12px;color:var(--muted)">
          Active Underlying: <b style="color:#fff">{underlying}</b> &middot; Expiry: <b style="color:#fff">{current_expiry}</b>
        </div>
      </div>
      <div class="strategy-grid">
        {"".join(strat_cards_html)}
      </div>
    </div>"""

    # Build Option Chain Rows
    strikes = chain_data.get("strikes") or []
    max_oi_val = max([max((s.get("ce") or {}).get("oi") or 0, (s.get("pe") or {}).get("oi") or 0) for s in strikes] or [1])

    chain_rows_html = []
    for s in strikes:
        k = float(s["strike"])
        is_atm = s.get("is_atm", False)
        is_call_itm = k < spot_ltp
        is_put_itm = k > spot_ltp

        ce = s.get("ce") or {}
        pe = s.get("pe") or {}

        ce_oi = ce.get("oi") or 0
        pe_oi = pe.get("oi") or 0
        ce_bar_pct = min(100, int((ce_oi / max_oi_val) * 100)) if max_oi_val > 0 else 0
        pe_bar_pct = min(100, int((pe_oi / max_oi_val) * 100)) if max_oi_val > 0 else 0

        ce_chg = ce.get("oi_change")
        pe_chg = pe.get("oi_change")
        ce_chg_col = "var(--green)" if (ce_chg or 0) >= 0 else "var(--red)"
        pe_chg_col = "var(--green)" if (pe_chg or 0) >= 0 else "var(--red)"
        ce_chg_txt = f"{'+' if (ce_chg or 0) >= 0 else ''}{_fmt_oi(ce_chg)}" if ce_chg is not None else "—"
        pe_chg_txt = f"{'+' if (pe_chg or 0) >= 0 else ''}{_fmt_oi(pe_chg)}" if pe_chg is not None else "—"

        ce_bid_ask = f"{_fmt(ce.get('bid'), 1)} / {_fmt(ce.get('ask'), 1)}" if ce.get("bid") is not None else "—"
        pe_bid_ask = f"{_fmt(pe.get('bid'), 1)} / {_fmt(pe.get('ask'), 1)}" if pe.get("bid") is not None else "—"

        tr_cls = "tr-atm" if is_atm else ""
        atm_badge = '<span class="atm-pill">ATM</span>' if is_atm else ""
        call_itm_cls = "itm-call" if is_call_itm else ""
        put_itm_cls = "itm-put" if is_put_itm else ""

        chain_rows_html.append(f"""
        <tr class="{tr_cls}">
          <td class="oi-cell {call_itm_cls}">
            <div class="oi-bar-call" style="width:{ce_bar_pct}%"></div>
            <span class="oi-txt">{_fmt_oi(ce_oi)}</span>
          </td>
          <td class="{call_itm_cls}" style="color:{ce_chg_col}">{ce_chg_txt}</td>
          <td class="{call_itm_cls}">{_fmt_oi(ce.get('volume'))}</td>
          <td class="{call_itm_cls}">{_fmt(ce.get('iv'), 1)}%</td>
          <td class="{call_itm_cls}" style="color:var(--lime)">{_fmt(ce.get('delta'), 2)}</td>
          <td class="{call_itm_cls}" style="font-size:11px;color:var(--muted)">{ce_bid_ask}</td>
          <td class="{call_itm_cls}" style="font-weight:700;color:var(--green);font-size:13px">₹{_fmt(ce.get('ltp'))}</td>
          <td class="td-strike">{int(k) if k.is_integer() else k}{atm_badge}</td>
          <td class="{put_itm_cls}" style="font-weight:700;color:var(--red);font-size:13px">₹{_fmt(pe.get('ltp'))}</td>
          <td class="{put_itm_cls}" style="font-size:11px;color:var(--muted)">{pe_bid_ask}</td>
          <td class="{put_itm_cls}" style="color:var(--lime)">{_fmt(pe.get('delta'), 2)}</td>
          <td class="{put_itm_cls}">{_fmt(pe.get('iv'), 1)}%</td>
          <td class="{put_itm_cls}">{_fmt_oi(pe.get('volume'))}</td>
          <td class="{put_itm_cls}" style="color:{pe_chg_col}">{pe_chg_txt}</td>
          <td class="oi-cell {put_itm_cls}">
            <div class="oi-bar-put" style="width:{pe_bar_pct}%"></div>
            <span class="oi-txt">{_fmt_oi(pe_oi)}</span>
          </td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Options Terminal &middot; {underlying} &middot; INDmoney</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    {base_style}
    {OPTIONS_CSS}
  </style>
</head>
<body>
  {nav_bar_fn("options")}

  <div class="opt-header-bar">
    <div class="opt-title-box">
      <h1>⚡ OPTIONS TRADING TERMINAL &middot; {underlying}</h1>
      <p>Intraday Stock Screener Options Engine, Live Institutional OI Profiler, and Algorithmic Execution Desk.</p>
    </div>
    <div class="controls-row">
      <label style="font-size:12.5px;color:var(--muted);font-weight:700">EXPIRY:</label>
      <select id="expiry-dropdown" class="opt-select" onchange="onExpiryChange()">
        {expiry_select_html}
      </select>
      <button class="btn-refresh" onclick="location.reload()">
        <span>🔄 Refresh</span>
      </button>
    </div>
  </div>

  {pills_bar}

  <div class="opt-stat-grid">
    <div class="opt-stat-card" style="--stat-bar:#3b82f6">
      <div class="opt-stat-title"><span>Spot Price</span><span>LTP</span></div>
      <div class="opt-stat-value">₹{_fmt(spot_ltp)}</div>
      <div class="opt-stat-sub">ATM Strike: <b style="color:#fff">{int(atm_strike) if float(atm_strike).is_integer() else atm_strike}</b></div>
    </div>
    <div class="opt-stat-card" style="--stat-bar:{'#22c55e' if pcr_sent=='BULLISH' else '#ef4444' if pcr_sent=='BEARISH' else '#eab308'}">
      <div class="opt-stat-title"><span>Put-Call Ratio (PCR)</span><span class="badge {pcr_cls}">{pcr_sent}</span></div>
      <div class="opt-stat-value">{_fmt(pcr, 2)}</div>
      <div class="opt-stat-sub">CE OI: {_fmt_oi(total_ce_oi)} &middot; PE OI: {_fmt_oi(total_pe_oi)}</div>
    </div>
    <div class="opt-stat-card" style="--stat-bar:#8b5cf6">
      <div class="opt-stat-title"><span>Max Pain &amp; OI Walls</span><span>INSTITUTIONAL</span></div>
      <div class="opt-stat-value">₹{int(max_pain) if float(max_pain).is_integer() else max_pain}</div>
      <div class="opt-stat-sub">Call Wall: <b>{int(high_call_k)}</b> &middot; Put Floor: <b>{int(high_put_k)}</b></div>
    </div>
    <div class="opt-stat-card" style="--stat-bar:#f59e0b">
      <div class="opt-stat-title"><span>ATM Straddle &amp; IV</span><span>RANGE</span></div>
      <div class="opt-stat-value">₹{_fmt(straddle_prem)}</div>
      <div class="opt-stat-sub">Range: <b>{int(lower_be)}</b> &mdash; <b>{int(upper_be)}</b> (IV: {_fmt(avg_iv, 1)}%)</div>
    </div>
  </div>

  {top_picks_board_html}

  {heatmap_html}

  {strategy_desk_html}

  <div class="section">
    <div class="section-head" style="margin-bottom:14px">
      <span class="section-bar"></span>
      <h2>Live Option Chain Ladder &mdash; {underlying} ({current_expiry})</h2>
    </div>
    <div class="oc-container">
      <div class="oc-table-scroll">
        <table class="oc-table">
          <thead>
            <tr>
              <th colspan="7" class="th-grp-call">CALLS (CE)</th>
              <th class="th-grp-strike">STRIKE</th>
              <th colspan="7" class="th-grp-put">PUTS (PE)</th>
            </tr>
            <tr style="background:#131722;border-bottom:1px solid var(--border);color:var(--muted);font-size:11px">
              <th>OI</th>
              <th>OI Chg</th>
              <th>Volume</th>
              <th>IV</th>
              <th>Delta</th>
              <th>Bid / Ask</th>
              <th>LTP</th>
              <th class="th-grp-strike">Strike</th>
              <th>LTP</th>
              <th>Bid / Ask</th>
              <th>Delta</th>
              <th>IV</th>
              <th>Volume</th>
              <th>OI Chg</th>
              <th>OI</th>
            </tr>
          </thead>
          <tbody>
            {"".join(chain_rows_html)}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
  function onExpiryChange() {{
    const sel = document.getElementById('expiry-dropdown');
    const expiry = sel ? sel.value : '';
    const url = new URL(window.location.href);
    if (expiry) {{
      url.searchParams.set('expiry', expiry);
    }}
    window.location.href = url.toString();
  }}

  // Auto-scroll to ATM strike on load
  window.addEventListener('DOMContentLoaded', () => {{
    setTimeout(() => {{
      const atmRow = document.querySelector('.tr-atm');
      if (atmRow) {{
        atmRow.scrollIntoView({{block: 'center', behavior: 'smooth'}});
      }}
    }}, 100);
  }});
  </script>
</body>
</html>"""
