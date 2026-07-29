/**
 * journal_engine.js - Core Decoupled Trade Journal & Zerodha Tax Engine
 * Standalone PnL App Engine - Zero dependency on backend scanner tables
 */

const STORAGE_KEY = 'finplus_pnl_v3';
const DATA_VERSION = '20260724_v1'; // Bump this to force-reset stale cached data
const VERSION_KEY = 'finplus_data_version';

/**
 * 1. Zerodha Official Charges Calculator
 * Calculates exact Brokerage, STT/CTT, Exchange Txn Fee, SEBI Charge, Stamp Duty, and 18% GST.
 */
export function calculateZerodhaCharges(trade) {
  const {
    instrument_type = 'Intraday',
    entry_price = 0,
    exit_price = 0,
    quantity = 0
  } = trade;

  const entry = Number(entry_price) || 0;
  const exit = Number(exit_price) || 0;
  const qty = Number(quantity) || 0;

  if (entry <= 0 || qty <= 0) {
    return {
      brokerage: 0,
      stt: 0,
      exchange_txn: 0,
      sebi: 0,
      stamp_duty: 0,
      gst: 0,
      total: 0,
      gross_pnl: 0,
      net_pnl: 0
    };
  }

  const typeLower = (instrument_type || '').toLowerCase();
  const symbolLower = String(trade.symbol || '').toLowerCase();

  const isShort = instrument_type === 'Intraday Short';

  // Detect commodity instruments (MCX: Crude Oil, Gold, Silver, Natural Gas, Copper, etc.)
  const COMMODITY_KEYWORDS = [
    'crude', 'gold', 'silver', 'copper', 'zinc', 'aluminium', 'nickel', 'lead',
    'naturalgas', 'natural gas', 'natgas', 'crudeoil', 'mentha', 'cotton',
    'cardamom', 'turmeric', 'jeera', 'mcx'
  ];
  const isCommodity =
    COMMODITY_KEYWORDS.some(k => typeLower.includes(k) || symbolLower.includes(k));

  const isOptions =
    typeLower.includes('option') ||
    /\b(ce|pe)\b/.test(typeLower);
  const isFutures =
    typeLower.includes('future') ||
    typeLower.includes('mini');
  const isDelivery = typeLower.includes('delivery');

  const buyTurnover = (isShort ? exit : entry) * qty;
  const sellTurnover = (isShort ? entry : exit) * qty;
  const totalTurnover = buyTurnover + sellTurnover;

  // Gross PnL
  let grossPnl = 0;
  if (exit > 0) {
    grossPnl = isShort ? (entry - exit) * qty : (exit - entry) * qty;
  }

  let brokerage = 0;
  let stt = 0;       // STT for equity / CTT for commodity
  let exchangeTxn = 0;
  let stampDuty = 0;

  if (isCommodity && isOptions) {
    // ── Commodity Options (MCX) ──────────────────────────────────────────────
    // Brokerage: Flat ₹20 per executed order  [Source: zerodha.com/charges]
    brokerage = exit > 0 ? 40 : 20;
    // CTT: 0.05% on sell side (on premium)
    stt = sellTurnover * 0.0005;
    // MCX Exchange Txn: 0.0418% (on premium)
    exchangeTxn = totalTurnover * 0.000418;
    // Stamp duty: 0.003% on buy side
    stampDuty = buyTurnover * 0.00003;

  } else if (isCommodity && isFutures) {
    // ── Commodity Futures (MCX) ──────────────────────────────────────────────
    // Brokerage: 0.03% or ₹20 per leg (whichever is lower)  [Source: zerodha.com/charges]
    const buyB = Math.min(20, buyTurnover * 0.0003);
    const sellB = exit > 0 ? Math.min(20, sellTurnover * 0.0003) : 0;
    brokerage = buyB + sellB;
    // CTT: 0.01% on sell side (Non-Agri)
    stt = sellTurnover * 0.0001;
    // MCX Exchange Txn: 0.0021%
    exchangeTxn = totalTurnover * 0.000021;
    // Stamp duty: 0.002% on buy side
    stampDuty = buyTurnover * 0.00002;

  } else if (isOptions) {
    // ── Equity / Currency F&O Options (NSE) ─────────────────────────────────
    // Brokerage: Flat ₹20 per executed order  [Source: zerodha.com/charges]
    brokerage = exit > 0 ? 40 : 20;
    // STT: 0.15% on sell side (on premium)
    stt = sellTurnover * 0.0015;
    // NSE Exchange Txn: 0.03553% (on premium)
    exchangeTxn = totalTurnover * 0.0003553;
    // Stamp duty: 0.003% on buy side
    stampDuty = buyTurnover * 0.00003;

  } else if (isFutures) {
    // ── Equity / Currency F&O Futures (NSE) ─────────────────────────────────
    // Brokerage: 0.03% or ₹20 per leg (whichever is lower)  [Source: zerodha.com/charges]
    const buyB = Math.min(20, buyTurnover * 0.0003);
    const sellB = exit > 0 ? Math.min(20, sellTurnover * 0.0003) : 0;
    brokerage = buyB + sellB;
    // STT: 0.05% on sell side
    stt = sellTurnover * 0.0005;
    // NSE Exchange Txn: 0.00183%
    exchangeTxn = totalTurnover * 0.0000183;
    // Stamp duty: 0.002% on buy side
    stampDuty = buyTurnover * 0.00002;

  } else if (isDelivery) {
    // ── Equity Delivery (NSE/BSE) ─────────────────────────────────────────────
    // Brokerage: ₹0  [Source: zerodha.com/charges]
    brokerage = 0;
    // STT: 0.1% on buy & sell
    stt = totalTurnover * 0.001;
    // NSE Exchange Txn: 0.00307%
    exchangeTxn = totalTurnover * 0.0000307;
    // Stamp duty: 0.015% on buy side
    stampDuty = buyTurnover * 0.00015;

  } else {
    // ── Equity Intraday (NSE/BSE) ─────────────────────────────────────────────
    // Brokerage: 0.03% or ₹20 per leg (whichever is lower)  [Source: zerodha.com/charges]
    const buyB = Math.min(20, buyTurnover * 0.0003);
    const sellB = exit > 0 ? Math.min(20, sellTurnover * 0.0003) : 0;
    brokerage = buyB + sellB;
    // STT: 0.025% on sell side
    stt = sellTurnover * 0.00025;
    // NSE Exchange Txn: 0.00297%
    exchangeTxn = totalTurnover * 0.0000297;
    // Stamp duty: 0.003% on buy side
    stampDuty = buyTurnover * 0.00003;
  }

  // SEBI turnover charge: ₹10 per crore (0.0001%)
  const sebi = totalTurnover * 0.000001;
  // GST: 18% on (Brokerage + Exchange Txn + SEBI)
  const gst = (brokerage + exchangeTxn + sebi) * 0.18;

  const totalCharges = brokerage + stt + exchangeTxn + sebi + stampDuty + gst;
  const netPnl = exit > 0 ? grossPnl - totalCharges : 0;

  return {
    brokerage: Number(brokerage.toFixed(2)),
    stt: Number(stt.toFixed(2)),
    exchange_txn: Number(exchangeTxn.toFixed(2)),
    sebi: Number(sebi.toFixed(2)),
    stamp_duty: Number(stampDuty.toFixed(2)),
    gst: Number(gst.toFixed(2)),
    total: Number(totalCharges.toFixed(2)),
    gross_pnl: Number(grossPnl.toFixed(2)),
    net_pnl: Number(netPnl.toFixed(2))
  };
}

const RECOVERED_RESERVE_TRADES = [
  {
    "id": 1,
    "uuid": "fp_mryv9p",
    "symbol": "CRUDEOIL",
    "instrument_type": "Crude Oil Options",
    "entry_price": 275.0,
    "quantity": 10,
    "exit_price": 265.25,
    "status": "CLOSED",
    "gross_pnl": -97.5,
    "net_pnl": -148.79,
    "created_at": "2026-07-24T11:38:24.549Z"
  },
  {
    "id": 2,
    "uuid": "fp_mrypn7",
    "symbol": "TMPV",
    "instrument_type": "Intraday Short",
    "entry_price": 319.55,
    "quantity": 38,
    "exit_price": 319.55,
    "status": "CLOSED",
    "gross_pnl": 0.0,
    "net_pnl": -12.87,
    "created_at": "2026-07-24T09:00:56.923Z"
  },
  {
    "id": 3,
    "uuid": "fp_mrypm5",
    "symbol": "NIFTY 24100",
    "instrument_type": "Nifty Options",
    "entry_price": 30.0,
    "quantity": 65,
    "exit_price": 28.05,
    "status": "CLOSED",
    "gross_pnl": -126.75,
    "net_pnl": -178.32,
    "created_at": "2026-07-24T09:00:06.931Z"
  },
  {
    "id": 4,
    "uuid": "fp_mrypl4",
    "symbol": "NIFTY 24050",
    "instrument_type": "Nifty Options",
    "entry_price": 35.15,
    "quantity": 260,
    "exit_price": 38.05,
    "status": "CLOSED",
    "gross_pnl": 754.0,
    "net_pnl": 683.69,
    "created_at": "2026-07-24T08:59:18.901Z"
  },
  {
    "id": 5,
    "uuid": "fp_mrypk2",
    "symbol": "NIFTY 24000",
    "instrument_type": "Nifty Options",
    "entry_price": 35.7,
    "quantity": 65,
    "exit_price": 33.7,
    "status": "CLOSED",
    "gross_pnl": -130.0,
    "net_pnl": -182.45,
    "created_at": "2026-07-24T08:58:30.399Z"
  },
  {
    "id": 6,
    "uuid": "fp_mrypj2",
    "symbol": "NIFTY 23950",
    "instrument_type": "Nifty Options",
    "entry_price": 36.9,
    "quantity": 65,
    "exit_price": 38.45,
    "status": "CLOSED",
    "gross_pnl": 100.75,
    "net_pnl": 47.68,
    "created_at": "2026-07-24T08:57:42.787Z"
  },
  {
    "id": 7,
    "uuid": "fp_mrypey",
    "symbol": "NIFTY 23350",
    "instrument_type": "Nifty Options",
    "entry_price": 31.95,
    "quantity": 65,
    "exit_price": 29.9,
    "status": "CLOSED",
    "gross_pnl": -133.25,
    "net_pnl": -185.12,
    "created_at": "2026-07-24T08:54:31.779Z"
  },
  {
    "id": 8,
    "uuid": "fp_mryilq",
    "symbol": "BHEL",
    "instrument_type": "Intraday Short",
    "entry_price": 402.95,
    "quantity": 29,
    "exit_price": 404.46,
    "status": "CLOSED",
    "gross_pnl": -43.79,
    "net_pnl": -56.21,
    "created_at": "2026-07-24T05:43:50.633Z"
  },
  {
    "id": 9,
    "uuid": "fp_mryil5",
    "symbol": "TMPV",
    "instrument_type": "Intraday Short",
    "entry_price": 319.55,
    "quantity": 38,
    "exit_price": 319.75,
    "status": "CLOSED",
    "gross_pnl": -7.6,
    "net_pnl": -20.48,
    "created_at": "2026-07-24T05:43:23.232Z"
  },
  {
    "id": 10,
    "uuid": "fp_20260723_trade1",
    "symbol": "NATGASMINI 275 CE",
    "instrument_type": "Natural Gas Options",
    "entry_price": 14.47,
    "quantity": 250,
    "exit_price": 10.05,
    "status": "CLOSED",
    "gross_pnl": -1105.0,
    "net_pnl": -1156.61,
    "created_at": "2026-07-23T14:27:48.540Z"
  }
];

export function getTradeKey(t) {
  if (!t) return '';
  if (t.uuid) return `uuid_${t.uuid}`;
  if (t.id != null && t.id !== '') return `id_${t.id}`;
  if (t.symbol && t.created_at) return `${String(t.symbol).toUpperCase()}_${t.created_at}`;
  return `${t.symbol}_${t.entry_price}`;
}

/** Collapse duplicate rows that differ only by id vs uuid or storage source. */
export function getTradeFingerprint(t) {
  if (!t) return '';
  const sym = String(t.symbol || '').toUpperCase().trim();
  const entry = Number(t.entry_price) || 0;
  const exit = Number(t.exit_price) || 0;
  const qty = Number(t.quantity) || 0;
  const day = String(t.created_at || t.entry_date || t.date || '').slice(0, 10);
  const status = String(t.status || '').toUpperCase();
  if (status === 'CLOSED' && exit > 0) {
    return `closed|${sym}|${entry}|${exit}|${qty}|${day}`;
  }
  return `open|${sym}|${entry}|${qty}|${day}`;
}

function dedupeTradesByFingerprint(trades) {
  const byFp = new Map();
  for (const t of trades) {
    if (!t) continue;
    const fp = getTradeFingerprint(t);
    const existing = byFp.get(fp);
    if (!existing) {
      byFp.set(fp, { ...t });
      continue;
    }
    const prefer =
      (t.status === 'CLOSED' && Number(t.exit_price) > 0) &&
      !(existing.status === 'CLOSED' && Number(existing.exit_price) > 0)
        ? t
        : existing;
    const other = prefer === t ? existing : t;
    byFp.set(fp, {
      ...other,
      ...prefer,
      uuid: prefer.uuid || other.uuid,
      id: prefer.id != null ? prefer.id : other.id,
      status: prefer.status === 'CLOSED' || other.status === 'CLOSED' ? 'CLOSED' : prefer.status,
      exit_price: Number(prefer.exit_price) > 0 ? prefer.exit_price : other.exit_price
    });
  }
  return Array.from(byFp.values());
}

/**
 * 2. Instant Local Storage Reader with Fail-safe Disk Reserve Merge
 */
export function loadJournalEngine() {
  let loaded = [];
  
  // Safely read and merge across all historical storage keys without wiping anything
  for (const k of ['finplus_pnl_v3', 'finplus_pnl_v2', 'finplus_pnl_journal_v1', 'journal_trades_backup']) {
    try {
      const raw = localStorage.getItem(k);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) {
          loaded = mergeJournalTrades(loaded, parsed);
        }
      }
    } catch (e) {}
  }

  // Merge recovered reserve trades as a safety baseline — ONLY ONCE.
  // Without this guard, these 10 hardcoded trades get re-merged on every
  // app load. Because they use numeric `id` fields instead of the `uuid`
  // scheme real trades use, mergeJournalTrades can't recognize them as
  // duplicates of already-recovered trades, so they get added again as new
  // trades each time — silently inflating your total P&L loss on every reload.
  const RESERVE_MERGE_FLAG = 'finplus_reserve_trades_merged_v1';
  if (!localStorage.getItem(RESERVE_MERGE_FLAG)) {
    loaded = mergeJournalTrades(loaded, RECOVERED_RESERVE_TRADES);
    try {
      localStorage.setItem(RESERVE_MERGE_FLAG, 'true');
    } catch (e) {}
  }

  loaded = dedupeTradesByFingerprint(loaded);

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(loaded));
    localStorage.setItem(VERSION_KEY, DATA_VERSION);
    for (const legacyKey of ['finplus_pnl_v2', 'finplus_pnl_journal_v1', 'journal_trades_backup']) {
      if (legacyKey !== STORAGE_KEY) localStorage.removeItem(legacyKey);
    }
  } catch (e) {}

  return loaded;
}

let lastSyncedJson = '';

/**
 * 3. Instant Local Storage & Disk Backend Sync Saver
 */
export function saveJournalEngine(trades) {
  try {
    if (Array.isArray(trades)) {
      const jsonStr = JSON.stringify(trades);
      localStorage.setItem(STORAGE_KEY, jsonStr);

      if (jsonStr === lastSyncedJson) return;
      lastSyncedJson = jsonStr;

      // Async sync with local Python backend to write to SQLite + disk JSON file
      const candidateUrls = [
        'http://127.0.0.1:8000'
      ];
      for (const url of candidateUrls) {
        fetch(`${url}/api/trades/sync`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ trades })
        }).catch(() => {});
      }
    }
  } catch (e) {
    console.error("[JournalEngine] Save error:", e);
  }
}

/**
 * 4. Immutable Trade UUID Generator
 */
export function createTradeUUID() {
  return 'fp_' + Date.now().toString(36) + '_' + Math.random().toString(36).substring(2, 9);
}

/**
 * 5. Strict Unique Union Merger (Zero Trade Collapsing)
 */
export function mergeJournalTrades(listA = [], listB = []) {
  const map = new Map();

  const getKey = (t) => {
    const stable = getTradeKey(t);
    if (stable) return stable;
    if (!t._tmp_uuid) {
      t._tmp_uuid = createTradeUUID();
    }
    return `tmp_${t._tmp_uuid}`;
  };

  for (const a of listA) {
    if (!a) continue;
    map.set(getKey(a), { ...a });
  }

  for (const b of listB) {
    if (!b) continue;
    const k = getKey(b);
    const existing = map.get(k);
    if (!existing) {
      map.set(k, { ...b });
    } else {
      // Last-Write-Wins based on updated_at or status=CLOSED preference
      if (b.status === 'CLOSED' && b.exit_price > 0) {
        map.set(k, { ...existing, ...b, status: 'CLOSED' });
      } else {
        map.set(k, { ...b, ...existing });
      }
    }
  }

  const merged = Array.from(map.values()).sort((x, y) => {
    const timeX = x.created_at || '';
    const timeY = y.created_at || '';
    return timeY.localeCompare(timeX);
  });
  return dedupeTradesByFingerprint(merged);
}

/**
 * 6. 1-Click Master JSON Backup Exporter (Trades + Capital & Risk Settings)
 */
export function exportMasterJsonBackup(trades, settings = {}) {
  try {
    const backupObj = {
      version: '2.0',
      exported_at: new Date().toISOString(),
      trades: Array.isArray(trades) ? trades : [],
      settings: {
        openingCapital: localStorage.getItem('finplus_opening_capital') || '500000',
        brokerAdjustment: localStorage.getItem('finplus_broker_adjustment') || '0',
        deposits: localStorage.getItem('finplus_deposits') || '0',
        withdrawals: localStorage.getItem('finplus_withdrawals') || '0',
        dailyRiskLimit: localStorage.getItem('finplus_daily_risk_limit') || '250',
        intradayRiskLimit: localStorage.getItem('finplus_intraday_risk_limit') || '100',
        optionsRiskLimit: localStorage.getItem('finplus_options_risk_limit') || '100',
        commoditiesRiskLimit: localStorage.getItem('finplus_commodities_risk_limit') || '100',
        challengeStartDate: localStorage.getItem('finplus_challenge_start_date') || new Date().toISOString().split('T')[0],
        totalChallengeDays: localStorage.getItem('finplus_total_challenge_days') || '1000',
        ...settings
      }
    };

    const jsonStr = JSON.stringify(backupObj, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const dateStr = new Date().toISOString().split('T')[0];
    const link = document.createElement('a');
    link.href = url;
    link.download = `finplus_pnl_master_backup_${dateStr}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    return true;
  } catch (err) {
    console.error("Export JSON error:", err);
    return false;
  }
}

/**
 * 7. 1-Click Master JSON Restore Importer
 */
export function importMasterJsonBackup(fileText, currentTrades = []) {
  try {
    const parsed = JSON.parse(fileText);
    let importedTrades = [];
    let importedSettings = null;

    if (Array.isArray(parsed)) {
      importedTrades = parsed;
    } else if (parsed && typeof parsed === 'object') {
      importedTrades = Array.isArray(parsed.trades) ? parsed.trades : [];
      importedSettings = parsed.settings || null;
    } else {
      throw new Error("Invalid backup format.");
    }

    if (importedSettings) {
      if (importedSettings.openingCapital) localStorage.setItem('finplus_opening_capital', importedSettings.openingCapital);
      if (importedSettings.brokerAdjustment) localStorage.setItem('finplus_broker_adjustment', importedSettings.brokerAdjustment);
      if (importedSettings.deposits) localStorage.setItem('finplus_deposits', importedSettings.deposits);
      if (importedSettings.withdrawals) localStorage.setItem('finplus_withdrawals', importedSettings.withdrawals);
      if (importedSettings.dailyRiskLimit) localStorage.setItem('finplus_daily_risk_limit', importedSettings.dailyRiskLimit);
      if (importedSettings.intradayRiskLimit) localStorage.setItem('finplus_intraday_risk_limit', importedSettings.intradayRiskLimit);
      if (importedSettings.optionsRiskLimit) localStorage.setItem('finplus_options_risk_limit', importedSettings.optionsRiskLimit);
      if (importedSettings.commoditiesRiskLimit) localStorage.setItem('finplus_commodities_risk_limit', importedSettings.commoditiesRiskLimit);
      if (importedSettings.challengeStartDate) localStorage.setItem('finplus_challenge_start_date', importedSettings.challengeStartDate);
      if (importedSettings.totalChallengeDays) localStorage.setItem('finplus_total_challenge_days', importedSettings.totalChallengeDays);
    }

    const merged = mergeJournalTrades(currentTrades, importedTrades);
    saveJournalEngine(merged);
    return { success: true, trades: merged, count: importedTrades.length, settings: importedSettings };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

/**
 * 8. CSV Exporter for Excel Accounting
 */
export function exportJournalCSV(trades) {
  if (!Array.isArray(trades) || trades.length === 0) return false;
  try {
    const headers = [
      "UUID/ID", "Symbol", "Type", "Entry Price (INR)", "Quantity", 
      "Exit Price (INR)", "Status", "Gross PnL", "Net PnL", "Total Charges", "Created At"
    ];
    const rows = trades.map(t => {
      const chg = calculateZerodhaCharges(t);
      return [
        `"${t.id || t.uuid || ''}"`,
        `"${t.symbol || ''}"`,
        `"${t.instrument_type || 'Intraday'}"`,
        t.entry_price || 0,
        t.quantity || 0,
        t.exit_price || '',
        `"${t.status || 'ACTIVE'}"`,
        chg.gross_pnl,
        chg.net_pnl,
        chg.total,
        `"${t.created_at || ''}"`
      ];
    });

    const csvStr = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
    const encoded = encodeURI(csvStr);
    const link = document.createElement("a");
    link.href = encoded;
    link.download = `finplus_pnl_journal_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    return true;
  } catch (e) {
    console.error("Export CSV error:", e);
    return false;
  }
}

/**
 * 9. CSV / Excel Importer for Trade Journal
 * Parses uploaded CSV / Excel exports and updates Closed PnL automatically.
 */
export function importJournalCSV(csvText, currentTrades = []) {
  try {
    if (!csvText || typeof csvText !== 'string') {
      throw new Error("Invalid CSV content.");
    }

    const lines = csvText.split(/\r?\n/).filter(line => line.trim().length > 0);
    if (lines.length < 2) {
      throw new Error("CSV file is empty or missing headers.");
    }

    const headers = lines[0].split(',').map(h => h.replace(/^["']|["']$/g, '').trim().toLowerCase());
    
    // Find column indices dynamically
    const symbolIdx = headers.findIndex(h => h.includes('symbol') || h.includes('scrip') || h.includes('tradingsymbol'));
    const entryIdx = headers.findIndex(h => h.includes('entry') || h.includes('buy price') || h.includes('price') || h.includes('rate'));
    const exitIdx = headers.findIndex(h => h.includes('exit') || h.includes('sell price'));
    const qtyIdx = headers.findIndex(h => h.includes('qty') || h.includes('quantity') || h.includes('volume'));
    const typeIdx = headers.findIndex(h => h.includes('type') || h.includes('segment') || h.includes('instrument'));
    const uuidIdx = headers.findIndex(h => h.includes('uuid') || h.includes('id'));
    const statusIdx = headers.findIndex(h => h.includes('status'));

    if (symbolIdx === -1) {
      throw new Error("CSV format unrecognized: Missing 'Symbol' column.");
    }

    const importedTrades = [];

    for (let i = 1; i < lines.length; i++) {
      const row = lines[i].split(',').map(cell => cell.replace(/^["']|["']$/g, '').trim());
      if (!row || row.length === 0) continue;

      const symbol = symbolIdx !== -1 ? row[symbolIdx] : '';
      if (!symbol) continue;

      const entryPrice = parseFloat(entryIdx !== -1 ? row[entryIdx] : '') || 0;
      const exitPrice = parseFloat(exitIdx !== -1 ? row[exitIdx] : '') || null;
      const quantity = parseInt(qtyIdx !== -1 ? row[qtyIdx] : '') || 1;
      const instType = (typeIdx !== -1 ? row[typeIdx] : '') || 'Intraday';
      const uuid = (uuidIdx !== -1 ? row[uuidIdx] : '') || createTradeUUID();
      const statusRaw = statusIdx !== -1 ? row[statusIdx] : '';

      const status = exitPrice && exitPrice > 0 ? 'CLOSED' : (statusRaw ? statusRaw.toUpperCase() : 'ACTIVE');

      if (entryPrice > 0) {
        importedTrades.push({
          uuid,
          symbol: symbol.toUpperCase(),
          instrument_type: instType,
          entry_price: entryPrice,
          quantity,
          stop_loss: null,
          target_price: null,
          exit_price: exitPrice && exitPrice > 0 ? exitPrice : null,
          status,
          created_at: new Date().toISOString()
        });
      }
    }

    if (importedTrades.length === 0) {
      throw new Error("No valid trade rows found in CSV.");
    }

    const merged = mergeJournalTrades(currentTrades, importedTrades);
    saveJournalEngine(merged);
    return { success: true, trades: merged, count: importedTrades.length };
  } catch (err) {
    console.error("[Import CSV Error]:", err);
    return { success: false, error: err.message };
  }
}

/**
 * 10. Real-time Cloud Synchronization Engine (Option A)
 * Syncs trade journal state and capital settings automatically between Mobile APK & PC.
 */
const CLOUD_SYNC_SERVERS = [
  'https://finplus-kite.onrender.com',
  'http://127.0.0.1:8000'
];

export async function pushJournalToCloud(trades, settings = {}) {
  const payload = {
    version: '1.0.0',
    last_synced_at: new Date().toISOString(),
    trades: Array.isArray(trades) ? trades : [],
    settings
  };

  for (const serverUrl of CLOUD_SYNC_SERVERS) {
    try {
      const res = await fetch(`${serverUrl}/api/journal/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        return { success: true, server: serverUrl, timestamp: payload.last_synced_at };
      }
    } catch (e) {
      // Try next server candidate
    }
  }
  return { success: false, error: "Cloud sync server offline." };
}

export async function fetchJournalFromCloud() {
  for (const serverUrl of CLOUD_SYNC_SERVERS) {
    try {
      const res = await fetch(`${serverUrl}/api/journal/sync`);
      if (res.ok) {
        const data = await res.json();
        if (data && Array.isArray(data.trades)) {
          return { success: true, trades: data.trades, settings: data.settings || null, server: serverUrl };
        }
      }
    } catch (e) {
      // Try next server candidate
    }
  }
  return { success: false, error: "Cloud fetch offline." };
}
