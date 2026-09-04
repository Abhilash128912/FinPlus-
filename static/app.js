
// ── DATA (injected by Python) ─────────────────────────────────────────────
var SCREENER_DATA = [];
var WATCHLIST_SEED = [];
var LT_WATCHLIST = [];
var CONFIG = {};
var COMMODITIES_DATA = {};
var MARKET_INFO = {};
var FNO_DATA = [];
var PENNY_STOCKS_DATA = [];
var INTRADAY_DATA = {};
var LT_MONTHLY_PICKS = {};
var LT_PORTFOLIO_SUMMARY = {};
var TREND_CONFIG = { states: {}, uptrend: [], downtrend: '' };

// Resolve a trend's badge class from the table the Python classifier owns
// (screener_engine.TREND_STATES), so the UI can never label a state the engine
// does not emit -- or miss one it does. Unknown/absent trends fall back to the
// neutral class rather than being styled as something they are not.
function trendBadgeClass(trend) {
  const meta = (TREND_CONFIG.states || {})[trend];
  // Neutral grey for an unknown/absent trend. Falling back to a real state's
  // colour would visually assert a classification the engine never made.
  return (meta && meta.class) || 'badge-gray';
}

// ── State ─────────────────────────────────────────────────────────────────
let watchlist = [];
let sortCol = 'total_score';
let sortDir = -1;
let filteredData = [];
let pollIntervalTimer = null;
let pollIntervalMs = 10000;
let currentPage = 1;
let pageSize = 50;
let lastLtpSuccessTime = null;
let lastLtpError = null;
// Set from /api/ltp. A scan in flight is a deliberate pause, not a failure, and the
// badge has to tell them apart or a normal hourly scan reads as a broken feed.
let ltpPaused = { active: false, resumesInSec: null };

function calculateCurrentMarketStatus() {
  const now = new Date();
  const istStr = now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' });
  const istDate = new Date(istStr);

  const dayOfWeek = istDate.getDay(); // 0 = Sun, 6 = Sat
  const hours = istDate.getHours();
  const minutes = istDate.getMinutes();
  const isWeekend = (dayOfWeek === 0 || dayOfWeek === 6);
  const tMins = hours * 60 + minutes;
  
  const eqOpenMins = 9 * 60 + 15;   // 09:15 AM
  const eqCloseMins = 15 * 60 + 30; // 03:30 PM
  const mcxOpenMins = 9 * 60;       // 09:00 AM
  const mcxCloseMins = 23 * 60 + 30; // 11:30 PM
  
  if (isWeekend) {
    return {
      status: "WEEKEND",
      badge: "🔴 Market Closed (Weekend)",
      badge_class: "badge-red",
      message: "NSE/BSE & MCX closed for the weekend.",
      is_open: false,
      is_equity_open: false,
      is_pre_market: false
    };
  }
  
  if (tMins < mcxOpenMins) {
    return {
      status: "PRE_MARKET",
      badge: "🔴 Market Closed (Opens 09:00 AM MCX / 09:15 AM Stock)",
      badge_class: "badge-yellow",
      message: "Pre-market session. MCX Commodity scan starts at 09:00 AM IST. Stock of the Day locks at 09:15 AM IST.",
      is_open: false,
      is_equity_open: false,
      is_pre_market: true
    };
  } else if (tMins >= mcxOpenMins && tMins < eqOpenMins) {
    return {
      status: "COMMODITY_LIVE",
      badge: "🟢 MCX Commodity Live (Stock Opens 09:15 AM IST)",
      badge_class: "badge-green",
      message: "MCX Commodity session is LIVE. Equity stock session opens at 09:15 AM IST.",
      is_open: true,
      is_equity_open: false,
      is_pre_market: true
    };
  } else if (tMins >= eqOpenMins && tMins <= eqCloseMins) {
    const timeFormatted = `${hours > 12 ? hours - 12 : (hours === 0 ? 12 : hours)}:${minutes < 10 ? '0' + minutes : minutes} ${hours >= 12 ? 'PM' : 'AM'}`;
    return {
      status: "LIVE_MARKET",
      badge: `🟢 Live Market (${timeFormatted} IST · Active)`,
      badge_class: "badge-green",
      message: `NSE/BSE & MCX Session Active (${timeFormatted} IST). Live prices & returns updating.`,
      is_open: true,
      is_equity_open: true,
      is_pre_market: false
    };
  } else if (tMins > eqCloseMins && tMins <= mcxCloseMins) {
    return {
      status: "COMMODITY_ONLY",
      badge: "🟢 MCX Commodity Session Active (Stock Session Ended)",
      badge_class: "badge-green",
      message: "Equity stock session ended at 03:30 PM. MCX Commodity market active until 11:30 PM IST.",
      is_open: true,
      is_equity_open: false,
      is_pre_market: false
    };
  } else {
    return {
      status: "POST_MARKET",
      badge: "🔴 Market Closed (All Sessions Ended)",
      badge_class: "badge-red",
      message: "All trading sessions closed for today.",
      is_open: false,
      is_equity_open: false,
      is_pre_market: false
    };
  }
}

function renderMarketStatusHeader() {
  const container = document.getElementById('mktStatusPillHeader');
  if (container) {
    const currentMkt = calculateCurrentMarketStatus();
    if (typeof MARKET_INFO !== 'undefined' && MARKET_INFO) {
      MARKET_INFO.is_open = currentMkt.is_open;
      MARKET_INFO.is_equity_open = currentMkt.is_equity_open;
      MARKET_INFO.is_pre_market = currentMkt.is_pre_market;
    }
    container.innerHTML = `<span class="badge ${currentMkt.badge_class || 'badge-green'}" style="font-size:12px;padding:6px 14px;font-weight:700" title="${currentMkt.message}">${currentMkt.badge}</span>`;
    updateLtpBadgeStatus();
  }

  // Populate NIFTY 50 Macro Regime Banner
  if (typeof MARKET_INFO !== 'undefined' && MARKET_INFO && MARKET_INFO.nifty) {
    const n = MARKET_INFO.nifty;
    const bBadge = document.getElementById('niftyRegimeBadge');
    const bLtp = document.getElementById('niftyRegimeLtp');
    const bStance = document.getElementById('niftyRegimeStance');
    const bGuidance = document.getElementById('niftyRegimeGuidance');
    if (bBadge) {
      bBadge.className = 'badge ' + (n.badge_class || 'badge-yellow');
      bBadge.textContent = n.badge || '🟡 NIFTY 50: Neutral';
    }
    if (bLtp && n.ltp) {
      const chgStr = n.change_pct !== undefined ? (n.change_pct >= 0 ? '+' : '') + n.change_pct + '%' : '';
      bLtp.textContent = `₹${n.ltp.toLocaleString('en-IN')} (${chgStr})`;
    }
    if (bStance && n.stance) {
      bStance.textContent = 'Tactical Stance: ' + n.stance;
    }
    if (bGuidance && n.guidance) {
      bGuidance.textContent = n.guidance;
    }
  }
}

function isRealDesktopPC() {
  const isCapacitor = !!(window.Capacitor || (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()));
  const isMobileUA = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent || '');
  const isFileProto = window.location.protocol === 'file:';
  const hasLocalPort = (window.location.port !== '' && window.location.port !== '80' && window.location.port !== '443') || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  return (!isCapacitor && !isMobileUA && (hasLocalPort || isFileProto));
}

async function triggerAppScan() {
  const overlay = document.getElementById('scanProgressOverlay');
  const btnText = document.getElementById('scanProgressText');
  const btnLog = document.getElementById('scanProgressLog');
  const barInner = document.getElementById('scanProgressBarInner');

  if (!isRealDesktopPC()) {
    const confirmed = confirm(
      '⚡ Cloud Auto-Scan Active\n\n' +
      'GitHub Actions automatically runs the full Nifty 500 scan every weekday at 9:15 AM IST before market opens.\n\n' +
      'Tap OK to reload and fetch the latest scan report.'
    );
    if (confirmed) window.location.reload();
    return;
  }

  if (overlay) overlay.style.display = 'flex';
  if (btnText) btnText.textContent = 'Initializing live stock & commodity scan...';
  if (barInner) barInner.style.width = '15%';
  if (btnLog) btnLog.textContent = 'Connecting to local scan engine server...';

  const scanUrl = 'http://localhost:' + (window.location.port || '8080') + '/api/scan';
  const statusUrl = 'http://localhost:' + (window.location.port || '8080') + '/api/scan/status';

  try {
    const res = await fetch(scanUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    if (res.ok) {
      if (barInner) barInner.style.width = '30%';
      if (btnText) btnText.textContent = 'Nifty 500 scan in progress...';
      if (btnLog) btnLog.textContent = 'Scoring technical setups, Mansfield RS, and Commodities...';

      let progressPct = 30;
      const pollTimer = setInterval(async () => {
        try {
          progressPct = Math.min(progressPct + 5, 90);
          if (barInner) barInner.style.width = progressPct + '%';

          const sResp = await fetch(statusUrl);
          if (sResp.ok) {
            const sData = await sResp.json();
            if (!sData.scan_in_progress) {
              clearInterval(pollTimer);
              if (barInner) barInner.style.width = '100%';
              if (btnText) btnText.textContent = 'Scan complete!';
              if (btnLog) btnLog.textContent = 'Reloading latest scan report...';
              setTimeout(() => { window.location.reload(); }, 600);
            }
          }
        } catch (e) {
          // Keep polling if transient network hiccup
        }
      }, 2000);

      // Safety timeout after 120 seconds
      setTimeout(() => {
        clearInterval(pollTimer);
        if (overlay && overlay.style.display !== 'none') {
          overlay.style.display = 'none';
          window.location.reload();
        }
      }, 120000);

    } else {
      throw new Error(`Server returned status ${res.status}`);
    }
  } catch (err) {
    console.warn('Direct scan endpoint failed or offline:', err);
    if (overlay) overlay.style.display = 'none';
    alert('⚡ Python Scan Server is not running.\n\nPlease launch "Run Screener.bat" on your PC to enable 1-click scanning.');
  }
}

// ── Render Commodity Bar ──────────────────────────────────────────────────
function renderCommodityBar() {
  const container = document.getElementById('commodityCards');
  if (!container || typeof COMMODITIES_DATA === 'undefined' || !COMMODITIES_DATA) return;

  let html = '';
  for (const [key, item] of Object.entries(COMMODITIES_DATA)) {
    if (!item) continue;
    const usdPriceStr = item.curr_price ? `${item.unit}${item.curr_price}` : 'N/A';
    const mcxPriceStr = item.mcx_inr_price ? ` · MCX Est: ₹${item.mcx_inr_price.toLocaleString('en-IN')}` : '';
    const emaStr = (item.ema15 && item.ema20) ? `15EMA: ${item.ema15} · 20EMA: ${item.ema20} (${item.diff_pct > 0 ? '+' : ''}${item.diff_pct}%)` : '';

    let badgeStyle = 'background: rgba(255,255,255,0.08); color:#ccc; border: 1px solid rgba(255,255,255,0.1);';
    if (item.signal === 'BUY') {
      badgeStyle = 'background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981;';
    } else if (item.signal === 'SELL') {
      badgeStyle = 'background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444;';
    } else if (item.signal === 'BULLISH_HOLD') {
      badgeStyle = 'background: rgba(99, 102, 241, 0.15); color: #a5b4fc; border: 1px solid #6366f155;';
    } else if (item.signal === 'BEARISH_HOLD') {
      badgeStyle = 'background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid #f59e0b55;';
    }

    html += `
      <div class="commodity-card">
        <span style="font-size:16px">${item.icon || '⛽'}</span>
        <div>
          <div class="commodity-card-name">${item.name} <span class="commodity-card-price">${usdPriceStr}</span><span style="color:#00d4aa;font-size:12px;font-weight:600">${mcxPriceStr}</span></div>
          <div class="commodity-card-emas">${emaStr}</div>
        </div>
        <span class="commodity-badge" style="${badgeStyle}">
          ${item.badge}
        </span>
      </div>
    `;
  }
  container.innerHTML = html;
}

// ── Swing Radar ───────────────────────────────────────────────────────────
let swingPreset = 'all';
let swingSortCol = 'swing_score';
let swingSortDir = -1; // -1 = descending

function getSwingData() {
  return SCREENER_DATA.filter(s => {
    // 1. HARD PRICE FLOOR: LTP >= ₹50.0 (Strictly No Penny Stocks)
    const ltp = parseFloat(s.ltp || s.current_ltp || 0);
    if (ltp < 50.0) return false;

    // 2. QUALITY CAP REQUIREMENT: Must be Large Cap, Mid Cap, or Zerodha MTF Quality Small Cap
    const mcap = parseFloat(s.market_cap || 0);
    const isLargeOrMid = (s.cap_category === 'Large Cap' || s.cap_category === 'Mid Cap' || s.is_large_cap || s.is_mid_cap || mcap >= 50000000000);
    const isMtfQuality = (s.is_mtf === true || s.is_mtf === 'true');
    if (!isLargeOrMid && !isMtfQuality) return false;

    // 3. VALID SETUP & SCORE FLOOR: Must have valid setup, calculated SL, and positive score
    const swingScore = parseFloat(s.swing_score || 0);
    const totalScore = parseFloat(s.total_score || 0);
    if (swingScore < 40 && totalScore < 45) return false;
    if (!s.swing_sl || parseFloat(s.swing_sl) <= 0) return false;

    return true;
  });
}

function applySwingPreset(data) {
  switch (swingPreset) {
    case 'rs':
      return data.filter(s => (s.rs_rating || 0) >= 80 && (s.setup_score >= 65 || s.swing_score >= 65));
    case 'blast':
      return data.filter(s => s.is_blast || (s.volume_spike >= 1.8 && (s.setup_score >= 70 || s.swing_score >= 70)));
    case 'inflow':
      return data.filter(s => s.is_order_flow_bull || (s.cmf >= 0.08 && s.clv >= 0.55 && (s.setup_score >= 65 || s.swing_score >= 65)));
    case 'momentum':
      return data.filter(s => s.is_momentum_surge || (s.momentum >= 70 && (s.setup_score >= 70 || s.swing_score >= 70)));
    case 'pullback':
      return data.filter(s => s.is_pullback || (s.entry_score >= 60 && s.setup_score >= 60));
    case 'quality':
      return data.filter(s => s.setup_score >= 70 && s.entry_score >= 50);
    default:
      return data;
  }
}

function setSwingPreset(preset) {
  swingPreset = preset;
  document.querySelectorAll('.swing-pill').forEach(p => p.classList.remove('swing-pill-active'));
  const pill = document.getElementById('swingPill-' + preset);
  if (pill) pill.classList.add('swing-pill-active');
  renderSwingRadar();
}

function sortSwingTable(col) {
  if (swingSortCol === col) { swingSortDir *= -1; }
  else { swingSortCol = col; swingSortDir = -1; }
  renderSwingRadar();
}

function getSwingCardClass(s) {
  if (s.swing_action === "EXTENDED — DON'T CHASE") return 'swing-card-extended';
  if (s.is_blast) return 'swing-card-blast';
  if (s.is_order_flow_bull) return 'swing-card-inflow';
  if (s.is_momentum_surge) return 'swing-card-momentum';
  if (s.is_pullback) return 'swing-card-pullback';
  return '';
}

function getSwingRingColor(s) {
  if (s.swing_action === "EXTENDED — DON'T CHASE") return '#f97316';
  if (s.swing_action === "BUY NOW") return '#10b981';
  if (s.swing_action === "BUY ON RETEST") return '#3b82f6';
  if (s.is_blast) return '#10b981';
  if (s.is_order_flow_bull) return '#6366f1';
  if (s.is_momentum_surge) return '#f59e0b';
  if (s.is_pullback) return '#3b82f6';
  return '#6c63ff';
}

function renderSwingRadar() {
  const allMtf = getSwingData();
  let filtered = applySwingPreset(allMtf);

  // Filter stocks by Title / Symbol / Badge / Reason search box
  const q = (document.getElementById('swingTitleFilter')?.value || '').trim().toLowerCase();
  if (q) {
    filtered = filtered.filter(s => 
      (s.symbol && s.symbol.toLowerCase().includes(q)) ||
      (s.name && s.name.toLowerCase().includes(q)) ||
      (s.swing_badge && s.swing_badge.toLowerCase().includes(q)) ||
      (s.swing_reason && s.swing_reason.toLowerCase().includes(q)) ||
      (s.swing_action && s.swing_action.toLowerCase().includes(q)) ||
      (s.cap_category && s.cap_category.toLowerCase().includes(q))
    );
  }

  // Multi-column sorting (handles both numbers & string titles)
  const sorted = [...filtered].sort((a, b) => {
    let av = a[swingSortCol];
    let bv = b[swingSortCol];

    if (swingSortCol === 'index') {
      av = allMtf.indexOf(a);
      bv = allMtf.indexOf(b);
    } else if (swingSortCol === 'cmf') {
      av = a.cmf ?? (a.is_order_flow_bull ? 1 : 0);
      bv = b.cmf ?? (b.is_order_flow_bull ? 1 : 0);
    }

    if (av === undefined || av === null) av = (typeof bv === 'string' ? '' : -999999);
    if (bv === undefined || bv === null) bv = (typeof av === 'string' ? '' : -999999);

    if (typeof av === 'string' || typeof bv === 'string') {
      return swingSortDir * String(av).localeCompare(String(bv));
    }
    return swingSortDir * (av - bv);
  });

  // Update header column sort indicators (↑ / ↓ / ↕)
  const swingCols = ['index','symbol','swing_score','rs_rating','swing_badge','ltp','volume_spike','rsi','momentum','cmf','swing_sl','swing_t1','swing_t2','swing_reason','swing_action'];
  swingCols.forEach(col => {
    const el = document.getElementById('swing_sort_' + col);
    if (el) {
      if (swingSortCol === col) {
        el.textContent = swingSortDir === -1 ? '↓' : '↑';
        el.style.color = 'var(--accent)';
      } else {
        el.textContent = '↕';
        el.style.color = 'var(--muted)';
      }
    }
  });

  // Update banner counts
  const mtfEl = document.getElementById('swingMtfCount');
  const rsEl = document.getElementById('swingRsCount');
  const blastEl = document.getElementById('swingBlastCount');
  const inflowEl = document.getElementById('swingInflowCount');
  if (mtfEl) mtfEl.textContent = allMtf.length;
  if (rsEl) rsEl.textContent = allMtf.filter(s => (s.rs_rating || 0) >= 80).length;
  if (blastEl) blastEl.textContent = allMtf.filter(s => s.is_blast).length;
  if (inflowEl) inflowEl.textContent = allMtf.filter(s => s.is_order_flow_bull).length;

  // Result count
  const rcEl = document.getElementById('swingResultCount');
  if (rcEl) {
    const filterNotice = q ? ` (filtered by "${q}")` : '';
    rcEl.textContent = `Showing ${sorted.length} swing stocks matching current preset${filterNotice}`;
  }

  // Top 10 Spotlight Cards (Always top 10 highest swing_score stocks overall, strictly sorted #1 to #10)
  const spotlight = document.getElementById('swingSpotlight');
  if (spotlight) {
    const top10 = [...allMtf].sort((a, b) => 
      (b.swing_score || 0) - (a.swing_score || 0) || 
      (b.total_score || 0) - (a.total_score || 0) || 
      (b.rs_rating || 0) - (a.rs_rating || 0) || 
      (a.symbol || '').localeCompare(b.symbol || '')
    ).slice(0, 10);
    if (top10.length === 0) {
      spotlight.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:20px">No stocks match this filter.</div>';
    } else {
      spotlight.innerHTML = top10.map((s, i) => {
        const score = s.swing_score || 0;
        const ringColor = getSwingRingColor(s);
        const cardClass = getSwingCardClass(s);
        const volStr = s.volume_spike ? `${s.volume_spike.toFixed(1)}x` : 'N/A';
        const rsiStr = s.rsi ? s.rsi.toFixed(0) : 'N/A';
        const rsVal = s.rs_rating || 50;
        const rsColor = rsVal >= 80 ? '#10b981' : rsVal >= 60 ? '#60a5fa' : rsVal >= 40 ? '#94a3b8' : '#ef4444';
        const slStr = s.swing_sl ? `₹${s.swing_sl.toFixed(1)}` : 'N/A';
        const t1Str = s.swing_t1 ? `₹${s.swing_t1.toFixed(1)}` : 'N/A';
        const t2Str = s.swing_t2 ? `₹${s.swing_t2.toFixed(1)}` : 'N/A';
        const slPct = s.swing_sl_pct ? `${s.swing_sl_pct}%` : '';
        const t1Pct = s.swing_t1_pct ? `+${s.swing_t1_pct}%` : '';
        return `
        <div class="swing-card ${cardClass}" onclick="document.getElementById('fSearch').value='${s.symbol}';switchTab('screener');applyFilters()">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px">
            <div>
              <div style="font-size:15px;font-weight:700;color:#fff">${i+1}. ${s.symbol}</div>
              <div style="font-size:11px;color:var(--muted);margin-top:1px">${(s.name||'').substring(0,28)}</div>
            </div>
            <div style="text-align:center">
              <div style="width:46px;height:46px;border-radius:50%;background:conic-gradient(${ringColor} ${score}%,rgba(255,255,255,0.06) 0);display:flex;align-items:center;justify-content:center">
                <div style="width:34px;height:34px;border-radius:50%;background:var(--card);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff">${score}</div>
              </div>
            </div>
          </div>
          <div style="font-size:11px;margin-bottom:8px;display:flex;gap:6px;align-items:center">
            <span style="background:rgba(108,99,255,0.15);color:#a5b4fc;border:1px solid #6c63ff33;border-radius:10px;padding:3px 9px;font-weight:600">${s.swing_badge||'–'}</span>
            <span class="badge ${rsVal>=80?'badge-green':rsVal>=60?'badge-green':rsVal>=40?'badge-gray':'badge-red'}" style="font-size:10px;font-weight:700">RS ${rsVal}</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:5px;font-size:11px;margin-bottom:10px">
            <div style="background:var(--card2);border-radius:6px;padding:5px;text-align:center">
              <div style="color:var(--muted);font-size:10px;display:flex;align-items:center;justify-content:center;gap:3px">LTP <span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:#10b981;box-shadow:0 0 4px #10b981"></span></div>
              <div style="font-weight:700;color:#fff;font-size:12px">₹${(s.ltp||0).toFixed(2)}</div>
              ${s.day_chg_pct !== undefined ? `<div style="font-size:9px;font-weight:700;color:${s.day_chg_pct>=0?'#34d399':'#f87171'}">${s.day_chg_pct>=0?'+':''}${s.day_chg_pct.toFixed(2)}%</div>` : ''}
            </div>
            <div style="background:var(--card2);border-radius:6px;padding:5px;text-align:center">
              <div style="color:var(--muted);font-size:10px">RS</div>
              <div style="font-weight:700;color:${rsColor}">${rsVal}</div>
            </div>
            <div style="background:var(--card2);border-radius:6px;padding:5px;text-align:center">
              <div style="color:var(--muted);font-size:10px">Vol</div>
              <div style="font-weight:700;color:${parseFloat(volStr)>=2?'#10b981':'#e2e8f0'}">${volStr}</div>
            </div>
            <div style="background:var(--card2);border-radius:6px;padding:5px;text-align:center">
              <div style="color:var(--muted);font-size:10px">RSI</div>
              <div style="font-weight:700;color:#e2e8f0">${rsiStr}</div>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;font-size:11px">
            <div style="text-align:center">
              <div style="color:#ef4444;font-size:10px">SL</div>
              <div class="swing-sl">${slStr}<span style="font-size:9px;color:var(--muted)"> ${slPct}</span></div>
            </div>
            <div style="text-align:center">
              <div style="color:#10b981;font-size:10px">T1 (1:1.5)</div>
              <div class="swing-t1">${t1Str}<span style="font-size:9px;color:var(--muted)"> ${t1Pct}</span></div>
            </div>
            <div style="text-align:center">
              <div style="color:#00d4aa;font-size:10px">T2 (1:2.5)</div>
              <div class="swing-t2">${t2Str}</div>
            </div>
          </div>
          <div style="display:flex;gap:6px;margin-top:8px;border-top:1px solid var(--border);padding-top:6px;align-items:center;justify-content:space-between">
            <div style="font-size:10px;color:var(--muted)">${s.swing_reason||''}</div>
            <div style="display:flex;gap:4px">
              <button class="btn-add" onclick="event.stopPropagation();openSwingCalcModal('${s.symbol}')" style="padding:3px 8px;font-size:10px;background:var(--card2)">🧮 Calc</button>
              <button class="btn-add" onclick="event.stopPropagation();addToWatchlist('${s.symbol}')" style="padding:3px 8px;font-size:10px;background:linear-gradient(135deg,#00d4aa,#10b981);color:#06060f;font-weight:700">⭐ +WL</button>
            </div>
          </div>
        </div>`;
      }).join('');
    }
  }

  // Full table
  const tbody = document.getElementById('swingBody');
  if (!tbody) return;
  if (sorted.length === 0) {
    tbody.innerHTML = '<tr><td colspan="15" style="text-align:center;padding:40px;color:var(--muted)">No stocks match this filter.</td></tr>';
    return;
  }
  tbody.innerHTML = sorted.map((s, i) => {
    const volStr = s.volume_spike ? `${s.volume_spike.toFixed(1)}x` : '–';
    const rsiStr = s.rsi ? s.rsi.toFixed(0) : '–';
    const rsVal = s.rs_rating || 50;
    const cmfStr = s.cmf !== undefined ? (s.cmf >= 0 ? '+' : '') + s.cmf.toFixed(2) : '–';
    const cmfColor = (s.cmf||0) >= 0.05 ? '#10b981' : (s.cmf||0) <= -0.05 ? '#ef4444' : '#94a3b8';
    const volColor = (s.volume_spike||0) >= 2.0 ? '#10b981' : (s.volume_spike||0) >= 1.5 ? '#fbbf24' : '#94a3b8';
    return `<tr>
      <td>${i+1}</td>
      <td><strong style="color:#e2e8f0">${s.symbol}</strong><br><span style="font-size:10px;color:var(--muted)">${(s.cap_category||'')}</span></td>
      <td><span style="font-weight:700;color:#a78bfa;font-size:15px">${s.swing_score||0}</span></td>
      <td><span class="badge ${rsVal>=80?'badge-green':rsVal>=60?'badge-green':rsVal>=40?'badge-gray':'badge-red'}" style="font-size:11px;font-weight:700">RS ${rsVal}</span></td>
      <td><span style="font-size:11px;background:rgba(108,99,255,0.12);border:1px solid rgba(108,99,255,0.3);border-radius:10px;padding:3px 8px;white-space:nowrap">${s.swing_badge||'–'}</span></td>
      <td>₹${(s.ltp||0).toFixed(2)}</td>
      <td style="color:${volColor};font-weight:600">${volStr}</td>
      <td>${rsiStr}</td>
      <td>${(s.momentum||0).toFixed(0)}</td>
      <td style="color:${cmfColor};font-weight:600">${cmfStr}<br><span style="font-size:10px;color:var(--muted)">${s.pa_badge||''}</span></td>
      <td class="swing-sl">${s.swing_sl ? '₹' + s.swing_sl.toFixed(1) : '–'}<br><span style="font-size:10px;color:#ef4444">${s.swing_sl_pct||0}%</span></td>
      <td class="swing-t1">${s.swing_t1 ? '₹' + s.swing_t1.toFixed(1) : '–'}<br><span style="font-size:10px;color:#10b981">+${s.swing_t1_pct||0}%</span></td>
      <td class="swing-t2">${s.swing_t2 ? '₹' + s.swing_t2.toFixed(1) : '–'}<br><span style="font-size:10px;color:#00d4aa">+${s.swing_t2_pct||0}%</span></td>
      <td style="font-size:11px;color:var(--muted);max-width:180px;white-space:normal">${s.swing_reason||'–'}</td>
      <td>
        <div style="display:flex;gap:4px">
          <button class="btn-add" onclick="openSwingCalcModal('${s.symbol}')" style="padding:3px 6px;font-size:10px;background:var(--card2)" title="Calculate Position Size">🧮</button>
          <button class="btn-add" onclick="addToWatchlist('${s.symbol}')" style="padding:3px 6px;font-size:10px" title="Add to Watchlist">⭐</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

// ─── S/R Breakout Radar ────────────────────────────────────────────────────

let srFilter = 'all';

function setSrFilter(f) {
  srFilter = f;
  document.querySelectorAll('[id^="srPill-"]').forEach(el => el.classList.remove('swing-pill-active'));
  const pill = document.getElementById('srPill-' + f);
  if (pill) pill.classList.add('swing-pill-active');
  renderSrBreakouts();
}

function renderSrBreakouts() {
  const all = SCREENER_DATA.filter(s => s.has_sr_setup && s.sr_type && s.sr_type !== 'NONE');

  // Count by type
  const breakCount    = all.filter(s => s.sr_type === 'BREAK_RES').length;
  const retestCount   = all.filter(s => s.sr_type === 'RETEST_BUY').length;
  const approachCount = all.filter(s => s.sr_type === 'APPROACHING_RES').length;
  const el = id => document.getElementById(id);
  if (el('srCountBreak'))   el('srCountBreak').textContent   = breakCount;
  if (el('srCountRetest'))  el('srCountRetest').textContent  = retestCount;
  if (el('srCountApproach'))el('srCountApproach').textContent = approachCount;
  if (el('srCountAll'))     el('srCountAll').textContent     = all.length;

  // Apply filter
  let filtered = all;
  if (srFilter === 'break')   filtered = all.filter(s => s.sr_type === 'BREAK_RES');
  if (srFilter === 'retest')  filtered = all.filter(s => s.sr_type === 'RETEST_BUY');
  if (srFilter === 'approach')filtered = all.filter(s => s.sr_type === 'APPROACHING_RES');

  // Sort by sr_score descending
  filtered = filtered.sort((a, b) => (b.sr_score || 0) - (a.sr_score || 0));

  const grid  = el('srBreakoutGrid');
  const empty = el('srBreakoutEmpty');
  if (!grid) return;

  if (filtered.length === 0) {
    grid.innerHTML = '';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  grid.innerHTML = filtered.map(s => {
    const typeColor  = s.sr_type === 'BREAK_RES' ? '#10b981' : s.sr_type === 'RETEST_BUY' ? '#a78bfa' : '#fbbf24';
    const typeBorder = s.sr_type === 'BREAK_RES' ? 'rgba(16,185,129,0.25)' : s.sr_type === 'RETEST_BUY' ? 'rgba(167,139,250,0.25)' : 'rgba(251,191,36,0.25)';
    const scoreBar   = s.sr_score || 0;
    const scoreFill  = scoreBar >= 80 ? '#10b981' : scoreBar >= 60 ? '#60a5fa' : scoreBar >= 40 ? '#fbbf24' : '#ef4444';
    const rsVal      = s.rs_rating || 50;
    const rsColor    = rsVal >= 80 ? '#10b981' : rsVal >= 60 ? '#60a5fa' : '#94a3b8';
    const distStr    = s.dist_from_res_pct != null ? (s.dist_from_res_pct >= 0 ? '+' : '') + s.dist_from_res_pct.toFixed(1) + '%' : '–';
    const slStr      = s.sr_sl    ? '₹' + s.sr_sl.toFixed(1) + (s.sr_sl_pct   ? ' (' + s.sr_sl_pct  + '%)' : '') : '–';
    const t1Str      = s.sr_t1    ? '₹' + s.sr_t1.toFixed(1) + (s.sr_t1_pct   ? ' (+' + s.sr_t1_pct + '%)' : '') : '–';
    const t2Str      = s.sr_t2    ? '₹' + s.sr_t2.toFixed(1) + (s.sr_t2_pct   ? ' (+' + s.sr_t2_pct + '%)' : '') : '–';
    const resStr     = s.res_level ? '₹' + s.res_level.toFixed(2) : '–';
    const supStr     = s.sup_level ? '₹' + s.sup_level.toFixed(2) : '–';

    return `
    <div style="background:var(--card);border:1px solid ${typeBorder};border-radius:14px;padding:16px;position:relative;overflow:hidden;cursor:pointer;transition:transform .15s,box-shadow .15s"
         onclick="document.getElementById('fSearch').value='${s.symbol}';switchTab('screener');applyFilters()"
         onmouseenter="this.style.transform='translateY(-2px)';this.style.boxShadow='0 8px 28px rgba(0,0,0,0.35)'"
         onmouseleave="this.style.transform='';this.style.boxShadow=''">
      <!-- Accent bar -->
      <div style="position:absolute;top:0;left:0;right:0;height:3px;background:${typeColor};border-radius:14px 14px 0 0"></div>

      <!-- Header row -->
      <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px;margin-top:4px">
        <div>
          <div style="font-size:15px;font-weight:800;color:#fff">${s.symbol}</div>
          <div style="font-size:10px;color:var(--muted);margin-top:1px">${(s.name||'').substring(0,26)} · ${s.cap_category||''}</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:11px;font-weight:700;color:${typeColor};background:rgba(0,0,0,0.25);border:1px solid ${typeBorder};border-radius:8px;padding:3px 8px;white-space:nowrap">${s.sr_badge||'–'}</div>
          <div style="font-size:10px;color:var(--muted);margin-top:3px">₹${(s.ltp||0).toFixed(2)}</div>
        </div>
      </div>

      <!-- SR Score bar -->
      <div style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin-bottom:3px">
          <span>SR Score</span><span style="color:${scoreFill};font-weight:700">${scoreBar}</span>
        </div>
        <div style="background:rgba(255,255,255,0.07);border-radius:4px;height:5px;overflow:hidden">
          <div style="height:100%;width:${scoreBar}%;background:${scoreFill};border-radius:4px;transition:width .4s"></div>
        </div>
      </div>

      <!-- Key levels grid -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;margin-bottom:10px">
        <div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:6px 8px">
          <div style="color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.05em">Resistance</div>
          <div style="color:#e2e8f0;font-weight:700;margin-top:1px">${resStr} <span style="color:${s.dist_from_res_pct!=null&&s.dist_from_res_pct>=0?'#10b981':'#fbbf24'};font-size:10px">${distStr}</span></div>
        </div>
        <div style="background:rgba(255,255,255,0.04);border-radius:8px;padding:6px 8px">
          <div style="color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.05em">Support</div>
          <div style="color:#e2e8f0;font-weight:700;margin-top:1px">${supStr}</div>
        </div>
        <div style="background:rgba(239,68,68,0.07);border-radius:8px;padding:6px 8px">
          <div style="color:#fca5a5;font-size:9px;text-transform:uppercase;letter-spacing:.05em">Stop Loss</div>
          <div style="color:#ef4444;font-weight:700;margin-top:1px">${slStr}</div>
        </div>
        <div style="background:rgba(16,185,129,0.07);border-radius:8px;padding:6px 8px">
          <div style="color:#6ee7b7;font-size:9px;text-transform:uppercase;letter-spacing:.05em">Target 1 (1:2)</div>
          <div style="color:#10b981;font-weight:700;margin-top:1px">${t1Str}</div>
        </div>
      </div>
      <div style="background:rgba(16,185,129,0.05);border:1px dashed rgba(16,185,129,0.2);border-radius:8px;padding:5px 8px;font-size:10px;color:var(--muted);margin-bottom:10px">
        🎯 Target 2 (1:3): <span style="color:#34d399;font-weight:700">${t2Str}</span>
      </div>

      <!-- Footer: RS + RSI + Reason -->
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">
        <span style="font-size:11px;font-weight:700;color:${rsColor}">RS ${rsVal}</span>
        <span style="font-size:10px;color:var(--muted)">RSI ${s.rsi ? s.rsi.toFixed(0) : '–'}</span>
        <button onclick="event.stopPropagation();addToWatchlist('${s.symbol}')" style="font-size:10px;padding:2px 8px;border-radius:6px;border:1px solid rgba(108,99,255,0.4);background:rgba(108,99,255,0.1);color:#a5b4fc;cursor:pointer">⭐ Watch</button>
      </div>
      <div style="font-size:10px;color:var(--muted);margin-top:7px;line-height:1.4">${s.sr_reason||''}</div>
    </div>`;
  }).join('');
}



let currentCalcStock = null;

function openSwingCalcModal(symbol) {
  const stock = SCREENER_DATA.find(s => s.symbol === symbol);
  if (!stock || !stock.ltp) {
    alert('Invalid stock price for calculation');
    return;
  }
  currentCalcStock = stock;
  const header = document.getElementById('swingCalcHeader');
  if (header) {
    header.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div style="font-size:16px;font-weight:700;color:var(--white)">${stock.symbol}</div>
          <div style="font-size:11px;color:var(--muted)">${stock.name || ''}</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:16px;font-weight:700;color:var(--accent2)">₹${stock.ltp.toFixed(2)}</div>
          <div style="font-size:11px;color:var(--muted)">LTP</div>
        </div>
      </div>
    `;
  }
  const addBtn = document.getElementById('swingCalcAddWlBtn');
  if (addBtn) {
    addBtn.onclick = function() {
      addToWatchlist(stock.symbol);
      closeSwingCalcModal();
    };
  }
  recalcSwingPosition();
  const modal = document.getElementById('swingCalcModalBg');
  if (modal) modal.style.display = 'flex';
}

function closeSwingCalcModal() {
  const modal = document.getElementById('swingCalcModalBg');
  if (modal) modal.style.display = 'none';
}

function setCapitalPreset(amt) {
  const inp = document.getElementById('swingCapitalInput');
  if (inp) {
    inp.value = amt;
    recalcSwingPosition();
  }
}

function recalcSwingPosition() {
  if (!currentCalcStock) return;
  const capital = parseFloat(document.getElementById('swingCapitalInput')?.value || 0);
  const ltp = currentCalcStock.ltp;
  if (!ltp || ltp <= 0) return;

  const qty = Math.floor(capital / ltp);
  const totalCost = qty * ltp;
  const minRequired = Math.ceil(ltp);
  
  const slPrice = currentCalcStock.swing_sl || (ltp * 0.96);
  const t1Price = currentCalcStock.swing_t1 || (ltp * 1.08);
  const t2Price = currentCalcStock.swing_t2 || (ltp * 1.15);

  const maxRiskAmt = Math.abs(ltp - slPrice) * qty;
  const maxRiskPct = ((Math.abs(ltp - slPrice) / ltp) * 100).toFixed(1);
  const profitT1 = (t1Price - ltp) * qty;
  const profitT2 = (t2Price - ltp) * qty;

  const resEl = document.getElementById('swingCalcResults');
  if (resEl) {
    if (qty <= 0) {
      resEl.innerHTML = `
        <div style="grid-column: 1 / -1; background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); border-radius:10px; padding:14px; color:var(--text); text-align:center">
          <div style="font-weight:700; color:#ef4444; font-size:13px; margin-bottom:4px">⚠️ Insufficient Capital to Buy 1 Share</div>
          <div style="font-size:12px">Your entered capital (₹${capital.toLocaleString('en-IN')}) is less than the price of 1 share (₹${minRequired.toLocaleString('en-IN')}).</div>
          <div style="font-size:11px; color:var(--muted); margin-top:6px">Minimum Capital Required: <strong>₹${minRequired.toLocaleString('en-IN')}</strong></div>
        </div>
      `;
    } else {
      resEl.innerHTML = `
        <div style="background:var(--card2);padding:10px;border-radius:8px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Shares to Buy</div>
          <div style="font-size:18px;font-weight:700;color:var(--white)">${qty} ${qty === 1 ? 'Share' : 'Shares'}</div>
          <div style="font-size:10px;color:var(--muted)">Est. Outlay: ₹${Math.round(totalCost).toLocaleString('en-IN')}</div>
        </div>
        <div style="background:var(--card2);padding:10px;border-radius:8px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Max Risk (SL)</div>
          <div style="font-size:18px;font-weight:700;color:#ef4444">-₹${Math.round(maxRiskAmt).toLocaleString('en-IN')}</div>
          <div style="font-size:10px;color:var(--muted)">SL @ ₹${slPrice.toFixed(1)} (-${maxRiskPct}%)</div>
        </div>
        <div style="background:var(--card2);padding:10px;border-radius:8px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Target 1 Profit (+8%)</div>
          <div style="font-size:18px;font-weight:700;color:#10b981">+₹${Math.round(profitT1).toLocaleString('en-IN')}</div>
          <div style="font-size:10px;color:var(--muted)">Target: ₹${t1Price.toFixed(1)}</div>
        </div>
        <div style="background:var(--card2);padding:10px;border-radius:8px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Target 2 Profit (+15%)</div>
          <div style="font-size:18px;font-weight:700;color:#00d4aa">+₹${Math.round(profitT2).toLocaleString('en-IN')}</div>
          <div style="font-size:10px;color:var(--muted)">Target: ₹${t2Price.toFixed(1)}</div>
        </div>
      `;
    }
  }
}

function updateWatchlistSignalsAndAlerts(item, live) {
  if (!live) return;
  item.ltp = live.ltp;
  item.current_score = live.total_score;
  item.current_strength = live.strength;
  item.current_value = live.value;
  item.current_momentum = live.momentum;
  item.roe_pct = live.roe_pct;
  item.de_ratio = live.de_ratio;
  item.npm_pct = live.npm_pct;
  item.rsi = live.rsi;
  item.wk52_return_pct = live.wk52_return_pct;
  item.news = live.news || [];

  let sig = "HOLD", sigBadge = "🟡 HOLD", sigReason = "Moderate quality score; maintain position";
  if (live.total_score >= 55 && live.strength >= 50) {
    sig = "BUY";
    sigBadge = "🟢 BUY";
    sigReason = `Strong quality score (${live.total_score.toFixed(1)}) & solid fundamentals`;
  } else if (live.total_score < 40) {
    sig = "SELL";
    sigBadge = "🔴 SELL";
    sigReason = `Quality score collapsed to ${live.total_score.toFixed(1)} (<40)`;
  }
  item.signal = sig;
  item.signal_badge = sigBadge;
  item.signal_reason = sigReason;
}

function populatePortfolioSeed() {
  watchlist = JSON.parse(JSON.stringify(WATCHLIST_SEED));
  watchlist.forEach(item => {
    const live = SCREENER_DATA.find(s => s.symbol === item.symbol);
    updateWatchlistSignalsAndAlerts(item, live);
  });
  saveWatchlist();
  renderWatchlist();
  updateWlCount();
  renderStats();
  alert("Successfully populated your 9 portfolio equity holdings!");
}

function clearAllWatchlist() {
  if (!confirm("Are you sure you want to clear all watchlist stocks?")) return;
  watchlist = [];
  localStorage.removeItem('quality_watchlist_v1');
  localStorage.removeItem('quality_watchlist_v2');
  localStorage.removeItem('quality_watchlist_v3');
  localStorage.removeItem('quality_watchlist_v4');
  localStorage.removeItem('quality_watchlist_v5');
  localStorage.removeItem('quality_watchlist_v6');
  localStorage.removeItem('quality_watchlist_v7');
  saveWatchlist();
  renderWatchlist();
  updateWlCount();
  renderStats();
  alert("Watchlist cleared successfully!");
}

// ── LT Watchlist — Dynamic Status Gate ────────────────────────────────────
let ltWatchlist = (typeof LT_WATCHLIST !== 'undefined' && Array.isArray(LT_WATCHLIST)) ? LT_WATCHLIST : [];
let ltFilterStatus = 'ALL';
let ltShowRetired = false;
let ltSortCol = 'durability_score';
let ltSortDir = -1;

function calculateClientStatus(item) {
  // BOUGHT always takes priority — user has an active position
  if (item.holding && (item.holding.qty > 0 || parseInt(item.holding.qty, 10) > 0)) {
    const qty = parseInt(item.holding.qty, 10) || 1;
    const avgPrice = parseFloat(item.holding.avg_price) || item.ltp || 0;
    const buyDate = item.holding.buy_date || '';
    const pnl = item.holding.unrealized_pnl || 0;
    const pnlPct = item.holding.unrealized_pnl_pct || 0;
    const pnlStr = pnl !== 0 ? `P&L: ${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(2)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}%)` : '';
    item.status = "BOUGHT";
    item.status_badge = `🟢 BOUGHT (${qty})`;
    item.status_badge_class = "badge-green";
    item.status_reason = `Purchased${buyDate ? ' on ' + buyDate : ''}: ${qty} share(s) @ ₹${avgPrice.toFixed(2)} · Cooling off / Holding active ${pnlStr}`.trim();
    return;
  }
  // Status priority: BUY_NOW > WAIT > WATCHLIST. Client can only UPGRADE, never downgrade.
  const statusRank = { 'BUY_NOW': 3, 'WAIT': 2, 'WATCHLIST': 1 };
  const serverStatus = item.status || 'WATCHLIST';
  const serverRank = statusRank[serverStatus] || 0;

  const uptrendStates = TREND_CONFIG.uptrend;
  const trend = item.trend || "Consolidation";
  const rsi = item.rsi || 50;
  const ltp = item.ltp || 0;
  const isAuto = (item.gtt_mode === 'auto' || item.gtt_mode == null || item.is_auto_gtt);
  const gtt = isAuto ? (item.auto_gtt || item.gtt_level) : item.gtt_level;
  const dayChg = item.day_chg_pct || 0;

  if (uptrendStates.includes(trend)) {
    if (gtt !== null && gtt !== undefined && gtt !== "" && ltp > 0 && ltp <= (gtt * 1.008) && rsi < 70) {
      if (dayChg >= -0.35 || (rsi > 42 && rsi < 70)) {
        if (statusRank['BUY_NOW'] > serverRank) {
          item.status = "BUY_NOW";
          item.status_badge = "🟢 BUY NOW";
          item.status_badge_class = "badge-green";
          item.status_reason = `A/E Breakout: Price ₹${ltp.toFixed(2)} at Support GTT ₹${parseFloat(gtt).toFixed(2)}`;
        }
        return;
      }
    }
    if (statusRank['WAIT'] > serverRank) {
      item.status = "WAIT";
      item.status_badge = "🔵 WAIT";
      item.status_badge_class = "badge-purple";
      item.status_reason = `Trend confirmed (${trend}) — waiting for pullback to GTT` + (gtt ? ` ₹${parseFloat(gtt).toFixed(2)}` : '');
    }
    return;
  }
  // Not in uptrend — keep server status unchanged (never downgrade to WATCHLIST)
}


function filterLtStatus(status) {
  ltFilterStatus = status;
  document.querySelectorAll('[id^="ltPill-"]').forEach(el => el.classList.remove('swing-pill-active'));
  const pill = document.getElementById('ltPill-' + status);
  if (pill) pill.classList.add('swing-pill-active');
  renderLtWatchlist();
}

function toggleLtShowRetired(checked) {
  ltShowRetired = checked;
  renderLtWatchlist();
}

function sortLtTable(col) {
  if (ltSortCol === col) {
    ltSortDir *= -1;
  } else {
    ltSortCol = col;
    ltSortDir = -1;
  }
  renderLtWatchlist();
}

function renderLtWatchlist() {
  if (!Array.isArray(ltWatchlist)) return;

  // Sync live price & recalculate status for all items
  ltWatchlist.forEach(item => {
    const live = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA))
      ? SCREENER_DATA.find(s => s.symbol === item.symbol)
      : null;
    if (live) {
      // Use live.ltp if it's a valid positive number; otherwise keep existing item.ltp
      if (live.ltp != null && live.ltp > 0) item.ltp = live.ltp;
      else if (item.ltp == null || item.ltp === 0) item.ltp = live.ltp || 0;
      item.rsi = live.rsi || item.rsi || 50;
      item.trend = live.trend || item.trend || 'Consolidation';
      item.trend_badge = live.tech_rating || item.trend_badge || '🟡 Consolidation Phase';
      item.rs_rating = live.rs_rating || item.rs_rating || 50;
      item.day_chg_pct = live.day_chg_pct || item.day_chg_pct || 0;

      const liveEma = live.ema20 || 0;
      const liveSup = live.sup_level || 0;
      const liveLow20 = live.low20 || 0;
      const liveMa50 = live.ma50 || 0;

      if (liveEma > 0 && liveEma < item.ltp) {
        item.auto_gtt = Math.round(liveEma * 100) / 100;
      } else if (liveSup > 0 && liveSup < item.ltp) {
        item.auto_gtt = Math.round(liveSup * 100) / 100;
      } else if (liveLow20 > 0 && liveLow20 < item.ltp) {
        item.auto_gtt = Math.round(liveLow20 * 100) / 100;
      } else if (liveMa50 > 0 && liveMa50 < item.ltp) {
        item.auto_gtt = Math.round(liveMa50 * 100) / 100;
      } else if (liveLow20 > 0) {
        item.auto_gtt = Math.round(liveLow20 * 100) / 100;
      } else if (liveEma > 0) {
        item.auto_gtt = Math.round(liveEma * 100) / 100;
      } else if (liveSup > 0) {
        item.auto_gtt = Math.round(liveSup * 100) / 100;
      } else if (item.ltp > 0) {
        item.auto_gtt = Math.round(item.ltp * 100) / 100;
      }
    }
    calculateClientStatus(item);
    const _effGtt = (item.gtt_mode === 'auto' || item.is_auto_gtt) ? (item.auto_gtt || item.gtt_level) : item.gtt_level;
    if (_effGtt && _effGtt > 0 && item.ltp > 0) {
      item.dist_from_gtt_pct = Math.round(((item.ltp - _effGtt) / _effGtt) * 1000) / 10;
    } else {
      item.dist_from_gtt_pct = null;
    }
  });

  const isCuratedLt = s => (typeof LT_WATCHLIST !== 'undefined' && Array.isArray(LT_WATCHLIST)) && LT_WATCHLIST.some(item => (item.symbol || '').toUpperCase() === (s.symbol || '').toUpperCase());

  const isPenny = s => {
    if (isCuratedLt(s)) return false;
    const p = parseFloat(s.ltp || 0);
    const hp = s.holding ? parseFloat(s.holding.avg_price || 0) : 0;
    return (p > 0 && p <= 75.0) || (hp > 0 && hp <= 75.0);
  };

  const activeList = ltWatchlist.filter(s => s.active !== false && !isPenny(s));
  const retiredList = ltWatchlist.filter(s => s.active === false && !isPenny(s));

  const buyNowCount = activeList.filter(s => s.status === 'BUY_NOW').length;
  const boughtCount = activeList.filter(s => s.status === 'BOUGHT' || (s.holding && s.holding.qty > 0)).length;
  const waitCount = activeList.filter(s => s.status === 'WAIT').length;
  const watchlistCount = activeList.filter(s => s.status === 'WATCHLIST').length;
  const totalActive = activeList.length;

  // Update Stats & Header Counts
  const el = id => document.getElementById(id);
  if (el('ltCountBuyNow')) el('ltCountBuyNow').textContent = buyNowCount;
  if (el('ltCountWait')) el('ltCountWait').textContent = waitCount;
  if (el('ltCountWatchlist')) el('ltCountWatchlist').textContent = watchlistCount;
  if (el('ltCountBought')) el('ltCountBought').textContent = boughtCount;
  if (el('ltCountTotal')) el('ltCountTotal').textContent = totalActive;
  if (el('wlCount')) el('wlCount').textContent = totalActive;
  if (el('ltRetiredCount')) el('ltRetiredCount').textContent = retiredList.length;

  if (el('ltPillCountALL')) el('ltPillCountALL').textContent = totalActive;
  if (el('ltPillCountBUY_NOW')) el('ltPillCountBUY_NOW').textContent = buyNowCount;
  if (el('ltPillCountBOUGHT')) el('ltPillCountBOUGHT').textContent = boughtCount;
  if (el('ltPillCountWAIT')) el('ltPillCountWAIT').textContent = waitCount;
  if (el('ltPillCountWATCHLIST')) el('ltPillCountWATCHLIST').textContent = watchlistCount;

  // Alert Banner
  const alertBox = el('ltBuyNowAlert');
  const alertText = el('ltBuyNowAlertText');
  if (alertBox) {
    if (buyNowCount > 0) {
      const buyNowItems = activeList.filter(s => s.status === 'BUY_NOW');
      const symbolsStr = buyNowItems.map(s => `${s.symbol} (LTP: ₹${s.ltp.toFixed(2)} ≤ GTT: ₹${parseFloat(s.gtt_level).toFixed(2)})`).join(', ');
      if (alertText) alertText.innerHTML = `<strong>${buyNowCount} Stock(s) Triggered:</strong> ${symbolsStr}`;
      alertBox.style.display = 'flex';
    } else {
      alertBox.style.display = 'none';
    }
  }

  // Filter display list
  let displayList = ltWatchlist.filter(s => !isPenny(s) && (ltShowRetired ? true : s.active !== false));
  if (ltFilterStatus !== 'ALL') {
    displayList = displayList.filter(s => s.status === ltFilterStatus);
  }

  // Sort
  displayList.sort((a, b) => {
    let av = a[ltSortCol];
    let bv = b[ltSortCol];
    if (ltSortCol === 'status') {
      const order = { 'BUY_NOW': 1, 'BOUGHT': 2, 'WAIT': 3, 'WATCHLIST': 4 };
      av = order[a.status] || 5;
      bv = order[b.status] || 5;
    }
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'string') return ltSortDir * av.localeCompare(bv);
    return ltSortDir * (av - bv);
  });

  const tbody = el('ltWatchlistBody');
  const empty = el('ltEmpty');
  if (!tbody) return;

  if (displayList.length === 0) {
    tbody.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  tbody.innerHTML = displayList.map((s, i) => {
    const isRetired = (s.active === false);
    const isBought = (s.status === 'BOUGHT' || (s.holding && s.holding.qty > 0 && s.status !== 'BUY_NOW'));
    const holdingQty = (s.holding && s.holding.qty) ? s.holding.qty : 1;
    const scoreVal = s.durability_score || 75;
    const scoreColor = scoreVal >= 85 ? '#10b981' : scoreVal >= 75 ? '#60a5fa' : '#fbbf24';
    const statusBadgeCls = isBought ? 'badge-green' : (s.status === 'BUY_NOW' ? 'badge-green' : s.status === 'WAIT' ? 'badge-purple' : 'badge-gray');
    const statusBadgeText = s.status_badge || (isBought ? `🟢 BOUGHT (${holdingQty})` : (s.status === 'BUY_NOW' ? '🟢 BUY NOW' : s.status === 'WAIT' ? '🔵 WAIT' : '⬜ WATCHING'));


    const isAutoGtt = (s.gtt_mode === 'auto' || s.gtt_mode == null || s.is_auto_gtt);
    const gttVal = isAutoGtt ? (s.auto_gtt || s.gtt_level) : s.gtt_level;
    const gttStr = gttVal ? `₹${parseFloat(gttVal).toFixed(2)}` : '—';
    const ltpStr = s.ltp ? `₹${s.ltp.toFixed(2)}` : '—';
    const distStr = s.dist_from_gtt_pct != null
      ? `<span style="color:${s.dist_from_gtt_pct <= 0 ? '#10b981' : '#a5b4fc'};font-weight:700">${s.dist_from_gtt_pct <= 0 ? '' : '+'}${s.dist_from_gtt_pct.toFixed(1)}%</span>`
      : '—';

    const rsiStr = s.rsi ? s.rsi.toFixed(0) : '—';

    const gttBtn = isAutoGtt
      ? `<button onclick="promptGttEdit('${s.symbol}', ${gttVal || 0}, true)" style="background:rgba(52,211,153,0.12);border:1px solid rgba(52,211,153,0.3);color:#34d399;font-weight:700;padding:4px 8px;border-radius:6px;cursor:pointer;font-size:11px" title="⚡ Auto-Trailing 20-EMA / Support Target (Click to edit or set custom level)">⚡ ${gttStr}</button>`
      : `<button onclick="promptGttEdit('${s.symbol}', ${gttVal || 0}, false)" style="background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);color:#fbbf24;font-weight:700;padding:4px 8px;border-radius:6px;cursor:pointer;font-size:11px" title="📌 Fixed Manual Level (Click to edit or reset to auto)">📌 ${gttStr}</button>`;

    return `
    <tr style="${isRetired ? 'opacity:0.5;background:rgba(0,0,0,0.2)' : ''}">
      <td>
        <div style="font-weight:800;color:${scoreColor};font-size:14px">${scoreVal} <span style="font-size:10px;color:var(--muted)">/100</span></div>
      </td>
      <td>
        <div style="font-weight:700;color:#fff;font-size:14px">${s.symbol}</div>
        <div style="font-size:10px;color:var(--muted)">${s.portfolio_role || ''}</div>
      </td>
      <td><span class="badge ${s.type === 'PSU' ? 'badge-yellow' : 'badge-purple'}" style="font-size:10px">${s.type || 'Private'}</span></td>
      <td><span style="font-size:11px;color:var(--text)">${s.sector || ''}</span></td>
      <td>
        <span class="badge ${statusBadgeCls}" style="font-size:11px;font-weight:700" title="${s.status_reason || ''}">${statusBadgeText}</span>
      </td>
      <td>
        <span class="badge ${trendBadgeClass(s.trend)}" style="font-size:10px">
          ${s.trend_badge || s.trend || '—'}
        </span>
      </td>
      <td><span style="font-size:11px;font-weight:600">${rsiStr}</span></td>
      <td><strong style="color:#fff;font-size:13px">${ltpStr}</strong></td>
      <td>${gttBtn}</td>
      <td>${distStr}</td>
      <td><span style="font-size:11px;color:var(--muted)">${s.portfolio_role || '—'}</span></td>
      <td>
        <div style="display:flex;gap:6px">
          ${!isRetired ? `
            ${isBought ? `
              <button onclick="openLtHoldingLogModal('${s.symbol}')" style="background:rgba(6,182,212,0.18);border:1px solid rgba(6,182,212,0.4);color:#22d3ee;font-weight:700;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="View Purchase Log & Holding details for ${s.symbol}">📋 Purchased (${holdingQty})</button>
              <button onclick="openLtBuyModal('${s.symbol}', ${s.ltp || 0})" style="background:var(--card2);border:1px solid var(--border);color:#a7f3d0;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Add More / Pyramid">+ Add</button>
            ` : `
              <button onclick="openLtBuyModal('${s.symbol}', ${s.ltp || 0})" style="background:rgba(16,185,129,0.18);border:1px solid rgba(16,185,129,0.4);color:#34d399;font-weight:700;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Record Buy Transaction for ${s.symbol}">🛒 Buy</button>
            `}
            <button onclick="promptGttEdit('${s.symbol}', ${s.gtt_level || 0})" style="background:var(--card2);border:1px solid var(--border);color:var(--text);font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Edit GTT Level">✏️ GTT</button>
            <button onclick="retireLtStock('${s.symbol}')" style="background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.3);color:#ef4444;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Soft-delete (Keep history)">🗑️ Retire</button>
          ` : `
            <button onclick="reactivateLtStock('${s.symbol}')" style="background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.3);color:#34d399;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer" title="Reactivate Stock">🔄 Reactivate</button>
          `}
        </div>
      </td>
    </tr>`;
  }).join('');
}

function openAddLtStockModal(prefillSymbol = '') {
  if (typeof prefillSymbol !== 'string') prefillSymbol = '';
  const el = id => document.getElementById(id);
  const modalBg = el('ltAddModalBg');
  if (prefillSymbol) {
    if (el('ltFormSymbol')) el('ltFormSymbol').value = prefillSymbol;
    const screenerItem = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) ? SCREENER_DATA.find(s => s.symbol === prefillSymbol) : null;
    if (screenerItem) {
      if (el('ltFormSector')) el('ltFormSector').value = screenerItem.sector || '';
      if (el('ltFormGtt')) el('ltFormGtt').value = screenerItem.ltp ? (screenerItem.ltp * 0.95).toFixed(2) : '';
    }
  } else {
    if (el('ltFormSymbol')) el('ltFormSymbol').value = '';
    if (el('ltFormSector')) el('ltFormSector').value = '';
    if (el('ltFormRole')) el('ltFormRole').value = '';
    if (el('ltFormGtt')) el('ltFormGtt').value = '';
  }

  if (modalBg) {
    modalBg.style.display = 'flex';
  } else {
    // Native Prompt Fallback (Works on any browser/environment unconditionally)
    const symInput = prompt('➕ ADD STOCK TO LT WATCHLIST\n\nEnter Stock Symbol (e.g. BEL, TATAPOWER, RELIANCE, INFOSYS):', prefillSymbol);
    if (!symInput) return;
    const sym = symInput.trim().toUpperCase();
    if (!sym) return;

    const typeChoice = prompt(`Adding ${sym} to LT Watchlist\n\nEnter Type (1 for Private, 2 for PSU):`, '1');
    const type = (typeChoice === '2') ? 'PSU' : 'Private';
    const role = prompt(`Enter Portfolio Role for ${sym}:`, 'Core growth') || 'Core growth';

    const screenerItem = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) ? SCREENER_DATA.find(s => s.symbol === sym) : null;
    const sector = screenerItem ? (screenerItem.sector || 'General') : 'General';
    const gtt = screenerItem && screenerItem.ltp ? (screenerItem.ltp * 0.95) : null;

    const newStock = {
      symbol: sym,
      ticker: `${sym}.NS`,
      type: type,
      durability_score: 75,
      sector: sector,
      portfolio_role: role,
      gtt_mode: gtt ? 'manual' : 'auto',
      gtt_level: gtt,
      ltp: screenerItem ? screenerItem.ltp : 0,
      status: 'WAIT',
      status_badge: '🔵 WAIT',
      status_badge_class: 'badge-purple',
      active: true,
      added_date: new Date().toISOString().split('T')[0]
    };

    let idx = ltWatchlist.findIndex(s => s.symbol === sym);
    if (idx >= 0) {
      ltWatchlist[idx] = { ...ltWatchlist[idx], ...newStock, active: true };
    } else {
      ltWatchlist.push(newStock);
    }

    renderLtWatchlist();

    fetch('/api/lt-watchlist/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym, type, durability_score: 75, sector, portfolio_role: role, gtt_level: gtt })
    }).finally(() => {
      fetchLtWatchlistApi();
    });

    alert(`✅ Successfully added ${sym} to LT Watchlist!`);
  }
}

window.openAddLtStockModal = openAddLtStockModal;
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('ltAddStockBtn');
    if (btn) {
      btn.onclick = (e) => {
        if (e) e.preventDefault();
        openAddLtStockModal();
      };
    }
  });
}

function closeAddLtStockModal() {
  const modalBg = document.getElementById('ltAddModalBg');
  if (modalBg) modalBg.style.display = 'none';
}

function submitAddLtStockForm(e) {
  if (e) e.preventDefault();
  const el = id => document.getElementById(id);
  const symbol = el('ltFormSymbol') ? el('ltFormSymbol').value.trim().toUpperCase() : '';
  const type = el('ltFormType') ? el('ltFormType').value : 'Private';
  const durability_score = parseInt(el('ltFormDurability') ? el('ltFormDurability').value : 75) || 75;
  const sector = el('ltFormSector') ? el('ltFormSector').value.trim() : '';
  const portfolio_role = el('ltFormRole') ? el('ltFormRole').value.trim() : '';
  const gtt_level = (el('ltFormGtt') && el('ltFormGtt').value) ? parseFloat(el('ltFormGtt').value) : null;

  if (!symbol) {
    alert('Please enter a stock symbol.');
    return;
  }

  const screenerItem = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) ? SCREENER_DATA.find(s => s.symbol === symbol) : null;
  const ltp = screenerItem ? screenerItem.ltp : 0;

  const newStock = {
    symbol,
    ticker: `${symbol}.NS`,
    type: type || 'Private',
    durability_score: durability_score || 75,
    sector: sector || (screenerItem ? screenerItem.sector : 'General'),
    portfolio_role: portfolio_role || 'Growth',
    gtt_mode: gtt_level ? 'manual' : 'auto',
    gtt_level: gtt_level || (ltp ? ltp * 0.95 : null),
    ltp: ltp,
    status: 'WAIT',
    status_badge: '🔵 WAIT',
    status_badge_class: 'badge-purple',
    active: true,
    added_date: new Date().toISOString().split('T')[0]
  };

  let existingIndex = ltWatchlist.findIndex(s => s.symbol === symbol);
  if (existingIndex >= 0) {
    ltWatchlist[existingIndex] = { ...ltWatchlist[existingIndex], ...newStock, active: true };
  } else {
    ltWatchlist.push(newStock);
  }

  closeAddLtStockModal();
  renderLtWatchlist();

  fetch('/api/lt-watchlist/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, type, durability_score, sector, portfolio_role, gtt_level })
  }).finally(() => {
    fetchLtWatchlistApi();
  });

  alert(`✅ Successfully added ${symbol} to LT Watchlist!`);
}

function promptGttEdit(symbol, currentGtt) {
  const newGttStr = prompt(`Enter new GTT Dip-Buy Target Price (₹) for ${symbol}:`, currentGtt || '');
  if (newGttStr === null) return;
  const newGtt = newGttStr.trim() !== '' ? parseFloat(newGttStr) : null;

  fetch('/api/lt-watchlist/update-gtt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, gtt_level: newGtt })
  }).finally(() => {
    const item = ltWatchlist.find(s => s.symbol === symbol);
    if (item) item.gtt_level = newGtt;
    renderLtWatchlist();
  });
}

function fetchLtWatchlistApi() {
  fetch('/api/lt-watchlist')
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(data => {
      if (Array.isArray(data) && data.length > 0) {
        ltWatchlist = data;
        renderLtWatchlist();
      }
    })
    .catch(err => {
      console.warn('Could not fetch live LT Watchlist from API, using offline fallback:', err);
      if (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist)) {
        renderLtWatchlist();
      }
    });
}

function deleteLtStock(symbol) {
  if (!confirm(`Permanently delete ${symbol} from watchlist?\nThis will remove it completely from lt_watchlist.json.`)) return;
  fetch('/api/lt-watchlist/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol: symbol })
  }).then(r => r.json()).then(res => {
    ltWatchlist = ltWatchlist.filter(s => s.symbol !== symbol);
    renderLtWatchlist();
    fetchLtWatchlistApi();
  }).catch(err => alert('Error deleting stock: ' + err));
}

function retireLtStock(symbol) {
  if (!confirm(`Are you sure you want to retire ${symbol} from active watchlist?\n(Stock will be soft-deleted and can be restored anytime via "Show Retired Stocks")`)) return;

  fetch('/api/lt-watchlist/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol })
  }).finally(() => {
    const item = ltWatchlist.find(s => s.symbol === symbol);
    if (item) item.active = false;
    fetchLtWatchlistApi();
  });
}

function reactivateLtStock(symbol) {
  fetch('/api/lt-watchlist/toggle-active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, active: true })
  }).finally(() => {
    const item = ltWatchlist.find(s => s.symbol === symbol);
    if (item) item.active = true;
    fetchLtWatchlistApi();
  });
}

function addToWatchlist(symbol) {
  openAddLtStockModal(symbol);
}

function toggleWatchlist(symbol) {
  openAddLtStockModal(symbol);
}

// ── Init ──────────────────────────────────────────────────────────────────
function init() {
  renderMarketStatusHeader();
  updateLtpBadgeStatus();
  renderCommodityBar();
  
  // Clear legacy localStorage cache keys
  localStorage.removeItem('quality_watchlist_v1');
  localStorage.removeItem('quality_watchlist_v2');
  localStorage.removeItem('quality_watchlist_v3');
  localStorage.removeItem('quality_watchlist_v4');
  localStorage.removeItem('quality_watchlist_v5');
  localStorage.removeItem('quality_watchlist_v6');
  localStorage.removeItem('quality_watchlist_v7');

  // Always initialize Watchlist directly from fresh server scan
  const freshServerWatchlist = JSON.parse(JSON.stringify(WATCHLIST_SEED || []));
  
  // Preserve any custom user-added stocks from localStorage
  const stored = localStorage.getItem('quality_watchlist_custom_items');
  if (stored) {
    try {
      const customItems = JSON.parse(stored);
      const serverSyms = new Set(freshServerWatchlist.map(s => s.symbol));
      customItems.forEach(item => {
        if (!serverSyms.has(item.symbol)) {
          freshServerWatchlist.push(item);
        }
      });
    } catch(e) {}
  }
  watchlist = freshServerWatchlist;

  // Update live data and dynamic signals for all watchlist items from current scan
  watchlist.forEach(item => {
    const live = (SCREENER_DATA || []).find(s => s.symbol === item.symbol);
    updateWatchlistSignalsAndAlerts(item, live);
  });

  saveWatchlist();

  // ltWatchlist's own top-level `let ltWatchlist = ...LT_WATCHLIST...` (near the top
  // of this file) runs at app.js PARSE time, before the small per-scan bootstrap
  // script (loaded after app.js) ever sets LT_WATCHLIST to its real value — so that
  // initial assignment always captured the empty default and was never revisited,
  // leaving the LT Screen tab permanently empty on every fresh page load until a
  // user action (add/remove stock) happened to call fetchLtWatchlistApi(). Rebuild
  // it here from the now-populated LT_WATCHLIST, exactly like watchlist above.
  ltWatchlist = JSON.parse(JSON.stringify(LT_WATCHLIST || []));

  renderStats();
  populateSectorFilter();
  applyFilters();
  renderWatchlist();
  renderLtWatchlist();
  fetchLtPortfolioStatus();
  updateWlCount();

  renderMarketStatusHeader();
  startPolling();
  setInterval(renderMarketStatusHeader, 30000);

  checkStartupScanStatus();
  startupScanPoller = setInterval(checkStartupScanStatus, 3000);
}

let startupScanPoller = null;
let wasScanning = false;

function checkStartupScanStatus() {
  fetch('/api/status')
    .then(r => r.json())
    .then(res => {
      const banner = document.getElementById('bgScanBanner');
      const overlay = document.getElementById('scanProgressOverlay');
      const textEl = document.getElementById('scanProgressText');
      const logEl = document.getElementById('scanProgressLog');

      if (res && res.is_scanning) {
        wasScanning = true;

        if (overlay && (typeof SCREENER_DATA === 'undefined' || !SCREENER_DATA || SCREENER_DATA.length === 0)) {
          overlay.style.display = 'flex';
          if (textEl) textEl.textContent = '⚡ Initializing Full Scan of 2,414 Stocks...';
          if (logEl) logEl.textContent = 'Multithreaded engine scanning live prices & technical ratings. Page will auto-load when complete...';
        }

        if (!banner) {
          const b = document.createElement('div');
          b.id = 'bgScanBanner';
          b.style.cssText = 'background:linear-gradient(135deg,rgba(108,99,255,0.25),rgba(0,212,170,0.25));border-bottom:1.5px solid var(--accent);padding:10px 20px;text-align:center;font-size:13px;font-weight:700;color:#fff;display:flex;align-items:center;justify-content:center;gap:10px;box-shadow:0 4px 16px rgba(0,0,0,0.3)';
          b.innerHTML = `<span style="font-size:16px;animation:spin 1.5s linear infinite">⚡</span> <span>Full Stock &amp; Commodity Scan in Progress (2414 stocks)... Page will auto-reload when complete.</span>`;
          document.body.prepend(b);
        }
      } else {
        if (overlay && wasScanning) {
          overlay.style.display = 'none';
        }
        if (banner) {
          banner.remove();
        }
        if (wasScanning) {
          window.location.reload();
          return;
        }
        if (startupScanPoller) clearInterval(startupScanPoller);
        // This only ever watched the ONE scan that happened to be running when the
        // page first loaded — once that finished (or never happened), the poller
        // stopped for good, so a tab left open across a LATER scan (the hourly
        // rescan, or a manual "Scan Now") never learned new data existed. Anyone
        // watching the Intraday tab in particular would keep seeing whatever picks
        // were computed when the page loaded, silently going stale. Hand off to a
        // slower, persistent watcher for the rest of the page's lifetime instead.
        if (res && res.last_scan_completed_at) {
          knownScanCompletedAt = res.last_scan_completed_at;
        }
        if (!freshScanPoller) {
          freshScanPoller = setInterval(checkForFreshScan, 60000);
        }
      }
    })
    .catch(() => {});
}

let freshScanPoller = null;
let knownScanCompletedAt = null;

function checkForFreshScan() {
  fetch('/api/status')
    .then(r => r.json())
    .then(res => {
      if (!res || res.is_scanning || !res.last_scan_completed_at) return;
      if (knownScanCompletedAt === null) {
        knownScanCompletedAt = res.last_scan_completed_at;
        return;
      }
      if (res.last_scan_completed_at === knownScanCompletedAt) return;

      if (freshScanPoller) { clearInterval(freshScanPoller); freshScanPoller = null; }
      const b = document.createElement('div');
      b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:999999;background:linear-gradient(135deg,rgba(108,99,255,0.95),rgba(0,212,170,0.95));color:#fff;padding:10px 20px;text-align:center;font-size:13px;font-weight:700;box-shadow:0 4px 16px rgba(0,0,0,0.4)';
      b.textContent = '⚡ A newer scan just finished — refreshing with fresh data...';
      document.body.prepend(b);
      setTimeout(() => window.location.reload(), 2500);
    })
    .catch(() => {});
}

function formatAgo(ms) {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  return `${h}h ago`;
}

function updateLtpBadgeStatus(lastTimeStr, polledCount, attemptedCount, staleCount) {
  const dot = document.getElementById('ltpStatusDot');
  const txt = document.getElementById('ltpStatusText');
  if (!txt) return;

  if (pollIntervalMs === 0) {
    if (dot) { dot.style.background = '#6b7280'; dot.style.boxShadow = 'none'; }
    txt.textContent = 'Live LTP Polling: Off';
    return;
  }

  // A scan suppresses live fetches by design, so every price this cycle is a
  // scan-time fallback. That is indistinguishable from a failure by counting alone
  // — both show zero fresh prices — which is why the server sends the reason.
  // Checked before the failure branch so a pause is never reported as a failure.
  if (ltpPaused.active) {
    if (dot) { dot.style.background = '#f59e0b'; dot.style.boxShadow = '0 0 8px #f59e0b'; }
    const secs = ltpPaused.resumesInSec;
    const when = (secs != null && secs > 0)
      ? ` — resumes within ${secs >= 60 ? Math.ceil(secs / 60) + 'm' : secs + 's'}`
      : ' — resumes when it finishes';
    const showing = staleCount > 0 ? ` (showing ${staleCount} scan-time prices)` : '';
    txt.textContent = `⏸ Live LTP Paused: scan in progress${when}${showing}`;
    return;
  }

  // Only treat this as a real failure once we've actually attempted a cycle and it
  // returned zero fresh prices — before the first cycle runs, attemptedCount is undefined.
  const hasFailed = attemptedCount != null && attemptedCount > 0 && (!polledCount || polledCount === 0);

  if (hasFailed) {
    if (dot) { dot.style.background = '#ef4444'; dot.style.boxShadow = '0 0 8px #ef4444'; }
    const sinceOk = lastLtpSuccessTime ? formatAgo(Date.now() - lastLtpSuccessTime) : 'never this session';
    const staleTag = staleCount > 0 ? ` (showing ${staleCount} stale scan-time prices)` : '';
    txt.textContent = `🔴 Live LTP Polling: Failed — last success ${sinceOk}${staleTag}`;
    return;
  }

  if (dot) { dot.style.background = '#10b981'; dot.style.boxShadow = '0 0 8px #10b981'; }
  const timeTag = lastTimeStr ? ` @ ${lastTimeStr}` : '';
  const countTag = (polledCount != null && polledCount > 0) ? ` — ${polledCount} prices synced${timeTag}` : (lastTimeStr ? ` — Last Sync: ${lastTimeStr}` : '');
  txt.textContent = `🟢 Live LTP Polling: Active (${pollIntervalMs / 1000}s)${countTag}`;
}

async function fetchLiveLTPForSymbol(ticker) {
  const ts = Date.now();
  if (isRealDesktopPC()) {
    const currentPort = window.location.port || '5050';
    const localEps = [
      window.location.origin && window.location.origin.startsWith('http') ? `${window.location.origin}/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}` : null,
      `http://127.0.0.1:${currentPort}/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://localhost:${currentPort}/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://127.0.0.1:5050/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://localhost:5050/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://127.0.0.1:8000/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://localhost:8000/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://127.0.0.1:8080/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`,
      `http://localhost:8080/api/ltp?ticker=${encodeURIComponent(ticker)}&_t=${ts}`
    ].filter((ep, idx, self) => ep && self.indexOf(ep) === idx);

    for (const ep of localEps) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 1500);
        const res = await fetch(ep, { signal: controller.signal });
        clearTimeout(timeoutId);
        if (res.ok) {
          const data = await res.json();
          if (data && (data.price || data.ltp) && (data.price > 0 || data.ltp > 0)) {
            return parseFloat(data.price || data.ltp);
          }
          const pObj = data.ltps || data.prices || {};
          const cleanTicker = ticker.replace('.NS', '');
          const p = pObj[ticker] || pObj[cleanTicker] || pObj[ticker + '.NS'];
          if (p && p > 0) return parseFloat(p);
        }
      } catch (e) {}
    }
  }

  const yUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=1m&range=1d&_t=${ts}`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(yUrl, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (res.ok) {
      const data = await res.json();
      const meta = data.chart?.result?.[0]?.meta;
      if (meta && meta.regularMarketPrice && meta.regularMarketPrice > 0) return meta.regularMarketPrice;
    }
  } catch (e) {}

  const proxies = [
    `https://api.allorigins.win/raw?url=${encodeURIComponent(yUrl)}`,
    `https://corsproxy.io/?${encodeURIComponent(yUrl)}`
  ];

  for (const px of proxies) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);
      const res = await fetch(px, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (res.ok) {
        const text = await res.text();
        let data = null;
        try { data = JSON.parse(text); } catch(err) { data = null; }
        if (data) {
          if (data.price && data.price > 0) return data.price;
          const meta = data.chart?.result?.[0]?.meta;
          if (meta && meta.regularMarketPrice) return meta.regularMarketPrice;
        }
      }
    } catch (e) {}
  }

  return null;
}

// Which tab is on screen. Only that tab's dataset needs live prices — polling
// every tab's data at once is most of what made the request 570 symbols wide.
function activeTabName() {
  const el = document.querySelector('.tab.active, .mobile-nav-item.active');
  return (el && el.dataset && el.dataset.tab) || 'screener';
}

// Symbols whose table rows are on screen, plus a margin either side so a scroll
// finds them already warm instead of waiting a cycle. Rows are tagged with
// data-symbol/data-ticker at render time.
//
// This matters because the server warms only the symbols recently asked for, in
// one bounded batch. Asking for hundreds of off-screen rows pushed the ones
// actually being looked at out of that batch, so the visible page showed stale
// prices while the warmer refreshed rows nobody could see.
function visibleRowSymbols(marginPx = 1200) {
  const found = [];
  try {
    const rows = document.querySelectorAll('tr[data-symbol]');
    const top = -marginPx;
    const bottom = (window.innerHeight || 800) + marginPx;
    rows.forEach(tr => {
      // offsetParent null => the row (or its tab) is display:none.
      if (tr.offsetParent === null) return;
      const r = tr.getBoundingClientRect();
      if (r.bottom >= top && r.top <= bottom) {
        found.push([tr.dataset.symbol, tr.dataset.ticker || (tr.dataset.symbol + '.NS')]);
      }
    });
  } catch (e) {}
  return found;
}

async function refreshLiveLTP(manual = false) {
  const dot = document.getElementById('ltpStatusDot');
  const txt = document.getElementById('ltpStatusText');
  if (dot) dot.classList.add('updating');
  if (txt) txt.textContent = manual ? 'Refreshing prices...' : 'Polling LTP...';

  let priceChanged = false;

  // Poll what is on screen, not everything the page knows about.
  //
  // This previously accumulated every tab's dataset plus every "qualified" stock
  // plus an arbitrary SCREENER_DATA.slice(0, 100), reaching ~570 symbols
  // regardless of what was being viewed. The server warms recently-requested
  // symbols in one bounded batch, so a request that wide pushed the rows
  // actually on screen out of the batch — the page showed "Live LTP Polling:
  // Failed" and stale prices while the warmer refreshed rows nobody could see.
  const symbolsToPoll = new Map();
  const addSym = (sym, ticker) => { if (sym) symbolsToPoll.set(sym, ticker || (sym + '.NS')); };

  // Always needed: the index drives the regime banner, and the top pick is shown
  // in the header on every tab.
  addSym('NIFTY_INDEX', '^NSEI');
  if (typeof TOP_PICK !== 'undefined' && TOP_PICK && TOP_PICK.symbol) {
    addSym(TOP_PICK.symbol, TOP_PICK.ticker);
  }

  // The user's own watchlist is small and is the thing they most want current,
  // so it stays regardless of which tab is open.
  if (typeof watchlist !== 'undefined' && Array.isArray(watchlist)) {
    watchlist.forEach(w => addSym(w.symbol, w.ticker));
  }

  // Only the visible tab's dataset. Each of these is small (10-30 rows); it was
  // holding all of them at once that was expensive.
  const tab = activeTabName();
  if (tab === 'watchlist') {
    if (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist)) ltWatchlist.forEach(w => addSym(w.symbol, w.ticker));
    if (typeof LT_WATCHLIST !== 'undefined' && Array.isArray(LT_WATCHLIST)) LT_WATCHLIST.forEach(w => addSym(w.symbol, w.ticker));
  } else if (tab === 'penny') {
    if (typeof PENNY_STOCKS_DATA !== 'undefined' && Array.isArray(PENNY_STOCKS_DATA)) PENNY_STOCKS_DATA.forEach(p => addSym(p.symbol, p.ticker));
  } else if (tab === 'intraday') {
    if (typeof INTRADAY_DATA !== 'undefined' && INTRADAY_DATA) {
      (INTRADAY_DATA.buy || []).forEach(s => addSym(s.symbol, s.ticker));
      (INTRADAY_DATA.sell || []).forEach(s => addSym(s.symbol, s.ticker));
    }
  } else if (tab === 'fno') {
    if (typeof FNO_DATA !== 'undefined' && Array.isArray(FNO_DATA)) FNO_DATA.forEach(f => addSym(f.symbol, f.ticker));
  } else if (tab === 'swing') {
    if (typeof getSwingData === 'function') {
      try {
        const swingPicks = getSwingData();
        if (Array.isArray(swingPicks)) swingPicks.forEach(s => addSym(s.symbol, s.ticker));
      } catch (e) {}
    }
  }

  // Rows currently on screen (plus a scroll margin), so scrolling a long page
  // brings its prices live without waiting for a page change.
  visibleRowSymbols().forEach(([sym, tick]) => addSym(sym, tick));

  // Fallback for the moment before the table has rendered: take the current
  // page slice so the first poll after load is not empty.
  if (symbolsToPoll.size <= 2 && typeof filteredData !== 'undefined' && Array.isArray(filteredData)) {
    const effSize = (typeof pageSize !== 'undefined' && pageSize === 'all') ? 60 : parseInt(pageSize || 50);
    const startIdx = (typeof currentPage !== 'undefined') ? Math.max(0, (currentPage - 1) * effSize) : 0;
    filteredData.slice(startIdx, startIdx + effSize).forEach(s => addSym(s.symbol, s.ticker));
  }

  const fetchedPrices = new Map();
  const stalePrices = new Set();
  // Cleared each cycle so "paused" only ever reflects what the server said on this
  // pass. Left sticky, a pause that ended would keep masking a real failure.
  ltpPaused = { active: false, resumesInSec: null };
  const tickerList = Array.from(symbolsToPoll.values());
  const attempted = symbolsToPoll.size;

  const ts = Date.now();
  const currentPort = window.location.port || '5050';
  const originEp = window.location.origin && window.location.origin.startsWith('http') ? window.location.origin + '/api/ltp' : null;
  // The hardcoded localhost/127.0.0.1 fallback ports only make sense when this page
  // itself is being served from a local dev instance — on a deployed/production
  // browser (or inside the Capacitor WebView) they can never resolve to the real
  // server and just waste time before falling through to originEp/per-symbol fetch.
  const localEndpoints = isRealDesktopPC() ? [
    originEp,
    `http://127.0.0.1:${currentPort}/api/ltp`,
    `http://localhost:${currentPort}/api/ltp`,
    'http://127.0.0.1:5050/api/ltp',
    'http://localhost:5050/api/ltp',
    'http://127.0.0.1:8000/api/ltp',
    'http://localhost:8000/api/ltp',
    'http://127.0.0.1:8080/api/ltp',
    'http://localhost:8080/api/ltp'
  ].filter((ep, idx, self) => ep && self.indexOf(ep) === idx) : (originEp ? [originEp] : []);

  for (const ep of localEndpoints) {
    if (fetchedPrices.size > 0) break;
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 20000);

      let res = await fetch(ep, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: tickerList }),
        signal: controller.signal
      }).catch(() => null);

      if (!res || !res.ok) {
        const bUrl = `${ep}?symbols=${encodeURIComponent(tickerList.slice(0, 100).join(','))}&_t=${ts}`;
        res = await fetch(bUrl, { signal: controller.signal }).catch(() => null);
      }

      clearTimeout(timeoutId);
      if (res && res.ok) {
        const data = await res.json();
        const pricesObj = data.ltps || data.prices || {};
        const staleObj = data.stale || {};
        if (typeof data.paused_for_scan === 'boolean') {
          ltpPaused = { active: data.paused_for_scan, resumesInSec: data.resumes_in_sec };
        }
        for (const [sym, ticker] of symbolsToPoll.entries()) {
          const cleanSym = sym.replace('.NS', '');
          const cleanTicker = ticker.replace('.NS', '');
          const p = pricesObj[ticker] || pricesObj[sym] || pricesObj[cleanSym] || pricesObj[cleanTicker] || pricesObj[sym + '.NS'] || pricesObj[ticker + '.NS'];
          if (p && p > 0) {
            fetchedPrices.set(sym, parseFloat(p));
            if (staleObj[ticker] || staleObj[sym] || staleObj[cleanSym] || staleObj[cleanTicker]) {
              stalePrices.add(sym);
            }
          }
        }
      } else if (!res) {
        lastLtpError = { when: Date.now(), stage: 'bulk', message: `no response from ${ep}` };
      }
    } catch (e) {
      lastLtpError = { when: Date.now(), stage: 'bulk', message: (e && e.message) || String(e) };
    }
  }

  // Per-symbol fallback for anything the bulk call missed. No longer hard-capped at
  // the first 60 unpolled symbols (that silently left larger watchlists/screener
  // pages stale with no indication to the user) — instead bounded by a wall-clock
  // budget, so a slow/offline stretch (e.g. while the server is busy running the
  // startup scan) can't stall an entire poll cycle for minutes; whatever doesn't
  // finish in time is simply picked up on the next cycle, 10s later by default.
  const unpolled = Array.from(symbolsToPoll.entries()).filter(([sym, ticker]) => !fetchedPrices.has(sym));
  if (unpolled.length > 0) {
    const chunkSize = 15;
    const fallbackDeadline = Date.now() + 12000;
    for (let i = 0; i < unpolled.length; i += chunkSize) {
      if (Date.now() > fallbackDeadline) {
        lastLtpError = { when: Date.now(), stage: 'fallback', message: `Time budget reached — ${unpolled.length - i} symbol(s) not retried this cycle` };
        break;
      }
      const chunk = unpolled.slice(i, i + chunkSize);
      await Promise.all(chunk.map(async ([sym, ticker]) => {
        const p = await fetchLiveLTPForSymbol(ticker);
        if (p && p > 0) fetchedPrices.set(sym, p);
      }));
    }
  }

  for (const [sym, newPrice] of fetchedPrices.entries()) {
    const cleanSym = sym.replace('.NS', '');

    if (sym === 'NIFTY_INDEX' || sym === '^NSEI' || (typeof MARKET_INFO !== 'undefined' && MARKET_INFO && MARKET_INFO.nifty && MARKET_INFO.nifty.symbol === sym)) {
      if (typeof MARKET_INFO !== 'undefined' && MARKET_INFO && MARKET_INFO.nifty) {
        if (Math.abs((MARKET_INFO.nifty.ltp || 0) - newPrice) > 0.01) {
          MARKET_INFO.nifty.old_ltp = MARKET_INFO.nifty.ltp;
          MARKET_INFO.nifty.ltp = newPrice;
          if (MARKET_INFO.nifty.prev_close && MARKET_INFO.nifty.prev_close > 0) {
            MARKET_INFO.nifty.change_pct = Math.round(((newPrice - MARKET_INFO.nifty.prev_close) / MARKET_INFO.nifty.prev_close) * 10000) / 100;
          }
          priceChanged = true;
        }
      }
    }

    if (typeof TOP_PICK !== 'undefined' && TOP_PICK && (TOP_PICK.symbol === sym || TOP_PICK.symbol === cleanSym)) {
      if (Math.abs((TOP_PICK.ltp || TOP_PICK.current_ltp || 0) - newPrice) > 0.01) {
        TOP_PICK.old_ltp = TOP_PICK.ltp;
        TOP_PICK.ltp = newPrice;
        TOP_PICK.current_ltp = newPrice;
        if (TOP_PICK.ma50) TOP_PICK.dist_ma50_pct = Math.round(((newPrice - TOP_PICK.ma50)/TOP_PICK.ma50)*1000)/10;
        if (TOP_PICK.ma200) TOP_PICK.dist_ma200_pct = Math.round(((newPrice - TOP_PICK.ma200)/TOP_PICK.ma200)*1000)/10;
        if (TOP_PICK.week_high_52) TOP_PICK.dist_52w_high_pct = Math.round(((newPrice - TOP_PICK.week_high_52)/TOP_PICK.week_high_52)*1000)/10;
        if (TOP_PICK.week_low_52) TOP_PICK.dist_52w_low_pct = Math.round(((newPrice - TOP_PICK.week_low_52)/TOP_PICK.week_low_52)*1000)/10;
        priceChanged = true;
      }
    }

    if (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA)) {
      const sc = SCREENER_DATA.find(s => s.symbol === sym || s.symbol === cleanSym);
      if (sc && Math.abs((sc.ltp || 0) - newPrice) > 0.01) {
        sc.old_ltp = sc.ltp;
        sc.ltp = newPrice;
        if (sc.gtt_breakout_level && sc.gtt_breakout_level > 0) {
          sc.dist_to_gtt_pct = Math.round(((sc.ltp - sc.gtt_breakout_level) / sc.gtt_breakout_level) * 10000) / 100;
          if (sc.ltp >= sc.gtt_breakout_level && (sc.status === 'WAIT' || sc.swing_action === 'WAIT FOR BREAKOUT')) {
            sc.status = 'BUY_NOW';
            sc.swing_action = 'BUY NOW';
          }
        }
        if (sc.target_price && sc.target_price > 0) {
          sc.dist_to_target_pct = Math.round(((sc.target_price - sc.ltp) / sc.ltp) * 10000) / 100;
        }
        if (sc.stop_loss && sc.stop_loss > 0) {
          sc.dist_to_sl_pct = Math.round(((sc.ltp - sc.stop_loss) / sc.ltp) * 10000) / 100;
        }
        priceChanged = true;
      }
    }

    if (typeof watchlist !== 'undefined' && Array.isArray(watchlist)) {
      const wl = watchlist.find(w => w.symbol === sym || w.symbol === cleanSym);
      if (wl && Math.abs(wl.ltp - newPrice) > 0.01) {
        wl.old_ltp = wl.ltp;
        wl.ltp = newPrice;
        if (wl.avg_cost && wl.qty > 0) {
          wl.unrealised_pnl = Math.round((wl.ltp - wl.avg_cost) * wl.qty * 100) / 100;
          wl.unrealised_pct = Math.round(((wl.ltp - wl.avg_cost) / wl.avg_cost) * 10000) / 100;
          wl.current_value = Math.round(wl.ltp * wl.qty * 100) / 100;
        }
        priceChanged = true;
      }
    }

    if (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist)) {
      const lt = ltWatchlist.find(w => w.symbol === sym || w.symbol === cleanSym);
      if (lt && Math.abs((lt.ltp || 0) - newPrice) > 0.01) {
        lt.old_ltp = lt.ltp;
        lt.ltp = newPrice;
        if (lt.gtt_breakout_level && lt.gtt_breakout_level > 0) {
          lt.dist_to_gtt_pct = Math.round(((lt.ltp - lt.gtt_breakout_level) / lt.gtt_breakout_level) * 10000) / 100;
          if (lt.ltp >= lt.gtt_breakout_level && lt.status === 'WAIT') {
            lt.status = 'BUY_NOW';
          }
        }
        priceChanged = true;
      }
    }

    if (typeof LT_WATCHLIST !== 'undefined' && Array.isArray(LT_WATCHLIST)) {
      const lt = LT_WATCHLIST.find(w => w.symbol === sym || w.symbol === cleanSym);
      if (lt && Math.abs((lt.ltp || 0) - newPrice) > 0.01) {
        lt.old_ltp = lt.ltp;
        lt.ltp = newPrice;
        priceChanged = true;
      }
    }

    if (typeof FNO_DATA !== 'undefined' && Array.isArray(FNO_DATA)) {
      const fn = FNO_DATA.find(f => f.symbol === sym || f.symbol === cleanSym);
      if (fn && Math.abs(fn.ltp - newPrice) > 0.01) {
        fn.old_ltp = fn.ltp;
        fn.ltp = newPrice;
        if (fn.prev_close && fn.prev_close > 0) {
          fn.day_chg_pct = Math.round(((newPrice - fn.prev_close) / fn.prev_close) * 10000) / 100;
        }
        priceChanged = true;
      }
    }

    if (typeof PENNY_STOCKS_DATA !== 'undefined' && Array.isArray(PENNY_STOCKS_DATA)) {
      const ps = PENNY_STOCKS_DATA.find(p => p.symbol === sym || p.symbol === cleanSym);
      if (ps && Math.abs((ps.ltp || 0) - newPrice) > 0.01) {
        ps.old_ltp = ps.ltp;
        ps.ltp = newPrice;
        if (ps.target_price && ps.target_price > 0) {
          ps.dist_to_target_pct = Math.round(((ps.target_price - ps.ltp) / ps.ltp) * 10000) / 100;
        }
        if (ps.stop_loss && ps.stop_loss > 0) {
          ps.dist_to_sl_pct = Math.round(((ps.ltp - ps.stop_loss) / ps.ltp) * 10000) / 100;
        }
        priceChanged = true;
      }
    }

    if (typeof INTRADAY_DATA !== 'undefined' && INTRADAY_DATA) {
      const idPick = [...(INTRADAY_DATA.buy || []), ...(INTRADAY_DATA.sell || [])]
        .find(s => s.symbol === sym || s.symbol === cleanSym);
      if (idPick && Math.abs((idPick.ltp || 0) - newPrice) > 0.01) {
        idPick.old_ltp = idPick.ltp;
        idPick.ltp = newPrice;
        if (idPick.prev_close && idPick.prev_close > 0) {
          idPick.day_chg_pct = Number((((newPrice - idPick.prev_close) / idPick.prev_close) * 100).toFixed(2));
          idPick.has_day_move = true;
        }
        priceChanged = true;
      }
    }
  }

  const nowStr = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
  if (dot) dot.classList.remove('updating');

  // Only count a cycle as a real success if at least some prices are actually fresh —
  // a cycle where every returned price is a stale scan-time fallback means live
  // fetching is failing even though the server still answered with *something*.
  const freshCount = fetchedPrices.size - stalePrices.size;
  if (freshCount > 0) {
    lastLtpSuccessTime = Date.now();
    lastLtpError = null;
  } else if (attempted > 0 && !lastLtpError) {
    lastLtpError = fetchedPrices.size > 0
      ? { when: Date.now(), stage: 'all', message: `All ${fetchedPrices.size} prices this cycle are stale fallbacks` }
      : { when: Date.now(), stage: 'all', message: 'No prices returned this cycle' };
  }
  updateLtpBadgeStatus(nowStr, freshCount, attempted, stalePrices.size);

  saveWatchlist();
  renderStats();
  renderTable();
  renderWatchlist();
  if (typeof renderLtWatchlist === 'function') renderLtWatchlist();
  if (typeof renderFnoTab === 'function') renderFnoTab();
  if (typeof renderIntradayTab === 'function') renderIntradayTab();
  if (typeof renderTopPick === 'function') renderTopPick();
  if (typeof renderSwingRadar === 'function') renderSwingRadar();
  if (typeof renderSrBreakouts === 'function') renderSrBreakouts();
  if (typeof renderNiftyRegimeBanner === 'function') renderNiftyRegimeBanner();
  if (typeof renderPennyStocksTab === 'function') renderPennyStocksTab();

  if (priceChanged || manual) {
    flashUpdatedPrices();
  }
}

function flashUpdatedPrices() {
  document.querySelectorAll('.price, .wl-ltp, .swing-card').forEach(el => {
    el.classList.remove('price-up', 'price-down');
    void el.offsetWidth;
    el.classList.add('price-up');
    setTimeout(() => el.classList.remove('price-up'), 1500);
  });
}

function startPolling() {
  if (pollIntervalTimer) {
    clearInterval(pollIntervalTimer);
    pollIntervalTimer = null;
  }

  if (pollIntervalMs <= 0) {
    updateLtpBadgeStatus();
    return;
  }

  refreshLiveLTP(false);
  pollIntervalTimer = setInterval(() => refreshLiveLTP(false), pollIntervalMs);
  updateLtpBadgeStatus();
}

function changePollInterval(val) {
  pollIntervalMs = parseInt(val);
  startPolling();
}

// Scrolling brings different rows on screen, and the poll only asks for what is
// visible — so without this a scroll would sit on scan-time prices until the next
// 10s tick. Debounced so a long flick fires one refresh when it settles, not one
// per scroll event, and skipped when no genuinely new symbol came into view.
let scrollRefreshTimer = null;
let lastVisibleKey = '';
document.addEventListener('scroll', () => {
  if (scrollRefreshTimer) clearTimeout(scrollRefreshTimer);
  scrollRefreshTimer = setTimeout(() => {
    scrollRefreshTimer = null;
    if (document.hidden) return;
    try {
      const key = visibleRowSymbols().map(v => v[0]).sort().join(',');
      if (key && key !== lastVisibleKey) {
        lastVisibleKey = key;
        refreshLiveLTP(false);
      }
    } catch (e) {}
  }, 400);
}, { passive: true });

// Pause polling while the tab/app is backgrounded instead of hammering the server
// and Yahoo endpoints from every hidden tab; resume with an immediate refresh.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    if (pollIntervalTimer) {
      clearInterval(pollIntervalTimer);
      pollIntervalTimer = null;
    }
  } else {
    startPolling();
  }
});

function saveWatchlist() {
  const seedSyms = new Set(WATCHLIST_SEED.map(s => s.symbol));
  const customItems = watchlist.filter(w => !seedSyms.has(w.symbol));
  localStorage.setItem('quality_watchlist_custom_items', JSON.stringify(customItems));
}

// ── Stats ─────────────────────────────────────────────────────────────────
function renderStats() {
  const el = document.getElementById('statsGrid');
  if (!el) return;
  const qualified = SCREENER_DATA.filter(s => s.qualified).length;
  const total = SCREENER_DATA.length;
  const avgScore = total > 0 ? (SCREENER_DATA.reduce((a,b)=>a+b.total_score,0)/total).toFixed(1) : 0;
  const alerts = watchlist.filter(w => w.alerts && w.alerts.length > 0).length;
  const totalInvested = watchlist.reduce((a,w)=>a+(w.total_invested||0),0);

  el.innerHTML = `
    <div class="stat-card"><div class="stat-val stat-purple">${total}</div><div class="stat-lbl">Stocks Scanned</div></div>
    <div class="stat-card"><div class="stat-val stat-green">${qualified}</div><div class="stat-lbl">Qualified (Score≥55)</div></div>
    <div class="stat-card"><div class="stat-val stat-purple">${avgScore}</div><div class="stat-lbl">Avg Score</div></div>
    <div class="stat-card"><div class="stat-val stat-purple">${watchlist.length}</div><div class="stat-lbl">Watchlist / ${CONFIG.max_stocks}</div></div>
    <div class="stat-card"><div class="stat-val ${alerts>0?'stat-danger':'stat-green'}">${alerts}</div><div class="stat-lbl">Quality Alerts</div></div>
    <div class="stat-card"><div class="stat-val stat-warn">₹${Math.round(totalInvested).toLocaleString()}</div><div class="stat-lbl">Invested</div></div>
  `;
}

// ── Tabs ──────────────────────────────────────────────────────────────────
function switchTab(tab) {
  // Both the desktop tab bar and mobile bottom nav carry a matching data-tab
  // attribute, so a single lookup drives the active-highlight for both — previously
  // the desktop bar used a hardcoded array matched to buttons by DOM position, which
  // had silently drifted out of sync with the actual button order and highlighted
  // the wrong tab as "active" on almost every switch.
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  document.querySelectorAll('.mobile-nav-item').forEach(m => {
    m.classList.toggle('active', m.dataset.tab === tab);
  });
  document.getElementById('tab-screener').style.display  = tab === 'screener'  ? '' : 'none';
  document.getElementById('tab-swing').style.display     = tab === 'swing'     ? '' : 'none';
  document.getElementById('tab-watchlist').style.display = tab === 'watchlist' ? '' : 'none';
  const pennyTab = document.getElementById('tab-penny');
  if (pennyTab) pennyTab.style.display                   = tab === 'penny'     ? '' : 'none';
  const intradayTab = document.getElementById('tab-intraday');
  if (intradayTab) intradayTab.style.display             = tab === 'intraday'  ? '' : 'none';
  document.getElementById('tab-fno').style.display       = tab === 'fno'       ? '' : 'none';
  document.getElementById('tab-holidays').style.display  = tab === 'holidays'  ? '' : 'none';
  if (tab === 'swing')      { renderSwingRadar(); renderSrBreakouts(); }
  if (tab === 'intraday')   renderIntradayTab();
  if (tab === 'watchlist')  { renderLtWatchlist(); renderLtMonthlyPicks(); fetchLtPortfolioStatus(); }
  if (tab === 'penny')      renderPennyStocksTab();
  if (tab === 'fno')        renderFnoTab();
  if (tab === 'holidays')   renderHolidaysTab();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

if (!window.fnoFilters) {
  window.fnoFilters = { conviction: 'all', signal: 'all', sort: 'conviction-desc' };
}

function applyFnoFilters() {
  const cEl = document.getElementById('fFnoConviction');
  const sEl = document.getElementById('fFnoSignal');
  const sortEl = document.getElementById('fFnoSort');
  if (cEl) window.fnoFilters.conviction = cEl.value;
  if (sEl) window.fnoFilters.signal = sEl.value;
  if (sortEl) window.fnoFilters.sort = sortEl.value;
  renderFnoTab();
}

function renderFnoTab() {
  const container = document.getElementById('tab-fno');
  if (!container) return;
  if (!FNO_DATA || !FNO_DATA.length) {
    container.innerHTML = '<div class="fno-no-data">⚠ No F&O data available. Run a scan.</div>';
    return;
  }

  const firstStock = FNO_DATA[0];
  const expiryStr  = firstStock ? firstStock.expiry_str : '';
  const daysLeft   = firstStock ? firstStock.days_to_expiry : '';

  function convColor(c) {
    if (c >= 70) return '#4ade80';
    if (c >= 50) return '#fbbf24';
    return '#f87171';
  }
  function convRatingLabel(c) {
    if (c >= 70) return '🔥 High';
    if (c >= 50) return '⚡ Medium';
    return '⚠️ Low';
  }
  function signalBadge(s) {
    if (s === 'CE') return '<span class="fno-signal-badge fno-signal-ce">▲ CE BUY</span>';
    if (s === 'PE') return '<span class="fno-signal-badge fno-signal-pe">▼ PE BUY</span>';
    return '<span class="fno-signal-badge fno-signal-neutral">◆ NEUTRAL</span>';
  }
  function priceChg(chg) {
    if (chg === undefined || chg === null) return '';
    const cls = chg >= 0 ? 'pos' : 'neg';
    return `<div class="fno-card-chg ${cls}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</div>`;
  }
  function maAlignPill(above50, above200) {
    if (above50 && above200)  return '<span class="fno-tech-pill" style="background:#052e1688;color:#4ade80;border:1px solid #16a34a">Above 50MA &amp; 200MA</span>';
    if (above50)              return '<span class="fno-tech-pill" style="background:#0c4a2688;color:#86efac;border:1px solid #22c55e">Above 50MA</span>';
    if (above200)             return '<span class="fno-tech-pill" style="background:#1c1c0888;color:#fde68a;border:1px solid #ca8a04">Above 200MA</span>';
    return                           '<span class="fno-tech-pill" style="background:#450a0a88;color:#f87171;border:1px solid #dc2626">Below 50MA &amp; 200MA</span>';
  }
  function rsiPill(rsi) {
    const cls = rsi >= 60 ? '#4ade80' : rsi >= 45 ? '#fbbf24' : '#f87171';
    return `<span class="fno-tech-pill" style="background:${cls}18;color:${cls};border:1px solid ${cls}44">RSI ${rsi}</span>`;
  }
  function volPill(vs) {
    const cls = vs >= 1.5 ? '#4ade80' : vs >= 1.0 ? '#fbbf24' : '#94a3b8';
    return `<span class="fno-tech-pill" style="background:${cls}18;color:${cls};border:1px solid ${cls}44">Vol ${vs}x</span>`;
  }
  function fmt(n) { return n ? '₹' + n.toLocaleString('en-IN', {minimumFractionDigits:2,maximumFractionDigits:2}) : '-'; }

  const strikeDir = s => s.signal === 'PE' ? 'PE' : 'CE';

  const filters = window.fnoFilters || { conviction: 'all', signal: 'all', sort: 'conviction-desc' };

  let filtered = FNO_DATA.filter(s => s.symbol === 'RELIANCE' || (s.ltp >= 1000 || s.lot_size < 500));
  if (filters.conviction !== 'all') {
    filtered = filtered.filter(s => {
      if (filters.conviction === 'high') return s.conviction >= 70;
      if (filters.conviction === 'medium') return s.conviction >= 50 && s.conviction < 70;
      if (filters.conviction === 'low') return s.conviction < 50;
      return true;
    });
  }
  if (filters.signal !== 'all') {
    filtered = filtered.filter(s => s.signal === filters.signal);
  }

  filtered.sort((a, b) => {
    if (filters.sort === 'conviction-desc') return b.conviction - a.conviction;
    if (filters.sort === 'conviction-asc') return a.conviction - b.conviction;
    if (filters.sort === 'symbol-asc') return a.symbol.localeCompare(b.symbol);
    return 0;
  });

  const cards = filtered.map(s => {
    const dir  = s.signal;
    const cc   = convColor(s.conviction);
    const s1   = dir === 'PE' ? s.pe_strike_1 : s.ce_strike_1;
    const s2   = dir === 'PE' ? s.pe_strike_2 : s.ce_strike_2;
    const o1   = dir === 'PE' ? s.pe_otm_pct_1 : s.ce_otm_pct_1;
    const o2   = dir === 'PE' ? s.pe_otm_pct_2 : s.ce_otm_pct_2;
    const slCls= dir === 'PE' ? 'pos' : 'neg';
    const tCls = dir === 'PE' ? 'neg' : 'pos';
    return `
    <div class="fno-card">
      <div class="fno-card-header">
        <div>
          <div class="fno-card-sym">${s.symbol}</div>
          <div class="fno-card-name">${s.name || ''}</div>
        </div>
        <div class="fno-card-price">
          <div class="fno-card-ltp">${fmt(s.ltp)}</div>
          ${priceChg(s.day_chg_pct)}
        </div>
      </div>
      <div class="fno-signal-row">
        ${signalBadge(dir)}
        <div class="fno-conviction">
          <div class="fno-conviction-label">
            <span>Conviction: <strong style="color:${cc}">${convRatingLabel(s.conviction)}</strong></span>
            <span style="color:${cc};font-weight:700">${s.conviction}%</span>
          </div>
          <div class="fno-conviction-bar">
            <div class="fno-conviction-fill" style="width:${s.conviction}%;background:${cc}"></div>
          </div>
        </div>
      </div>
      <div class="fno-body">
        <!-- Recommended Strikes -->
        <div class="fno-section-title">Recommended OTM Strikes (${dir === 'NEUTRAL' ? 'CE/PE' : dir})</div>
        <table class="fno-strikes-table">
          <tr><th>Strike</th><th>OTM%</th><th>Underlying Target</th></tr>
          <tr>
            <td><span class="fno-strike-val">₹${(s1||0).toLocaleString('en-IN')}</span></td>
            <td><span class="fno-strike-otm">${o1}% OTM</span></td>
            <td style="color:#fbbf24;font-weight:600">${dir === 'PE' ? fmt(s.t1_price) + ' ▼' : '▲ ' + fmt(s.t1_price)}</td>
          </tr>
          <tr>
            <td><span class="fno-strike-val">₹${(s2||0).toLocaleString('en-IN')}</span></td>
            <td><span class="fno-strike-otm">${o2}% OTM</span></td>
            <td style="color:#10b981;font-weight:600">${dir === 'PE' ? fmt(s.t2_price) + ' ▼' : '▲ ' + fmt(s.t2_price)}</td>
          </tr>
        </table>
        <!-- R/R on Underlying -->
        <div class="fno-section-title">Underlying Risk / Reward</div>
        <div class="fno-rr-grid">
          <div class="fno-rr-cell">
            <div class="fno-rr-label">SL (2%)</div>
            <div class="fno-rr-val ${slCls}">${fmt(s.sl_price)}</div>
          </div>
          <div class="fno-rr-cell">
            <div class="fno-rr-label">Target 1 (3.5%)</div>
            <div class="fno-rr-val ${tCls}">${fmt(s.t1_price)}</div>
          </div>
          <div class="fno-rr-cell">
            <div class="fno-rr-label">Target 2 (6%)</div>
            <div class="fno-rr-val ${tCls}">${fmt(s.t2_price)}</div>
          </div>
        </div>
        <!-- Technicals -->
        <div class="fno-section-title">Technicals</div>
        <div class="fno-tech-row">
          ${rsiPill(s.rsi)}
          ${volPill(s.vol_spike)}
          ${maAlignPill(s.above_ma50, s.above_ma200)}
        </div>
        <div class="fno-lot-info">
          <span>Lot Size: <strong>${s.lot_size}</strong> shares</span>
          <span>Strike Interval: ₹${s.strike_interval}</span>
          <span>52W Ret: <strong style="color:${s.wk52_return_pct >= 0 ? '#10b981' : '#ef4444'}">${s.wk52_return_pct >= 0 ? '+' : ''}${s.wk52_return_pct}%</strong></span>
        </div>
      </div>
    </div>`;
  }).join('');

  const gridContent = cards || `<div class="fno-no-data" style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--muted)">⚠ No stocks match the selected filters.</div>`;

  container.innerHTML = `
    <div class="fno-header">
      <div class="fno-header-left">
        <span style="font-size:28px">📊</span>
        <div>
          <div class="fno-header-title">F&amp;O Weekly Options Signal</div>
          <div class="fno-header-sub">Strategy: OTM CE / PE &bull; Hold 5–7 Trading Days &bull; Monthly Contract</div>
        </div>
      </div>
      <div class="fno-expiry-badge">⏰ Expiry: ${expiryStr} (${daysLeft} days)</div>
    </div>
    <div class="fno-disclaimer">
      <span>⚠</span>
      <span>These are <strong>underlying price signals</strong>, not option premium calls. Verify live IV, premium &amp; bid-ask from your broker's option chain before entering. Physical settlement applies on expiry — square off before expiry Tuesday.</span>
    </div>
    <div class="filters">
      <div class="filter-group">
        <label>Conviction Rating</label>
        <select id="fFnoConviction" onchange="applyFnoFilters()">
          <option value="all" ${filters.conviction === 'all' ? 'selected' : ''}>All Convictions</option>
          <option value="high" ${filters.conviction === 'high' ? 'selected' : ''}>High Conviction (≥70%)</option>
          <option value="medium" ${filters.conviction === 'medium' ? 'selected' : ''}>Medium Conviction (50% - 69%)</option>
          <option value="low" ${filters.conviction === 'low' ? 'selected' : ''}>Low Conviction (&lt;50%)</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Signal Type</label>
        <select id="fFnoSignal" onchange="applyFnoFilters()">
          <option value="all" ${filters.signal === 'all' ? 'selected' : ''}>All Signals</option>
          <option value="CE" ${filters.signal === 'CE' ? 'selected' : ''}>CE Buy</option>
          <option value="PE" ${filters.signal === 'PE' ? 'selected' : ''}>PE Buy</option>
          <option value="NEUTRAL" ${filters.signal === 'NEUTRAL' ? 'selected' : ''}>Neutral</option>
        </select>
      </div>
      <div class="filter-group">
        <label>Sort By</label>
        <select id="fFnoSort" onchange="applyFnoFilters()">
          <option value="conviction-desc" ${filters.sort === 'conviction-desc' ? 'selected' : ''}>Conviction (High to Low)</option>
          <option value="conviction-asc" ${filters.sort === 'conviction-asc' ? 'selected' : ''}>Conviction (Low to High)</option>
          <option value="symbol-asc" ${filters.sort === 'symbol-asc' ? 'selected' : ''}>Symbol (A to Z)</option>
        </select>
      </div>
    </div>
    <div class="fno-grid">${gridContent}</div>
  `;
}

// ── Intraday Buy/Sell Tab (Top 5 MIS long + Top 5 MIS short setups) ────
function renderIntradayTab() {
  const container = document.getElementById('tab-intraday');
  if (!container) return;

  const data = (typeof INTRADAY_DATA !== 'undefined' && INTRADAY_DATA) ? INTRADAY_DATA : { buy: [], sell: [] };
  const buys = data.buy || [];
  const sells = data.sell || [];

  function fmt(n) { return (n || n === 0) ? '₹' + Number(n).toLocaleString('en-IN', {minimumFractionDigits:2,maximumFractionDigits:2}) : '-'; }
  function pillColor(v, goodAbove) { return v >= goodAbove ? '#4ade80' : v >= goodAbove * 0.6 ? '#fbbf24' : '#f87171'; }

  function card(s) {
    const isBuy = s.direction === 'BUY';
    const hasChg = s.has_day_move && s.day_chg_pct != null;
    const chgCls = hasChg ? (s.day_chg_pct >= 0 ? 'pos' : 'neg') : '';
    const chgLabel = hasChg ? `${s.day_chg_pct >= 0 ? '+' : ''}${s.day_chg_pct}%` : 'Day chg n/a';
    const dirBadge = isBuy
      ? '<span class="fno-signal-badge fno-signal-ce">▲ BUY (Long)</span>'
      : '<span class="fno-signal-badge fno-signal-pe">▼ SELL (Short)</span>';
    const rsiCls = pillColor(isBuy ? s.rsi : (100 - s.rsi), 55);
    const volCls = pillColor(s.volume_spike, 1.5);
    return `
    <div class="fno-card">
      <div class="fno-card-header">
        <div>
          <div class="fno-card-sym">${s.symbol}</div>
          <div class="fno-card-name">${s.name || ''}</div>
        </div>
        <div class="fno-card-price">
          <div class="fno-card-ltp">${fmt(s.ltp)}</div>
          <div class="fno-card-chg ${chgCls}">${chgLabel}</div>
        </div>
      </div>
      <div class="fno-signal-row">
        ${dirBadge}
      </div>
      <div class="fno-section-title">Intraday Risk / Reward (MIS)</div>
      <div class="fno-rr-grid">
        <div class="fno-rr-cell">
          <div class="fno-rr-label">Stop Loss</div>
          <div class="fno-rr-val ${isBuy ? 'neg' : 'pos'}">${fmt(s.stop_loss)}</div>
        </div>
        <div class="fno-rr-cell">
          <div class="fno-rr-label">Target 1</div>
          <div class="fno-rr-val ${isBuy ? 'pos' : 'neg'}">${fmt(s.target1)}</div>
        </div>
        <div class="fno-rr-cell">
          <div class="fno-rr-label">Target 2</div>
          <div class="fno-rr-val ${isBuy ? 'pos' : 'neg'}">${fmt(s.target2)}</div>
        </div>
      </div>
      <div class="fno-tech-row">
        <span class="fno-tech-pill" style="background:${rsiCls}18;color:${rsiCls};border:1px solid ${rsiCls}44">RSI ${s.rsi}</span>
        <span class="fno-tech-pill" style="background:${volCls}18;color:${volCls};border:1px solid ${volCls}44">Vol ${s.volume_spike}x</span>
        <span class="fno-tech-pill" style="background:#6c63ff18;color:#a5b4fc;border:1px solid #6c63ff44">50DMA ${s.dist_ma50_pct >= 0 ? '+' : ''}${s.dist_ma50_pct}%</span>
      </div>
      <div class="fno-lot-info" style="padding:10px 18px 16px">
        <span style="color:var(--muted);font-size:11.5px">${s.rationale || ''}</span>
      </div>
    </div>`;
  }

  const buyCards = buys.map(card).join('') || '<div class="fno-no-data" style="grid-column: 1 / -1; padding: 30px">⚠ No strong intraday buy setups found in today\'s scan.</div>';
  const sellCards = sells.map(card).join('') || '<div class="fno-no-data" style="grid-column: 1 / -1; padding: 30px">⚠ No strong intraday sell setups found in today\'s scan.</div>';

  container.innerHTML = `
    <div class="fno-header">
      <div class="fno-header-left">
        <span style="font-size:28px">🎯</span>
        <div>
          <div class="fno-header-title">Intraday MIS Buy / Sell Setups</div>
          <div class="fno-header-sub">Same-day square-off &bull; Ranked by today's move + volume confirmation &bull; Not investment advice</div>
        </div>
      </div>
    </div>
    <div class="fno-section-title" style="margin-top:4px">🟢 Top ${buys.length} Buy (Long) Setups</div>
    <div class="fno-grid">${buyCards}</div>
    <div class="fno-section-title" style="margin-top:24px">🔴 Top ${sells.length} Sell (Short) Setups</div>
    <div class="fno-grid">${sellCards}</div>
  `;
}

// ── This Month's Locked LT Discovery Picks (lock-state banner only) ──
function renderLtMonthlyPicks() {
  const container = document.getElementById('ltMonthlyPicksSection');
  if (!container) return;

  // Auto-picks now live as real LT Watchlist entries (tagged lt_monthly_batch:true).
  // LT_MONTHLY_PICKS now carries only lock-state metadata, not full stock objects.
  const data = (typeof LT_MONTHLY_PICKS !== 'undefined' && LT_MONTHLY_PICKS) ? LT_MONTHLY_PICKS : {};
  const batchSymbols = Array.isArray(data.batch_symbols) ? data.batch_symbols : [];
  const batchSize = data.batch_size || batchSymbols.length || 0;
  const lockedUntil = data.locked_until || null;
  const generatedOn = data.generated_on || null;

  // Hide entirely if no batch info yet (first run before scan)
  if (!lockedUntil && batchSize === 0) {
    container.innerHTML = '';
    return;
  }

  const fmtDate = iso => iso
    ? new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
    : '\u2014';
  const daysLeft = lockedUntil ? Math.max(0, Math.ceil((new Date(lockedUntil) - new Date()) / 86400000)) : 0;

  const pillsHtml = batchSymbols.map(sym => {
    const inWl = (typeof ltWatchlist !== 'undefined') &&
      ltWatchlist.some(s => (s.symbol||'').toUpperCase() === sym.toUpperCase() && s.lt_monthly_batch);
    return '<span style="display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;' +
      'background:' + (inWl ? 'rgba(16,185,129,0.15)' : 'rgba(100,116,139,0.15)') + ';' +
      'color:' + (inWl ? '#34d399' : '#94a3b8') + ';' +
      'border:1px solid ' + (inWl ? 'rgba(16,185,129,0.4)' : 'rgba(100,116,139,0.3)') + ';">' + sym + '</span>';
  }).join(' ');

  container.innerHTML =
    '<div style="background:linear-gradient(135deg,rgba(99,102,241,0.10),rgba(139,92,246,0.08));' +
    'border:1px solid rgba(99,102,241,0.30);border-radius:12px;padding:14px 20px;margin-bottom:18px;' +
    'display:flex;align-items:flex-start;gap:14px;flex-wrap:wrap">' +
    '<div style="font-size:22px;margin-top:2px">\uD83D\uDD12</div>' +
    '<div style="flex:1;min-width:200px">' +
    '<div style="font-size:13px;font-weight:700;color:#c4b5fd;margin-bottom:4px">' +
    '\uD83D\uDD12 Monthly Auto-Picks Locked \u2014 ' + batchSize + ' stock' + (batchSize !== 1 ? 's' : '') + ' added to your LT Watchlist below</div>' +
    '<div style="font-size:11.5px;color:var(--muted);margin-bottom:8px">' +
    'Generated ' + fmtDate(generatedOn) + ' &bull; Locked until <strong style="color:#a5b4fc">' + fmtDate(lockedUntil) + '</strong>' +
    ' &bull; <strong style="color:' + (daysLeft > 7 ? '#34d399' : '#fbbf24') + '">' + daysLeft + ' day' + (daysLeft !== 1 ? 's' : '') + ' remaining</strong>' +
    ' &bull; LTP &lt; \u20b9600 &bull; Quality \u2265 70/100 &bull; See their BUY\u200bNOW/WAIT/WATCHING status in the watchlist table below</div>' +
    '<div style="display:flex;flex-wrap:wrap;gap:5px">' + pillsHtml + '</div>' +
    '</div></div>';
}

// ── Quality Penny Stocks Tab (Top 20 Micro-Cap Wealth Builder) ─────────
let pennyFilterCategory = 'all';
let customPennyMonthlyBudget = 200.0;

function renderPennyStocksTab() {
  const container = document.getElementById('tab-penny');
  if (!container) return;

  const pennyList = (typeof PENNY_STOCKS_DATA !== 'undefined' && Array.isArray(PENNY_STOCKS_DATA)) ? [...PENNY_STOCKS_DATA] : [];
  const holdingsList = (typeof LT_PORTFOLIO_SUMMARY !== 'undefined' && LT_PORTFOLIO_SUMMARY && Array.isArray(LT_PORTFOLIO_SUMMARY.holdings)) ? LT_PORTFOLIO_SUMMARY.holdings : [];

  holdingsList.forEach(h => {
    const sym = (h.symbol || '').toUpperCase();
    const price = parseFloat(h.live_price || h.last_price || h.avg_price || 0);
    if (h.qty > 0 && price <= 75.0 && !pennyList.some(s => (s.symbol || '').toUpperCase() === sym)) {
      // Pull the real scan row for this holding. Everything below must come from
      // measured data or be left null -- never invented. Nulls render as an
      // em dash, and the ROE/D-E quality filters drop null rows, which is the
      // correct outcome for a stock whose fundamentals we do not actually know.
      //
      // These fields used to be fabricated (roe 15.0, D/E 0.1, npm 10.0, trend
      // 'Strong Uptrend'). Those numbers sat exactly on the filter thresholds
      // (roe >= 15.0, de <= 0.15), so every held penny stock silently passed
      // quality screening no matter what its real financials were, and showed a
      // strong-uptrend badge regardless of its actual price structure.
      const scan = (typeof SCREENER_DATA !== 'undefined' && Array.isArray(SCREENER_DATA))
        ? SCREENER_DATA.find(s => (s.symbol || '').toUpperCase() === sym)
        : null;
      const pick = (key) => (h[key] != null ? h[key] : (scan && scan[key] != null ? scan[key] : null));

      pennyList.push({
        symbol: h.symbol,
        name: (scan && scan.name) || h.symbol,
        ltp: h.live_price || h.last_price || h.avg_price,
        status: 'BOUGHT',
        status_badge: `🟢 BOUGHT (${h.qty})`,
        status_badge_class: 'badge-green',
        status_reason: `Purchased on ${h.buy_date || ''} (${h.qty} shares @ ₹${parseFloat(h.avg_price).toFixed(2)})`,
        roe_pct: pick('roe_pct'),
        de_ratio: pick('de_ratio'),
        npm_pct: pick('npm_pct'),
        trend: scan ? scan.trend : null,
        trend_badge: scan ? (scan.trend_badge || scan.tech_rating) : null,
        auto_gtt: h.avg_price
      });
    }
  });

  const hMap = {};
  holdingsList.forEach(h => {
    const sym = (h.symbol || '').toUpperCase();
    const price = parseFloat(h.live_price || h.last_price || h.avg_price || 0);
    const isPennyData = (typeof PENNY_STOCKS_DATA !== 'undefined' && Array.isArray(PENNY_STOCKS_DATA)) && PENNY_STOCKS_DATA.some(s => (s.symbol || '').toUpperCase() === sym);
    if (price <= 75.0 || isPennyData) {
      hMap[sym] = h;
    }
  });

  const getCategory = (s) => {
    const sym = (s.symbol || '').toUpperCase();
    const isB = hMap[sym] && hMap[sym].qty > 0;
    if (isB || s.status === 'BOUGHT') return 'bought';
    const st = (s.status || '').toUpperCase();
    const badge = (s.status_badge || '').toUpperCase();
    if (badge.includes('START SIP NOW') || st === 'START_SIP_NOW') {
      return 'buy_now';
    }
    if (badge.includes('SIP ON DIP') || badge.includes('RETEST') || st === 'WAIT') {
      return 'wait';
    }
    if (st === 'BUY_NOW' || st === 'BUY' || badge.includes('BUY NOW')) {
      return 'buy_now';
    }
    return 'watching';
  };

  const buyNowCount = pennyList.filter(s => getCategory(s) === 'buy_now').length;
  const boughtCount = pennyList.filter(s => getCategory(s) === 'bought').length;
  const waitCount = pennyList.filter(s => getCategory(s) === 'wait').length;
  const watchingCount = pennyList.filter(s => getCategory(s) === 'watching').length;

  let filtered = [...pennyList];
  if (pennyFilterCategory === 'buy_now') {
    filtered = filtered.filter(s => getCategory(s) === 'buy_now');
  } else if (pennyFilterCategory === 'bought') {
    filtered = filtered.filter(s => getCategory(s) === 'bought');
  } else if (pennyFilterCategory === 'wait') {
    filtered = filtered.filter(s => getCategory(s) === 'wait');
  } else if (pennyFilterCategory === 'watching') {
    filtered = filtered.filter(s => getCategory(s) === 'watching');
  } else if (pennyFilterCategory === 'debt_free') {
    filtered = filtered.filter(s => s.de_ratio != null && s.de_ratio <= 0.15);
  } else if (pennyFilterCategory === 'high_roe') {
    filtered = filtered.filter(s => s.roe_pct != null && s.roe_pct >= 15.0);
  } else if (pennyFilterCategory === 'under_30') {
    filtered = filtered.filter(s => s.ltp != null && s.ltp <= 30.0);
  } else if (pennyFilterCategory === 'under_50') {
    filtered = filtered.filter(s => s.ltp != null && s.ltp <= 50.0);
  }

  const budget = customPennyMonthlyBudget || 200.0;

  const cardsHtml = filtered.map((s, idx) => {
    const sym = (s.symbol || '').toUpperCase();
    const ltp = parseFloat(s.ltp || 0);
    const sipQty = ltp > 0 ? Math.max(1, Math.floor(budget / ltp)) : 1;
    const sipCost = (sipQty * ltp).toFixed(2);
    const roeVal = s.roe_pct != null ? s.roe_pct.toFixed(1) + '%' : '—';
    const deVal = s.de_ratio != null ? s.de_ratio.toFixed(2) : '—';
    const npmVal = s.npm_pct != null ? s.npm_pct.toFixed(1) + '%' : '—';
    const volVal = s.avg_volume_10d ? (s.avg_volume_10d / 1000).toFixed(0) + 'k' : '—';

    const holding = hMap[sym];
    const isBought = !!(holding && holding.qty > 0);
    const gateStatus = isBought ? 'BOUGHT' : ((s.status === 'BUY_NOW') ? 'BUY_NOW' : (s.status || 'WATCHLIST'));


    // Status Badge
    let statusBadgeHtml = '';
    if (isBought) {
      statusBadgeHtml = `<span class="badge badge-green" style="font-size:10px;font-weight:700" title="Purchased on ${holding.buy_date || ''} (${holding.qty} shares @ ₹${parseFloat(holding.avg_price || 0).toFixed(2)})">🟢 BOUGHT (${holding.qty})</span>`;
    } else if (s.status_badge) {
      const cls = s.status_badge_class || (gateStatus === 'BUY_NOW' ? 'badge-green' : gateStatus === 'WAIT' ? 'badge-purple' : 'badge-gray');
      statusBadgeHtml = `<span class="badge ${cls}" style="font-size:10px;font-weight:700" title="${s.status_reason || ''}">${s.status_badge}</span>`;
    } else if (gateStatus === 'BUY_NOW') {
      statusBadgeHtml = `<span class="badge badge-green" style="font-size:10px;font-weight:700" title="${s.status_reason || ''}">🟢 BUY NOW</span>`;
    } else if (gateStatus === 'WAIT') {
      statusBadgeHtml = `<span class="badge badge-purple" style="font-size:10px;font-weight:700" title="${s.status_reason || ''}">🔵 WAIT</span>`;
    } else {
      statusBadgeHtml = `<span class="badge badge-gray" style="font-size:10px;font-weight:700" title="${s.status_reason || ''}">⬜ WATCHING</span>`;
    }


    // Trend & CMF Badge
    // No trend claim when the stock is not in the scan set — an em dash is
    // honest, whereas defaulting to a named state asserts something unmeasured.
    const trendText = s.trend_badge || s.trend || '—';
    const trendClass = trendBadgeClass(s.trend);
    const cmfBadge = s.pa_badge ? `<div style="font-size:9px;margin-top:3px"><span class="badge ${s.pa_class || 'badge-gray'}" style="font-size:9px">${s.pa_badge}</span></div>` : '';

    // Support Target GTT
    const gttVal = s.auto_gtt || s.gtt_level;
    const gttStr = gttVal ? `₹${parseFloat(gttVal).toFixed(2)}` : '—';
    const distStr = s.dist_from_gtt_pct != null ? `${s.dist_from_gtt_pct <= 0 ? '' : '+'}${s.dist_from_gtt_pct.toFixed(1)}%` : '—';
    const gttBoxHtml = `
      <div style="display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:8px;padding:6px 10px;margin-bottom:10px;font-size:10px">
        <span style="color:var(--muted);font-weight:600">⚡ Support GTT Target:</span>
        <span style="color:#34d399;font-weight:800">${gttStr} <span style="color:${s.dist_from_gtt_pct <= 0 ? '#10b981' : '#a5b4fc'};font-size:9px">(${distStr})</span></span>
      </div>
    `;

    // Smart Action Button
    let actionBtnHtml = '';
    if (isBought) {
      actionBtnHtml = `
        <div style="margin-top:10px;display:flex;gap:8px">
          <button onclick="openLtHoldingLogModal('${sym}')" style="flex:1;background:rgba(6,182,212,0.18);border:1px solid rgba(6,182,212,0.4);color:#22d3ee;font-weight:700;font-size:11px;padding:8px 12px;border-radius:8px;cursor:pointer" title="View Purchase Log for ${sym}">📋 Purchased (${holding.qty})</button>
          <button onclick="openLtBuyModal('${sym}', ${ltp})" style="background:linear-gradient(135deg,#7c3aed,#c084fc);color:#fff;font-weight:700;font-size:11px;padding:8px 12px;border-radius:8px;border:none;cursor:pointer" title="Record additional SIP for ${sym}">+ Add SIP</button>
        </div>
      `;
    } else if (gateStatus === 'BUY_NOW') {
      actionBtnHtml = `
        <div style="margin-top:10px">
          <button onclick="openLtBuyModal('${sym}', ${ltp})" style="width:100%;background:linear-gradient(135deg,#10b981,#059669);color:#fff;font-weight:800;font-size:11px;padding:8px 12px;border-radius:8px;border:none;cursor:pointer;box-shadow:0 4px 12px rgba(16,185,129,0.3)" title="Breakout confirmed at Support — Record Buy/SIP">🟢 BUY NOW / Record SIP</button>
        </div>
      `;
    } else if (gateStatus === 'WAIT') {
      actionBtnHtml = `
        <div style="margin-top:10px">
          <button onclick="openLtBuyModal('${sym}', ${ltp})" style="width:100%;background:rgba(99,102,241,0.18);border:1px solid rgba(99,102,241,0.4);color:#a5b4fc;font-weight:700;font-size:11px;padding:8px 12px;border-radius:8px;cursor:pointer" title="Coiling at support GTT ${gttStr} — Click if buying manual pullback">🔵 WAIT — Support GTT ${gttStr}</button>
        </div>
      `;
    } else {
      actionBtnHtml = `
        <div style="margin-top:10px">
          <button onclick="openLtBuyModal('${sym}', ${ltp})" style="width:100%;background:rgba(100,116,139,0.15);border:1px solid rgba(100,116,139,0.3);color:#94a3b8;font-weight:600;font-size:11px;padding:8px 12px;border-radius:8px;cursor:pointer" title="Trend not confirmed (${s.trend || 'Consolidation'}) — Avoid blind buy">⚠️ WATCHING (${s.trend || 'Consolidation'})</button>
        </div>
      `;
    }

    return `
    <div style="background:var(--card);border:1px solid ${isBought ? '#10b981' : (gateStatus === 'BUY_NOW' ? 'rgba(16,185,129,0.6)' : 'var(--border)')};border-radius:16px;padding:20px;box-shadow:0 8px 24px rgba(0,0,0,0.3);position:relative;overflow:hidden">
      <div style="position:absolute;top:0;left:0;right:0;height:3px;background:${isBought ? '#10b981' : (gateStatus === 'BUY_NOW' ? '#10b981' : 'linear-gradient(90deg,#7c3aed,#c084fc)')}"></div>
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
        <div>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            <span style="font-size:10px;font-weight:800;color:#c084fc;background:rgba(192,132,252,0.12);padding:2px 8px;border-radius:12px">#${idx + 1} Top Penny</span>
            ${statusBadgeHtml}
            <span class="badge ${trendClass}" style="font-size:10px">${trendText}</span>
          </div>
          ${cmfBadge}
          <div style="font-size:18px;font-weight:800;color:#fff;margin-top:6px">${sym}</div>
          <div style="font-size:11px;color:var(--muted);margin-top:1px">${(s.name || '').substring(0, 28)} · ${s.sector || 'Micro-Cap'}</div>
        </div>
        <div style="text-align:right">
          <div style="font-size:18px;font-weight:800;color:var(--accent2)">₹${ltp.toFixed(2)}</div>
          <div style="font-size:10px;color:${(s.day_chg_pct || 0) >= 0 ? '#10b981' : '#ef4444'};margin-top:2px;font-weight:700">
            ${(s.day_chg_pct || 0) >= 0 ? '+' : ''}${(s.day_chg_pct || 0).toFixed(2)}%
          </div>
        </div>
      </div>

      <!-- Support GTT Target -->
      ${gttBoxHtml}

      <!-- Fundamental Metrics Grid -->
      <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:6px;background:rgba(255,255,255,0.03);border-radius:10px;padding:8px;margin-bottom:10px;text-align:center">
        <div>
          <div style="font-size:9px;color:var(--muted);text-transform:uppercase">ROE %</div>
          <div style="font-size:12px;font-weight:700;color:#10b981;margin-top:2px">${roeVal}</div>
        </div>
        <div>
          <div style="font-size:9px;color:var(--muted);text-transform:uppercase">Debt/Equity</div>
          <div style="font-size:12px;font-weight:700;color:#38bdf8;margin-top:2px">${deVal}</div>
        </div>
        <div>
          <div style="font-size:9px;color:var(--muted);text-transform:uppercase">Margin</div>
          <div style="font-size:12px;font-weight:700;color:#c084fc;margin-top:2px">${npmVal}</div>
        </div>
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center;font-size:10px;color:var(--muted);margin-bottom:10px;padding:0 2px">
        <span>Avg Vol (10d): <strong style="color:#fff">${volVal}</strong></span>
        <span>Quality Score: <strong style="color:var(--accent2)">${s.total_score || 0}/100</strong></span>
      </div>

      <!-- Monthly SIP Recommendation Box -->
      <div style="background:linear-gradient(135deg,rgba(124,58,237,0.12),rgba(192,132,252,0.08));border:1px solid rgba(192,132,252,0.25);border-radius:10px;padding:8px 12px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div>
            <div style="font-size:9px;color:#c084fc;font-weight:700;text-transform:uppercase">Monthly SIP Outlay</div>
            <div style="font-size:13px;font-weight:800;color:#fff;margin-top:1px">Buy ${sipQty} Share${sipQty > 1 ? 's' : ''} / mo</div>
          </div>
          <div style="text-align:right">
            <div style="font-size:9px;color:var(--muted)">Est. Cost</div>
            <div style="font-size:13px;font-weight:800;color:#34d399;margin-top:1px">₹${sipCost}</div>
          </div>
        </div>
      </div>

      ${actionBtnHtml}
    </div>
    `;
  }).join('');

  container.innerHTML = `
    <!-- Header Banner -->
    <div style="background:linear-gradient(135deg,#1e1035,#0f0a1e);border:1px solid #7c3aed;border-radius:16px;padding:22px;margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px">
      <div>
        <div style="display:flex;align-items:center;gap:10px">
          <span style="font-size:24px">💎</span>
          <div>
            <div style="font-size:20px;font-weight:800;color:#c084fc">Quality Penny & Micro-Cap Wealth-Builder Screener</div>
            <div style="font-size:12px;color:#a78bfa;margin-top:2px">Strict 6-Point Gate + Technical Entry Filter (Support GTT & CMF Accumulation/Distribution)</div>
          </div>
        </div>
      </div>
      <div style="background:rgba(192,132,252,0.12);border:1px solid rgba(192,132,252,0.3);padding:8px 16px;border-radius:12px;text-align:right">
        <div style="font-size:10px;color:#c084fc;text-transform:uppercase;font-weight:700">Qualified Penny Candidates</div>
        <div style="font-size:20px;font-weight:900;color:#fff;margin-top:1px">${pennyList.length} Stocks Scanned</div>
      </div>
    </div>

    <!-- Filter & SIP Budget Controller Row -->
    <div class="filters" style="margin-bottom:20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <span style="font-size:11px;color:var(--muted);font-weight:700;margin-right:2px">Gate Status:</span>
        <button onclick="pennyFilterCategory='all';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='all'?'active':''}" style="padding:6px 12px;font-size:11px">↺ All (${pennyList.length})</button>
        <button onclick="pennyFilterCategory='buy_now';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='buy_now'?'active':''}" style="padding:6px 12px;font-size:11px;border-color:#10b981;color:#34d399">🟢 BUY NOW (${buyNowCount})</button>
        <button onclick="pennyFilterCategory='bought';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='bought'?'active':''}" style="padding:6px 12px;font-size:11px;border-color:#06b6d4;color:#22d3ee">🟢 BOUGHT (${boughtCount})</button>
        <button onclick="pennyFilterCategory='wait';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='wait'?'active':''}" style="padding:6px 12px;font-size:11px;border-color:#6366f1;color:#a5b4fc">🔵 WAIT (${waitCount})</button>
        <button onclick="pennyFilterCategory='watching';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='watching'?'active':''}" style="padding:6px 12px;font-size:11px;border-color:#64748b;color:#94a3b8">⬜ WATCHING (${watchingCount})</button>
        <span style="border-left:1px solid var(--border);height:16px;margin:0 4px"></span>
        <button onclick="pennyFilterCategory='debt_free';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='debt_free'?'active':''}" style="padding:6px 12px;font-size:11px">💎 Debt-Free</button>
        <button onclick="pennyFilterCategory='high_roe';renderPennyStocksTab()" class="tab ${pennyFilterCategory==='high_roe'?'active':''}" style="padding:6px 12px;font-size:11px">🔥 High ROE</button>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <label style="font-size:11px;color:var(--muted);font-weight:700">Monthly SIP Amount (₹):</label>
        <input type="number" id="pennyBudgetInput" value="${budget}" min="50" max="5000" step="50"
               onchange="customPennyMonthlyBudget=parseFloat(this.value)||200;renderPennyStocksTab()"
               style="background:var(--card);border:1px solid var(--border);color:#fff;padding:6px 10px;border-radius:8px;width:100px;font-size:12px;font-weight:700">
      </div>
    </div>

    <!-- Cards Grid -->
    <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(310px, 1fr));gap:16px">
      ${cardsHtml || '<div style="color:var(--muted);text-align:center;grid-column:1/-1;padding:40px">No penny stocks match this filter.</div>'}
    </div>
  `;
}

// ── Market Holidays Tab (Y2026 List) ──────────────────────────────────────
function renderHolidaysTab() {
  const container = document.getElementById('tab-holidays');
  if (!container) return;

  const holidays = [
    { date: "2026-01-26", display: "26 Jan 2026", day: "Monday", name: "Republic Day", type: "Trading Holiday", status: "CLOSED", icon: "🇮🇳" },
    { date: "2026-02-15", display: "15 Feb 2026", day: "Sunday", name: "Mahashivratri", type: "Weekend Holiday", status: "WEEKEND", icon: "🕉️" },
    { date: "2026-03-03", display: "03 Mar 2026", day: "Tuesday", name: "Holi", type: "Trading Holiday", status: "CLOSED", icon: "🎨" },
    { date: "2026-03-21", display: "21 Mar 2026", day: "Saturday", name: "Id-Ul-Fitr (Ramadan Eid)", type: "Weekend Holiday", status: "WEEKEND", icon: "🌙" },
    { date: "2026-03-26", display: "26 Mar 2026", day: "Thursday", name: "Shri Ram Navami", type: "Trading Holiday", status: "CLOSED", icon: "🛕" },
    { date: "2026-03-31", display: "31 Mar 2026", day: "Tuesday", name: "Shri Mahavir Jayanti", type: "Trading Holiday", status: "CLOSED", icon: "🙏" },
    { date: "2026-04-03", display: "03 Apr 2026", day: "Friday", name: "Good Friday", type: "Trading Holiday", status: "CLOSED", icon: "✝️" },
    { date: "2026-04-14", display: "14 Apr 2026", day: "Tuesday", name: "Dr. Baba Saheb Ambedkar Jayanti", type: "Trading Holiday", status: "CLOSED", icon: "📜" },
    { date: "2026-05-01", display: "01 May 2026", day: "Friday", name: "Maharashtra Day", type: "Trading Holiday", status: "CLOSED", icon: "🚩" },
    { date: "2026-05-28", display: "28 May 2026", day: "Thursday", name: "Bakri Id (Id-Ul-Adha)", type: "Trading Holiday", status: "CLOSED", icon: "🌙" },
    { date: "2026-06-26", display: "26 Jun 2026", day: "Friday", name: "Muharram", type: "Trading Holiday", status: "CLOSED", icon: "🕌" },
    { date: "2026-08-15", display: "15 Aug 2026", day: "Saturday", name: "Independence Day", type: "Weekend Holiday", status: "WEEKEND", icon: "🇮🇳" },
    { date: "2026-09-14", display: "14 Sep 2026", day: "Monday", name: "Ganesh Chaturthi", type: "Trading Holiday", status: "CLOSED", icon: "🐘" },
    { date: "2026-10-02", display: "02 Oct 2026", day: "Friday", name: "Mahatma Gandhi Jayanti", type: "Trading Holiday", status: "CLOSED", icon: "🕊️" },
    { date: "2026-10-20", display: "20 Oct 2026", day: "Tuesday", name: "Dussehra", type: "Trading Holiday", status: "CLOSED", icon: "🏹" },
    { date: "2026-11-08", display: "08 Nov 2026", day: "Sunday", name: "Diwali Laxmi Pujan", type: "Special Session (Muhurat Trading)", status: "MUHURAT", icon: "🪔", note: "⭐ Special Evening Muhurat Trading session" },
    { date: "2026-11-10", display: "10 Nov 2026", day: "Tuesday", name: "Diwali-Balipratipada", type: "Trading Holiday", status: "CLOSED", icon: "🪔" },
    { date: "2026-11-24", display: "24 Nov 2026", day: "Tuesday", name: "Guru Nanak Jayanti", type: "Trading Holiday", status: "CLOSED", icon: "🪯" },
    { date: "2026-12-25", display: "25 Dec 2026", day: "Friday", name: "Christmas", type: "Trading Holiday", status: "CLOSED", icon: "🎄" }
  ];

  const weekdayHolidaysCount = holidays.filter(h => h.status === 'CLOSED').length;
  const weekendHolidaysCount = holidays.filter(h => h.status === 'WEEKEND').length;

  const rowsHtml = holidays.map(h => {
    let badgeClass = "badge-red";
    let badgeLabel = "🔴 Market Closed";
    if (h.status === "WEEKEND") {
      badgeClass = "badge-yellow";
      badgeLabel = "🟡 Weekend Holiday";
    } else if (h.status === "MUHURAT") {
      badgeClass = "badge-purple";
      badgeLabel = "⭐ Muhurat Session";
    }

    return `<tr>
      <td><strong style="color:var(--accent2);font-size:13px">${h.display}</strong></td>
      <td><span style="color:var(--text);font-weight:600">${h.day}</span></td>
      <td>
        <div style="font-weight:700;display:flex;align-items:center;gap:8px">
          <span>${h.icon}</span>
          <span>${h.name}</span>
        </div>
        ${h.note ? `<div style="font-size:11px;color:var(--warn);margin-top:2px">${h.note}</div>` : ''}
      </td>
      <td><span class="badge ${badgeClass}" style="font-size:11px;font-weight:700">${badgeLabel}</span></td>
      <td><span class="badge badge-gray">${h.type}</span></td>
    </tr>`;
  }).join('');

  container.innerHTML = `
    <!-- Top Spotlight Card -->
    <div class="hero-spotlight" style="margin-bottom:20px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
        <div>
          <div class="hero-badge-tag">📅 Official Market Calendar 2026</div>
          <div style="font-size:24px;font-weight:800;color:var(--white);margin-top:4px">NSE & BSE Trading Holidays List (Y2026)</div>
          <div style="font-size:13px;color:var(--muted);margin-top:4px">
            Official exchange holidays for Equity, Equity Derivatives, and SLB trading segments in India.
          </div>
        </div>
        <div class="badge badge-purple" style="font-size:13px;font-weight:700;padding:8px 16px">
          🇮🇳 Indian Stock Markets (NSE / BSE)
        </div>
      </div>

      <!-- Quick Summary Stats Grid -->
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:18px">
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center">
          <div style="font-size:24px;font-weight:800;color:var(--danger)">${weekdayHolidaysCount}</div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;margin-top:2px">Weekday Trading Holidays</div>
        </div>
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center">
          <div style="font-size:24px;font-weight:800;color:var(--warn)">${weekendHolidaysCount}</div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;margin-top:2px">Weekend Holidays</div>
        </div>
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;text-align:center">
          <div style="font-size:24px;font-weight:800;color:#a5b4fc">1</div>
          <div style="font-size:11px;color:var(--muted);text-transform:uppercase;margin-top:2px">Special Muhurat Session</div>
        </div>
      </div>
    </div>

    <!-- Holidays List Table -->
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Day</th>
            <th>Holiday / Occasion</th>
            <th>Exchange Status</th>
            <th>Category</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    </div>
  `;
}

// ── Stock of the Day & History ──────────────────────────────────────────
function renderTopPick() {
  const container = document.getElementById('topPickInnerContent') || document.getElementById('tab-top-pick');
  if (!container || !TOP_PICK || !TOP_PICK.symbol) return;

  const inWl = watchlist.some(w => w.symbol === TOP_PICK.symbol);

  const mktBannerHtml = (MARKET_INFO && MARKET_INFO.is_pre_market) ? `
    <div style="background:rgba(245, 158, 11, 0.12);border:1px solid rgba(245, 158, 11, 0.3);border-radius:12px;padding:14px 18px;margin-bottom:18px;display:flex;align-items:center;gap:14px">
      <span style="font-size:24px">⏳</span>
      <div>
        <div style="font-weight:700;color:var(--warn);font-size:14px">Pre-Market Session (${MARKET_INFO.time_str || ''}) — Market Closed</div>
        <div style="font-size:12px;color:var(--text);margin-top:2px">
          Trading on NSE/BSE has not opened yet today. Today's official <strong>Stock of the Day</strong> and pick entry price will lock at <strong>09:15 AM IST</strong> when the market opens. Below is the current top candidate based on pre-market/previous close data.
        </div>
      </div>
    </div>` : (MARKET_INFO && MARKET_INFO.is_open) ? `
    <div style="background:rgba(16, 185, 129, 0.12);border:1px solid rgba(16, 185, 129, 0.3);border-radius:12px;padding:12px 18px;margin-bottom:18px;display:flex;align-items:center;gap:12px">
      <span style="font-size:20px">🟢</span>
      <div>
        <div style="font-weight:700;color:var(--green);font-size:13px">Live Market Session Active (09:15 - 15:30 IST)</div>
        <div style="font-size:12px;color:var(--text);margin-top:2px">
          Today's official pick was locked at Market Open. Current price & live returns update automatically in real-time.
        </div>
      </div>
    </div>` : `
    <div style="background:rgba(239, 68, 68, 0.1);border:1px solid rgba(239, 68, 68, 0.25);border-radius:12px;padding:12px 18px;margin-bottom:18px;display:flex;align-items:center;gap:12px">
      <span style="font-size:20px">🔴</span>
      <div>
        <div style="font-weight:700;color:var(--danger);font-size:13px">${MARKET_INFO ? MARKET_INFO.badge : 'Market Closed'}</div>
        <div style="font-size:12px;color:var(--text);margin-top:2px">
          ${MARKET_INFO ? MARKET_INFO.message : 'Market is closed. Showing finalized daily picks.'}
        </div>
      </div>
    </div>`;

  const highlightsHtml = (TOP_PICK.highlights || []).map(h =>
    `<li style="margin-bottom:6px;display:flex;align-items:center;gap:8px"><span>✅</span><span>${h}</span></li>`
  ).join('');

  const heroCurrentPrice = TOP_PICK.current_ltp || TOP_PICK.ltp || TOP_PICK.ltp_at_pick || 0;
  let heroPrevClose = TOP_PICK.prev_close;
  if ((!heroPrevClose || Math.abs(heroPrevClose - (TOP_PICK.ltp_at_pick || heroCurrentPrice)) < 0.05) && DAILY_PICKS_HISTORY && DAILY_PICKS_HISTORY.length > 1) {
    const prev = DAILY_PICKS_HISTORY[1];
    heroPrevClose = prev.session_close || prev.close || prev.ltp_at_pick;
  }

  let heroGapHtml = '⚪ Flat Open (0.00%)';
  let heroGapCls = 'badge-gray';
  if (heroPrevClose && heroPrevClose > 0) {
    const refPickPrice = TOP_PICK.ltp_at_pick || heroCurrentPrice;
    const gAmt = refPickPrice - heroPrevClose;
    const gPct = (gAmt / heroPrevClose) * 100;
    if (Math.abs(gPct) >= 0.01) {
      heroGapCls = gPct > 0 ? 'badge-green' : 'badge-red';
      const gIcon = gPct > 0 ? '▲' : '▼';
      const gTag = gAmt > 0 ? 'Gap Up' : 'Gap Down';
      heroGapHtml = `${gIcon} ${gTag} ${gPct >= 0 ? '+' : ''}${gPct.toFixed(2)}% (${gAmt >= 0 ? '+' : ''}₹${gAmt.toFixed(2)})`;
    }
  }

  const historyRows = (DAILY_PICKS_HISTORY || []).map((h, idx, arr) => {
    const pickPrice = h.ltp_at_pick || h.ltp || 0;
    const curPrice = h.current_ltp || h.ltp || pickPrice;
    const sessionClose = h.session_close || h.close || (idx === 0 ? curPrice : pickPrice);

    // Total P&L from original Pick Entry Price
    const totalPnlAmt = curPrice - pickPrice;
    const totalPnlPct = pickPrice > 0 ? (totalPnlAmt / pickPrice) * 100 : 0;
    const totalCls = totalPnlAmt > 0 ? 'pos' : totalPnlAmt < 0 ? 'neg' : 'neu';

    // Day Change P&L (Current LTP vs Session Close / Prev Close)
    let refClose = sessionClose;
    if (idx === 0 && arr.length > 1) {
      const prev = arr[1];
      refClose = prev.session_close || prev.close || prev.ltp_at_pick || curPrice;
    }
    const dayChgAmt = curPrice - refClose;
    const dayChgPct = refClose > 0 ? (dayChgAmt / refClose) * 100 : 0;
    const dayCls = dayChgAmt > 0 ? 'pos' : dayChgAmt < 0 ? 'neg' : 'neu';

    const stBadge = h.is_pre_market ? '⏳ PENDING MARKET OPEN' : (h.status_badge || '🟢 ACTIVE');
    const stReason = h.status_reason || '';
    const badgeClass = h.is_pre_market ? 'badge-yellow' : (h.status === 'INVALIDATED' ? 'badge-yellow' : h.status === 'INACTIVE' ? 'badge-red' : 'badge-green');

    return `<tr>
      <td><strong style="color:var(--accent2)">${h.display_date || h.date}</strong></td>
      <td>
        <div style="font-weight:700">${h.symbol} ${h.is_pre_market ? '<span style="font-size:10px;color:var(--warn)">(Candidate)</span>' : ''}</div>
        <div style="font-size:11px;color:var(--muted)">${h.name || ''}</div>
      </td>
      <td><span class="badge ${badgeClass}" title="${stReason}">${stBadge}</span></td>
      <td>${scoreBar(h.total_score || 0)}</td>
      <td>
        <div style="font-weight:700">₹${pickPrice.toFixed(2)}</div>
        <div style="font-size:10px;color:var(--muted)">Market Open Entry</div>
      </td>
      <td>
        <div style="font-weight:700;color:var(--text)">₹${sessionClose.toFixed(2)}</div>
        <div style="font-size:10px;color:var(--muted)">Pick Day Close</div>
      </td>
      <td><span class="price" style="font-weight:700">₹${curPrice.toFixed(2)}</span></td>
      <td>
        <span class="${dayCls}" style="font-weight:700">${dayChgAmt >= 0 ? '+' : ''}₹${dayChgAmt.toFixed(2)} (${dayChgPct >= 0 ? '+' : ''}${dayChgPct.toFixed(2)}%)</span>
      </td>
      <td>
        <span class="${totalCls}" style="font-weight:800;font-size:13px">${totalPnlAmt >= 0 ? '+' : ''}₹${totalPnlAmt.toFixed(2)} (${totalPnlPct >= 0 ? '+' : ''}${totalPnlPct.toFixed(2)}%)</span>
      </td>
      <td>
        <button class="btn-add" onclick="openModal('${h.symbol}')">Detail</button>
      </td>
    </tr>`;
  }).join('');

  const currentMkt = calculateCurrentMarketStatus();
  const isPreMktActive = currentMkt.is_pre_market;
  const showStatusWarning = TOP_PICK.status && TOP_PICK.status !== 'ACTIVE' && (TOP_PICK.status !== 'PENDING' || isPreMktActive);

  container.innerHTML = `
    ${mktBannerHtml}

    <div class="hero-spotlight">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <div class="hero-badge-tag">🏆 Stock of the Day · ${TOP_PICK.display_date || TOP_PICK.date}</div>
          ${(TOP_PICK.streak_days && TOP_PICK.streak_days > 1) ? `
          <span class="badge badge-yellow" style="font-weight:700;font-size:12px;padding:6px 12px">
            ⭐ Streak: ${TOP_PICK.streak_days} Consecutive Days (#1 Pick)
          </span>` : `
          <span class="badge badge-purple" style="font-weight:700;font-size:12px;padding:6px 12px">
            ✨ ${isPreMktActive ? "Today's #1 Candidate" : "Today's #1 Highest-Scoring Stock"}
          </span>`}
          <span class="badge ${isPreMktActive ? 'badge-yellow' : (TOP_PICK.status === 'INVALIDATED' ? 'badge-yellow' : TOP_PICK.status === 'INACTIVE' ? 'badge-red' : 'badge-green')}" style="font-weight:700;font-size:12px;padding:6px 12px">
            ${isPreMktActive ? '⏳ PENDING MARKET OPEN' : (TOP_PICK.status_badge && TOP_PICK.status !== 'PENDING' ? TOP_PICK.status_badge : '🟢 ACTIVE')}
          </span>
        </div>
        <div class="badge ${TOP_PICK.tech_class || 'badge-green'}" style="font-size:14px;font-weight:800;padding:8px 18px;border-radius:20px;box-shadow:0 4px 14px rgba(0,0,0,0.3);letter-spacing:0.02em">
          ${TOP_PICK.tech_rating || '🟢 Strong Uptrend'}
        </div>
      </div>

      ${showStatusWarning ? `
      <div class="alert-row alert-SELL" style="margin-bottom:14px;padding:10px 14px;font-size:13px">
        <span>⚠️</span>
        <div>
          <strong>Stock of the Day Status: ${TOP_PICK.status}</strong> — ${TOP_PICK.status_reason || 'Quality score dropped below qualification threshold.'}
          <div style="font-size:11px;margin-top:2px;color:var(--text)">If this stock re-qualifies (Score ≥55, Strength ≥50), its status will automatically restore back to 🟢 ACTIVE.</div>
        </div>
      </div>
      ` : ''}

      <div class="hero-grid">
        <div>
          <div style="font-size:28px;font-weight:800;color:var(--white)">${TOP_PICK.symbol} <span style="font-size:16px;font-weight:400;color:var(--muted)">— ${TOP_PICK.name || ''}</span></div>
          <div style="font-size:13px;color:var(--accent2);margin-top:2px">${TOP_PICK.sector || ''}</div>
          <div style="font-size:26px;font-weight:700;margin:12px 0">
            <span class="price">₹${heroCurrentPrice.toFixed(2)}</span>
          </div>

          <!-- Fundamental Badges -->
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0">
            <span class="badge badge-purple">ROE: ${TOP_PICK.roe_pct != null ? TOP_PICK.roe_pct.toFixed(1) + '%' : '—'}</span>
            <span class="badge badge-green">Debt/Eq: ${TOP_PICK.de_ratio != null ? TOP_PICK.de_ratio.toFixed(2) : '—'}</span>
            <span class="badge badge-purple">Net Margin: ${TOP_PICK.npm_pct != null ? TOP_PICK.npm_pct.toFixed(1) + '%' : '—'}</span>
            <span class="badge badge-yellow">P/E: ${TOP_PICK.pe != null ? TOP_PICK.pe.toFixed(1) : '—'}</span>
          </div>

          <!-- ⚡ Overnight Price Fluctuation & Gap Analysis Card -->
          <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:14px;margin:14px 0">
            <div style="font-size:12px;font-weight:700;color:var(--accent2);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.05em">⚡ Overnight Price Fluctuation & Gap Analysis</div>
            <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:13px">
              <div><span style="color:var(--muted)">Prev Session Close:</span> <strong>₹${heroPrevClose ? heroPrevClose.toFixed(2) : '—'}</strong></div>
              <div><span style="color:var(--muted)">Pick Price (Open Entry):</span> <strong>₹${(TOP_PICK.ltp_at_pick || heroCurrentPrice).toFixed(2)}</strong></div>
              <div><span style="color:var(--muted)">Overnight Fluctuation:</span> <span class="badge ${heroGapCls}" style="font-weight:700">${heroGapHtml}</span></div>
            </div>
          </div>

          <!-- 🎯 7-Day Swing Trade Plan Card -->
          <div style="background:linear-gradient(135deg, rgba(16,185,129,0.1), rgba(108,99,255,0.1));border:1.5px solid var(--green);border-radius:14px;padding:16px;margin:14px 0;box-shadow:0 4px 16px rgba(16,185,129,0.15)">
            <div style="font-size:13px;font-weight:800;color:var(--green);margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
              <span>🎯 Recommended 7-Day Swing Trade Plan</span>
              <span class="badge badge-green" style="font-size:11px;font-weight:700">Timeframe: 3 to 7 Trading Days</span>
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;text-align:center">
              <div style="background:var(--card);border:1px solid var(--border);padding:10px;border-radius:10px">
                <div style="font-size:10px;color:var(--muted);text-transform:uppercase;font-weight:700">Suggested Entry</div>
                <div style="font-size:17px;font-weight:800;color:var(--white);margin-top:2px">₹${(TOP_PICK.ltp || TOP_PICK.ltp_at_pick || 0).toFixed(2)}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">Market Price / Breakout</div>
              </div>
              <div style="background:var(--card);border:1px solid var(--danger);padding:10px;border-radius:10px">
                <div style="font-size:10px;color:var(--danger);text-transform:uppercase;font-weight:700">Stop Loss (SL)</div>
                <div style="font-size:17px;font-weight:800;color:var(--danger);margin-top:2px">₹${TOP_PICK.stop_loss != null ? TOP_PICK.stop_loss.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--danger);margin-top:2px">${TOP_PICK.stop_loss_pct || 0}% Below Entry</div>
              </div>
              <div style="background:var(--card);border:1px solid var(--green);padding:10px;border-radius:10px">
                <div style="font-size:10px;color:var(--green);text-transform:uppercase;font-weight:700">Target 1 (1:1.5 R:R)</div>
                <div style="font-size:17px;font-weight:800;color:var(--green);margin-top:2px">₹${TOP_PICK.target1 != null ? TOP_PICK.target1.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--green);margin-top:2px">+${TOP_PICK.target1_pct || 0}% Upside</div>
              </div>
              <div style="background:var(--card);border:1px solid var(--purple);padding:10px;border-radius:10px">
                <div style="font-size:10px;color:var(--purple);text-transform:uppercase;font-weight:700">Target 2 (1:2.5 R:R)</div>
                <div style="font-size:17px;font-weight:800;color:var(--purple);margin-top:2px">₹${TOP_PICK.target2 != null ? TOP_PICK.target2.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--purple);margin-top:2px">+${TOP_PICK.target2_pct || 0}% Upside</div>
              </div>
            </div>
          </div>

          <!-- Technical Analysis Dashboard Grid -->
          <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px;margin:14px 0">
            <div style="font-size:12px;font-weight:700;color:var(--accent2);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.05em">⚡ Technical Analysis & Trend Setup</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px">
              <div class="modal-metric">
                <div class="lbl">50-Day MA</div>
                <div class="val">₹${TOP_PICK.ma50 != null ? TOP_PICK.ma50.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${TOP_PICK.dist_ma50_pct != null ? (TOP_PICK.dist_ma50_pct >= 0 ? '🟢 +' : '🔴 ') + TOP_PICK.dist_ma50_pct + '% vs 50MA' : '—'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">200-Day MA</div>
                <div class="val">₹${TOP_PICK.ma200 != null ? TOP_PICK.ma200.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${TOP_PICK.dist_ma200_pct != null ? (TOP_PICK.dist_ma200_pct >= 0 ? '🟢 +' : '🔴 ') + TOP_PICK.dist_ma200_pct + '% vs 200MA' : '—'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">RSI (14-Day)</div>
                <div class="val" style="color:var(--accent2)">${TOP_PICK.rsi != null ? TOP_PICK.rsi.toFixed(1) : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${TOP_PICK.rsi_status || 'Neutral'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">52W Channel</div>
                <div class="val">₹${TOP_PICK.week_high_52 != null ? TOP_PICK.week_high_52.toFixed(2) : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${TOP_PICK.dist_52w_high_pct != null ? TOP_PICK.dist_52w_high_pct + '% from High' : '—'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">Vol Spike</div>
                <div class="val">${TOP_PICK.volume_spike != null ? TOP_PICK.volume_spike.toFixed(2) + 'x' : '—'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">10d Avg Volume</div>
              </div>
            </div>
          </div>

          <!-- 🌊 Institutional Money Flow & Price Action Breakdown Card -->
          <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px;margin:14px 0">
            <div style="font-size:12px;font-weight:700;color:var(--accent2);margin-bottom:12px;text-transform:uppercase;letter-spacing:0.05em">🌊 Institutional Order Flow & Price Action Analysis</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px">
              <div class="modal-metric">
                <div class="lbl">Money Flow (CMF)</div>
                <div class="val" style="color:${(TOP_PICK.cmf || 0) >= 0.05 ? '#10b981' : (TOP_PICK.cmf || 0) <= -0.05 ? '#ef4444' : '#fbbf24'}">${TOP_PICK.cmf != null ? (TOP_PICK.cmf >= 0 ? '+' : '') + TOP_PICK.cmf.toFixed(3) : '0.000'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${(TOP_PICK.cmf || 0) >= 0.10 ? '🟢 Accumulation' : (TOP_PICK.cmf || 0) <= -0.10 ? '🔴 Distribution' : '🔵 Neutral Flow'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">Buyer Control (CLV)</div>
                <div class="val" style="color:${(TOP_PICK.clv || 0.5) >= 0.65 ? '#10b981' : '#a5b4fc'}">${TOP_PICK.clv != null ? Math.round((TOP_PICK.clv || 0.5) * 100) + '%' : '50%'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">${(TOP_PICK.clv || 0.5) >= 0.65 ? '🟢 Buyer Control' : '⚪ Neutral Close'}</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">Market Structure</div>
                <div class="val" style="font-size:13px;color:var(--white)">${TOP_PICK.market_structure || 'HH/HL Structure'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">20-Bar Trend</div>
              </div>
              <div class="modal-metric">
                <div class="lbl">Price Action Pattern</div>
                <div class="val" style="font-size:13px;color:var(--accent2)">${TOP_PICK.pa_pattern || 'No Key Trigger'}</div>
                <div style="font-size:10px;color:var(--muted);margin-top:2px">FVG / Rejection</div>
              </div>
            </div>
          </div>

          ${highlightsHtml ? `
          <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:14px;margin-top:14px">
            <div style="font-size:12px;font-weight:700;color:var(--accent2);margin-bottom:8px;text-transform:uppercase">Key Selection Thesis</div>
            <ul style="list-style:none;font-size:13px;color:var(--text)">${highlightsHtml}</ul>
          </div>
          ` : ''}

          <div style="display:flex;gap:12px;margin-top:18px">
            <button class="btn-add" onclick="addToWl('${TOP_PICK.symbol}')" ${inWl ? 'disabled' : ''} style="padding:10px 18px;font-size:13px">
              ${inWl ? '✓ In Watchlist' : '⭐ Add Today\'s Pick to Watchlist'}
            </button>
            <button class="btn-add" onclick="openModal('${TOP_PICK.symbol}')" style="background:var(--card2);border:1px solid var(--border);padding:10px 18px;font-size:13px">
              📊 Full Analysis
            </button>
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:12px">
          <div class="hero-score-ring">
            <div class="hero-score-val" style="color:${scoreColor(TOP_PICK.total_score)}">${TOP_PICK.total_score.toFixed(0)}</div>
            <div style="font-size:11px;color:var(--muted);margin-top:6px;text-transform:uppercase;letter-spacing:0.05em">Overall Quality Score</div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
            <div class="wl-score-box"><div class="val" style="color:${scoreColor(TOP_PICK.strength)}">${TOP_PICK.strength.toFixed(0)}</div><div class="lbl">Strength</div></div>
            <div class="wl-score-box"><div class="val" style="color:${scoreColor(TOP_PICK.value)}">${TOP_PICK.value.toFixed(0)}</div><div class="lbl">Value</div></div>
            <div class="wl-score-box"><div class="val" style="color:${scoreColor(TOP_PICK.momentum)}">${TOP_PICK.momentum.toFixed(0)}</div><div class="lbl">Momentum</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Daily Picks History Table -->
    <div style="margin-top:30px">
      <h3 style="font-size:16px;font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:8px">
        <span>📜</span><span>Daily Top Picks History & Performance</span>
      </h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date Stamp</th>
              <th>Stock Pick</th>
              <th>Status</th>
              <th>Score at Pick</th>
              <th>Entry Price (Open)</th>
              <th>Pick Day Close</th>
              <th>Current Price (LTP)</th>
              <th>Today's Change</th>
              <th>Total Return</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${historyRows || `<tr><td colspan="10" class="no-data">No historical picks recorded yet.</td></tr>`}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

// ── Score colour ──────────────────────────────────────────────────────────
function scoreColor(s) {
  if (s >= 70) return '#10b981';
  if (s >= 55) return '#6c63ff';
  if (s >= 40) return '#f59e0b';
  return '#ef4444';
}

function scoreBar(val, max=100) {
  const c = scoreColor(val);
  return `<div class="score-bar-wrap">
    <div class="score-bar"><div class="score-fill" style="width:${val}%;background:${c}"></div></div>
    <div class="score-num" style="color:${c}">${val.toFixed(0)}</div>
  </div>`;
}

function fmt(val, suffix='', dec=1) {
  if (val == null || val === undefined) return '<span class="neu">—</span>';
  const n = parseFloat(val);
  if (isNaN(n)) return '<span class="neu">—</span>';
  const cls = n > 0 ? 'pos' : n < 0 ? 'neg' : 'neu';
  return `<span class="${cls}">${n.toFixed(dec)}${suffix}</span>`;
}

// ── Screener table ────────────────────────────────────────────────────────
function onQualDropdownChange(val) {
  const scoreSlider = document.getElementById('fScore');
  if (!scoreSlider) return;
  if (val === 'all') {
    scoreSlider.value = 0;
  } else if (val === 'qualified') {
    scoreSlider.value = 55;
  } else if (val === 'watch') {
    scoreSlider.value = 45;
  }
}

// ── Screener table ────────────────────────────────────────────────────────
function populateSectorFilter() {
  const select = document.getElementById('fSector');
  if (!select) return;
  const currentVal = select.value || 'all';
  const sectors = Array.from(new Set(SCREENER_DATA.map(s => s.sector).filter(Boolean))).sort();
  select.innerHTML = '<option value="all">All Sectors</option>' +
    sectors.map(sec => `<option value="${sec}">${sec}</option>`).join('');
  select.value = currentVal;
}

const STOCK_SEARCH_ALIASES = {
  "SEKURITIND": ["saint gobain", "saint goban", "saint-gobain", "saintgobain", "saintgoban", "sekurit", "saint gobain glass", "saint goban glasses", "auto glass", "safety glass", "glass", "glasses"],
  "BORANA": ["borosil", "glassware", "borosil glass"],
  "NATIONALUM": ["nalco", "aluminium"],
  "TATAMOTORS": ["tmo", "tata motors", "jaguar", "jlr"],
  "M&M": ["mahindra", "mahindra & mahindra"],
  "RELIANCE": ["ril", "jio"],
  "BAJFINANCE": ["bajaj finance"],
  "BAJAJFINSV": ["bajaj finserv"],
  "HDFCBANK": ["hdfc bank"],
  "ICICIBANK": ["icici bank"],
  "SBIN": ["sbi", "state bank"],
  "BHARTIARTL": ["airtel", "bharti airtel"]
};

function normStr(str) {
  return (str || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function matchSearch(stock, rawQuery) {
  if (!rawQuery || rawQuery.trim().length === 0) return true;
  const qNorm = normStr(rawQuery);
  if (!qNorm) return true;

  const symNorm  = normStr(stock.symbol);
  const nameNorm = normStr(stock.name);
  const secNorm  = normStr(stock.sector);

  if (symNorm.includes(qNorm) || nameNorm.includes(qNorm) || secNorm.includes(qNorm)) return true;

  const aliases = STOCK_SEARCH_ALIASES[stock.symbol] || stock.aliases || [];
  if (aliases.some(a => normStr(a).includes(qNorm) || qNorm.includes(normStr(a)))) return true;

  const rawTokens = rawQuery.toLowerCase().split(/\s+/).map(t => normStr(t)).filter(Boolean);
  if (rawTokens.length > 0) {
    const aliasStr = aliases.map(a => normStr(a)).join(' ');
    const combinedTarget = (symNorm + ' ' + nameNorm + ' ' + secNorm + ' ' + aliasStr).toLowerCase();

    const normToken = (t) => {
      if (t === 'goban') return 'gobain';
      if (t === 'glasses') return 'glass';
      return t;
    };

    return rawTokens.every(t => {
      const nt = normToken(t);
      if (combinedTarget.includes(t) || combinedTarget.includes(nt)) return true;
      if (['glass', 'glasses', 'ltd', 'limited', 'india', 'co', 'inc', 'corp', 'corporation'].includes(t)) return true;
      return false;
    });
  }
  return false;
}

function applyFilters() {
  const search   = document.getElementById('fSearch').value.trim();
  const qual     = document.getElementById('fQual').value;
  const sector   = document.getElementById('fSector') ? document.getElementById('fSector').value : 'all';
  const mcap     = document.getElementById('fMcap') ? document.getElementById('fMcap').value : 'all';
  const trend    = document.getElementById('fTrend').value;

  filteredData = SCREENER_DATA.filter(s => {
    if (!search && qual === 'qualified' && !s.qualified) return false;
    if (!search && qual === 'watch' && s.total_score < 45) return false;

    if (search && !matchSearch(s, search)) return false;

    if (sector !== 'all' && s.sector !== sector) return false;

    if (mcap !== 'all') {
      const mc = s.market_cap || 0;
      if (mcap === 'large' && mc < 200000000000) return false;
      if (mcap === 'mid' && (mc < 50000000000 || mc >= 200000000000)) return false;
      if (mcap === 'small' && (mc <= 0 || mc >= 50000000000)) return false;
    }

    if (trend === 'uptrend_downtrend') {
      const keep = (TREND_CONFIG.uptrend || []).concat([TREND_CONFIG.downtrend]);
      if (!keep.includes(s.trend)) return false;
    } else if (trend !== 'all' && s.trend !== trend) {
      return false;
    }
    return true;
  });

  filteredData.sort((a,b) => sortDir * ((a[sortCol]??-999) - (b[sortCol]??-999)));
  renderTable();
  document.getElementById('resultCount').textContent = `Showing ${filteredData.length} stocks`;

  renderSearchQuickView(search);
}

function renderSearchQuickView(search) {
  const container = document.getElementById('searchQuickView');
  if (!container) return;

  if (!search || search.length < 2) {
    container.innerHTML = '';
    return;
  }

  const qNorm = normStr(search);
  const match = SCREENER_DATA.find(s => normStr(s.symbol) === qNorm) ||
                SCREENER_DATA.find(s => normStr(s.symbol).startsWith(qNorm)) ||
                SCREENER_DATA.find(s => matchSearch(s, search));

  if (!match) {
    container.innerHTML = `
      <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px 18px;font-size:13px;color:var(--muted);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px">
        <div>🔍 No local match for "<strong>${search}</strong>" in current Nifty universe.</div>
        <button onclick="openAddLtStockModal()" style="background:linear-gradient(135deg,#6c63ff,#00d4aa);color:#fff;border:none;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer">➕ Search &amp; Add "${search.toUpperCase()}" via Yahoo Finance</button>
      </div>`;
    return;
  }

  const inWl = watchlist.some(w => w.symbol === match.symbol);
  const trendBadge = match.tech_rating || '🟡 Consolidating Trend';

  container.innerHTML = `
    <div style="background:linear-gradient(135deg,#0e0e24,#151535);border:1.5px solid var(--accent);border-radius:14px;padding:16px 20px;box-shadow:0 8px 24px rgba(108,99,255,0.25);margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
        <div>
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:20px;font-weight:800;color:var(--white)">${match.symbol}</span>
            <span style="font-size:13px;color:var(--muted)">— ${match.name||''}</span>
            <span class="badge ${match.tech_class || 'badge-green'}" style="font-weight:700">${trendBadge}</span>
          </div>
          <div style="font-size:12px;color:var(--accent2);margin-top:2px">${match.sector||''}</div>
        </div>
        <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
          <div>
            <div style="font-size:10px;color:var(--muted);text-transform:uppercase">LTP Price</div>
            <div style="font-size:22px;font-weight:800;color:var(--white)">₹${match.ltp.toFixed(2)}</div>
          </div>
          <div>
            <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Total Score</div>
            <div style="font-size:22px;font-weight:800;color:${scoreColor(match.total_score)}">${match.total_score.toFixed(0)} <span style="font-size:11px;font-weight:400;color:var(--muted)">/ 100</span></div>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn-add" onclick="openModal('${match.symbol}')" style="padding:8px 14px;font-size:12px">📊 Full Metrics & Analysis</button>
            <button class="btn-add" onclick="addToWl('${match.symbol}')" ${inWl?'disabled':''} style="background:var(--card2);border:1px solid var(--border);padding:8px 14px;font-size:12px">
              ${inWl ? '✓ In Watchlist' : '+ Add to Watchlist'}
            </button>
          </div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:12px">
        <div><span style="color:var(--muted)">Strength:</span> <strong style="color:${scoreColor(match.strength)}">${match.strength.toFixed(0)}</strong></div>
        <div><span style="color:var(--muted)">Value:</span> <strong style="color:${scoreColor(match.value)}">${match.value.toFixed(0)}</strong></div>
        <div><span style="color:var(--muted)">Momentum:</span> <strong style="color:${scoreColor(match.momentum)}">${match.momentum.toFixed(0)}</strong></div>
        <div><span style="color:var(--muted)">ROE:</span> <strong>${match.roe_pct != null ? match.roe_pct.toFixed(1) + '%' : '—'}</strong></div>
        <div><span style="color:var(--muted)">D/E Ratio:</span> <strong>${match.de_ratio != null ? match.de_ratio.toFixed(2) : '—'}</strong></div>
        <div><span style="color:var(--muted)">RSI (14):</span> <strong>${match.rsi != null ? match.rsi.toFixed(0) : '—'}</strong></div>
        <div><span style="color:var(--muted)">52W Return:</span> <strong>${match.wk52_return_pct != null ? (match.wk52_return_pct >= 0 ? '+' : '') + match.wk52_return_pct.toFixed(1) + '%' : '—'}</strong></div>
        <div><span style="color:var(--muted)">Vol Spike:</span> <strong>${match.volume_spike != null ? match.volume_spike.toFixed(2) + 'x' : '—'}</strong></div>
      </div>
    </div>`;
}

function resetFilters() {
  if (document.getElementById('fSearch')) document.getElementById('fSearch').value = '';
  if (document.getElementById('fQual')) document.getElementById('fQual').value = 'all';
  if (document.getElementById('fSector')) document.getElementById('fSector').value = 'all';
  if (document.getElementById('fMcap')) document.getElementById('fMcap').value = 'all';
  if (document.getElementById('fTrend')) document.getElementById('fTrend').value = 'all';
  applyFilters();
}

function sortTable(col) {
  if (sortCol === col) sortDir *= -1;
  else { sortCol = col; sortDir = -1; }
  document.querySelectorAll('th').forEach(th => {
    th.classList.remove('sorted-asc','sorted-desc');
    if (th.textContent.replace(/ [↑↓↕]/,'').trim().toLowerCase().replace(/\s/g,'_') === col) {
      th.classList.add(sortDir === -1 ? 'sorted-desc' : 'sorted-asc');
    }
  });
  filteredData.sort((a,b) => {
    let av = a[sortCol];
    let bv = b[sortCol];
    if (av === undefined || av === null) av = (typeof bv === 'string' ? '' : -999999);
    if (bv === undefined || bv === null) bv = (typeof av === 'string' ? '' : -999999);
    if (typeof av === 'string' || typeof bv === 'string') {
      return sortDir * String(av).localeCompare(String(bv));
    }
    return sortDir * (av - bv);
  });
  renderTable();
}

function renderTable() {
  const inWl = new Set(watchlist.map(w=>w.symbol));
  const maxSlots = CONFIG.max_stocks;
  const totalItems = filteredData.length;

  let effectiveSize = (pageSize === 'all') ? totalItems : parseInt(pageSize || 50);
  const totalPages = Math.max(1, Math.ceil(totalItems / (effectiveSize || 1)));

  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;

  const startIdx = (pageSize === 'all') ? 0 : (currentPage - 1) * effectiveSize;
  const endIdx = (pageSize === 'all') ? totalItems : Math.min(totalItems, startIdx + effectiveSize);
  const pagedData = filteredData.slice(startIdx, endIdx);

  const infoEl = document.getElementById('paginationInfo');
  if (infoEl) {
    infoEl.textContent = totalItems === 0
      ? 'No stocks match current filter'
      : `Showing ${startIdx + 1}-${endIdx} of ${totalItems} stocks`;
  }

  const numbersEl = document.getElementById('pageNumbers');
  if (numbersEl) {
    numbersEl.textContent = `Page ${currentPage} of ${totalPages}`;
  }

  const prevBtn = document.getElementById('btnPrevPage');
  const nextBtn = document.getElementById('btnNextPage');
  if (prevBtn) prevBtn.disabled = (currentPage <= 1);
  if (nextBtn) nextBtn.disabled = (currentPage >= totalPages);

  const body = pagedData.map(s => {
    const inWlSet = inWl.has(s.symbol);
    const full = watchlist.length >= maxSlots && !inWlSet;
    const badge = s.qualified
      ? `<span class="badge badge-green">🟢 Qualified</span>`
      : s.total_score >= 45
        ? `<span class="badge badge-yellow">🟡 Watch</span>`
        : `<span class="badge badge-red">🔴 Avoid</span>`;

    const rsVal = s.rs_rating || 50;
    const rsBadge = `<span class="badge ${rsVal>=80?'badge-green':rsVal>=60?'badge-green':rsVal>=40?'badge-gray':'badge-red'}" style="font-size:11px;font-weight:700">RS ${rsVal}</span>`;

    return `<tr data-symbol="${s.symbol}" data-ticker="${s.ticker || (s.symbol + '.NS')}">
      <td>
        <div class="stock-name">${s.symbol}</div>
        <div class="stock-sym">${s.name||''}</div>
        <div class="stock-sector">${s.sector||''}</div>
      </td>
      <td><span class="price">₹${s.ltp.toFixed(2)}</span></td>
      <td>${scoreBar(s.total_score)}</td>
      <td>${rsBadge}</td>
      <td>${scoreBar(s.strength)}</td>
      <td>${scoreBar(s.value)}</td>
      <td>${scoreBar(s.momentum)}</td>
      <td>${fmt(s.pe,'',1)}</td>
      <td>${fmt(s.roe_pct,'%')}</td>
      <td>${fmt(s.de_ratio,'',2)}</td>
      <td>${fmt(s.npm_pct,'%')}</td>
      <td>${fmt(s.wk52_return_pct,'%')}</td>
      <td>${fmt(s.rsi,'',0)}</td>
      <td>${s.volume_spike != null ? fmt(s.volume_spike, 'x', 2) : fmt(null)}</td>
      <td><span class="badge ${s.pa_class || 'badge-gray'}" style="font-size:10px;white-space:nowrap" title="${s.pa_pattern || ''}">${s.pa_badge || '⚪ Neutral Flow'}</span></td>
      <td><span class="badge ${s.tech_class || 'badge-yellow'}" style="font-size:11px;white-space:nowrap" title="${s.tech_trend || ''}">${s.tech_rating || s.tech_badge || '🟡 Rangebound'}</span></td>
      <td>${badge}</td>
      <td>
        <button class="btn btn-sm ${inWlSet ? 'btn-danger' : 'btn-primary'}"
                onclick="toggleWatchlist('${s.symbol}')"
                ${full ? 'disabled title="Watchlist is full (20/20)"' : ''}>
          ${inWlSet ? '✓ Added' : '+ Add'}
        </button>
      </td>
    </tr>`;
  }).join('');

  const targetBody = document.getElementById('screenerBody') || document.getElementById('screenerTableBody');
  if (targetBody) targetBody.innerHTML = body;

  const countEl = document.getElementById('resultCount');
  if (countEl) {
    countEl.textContent = `Showing ${totalItems} stock${totalItems !== 1 ? 's' : ''}`;
  }
}

function changePage(delta) {
  currentPage += delta;
  renderTable();
}

function changePageSize(val) {
  pageSize = val;
  currentPage = 1;
  renderTable();
}

function addToWl(symbol) {
  if (watchlist.length >= CONFIG.max_stocks) {
    alert('Phase 1 limit reached: 20 stocks maximum.');
    return;
  }
  const s = SCREENER_DATA.find(x=>x.symbol===symbol);
  if (!s) return;
  if (watchlist.find(w=>w.symbol===symbol)) return;

  watchlist.push({
    symbol: s.symbol,
    ticker: s.ticker,
    name: s.name,
    qty: 0,
    avg_cost: null,
    total_invested: 0,
    added_at: new Date().toISOString().slice(0,10),
    score_at_entry: s.total_score,
    strength_at_entry: s.strength,
    value_at_entry: s.value,
    momentum_at_entry: s.momentum,
    roe_at_entry: s.roe_pct,
    de_at_entry: s.de_ratio,
    npm_at_entry: s.npm_pct,
    current_score: s.total_score,
    current_strength: s.strength,
    current_value: s.value,
    current_momentum: s.momentum,
    ltp: s.ltp,
    sector: s.sector,
    roe_pct: s.roe_pct,
    de_ratio: s.de_ratio,
    npm_pct: s.npm_pct,
    rsi: s.rsi,
    wk52_return_pct: s.wk52_return_pct,
    volume_spike: s.volume_spike,
    today_volume: s.today_volume,
    avg_volume_10d: s.avg_volume_10d,
    news: s.news || [],
    alerts: []
  });
  saveWatchlist();
  updateWlCount();
  renderTable();
  renderStats();
  alert(`✅ ${symbol} added to watchlist!`);
}

function removeFromWl(symbol) {
  if (!confirm(`Remove ${symbol} from watchlist?`)) return;
  watchlist = watchlist.filter(w=>w.symbol!==symbol);
  saveWatchlist();
  updateWlCount();
  renderWatchlist();
  renderStats();
}

function adjustQty(symbol, delta) {
  const item = watchlist.find(w => w.symbol === symbol);
  if (!item) return;
  const currentQty = item.qty || 1;
  const newQty = currentQty + delta;
  if (newQty <= 0) {
    removeFromWl(symbol);
    return;
  }
  item.qty = newQty;
  const avg = item.avg_cost || item.ltp || 0;
  item.total_invested = Math.round(avg * newQty * 100) / 100;
  if (item.ltp && avg) {
    item.unrealised_pnl = Math.round((item.ltp - avg) * newQty * 100) / 100;
    item.unrealised_pct = Math.round(((item.ltp - avg) / avg) * 10000) / 100;
    item.current_value = Math.round(item.ltp * newQty * 100) / 100;
  }
  saveWatchlist();
  renderWatchlist();
  renderStats();
}

function editQtyModal(symbol) {
  const item = watchlist.find(w => w.symbol === symbol);
  if (!item) return;
  const currentQty = item.qty || 1;
  const currentAvg = item.avg_cost ? item.avg_cost.toFixed(2) : (item.ltp ? item.ltp.toFixed(2) : '0.00');

  const newQtyStr = prompt(`Edit Quantity held for ${symbol}:`, currentQty);
  if (newQtyStr === null) return;
  const newQty = parseInt(newQtyStr, 10);
  if (isNaN(newQty) || newQty <= 0) {
    if (confirm(`Set quantity to 0? This will remove ${symbol} from watchlist.`)) {
      removeFromWl(symbol);
    }
    return;
  }

  const newAvgStr = prompt(`Edit Average Buy Price (₹) for ${symbol}:`, currentAvg);
  if (newAvgStr === null) return;
  const newAvg = parseFloat(newAvgStr);
  if (isNaN(newAvg) || newAvg <= 0) return;

  item.qty = newQty;
  item.avg_cost = newAvg;
  item.total_invested = Math.round(newAvg * newQty * 100) / 100;
  if (item.ltp) {
    item.unrealised_pnl = Math.round((item.ltp - newAvg) * newQty * 100) / 100;
    item.unrealised_pct = Math.round(((item.ltp - newAvg) / newAvg) * 10000) / 100;
    item.current_value = Math.round(item.ltp * newQty * 100) / 100;
  }
  saveWatchlist();
  renderWatchlist();
  renderStats();
  alert(`✅ Updated ${symbol}: ${newQty} shares @ ₹${newAvg.toFixed(2)} (Total Invested: ₹${item.total_invested.toLocaleString()})`);
}

function updateWlCount() {
  document.getElementById('wlCount').textContent = watchlist.length;
}

let currentWlSignalFilter = 'ALL';

function filterWlSignal(sig) {
  currentWlSignalFilter = sig;
  ['ALL', 'BUY', 'HOLD', 'SELL'].forEach(s => {
    const btn = document.getElementById('wlSigBtn' + s);
    if (btn) {
      const active = (s === sig);
      btn.style.fontWeight = active ? '700' : '400';
      btn.style.borderWidth = active ? '2px' : '1px';
    }
  });
  renderWatchlist();
}

let wlViewMode = 'cards';
let wlSortCol = 'current_score';
let wlSortDir = -1; // -1 for desc, 1 for asc

function sortWlTable(col) {
  if (wlSortCol === col) {
    wlSortDir *= -1;
  } else {
    wlSortCol = col;
    if (col === 'symbol' || col === 'signal') {
      wlSortDir = 1;
    } else {
      wlSortDir = -1;
    }
  }
  renderWatchlist();
}

function setWlViewMode(mode) {
  wlViewMode = mode;
  const cardsBtn = document.getElementById('wlViewCardsBtn');
  const tableBtn = document.getElementById('wlViewTableBtn');
  const grid = document.getElementById('watchlistGrid');
  const tableWrap = document.getElementById('watchlistTableWrap');

  if (cardsBtn && tableBtn) {
    if (mode === 'cards') {
      cardsBtn.style.background = 'var(--accent)';
      cardsBtn.style.color = '#fff';
      tableBtn.style.background = 'none';
      tableBtn.style.color = 'var(--muted)';
      if (grid) grid.style.display = 'grid';
      if (tableWrap) tableWrap.style.display = 'none';
    } else {
      tableBtn.style.background = 'var(--accent)';
      tableBtn.style.color = '#fff';
      cardsBtn.style.background = 'none';
      cardsBtn.style.color = 'var(--muted)';
      if (grid) grid.style.display = 'none';
      if (tableWrap) tableWrap.style.display = 'block';
    }
  }
  renderWatchlist();
}

function renderWatchlist() {
  const grid = document.getElementById('watchlistGrid');
  const tableWrap = document.getElementById('watchlistTableWrap');
  const tableBody = document.getElementById('watchlistTableBody');
  const empty = document.getElementById('wlEmpty');
  const slotsEl = document.getElementById('slotsUsed');
  const fillEl = document.getElementById('slotFill');
  const invEl = document.getElementById('totalInvested');

  const totalInv = watchlist.reduce((a,w)=>a+(w.total_invested||0),0);
  if (slotsEl) slotsEl.textContent = watchlist.length;
  if (fillEl) fillEl.style.width = (watchlist.length/CONFIG.max_stocks*100)+'%';
  if (invEl) invEl.textContent = Math.round(totalInv).toLocaleString();

  // Summary Banner P&L & Signals
  let totPnl = 0;
  let totCost = 0;
  let cntBuy = 0, cntHold = 0, cntSell = 0;

  watchlist.forEach(w => {
    const activeSig = w.signal || 'HOLD';
    if (activeSig === 'BUY') cntBuy++;
    else if (activeSig === 'SELL') cntSell++;
    else cntHold++;

    if (w.avg_cost && w.ltp && w.qty > 0) {
      totPnl += (w.ltp - w.avg_cost) * w.qty;
      totCost += w.avg_cost * w.qty;
    }
  });

  const pnlEl = document.getElementById('wlPortfolioPnl');
  const pnlPctEl = document.getElementById('wlPortfolioPnlPct');
  const countsEl = document.getElementById('wlSignalCounts');

  if (pnlEl) {
    pnlEl.innerHTML = `<span class="${totPnl >= 0 ? 'pos' : 'neg'}">${totPnl >= 0 ? '+' : ''}₹${totPnl.toFixed(2)}</span>`;
  }
  if (pnlPctEl) {
    const pct = totCost > 0 ? (totPnl / totCost) * 100 : 0;
    pnlPctEl.innerHTML = `<span class="${totPnl >= 0 ? 'pos' : 'neg'}">${totPnl >= 0 ? '+' : ''}${pct.toFixed(2)}%</span>`;
  }
  if (countsEl) {
    countsEl.innerHTML = `<span style="color:var(--green)">🟢 ${cntBuy} BUY</span> <span style="color:var(--warn)">🟡 ${cntHold} HOLD</span> <span style="color:var(--danger)">🔴 ${cntSell} SELL</span>`;
  }

  // Update Watchlist Table Header Sort Arrows
  ['symbol', 'signal', 'ltp', 'unrealised_pnl', 'current_score', 'current_strength', 'roe_pct', 'de_ratio', 'rsi'].forEach(c => {
    const el = document.getElementById('wlSort_' + c);
    if (el) {
      if (wlSortCol === c) {
        el.innerHTML = wlSortDir === -1 ? ' <b style="color:var(--accent2)">▼</b>' : ' <b style="color:var(--accent2)">▲</b>';
      } else {
        el.innerHTML = ' <span style="opacity:0.35;font-size:10px">↕</span>';
      }
    }
  });

  let itemsToDisplay = watchlist;
  if (currentWlSignalFilter !== 'ALL') {
    itemsToDisplay = watchlist.filter(w => {
      const activeSig = w.signal || 'HOLD';
      return activeSig === currentWlSignalFilter;
    });
  }

  // Sort Watchlist items by selected column header
  itemsToDisplay = itemsToDisplay.slice().sort((a, b) => {
    let va = a[wlSortCol];
    let vb = b[wlSortCol];

    if (wlSortCol === 'signal') {
      const sigOrder = { 'BUY': 1, 'HOLD': 2, 'SELL': 3 };
      va = sigOrder[a.signal || 'HOLD'] || 9;
      vb = sigOrder[b.signal || 'HOLD'] || 9;
    } else if (wlSortCol === 'unrealised_pnl') {
      va = (a.avg_cost && a.ltp && a.qty > 0) ? ((a.ltp - a.avg_cost) * a.qty) : -9999999;
      vb = (b.avg_cost && b.ltp && b.qty > 0) ? ((b.ltp - b.avg_cost) * b.qty) : -9999999;
    }

    if (va == null) va = (wlSortDir === 1 ? 'ZZZZZZ' : -9999999);
    if (vb == null) vb = (wlSortDir === 1 ? 'ZZZZZZ' : -9999999);

    if (typeof va === 'string' && typeof vb === 'string') {
      return wlSortDir * va.localeCompare(vb);
    }
    return wlSortDir * (va - vb);
  });

  if (itemsToDisplay.length === 0) {
    if (grid) grid.innerHTML = '';
    if (tableBody) tableBody.innerHTML = '';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  if (wlViewMode === 'cards') {
    if (grid) grid.style.display = 'grid';
    if (tableWrap) tableWrap.style.display = 'none';

    if (grid) {
      grid.innerHTML = itemsToDisplay.map(w => {
        const hasAlert = w.alerts && w.alerts.length > 0;
        const scoreChange = w.score_at_entry != null ? (w.current_score - w.score_at_entry).toFixed(1) : null;
        const scCls = scoreChange > 0 ? 'pos' : scoreChange < 0 ? 'neg' : 'neu';

        const pnl = w.avg_cost && w.ltp && w.qty > 0 ? ((w.ltp - w.avg_cost) * w.qty) : null;
        const pnlPct = w.avg_cost && w.ltp ? ((w.ltp - w.avg_cost)/w.avg_cost*100) : null;

        const activeSig = w.custom_signal || w.signal || 'HOLD';
        const sigBadge = activeSig === 'BUY' ? '🟢 BUY' : activeSig === 'SELL' ? '🔴 SELL' : '🟡 HOLD';
        const sigClass = activeSig === 'BUY' ? 'badge-green' : activeSig === 'SELL' ? 'badge-red' : 'badge-yellow';
        const sigReason = w.signal_reason || '';

        const alertsHtml = (w.alerts||[]).map(a =>
          `<div class="alert-row alert-${a.level}"><span>${a.icon}</span><span>${a.message}</span></div>`
        ).join('');

        return `<div class="wl-card ${hasAlert?'has-alert':''}" style="padding:18px">
          <div class="wl-header" style="margin-bottom:12px">
            <div>
              <div style="display:flex;align-items:center;gap:8px">
                <div class="wl-sym">${w.symbol}</div>
                <span class="badge ${sigClass}" style="font-weight:700;font-size:11px">${sigBadge}</span>
              </div>
              <div class="wl-name">${w.name||''}</div>
              <div class="wl-name" style="margin-top:2px;color:var(--accent2);font-size:11px">${w.sector||''} ${sigReason ? '· ' + sigReason : ''}</div>
              <div onclick="editQtyModal('${w.symbol}')" title="Click to edit quantity or buy price for ${w.symbol}" style="display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--muted);margin-top:6px;background:var(--card2);padding:4px 8px;border-radius:6px;border:1px solid #6c63ff44;cursor:pointer;user-select:none" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='#6c63ff44'">
                <span>Holdings:</span>
                <button onclick="event.stopPropagation();adjustQty('${w.symbol}', -1)" title="Decrease Quantity" style="padding:0 6px;height:18px;line-height:16px;border-radius:3px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-weight:700;font-size:11px">-</button>
                <b style="color:var(--white);font-weight:700">${w.qty||1} Qty</b>
                <button onclick="event.stopPropagation();adjustQty('${w.symbol}', 1)" title="Increase Quantity" style="padding:0 6px;height:18px;line-height:16px;border-radius:3px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-weight:700;font-size:11px">+</button>
                <span>@ <b style="color:var(--white)">₹${w.avg_cost?w.avg_cost.toFixed(2):'0.00'}</b></span>
                <span style="color:#a5b4fc;font-weight:600;font-size:10px;margin-left:2px">✏️ Edit</span>
              </div>
            </div>
            <div style="text-align:right">
              <div class="wl-ltp">${w.ltp?'₹'+w.ltp.toFixed(2):'—'}</div>
              ${pnl!=null?`<div class="wl-pnl ${pnl>=0?'pos':'neg'}" style="font-size:12px">${pnl>=0?'+':''}₹${pnl.toFixed(2)} (${pnlPct.toFixed(2)}%)</div>`:''}
            </div>
          </div>

          <div style="display:flex;align-items:center;justify-content:space-between;background:var(--card2);padding:10px 14px;border-radius:10px;border:1px solid var(--border);margin-bottom:12px">
            <div>
              <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Quality Score</div>
              <div style="font-size:20px;font-weight:800;color:${scoreColor(w.current_score||0)}">${(w.current_score||0).toFixed(0)} <span style="font-size:11px;font-weight:400;color:var(--muted)">/ 100</span></div>
            </div>
            <div style="text-align:center">
              <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Strength</div>
              <div style="font-size:15px;font-weight:700;color:${scoreColor(w.current_strength||0)}">${(w.current_strength||0).toFixed(0)}</div>
            </div>
            <div style="text-align:center">
              <div style="font-size:10px;color:var(--muted);text-transform:uppercase">Momentum</div>
              <div style="font-size:15px;font-weight:700;color:${scoreColor(w.current_momentum||0)}">${(w.current_momentum||0).toFixed(0)}</div>
            </div>
          </div>

          ${alertsHtml?`<div class="wl-alerts" style="margin-bottom:12px">${alertsHtml}</div>`:''}

          <!-- Collapsible Details & Metrics Drawer -->
          <details style="margin-bottom:12px;cursor:pointer">
            <summary style="font-size:12px;font-weight:600;color:var(--accent2);outline:none;user-select:none;padding:4px 0">
              🔍 Details & Metrics (ROE, D/E, RSI, News)
            </summary>
            <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
              ${scoreChange!=null?`<div style="font-size:11px;color:var(--muted);margin-bottom:8px">
                Score since entry: <span class="${scCls}" style="font-weight:600">${scoreChange>0?'+':''}${scoreChange} pts</span> (Entry: ${w.score_at_entry})
              </div>`:''}

              <div class="wl-metrics">
                <div class="wl-metric"><span>ROE</span><span>${w.roe_pct!=null?w.roe_pct.toFixed(1)+'%':'—'}</span></div>
                <div class="wl-metric"><span>D/E</span><span>${w.de_ratio!=null?w.de_ratio.toFixed(2):'—'}</span></div>
                <div class="wl-metric"><span>Margin</span><span>${w.npm_pct!=null?w.npm_pct.toFixed(1)+'%':'—'}</span></div>
                <div class="wl-metric"><span>RSI</span><span>${w.rsi!=null?w.rsi.toFixed(0):'—'}</span></div>
                <div class="wl-metric"><span>52W Ret</span><span>${w.wk52_return_pct!=null?w.wk52_return_pct.toFixed(1)+'%':'—'}</span></div>
                <div class="wl-metric"><span>Vol Spike</span><span>${w.volume_spike!=null?w.volume_spike.toFixed(2)+'x':'—'}</span></div>
                <div class="wl-metric"><span>Qty</span><span>${w.qty||0} shares</span></div>
              </div>

              ${(w.news && w.news.length > 0) ? `
              <div style="margin-top:8px">
                <div style="font-size:11px;font-weight:600;color:var(--muted);margin-bottom:6px">📰 Related News</div>
                <div style="display:flex;flex-direction:column;gap:6px;max-height:120px;overflow-y:auto">
                  ${w.news.slice(0, 2).map(n => `
                    <div style="background:var(--card2);padding:6px 8px;border-radius:6px;font-size:11px;border:1px solid var(--border)">
                      <a href="${n.url}" target="_blank" style="color:var(--text);text-decoration:none;font-weight:500;display:block;line-height:1.3">
                        ${n.title}
                      </a>
                    </div>
                  `).join('')}
                </div>
              </div>
              ` : ''}
            </div>
          </details>

          <div class="wl-footer" style="justify-content:flex-end">
            <div style="display:flex;gap:6px">
              <button class="btn-add" onclick="openModal('${w.symbol}')" style="padding:4px 10px;font-size:11px">Analysis</button>
              <button class="btn-remove" onclick="removeFromWl('${w.symbol}')">Remove</button>
            </div>
          </div>
        </div>`;
      }).join('');
    }
  } else {
    // Table View
    if (grid) grid.style.display = 'none';
    if (tableWrap) tableWrap.style.display = 'block';

    if (tableBody) {
      tableBody.innerHTML = itemsToDisplay.map(w => {
        const pnl = w.avg_cost && w.ltp && w.qty > 0 ? ((w.ltp - w.avg_cost) * w.qty) : null;
        const pnlPct = w.avg_cost && w.ltp ? ((w.ltp - w.avg_cost)/w.avg_cost*100) : null;
        const activeSig = w.signal || 'HOLD';
        const sigBadge = activeSig === 'BUY' ? '🟢 BUY' : activeSig === 'SELL' ? '🔴 SELL' : '🟡 HOLD';
        const sigClass = activeSig === 'BUY' ? 'badge-green' : activeSig === 'SELL' ? 'badge-red' : 'badge-yellow';

        return `<tr>
          <td>
            <div style="font-weight:700">${w.symbol}</div>
            <div style="font-size:11px;color:var(--muted)">${w.name||''}</div>
          </td>
          <td><span class="badge ${sigClass}" style="font-weight:700">${sigBadge}</span></td>
          <td><span class="price">₹${w.ltp ? w.ltp.toFixed(2) : '—'}</span></td>
          <td>${pnl != null ? `<span class="${pnl>=0?'pos':'neg'}" style="font-weight:700">${pnl>=0?'+':''}₹${pnl.toFixed(2)} (${pnlPct.toFixed(2)}%)</span>` : '—'}</td>
          <td>${scoreBar(w.current_score||0)}</td>
          <td>${scoreBar(w.current_strength||0)}</td>
          <td>${fmt(w.roe_pct, '%')}</td>
          <td>${fmt(w.de_ratio, '', 2)}</td>
          <td>${fmt(w.rsi, '', 0)}</td>
          <td>
            <button onclick="editQtyModal('${w.symbol}')" title="Edit Quantity & Buy Price" style="padding:4px 8px;font-size:11px;margin-right:4px;border-radius:4px;border:1px solid #6c63ff55;background:linear-gradient(135deg,#6c63ff22,#00d4aa22);color:#a5b4fc;cursor:pointer;font-weight:600">✏️ Qty</button>
            <button class="btn-add" onclick="openModal('${w.symbol}')" style="padding:4px 8px;font-size:11px;margin-right:4px">Detail</button>
            <button class="btn-remove" onclick="removeFromWl('${w.symbol}')" style="padding:4px 8px;font-size:11px">✕</button>
          </td>
        </tr>`;
      }).join('');
    }
  }
}

// ── Detail Modal ──────────────────────────────────────────────────────────
function openModal(symbol) {
  const s = SCREENER_DATA.find(x=>x.symbol===symbol);
  if (!s) return;
  const inWl = watchlist.find(w=>w.symbol===symbol);
  const maxFull = watchlist.length >= CONFIG.max_stocks && !inWl;

  document.getElementById('modal').innerHTML = `
    <button class="modal-close" onclick="closeModal()">✕</button>
    <h3>${s.symbol}</h3>
    <div style="color:var(--muted);font-size:13px;margin-bottom:4px">${s.name||''} · ${s.sector||''}</div>
    <div style="font-size:22px;font-weight:700;margin:8px 0">₹${s.ltp.toFixed(2)}</div>

    <div style="margin:12px 0">
      <div style="display:flex;gap:12px;margin-bottom:8px">
        ${['Total Score','Strength','Value','Momentum'].map((l,i)=>{
          const v=[s.total_score,s.strength,s.value,s.momentum][i];
          return `<div style="flex:1;background:var(--card2);border-radius:8px;padding:10px;text-align:center">
            <div style="font-size:20px;font-weight:700;color:${scoreColor(v)}">${v.toFixed(0)}</div>
            <div style="font-size:10px;color:var(--muted);margin-top:2px">${l}</div>
          </div>`;
        }).join('')}
      </div>
    </div>

    <div class="modal-grid">
      <div class="modal-metric"><div class="lbl">ROE</div><div class="val">${s.roe_pct!=null?s.roe_pct.toFixed(1)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">ROCE (est.)</div><div class="val">${s.roce_pct!=null?s.roce_pct.toFixed(1)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Debt / Equity</div><div class="val">${s.de_ratio!=null?s.de_ratio.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Net Margin</div><div class="val">${s.npm_pct!=null?s.npm_pct.toFixed(1)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Revenue Growth</div><div class="val">${s.rev_growth_pct!=null?s.rev_growth_pct.toFixed(1)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">P/E (TTM)</div><div class="val">${s.pe!=null?s.pe.toFixed(1):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Div Yield</div><div class="val">${s.div_yield_pct!=null?s.div_yield_pct.toFixed(2)+'%':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">RSI (14-day)</div><div class="val">${s.rsi!=null?s.rsi.toFixed(0):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">50-day MA</div><div class="val">${s.ma50!=null?'₹'+s.ma50.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">200-day MA</div><div class="val">${s.ma200!=null?'₹'+s.ma200.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">52-week High</div><div class="val">${s.week_high_52?'₹'+s.week_high_52.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">52-week Low</div><div class="val">${s.week_low_52?'₹'+s.week_low_52.toFixed(2):'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Vol Spike (10d)</div><div class="val">${s.volume_spike!=null?s.volume_spike.toFixed(2)+'x':'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Today's Volume</div><div class="val">${s.today_volume?s.today_volume.toLocaleString():'—'}</div></div>
      <div class="modal-metric"><div class="lbl">Avg Vol (10d)</div><div class="val">${s.avg_volume_10d?s.avg_volume_10d.toLocaleString():'—'}</div></div>
    </div>

    ${(s.corporate_actions && s.corporate_actions.length > 0) ? `
    <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
      <h4 style="font-size:14px;font-weight:600;margin-bottom:10px;color:var(--accent)">🎁 Corporate Actions</h4>
      <div style="display:flex;flex-direction:column;gap:8px;max-height:180px;overflow-y:auto;padding-right:4px">
        ${s.corporate_actions.map(ca => `
          <div style="background:var(--card2);padding:10px;border-radius:8px;border:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
            <div>
              <div style="font-size:13px;font-weight:600;color:var(--white)">${ca.subject || ca.purpose || 'Corporate Action'}</div>
              <div style="font-size:11px;color:var(--muted);margin-top:2px">
                Ex-Date: <span style="color:var(--accent2);font-weight:600">${ca.ex_date || 'N/A'}</span>
                ${ca.record_date ? ` · Record Date: ${ca.record_date}` : ''}
              </div>
            </div>
            <span style="font-size:10px;padding:3px 8px;border-radius:12px;font-weight:700;background:rgba(255,193,7,0.15);color:#ffc107;border:1px solid rgba(255,193,7,0.3)">
              ${ca.type || 'ACTION'}
            </span>
          </div>
        `).join('')}
      </div>
    </div>
    ` : ''}

    ${(s.news && s.news.length > 0) ? `
    <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
      <h4 style="font-size:14px;font-weight:600;margin-bottom:10px;color:var(--accent2)">📰 Related News</h4>
      <div style="display:flex;flex-direction:column;gap:10px;max-height:250px;overflow-y:auto;padding-right:4px">
        ${s.news.map(n => {
          const pubTime = n.pubDate ? new Date(n.pubDate).toLocaleDateString() : '';
          const provider = n.provider ? ` · ${n.provider}` : '';
          const summary = n.summary ? `<p style="font-size:12px;color:var(--muted);margin-top:4px;line-height:1.4">${n.summary}</p>` : '';
          return `
            <div style="background:var(--card2);padding:10px;border-radius:8px;border:1px solid var(--border)">
              <a href="${n.url}" target="_blank" style="color:var(--white);text-decoration:none;font-weight:500;font-size:13px;display:block;line-height:1.4" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='var(--white)'">
                ${n.title}
              </a>
              <div style="font-size:11px;color:var(--muted);margin-top:4px">
                ${pubTime}${provider}
              </div>
              ${summary}
            </div>
          `;
        }).join('')}
      </div>
    </div>
    ` : `
    <div style="margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
      <p style="color:var(--muted);font-size:12px">No recent news found for this stock.</p>
    </div>
    `}

    <div class="modal-actions">
      <button class="btn-add" onclick="addToWl('${s.symbol}');closeModal()"
        ${inWl?'disabled':''}
        ${maxFull?'disabled title="20 slots full"':''}
        style="flex:1;padding:10px"
      >${inWl?'✓ Already in Watchlist':'+ Add to Watchlist'}</button>
      <button onclick="closeModal()" style="flex:1;padding:10px;background:var(--card2);border:1px solid var(--border);border-radius:8px;color:var(--text);cursor:pointer">Close</button>
    </div>
  `;
  document.getElementById('modalBg').style.display = 'flex';
}

function closeModal() { document.getElementById('modalBg').style.display = 'none'; }
function openBseModal() {
  document.getElementById('bseModalBg').style.display = 'flex';
  document.getElementById('bseSymbolInput').value = '';
  document.getElementById('bseAddStatus').innerHTML = '';
}
function closeBseModal() {
  document.getElementById('bseModalBg').style.display = 'none';
}

function addCustomBseStock() {
  const input = document.getElementById('bseSymbolInput');
  const statusEl = document.getElementById('bseAddStatus');
  let rawSym = input.value.trim().toUpperCase();

  if (!rawSym) {
    statusEl.innerHTML = '<span style="color:var(--danger)">Please enter a valid ticker or BSE code.</span>';
    return;
  }

  let ticker = rawSym;
  if (/^\d+$/.test(rawSym)) {
    ticker = rawSym + '.BO';
  } else if (!rawSym.includes('.')) {
    ticker = rawSym + '.NS';
  }

  const cleanSym = ticker.replace(/\.(NS|BO)$/i, '');

  if (watchlist.length >= CONFIG.max_stocks) {
    statusEl.innerHTML = '<span style="color:var(--danger)">Watchlist limit reached (20 slots maximum).</span>';
    return;
  }

  if (watchlist.some(w => w.symbol === cleanSym || w.ticker === ticker)) {
    statusEl.innerHTML = `<span style="color:var(--warn)">${cleanSym} is already in your Watchlist.</span>`;
    return;
  }

  const existing = SCREENER_DATA.find(s => s.symbol === cleanSym || s.ticker === ticker);
  if (existing) {
    addToWl(existing.symbol);
    closeBseModal();
    return;
  }

  const newItem = {
    symbol: cleanSym,
    ticker: ticker,
    name: cleanSym + (ticker.endsWith('.BO') ? ' (BSE)' : ''),
    qty: 0,
    avg_cost: null,
    total_invested: 0,
    added_at: new Date().toISOString().slice(0, 10),
    score_at_entry: 50,
    current_score: 50,
    ltp: 0,
    sector: ticker.endsWith('.BO') ? 'BSE Listed' : 'NSE Listed',
    signal: 'BUY',
    signal_reason: 'Custom Added Stock'
  };

  watchlist.push(newItem);
  saveWatchlist();
  updateWlCount();
  renderWatchlist();
  renderStats();
  closeBseModal();
  alert(`✅ Custom Stock ${cleanSym} (${ticker}) added to Watchlist!`);
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeModal();
    closeBseModal();
  }
});

// ── LT Capital Accumulator & Portfolio Functions ─────────────────────────
function syncLtWatchlistHoldings(summary) {
  if (!summary || !Array.isArray(summary.holdings) || !Array.isArray(ltWatchlist)) return;
  const hMap = {};
  summary.holdings.forEach(h => { hMap[h.symbol] = h; });
  ltWatchlist.forEach(item => {
    if (hMap[item.symbol] && hMap[item.symbol].qty > 0) {
      item.holding = hMap[item.symbol];
    } else {
      delete item.holding;
    }
  });
  renderLtWatchlist();
}

function fetchLtPortfolioStatus() {
  // Recalculate days_active client-side so the counter is always current,
  // even when the baked-in LT_PORTFOLIO_SUMMARY is from a previous scan day.
  function recalcDaysActive(summary) {
    if (summary && summary.start_date) {
      try {
        const nseHolidays = ["2026-01-26","2026-03-10","2026-03-24","2026-04-02","2026-04-03","2026-04-14","2026-05-01","2026-05-28","2026-06-26","2026-08-15","2026-08-27","2026-09-16","2026-10-02","2026-10-20","2026-11-09","2026-11-10","2026-11-24","2026-12-25"];
        const parts = summary.start_date.split('-');
        let cur = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        cur.setHours(0, 0, 0, 0);
        let tradingDays = 0;
        while (cur <= today) {
          const dayOfWeek = cur.getDay(); // 0 = Sun, 6 = Sat
          const yyyy = cur.getFullYear();
          const mm = String(cur.getMonth() + 1).padStart(2, '0');
          const dd = String(cur.getDate()).padStart(2, '0');
          const dateStr = `${yyyy}-${mm}-${dd}`;
          if (dayOfWeek !== 0 && dayOfWeek !== 6 && !nseHolidays.includes(dateStr)) {
            tradingDays++;
          }
          cur.setDate(cur.getDate() + 1);
        }
        summary.days_active = Math.max(1, tradingDays);
        const dailyRate = summary.daily_accrual_rate || 100;
        const extraDeposits = summary.extra_deposits || 0;
        summary.total_deposited = parseFloat((summary.days_active * dailyRate + extraDeposits).toFixed(2));
      } catch(e) {}
    }
    return summary;
  }

  if (typeof LT_PORTFOLIO_SUMMARY !== 'undefined' && LT_PORTFOLIO_SUMMARY) {
    recalcDaysActive(LT_PORTFOLIO_SUMMARY);
    renderLtPortfolioSummary(LT_PORTFOLIO_SUMMARY);
    syncLtWatchlistHoldings(LT_PORTFOLIO_SUMMARY);
    if (typeof renderPennyStocksTab === 'function') renderPennyStocksTab();
  }
  fetch('/api/lt-portfolio/status')
    .then(r => r.json())
    .then(res => {
      if (res && res.status === 'ok' && res.summary) {
        recalcDaysActive(res.summary);
        window.LT_PORTFOLIO_SUMMARY = res.summary;
        renderLtPortfolioSummary(res.summary);
        syncLtWatchlistHoldings(res.summary);
        if (typeof renderPennyStocksTab === 'function') renderPennyStocksTab();
      }
    })
    .catch(err => {
      if (typeof LT_PORTFOLIO_SUMMARY !== 'undefined' && LT_PORTFOLIO_SUMMARY) {
        recalcDaysActive(LT_PORTFOLIO_SUMMARY);
        renderLtPortfolioSummary(LT_PORTFOLIO_SUMMARY);
        syncLtWatchlistHoldings(LT_PORTFOLIO_SUMMARY);
        if (typeof renderPennyStocksTab === 'function') renderPennyStocksTab();
      }
    });
}


function openLtHoldingLogModal(symbol) {
  const item = (typeof ltWatchlist !== 'undefined' && Array.isArray(ltWatchlist))
    ? ltWatchlist.find(s => s.symbol === symbol)
    : null;
  const holding = item ? item.holding : null;

  if (!holding) {
    alert(`No active holding record found for ${symbol}. Use 🛒 Buy button to record a purchase.`);
    return;
  }

  const pnl = holding.unrealized_pnl || 0;
  const pnlPct = holding.unrealized_pnl_pct || 0;
  const pnlStr = `${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(2)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}%)`;

  const msg = `📋 PURCHASE LOG & HOLDING DETAILS — ${symbol}\n\n` +
    `• Gate Status: 🟢 BOUGHT (Cooling Off Active)\n` +
    `• Quantity Held: ${holding.qty} share(s)\n` +
    `• Avg Buy Price: ₹${parseFloat(holding.avg_price).toFixed(2)}\n` +
    `• Buy Date: ${holding.buy_date || 'N/A'}\n` +
    `• Current Price (LTP): ₹${parseFloat(holding.live_price || (item ? item.ltp : 0) || 0).toFixed(2)}\n` +
    `• Invested Capital: ₹${parseFloat(holding.buy_value || (holding.qty * holding.avg_price)).toFixed(2)}\n` +
    `• Current Value: ₹${parseFloat(holding.market_value || (holding.qty * (holding.live_price || (item ? item.ltp : 0)))).toFixed(2)}\n` +
    `• Live P&L: ${pnlStr}\n` +
    `========================================\n` +
    `This stock is currently held in your portfolio and set to Cooling Off status. You can track its live performance or click "+ Add" if you wish to pyramid.`;

  alert(msg);
}

function renderLtPortfolioSummary(summary) {
  const el = id => document.getElementById(id);
  if (el('ltDayCounterBadge')) el('ltDayCounterBadge').textContent = `DAY ${summary.days_active} ACTIVE`;
  if (el('ltAvailableCashVal')) el('ltAvailableCashVal').textContent = `₹${summary.available_cash.toFixed(2)}`;
  if (el('ltTotalDepositedVal')) el('ltTotalDepositedVal').textContent = `₹${summary.total_deposited.toFixed(2)}`;
  if (el('ltInvestedCapitalVal')) el('ltInvestedCapitalVal').textContent = `₹${summary.invested_capital.toFixed(2)}`;
  if (el('ltPortfolioValueVal')) el('ltPortfolioValueVal').textContent = `₹${summary.current_portfolio_val.toFixed(2)}`;

  if (el('ltTotalPnlVal')) {
    const pnl = summary.total_pnl || 0;
    const pnlCls = pnl > 0 ? '#10b981' : pnl < 0 ? '#ef4444' : 'var(--muted)';
    el('ltTotalPnlVal').innerHTML = `<span style="color:${pnlCls}">P&L: ${pnl >= 0 ? '+' : ''}₹${pnl.toFixed(2)}</span>`;
  }

  const tbody = el('ltHoldingsTableBody');
  if (tbody) {
    if (!summary.holdings || summary.holdings.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="padding:16px;text-align:center;color:var(--muted)">No active holdings yet. Buy stocks when status is 🟢 BUY NOW!</td></tr>`;
    } else {
      tbody.innerHTML = summary.holdings.map(h => {
        const pnlCls = h.unrealized_pnl >= 0 ? '#10b981' : '#ef4444';
        return `
          <tr style="border-bottom:1px solid var(--border)">
            <td style="padding:8px"><strong style="color:#fff">${h.symbol}</strong></td>
            <td style="padding:8px">${h.qty}</td>
            <td style="padding:8px">₹${h.avg_price.toFixed(2)}</td>
            <td style="padding:8px">₹${h.live_price.toFixed(2)}</td>
            <td style="padding:8px">₹${h.buy_value.toFixed(2)}</td>
            <td style="padding:8px">₹${h.market_value.toFixed(2)}</td>
            <td style="padding:8px;font-weight:700;color:${pnlCls}">${h.unrealized_pnl >= 0 ? '+' : ''}₹${h.unrealized_pnl.toFixed(2)} (${h.unrealized_pnl_pct >= 0 ? '+' : ''}${h.unrealized_pnl_pct.toFixed(1)}%)</td>
            <td style="padding:8px">
              <button onclick="openLtSellModal('${h.symbol}', ${h.qty}, ${h.avg_price}, ${h.live_price})" style="background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);color:#ef4444;font-weight:700;font-size:11px;padding:3px 8px;border-radius:6px;cursor:pointer">🔴 Sell</button>
            </td>
          </tr>
        `;
      }).join('');
    }
  }
}

function toggleLtHoldingsDrawer() {
  const drawer = document.getElementById('ltHoldingsDrawer');
  if (drawer) {
    drawer.style.display = (drawer.style.display === 'none' || !drawer.style.display) ? 'block' : 'none';
  }
}

function openLtBuyModal(symbol, ltp) {
  let sym = symbol ? symbol.trim().toUpperCase() : '';
  let priceInfo = ltp && ltp > 0 ? ` (LTP: ₹${ltp.toFixed(2)})` : '';
  alert(`ℹ️ Stock Screener Technical Signals:\n\nStock: ${sym || 'Selected Ticker'}${priceInfo}\n\nUse this Stock Screener for GTT breakout levels, Mansfield RS ratings, and technical discovery.`);
}

function openLtSellModal(symbol, maxQty, avgPrice, ltp) {
  let sym = symbol ? symbol.trim().toUpperCase() : '';
  alert(`ℹ️ Stock Screener Technical Signals:\n\nStock: ${sym || 'Selected Ticker'}\n\nUse this Stock Screener for GTT breakout levels, Mansfield RS ratings, and technical discovery.`);
}

// ── Boot ──────────────────────────────────────────────────────────────────
