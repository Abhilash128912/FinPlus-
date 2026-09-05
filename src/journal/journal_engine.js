/**
 * journal_engine.js - Core Decoupled Trade Journal & Zerodha Tax Engine
 * Standalone PnL App Engine - Zero dependency on backend scanner tables
 */

import { authHeaders } from './risk/api_key.js';

const STORAGE_KEY = 'finplus_pnl_v4_fresh';
const DATA_VERSION = '20260907_fresh_start_v2';
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
  } = trade || {};

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
    // Brokerage: Flat ₹20 per executed order
    brokerage = exit > 0 ? 40 : 20;
    stt = sellTurnover * 0.0005;
    exchangeTxn = totalTurnover * 0.000418;
    stampDuty = buyTurnover * 0.00003;

  } else if (isCommodity && isFutures) {
    // ── Commodity Futures (MCX) ──────────────────────────────────────────────
    const buyB = Math.min(20, buyTurnover * 0.0003);
    const sellB = exit > 0 ? Math.min(20, sellTurnover * 0.0003) : 0;
    brokerage = buyB + sellB;
    stt = sellTurnover * 0.0001;
    exchangeTxn = totalTurnover * 0.000021;
    stampDuty = buyTurnover * 0.00002;

  } else if (isOptions) {
    // ── Equity / Currency F&O Options (NSE) ─────────────────────────────────
    brokerage = exit > 0 ? 40 : 20;
    stt = sellTurnover * 0.001;
    exchangeTxn = totalTurnover * 0.0003553;
    stampDuty = buyTurnover * 0.00003;

  } else if (isFutures) {
    // ── Equity / Currency F&O Futures (NSE) ─────────────────────────────────
    const buyB = Math.min(20, buyTurnover * 0.0003);
    const sellB = exit > 0 ? Math.min(20, sellTurnover * 0.0003) : 0;
    brokerage = buyB + sellB;
    stt = sellTurnover * 0.0005;
    exchangeTxn = totalTurnover * 0.0000183;
    stampDuty = buyTurnover * 0.00002;

  } else if (isDelivery) {
    // ── Equity Delivery (NSE/BSE) ─────────────────────────────────────────────
    brokerage = 0;
    stt = totalTurnover * 0.001;
    exchangeTxn = totalTurnover * 0.0000307;
    stampDuty = buyTurnover * 0.00015;

  } else {
    // ── Equity Intraday (NSE/BSE) ─────────────────────────────────────────────
    const buyB = Math.min(20, buyTurnover * 0.0003);
    const sellB = exit > 0 ? Math.min(20, sellTurnover * 0.0003) : 0;
    brokerage = buyB + sellB;
    stt = sellTurnover * 0.00025;
    exchangeTxn = totalTurnover * 0.000297;
    stampDuty = buyTurnover * 0.00003;
  }

  const sebi = totalTurnover * 0.000001;
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

const RECOVERED_RESERVE_TRADES = [];

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
 * 2. Instant Local Storage Reader starting fresh from 2026-08-17
 */
export function loadJournalEngine() {
  const version = localStorage.getItem('finplus_journal_fresh_version');
  if (version !== DATA_VERSION) {
    localStorage.setItem('finplus_journal_fresh_version', DATA_VERSION);
    localStorage.setItem(STORAGE_KEY, JSON.stringify([]));
    return [];
  }

  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed;
    }
  } catch (e) {}

  return [];
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
      const isNative = typeof window !== 'undefined' && (Boolean(window.Capacitor?.isNativePlatform?.()) || window.location.protocol === 'capacitor:');
      const defaultCloudUrl = 'https://finplus.onrender.com';
      const customUrl = typeof window !== 'undefined' && localStorage.getItem('finplus_server_url');
      
      const candidateUrls = [];
      if (customUrl) candidateUrls.push(customUrl);
      if (isNative) candidateUrls.push(defaultCloudUrl);
      candidateUrls.push('http://127.0.0.1:8000');

      for (const url of candidateUrls) {
        fetch(`${url}/api/trades/sync`, {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
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
 * 10. Real-time Cloud & LAN Synchronization Engine
 * Syncs trade journal state and capital settings automatically between Mobile APK & PC.
 */
export const getCloudSyncServers = () => {
  const isNative = typeof window !== 'undefined' && (Boolean(window.Capacitor?.isNativePlatform?.()) || window.location.protocol === 'capacitor:');
  const defaultCloudUrl = 'https://finplus.onrender.com';
  const customUrl = typeof window !== 'undefined' && localStorage.getItem('finplus_server_url');
  
  const servers = [];
  if (customUrl) {
    const clean = customUrl.trim().replace(/\/$/, '');
    if (clean) servers.push(clean);
  }
  if (typeof window !== 'undefined' && window.location.hostname && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1' && window.location.protocol.startsWith('http')) {
    servers.push(`${window.location.protocol}//${window.location.hostname}:8000`);
  }
  servers.push('http://127.0.0.1:8000');
  servers.push('http://localhost:8000');
  if (isNative || !customUrl) {
    servers.push(defaultCloudUrl);
  }
  return Array.from(new Set(servers.filter(Boolean)));
};

export async function pushJournalToCloud(trades, settings = {}) {
  const payload = {
    version: '1.0.0',
    last_synced_at: new Date().toISOString(),
    trades: Array.isArray(trades) ? trades : [],
    settings
  };

  const syncServers = getCloudSyncServers();
  for (const serverUrl of syncServers) {
    try {
      const res = await fetch(`${serverUrl}/api/journal/sync`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
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
  const syncServers = getCloudSyncServers();
  for (const serverUrl of syncServers) {
    try {
      const res = await fetch(`${serverUrl}/api/journal/sync`, { headers: authHeaders() });
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


/**
 * INDmoney Official Charges Calculator (Long-Term Delivery)
 */
export function calculateINDmoneyCharges(trade) {
  const {
    entry_price = 0,
    exit_price = 0,
    quantity = 0
  } = trade || {};

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
      dp_charges: 0,
      total: 0,
      gross_pnl: 0,
      net_pnl: 0
    };
  }

  const buyTurnover = entry * qty;
  const sellTurnover = (exit > 0 ? exit : entry) * qty;
  const totalTurnover = buyTurnover + (exit > 0 ? sellTurnover : 0);

  const grossPnl = exit > 0 ? (exit - entry) * qty : 0;

  const brokerage = 0;
  const stt = (buyTurnover * 0.001) + (exit > 0 ? (sellTurnover * 0.001) : 0);
  const exchangeTxn = totalTurnover * 0.0000297;
  const sebi = totalTurnover * 0.000001;
  const stampDuty = buyTurnover * 0.00015;
  const gst = (brokerage + exchangeTxn + sebi) * 0.18;
  const dpCharges = exit > 0 ? 14.75 : 0;

  const total = brokerage + stt + exchangeTxn + sebi + stampDuty + gst + dpCharges;
  const netPnl = grossPnl - total;

  return {
    brokerage,
    stt,
    exchange_txn: exchangeTxn,
    sebi,
    stamp_duty: stampDuty,
    gst,
    dp_charges: dpCharges,
    total,
    gross_pnl: grossPnl,
    net_pnl: netPnl
  };
}

/**
 * Zerodha Kite Official Charges Calculator (Swing & Penny Delivery)
 */
export function calculateKiteDeliveryCharges(trade) {
  const {
    entry_price = 0,
    exit_price = 0,
    quantity = 0
  } = trade || {};

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
      dp_charges: 0,
      total: 0,
      gross_pnl: 0,
      net_pnl: 0
    };
  }

  const buyTurnover = entry * qty;
  const sellTurnover = (exit > 0 ? exit : entry) * qty;
  const totalTurnover = buyTurnover + (exit > 0 ? sellTurnover : 0);

  const grossPnl = exit > 0 ? (exit - entry) * qty : 0;

  const brokerage = 0;
  const stt = (buyTurnover * 0.001) + (exit > 0 ? (sellTurnover * 0.001) : 0);
  const exchangeTxn = totalTurnover * 0.0000297;
  const sebi = totalTurnover * 0.000001;
  const stampDuty = buyTurnover * 0.00015;
  const gst = (brokerage + exchangeTxn + sebi) * 0.18;
  const dpCharges = exit > 0 ? 15.34 : 0;

  const total = brokerage + stt + exchangeTxn + sebi + stampDuty + gst + dpCharges;
  const netPnl = grossPnl - total;

  return {
    brokerage,
    stt,
    exchange_txn: exchangeTxn,
    sebi,
    stamp_duty: stampDuty,
    gst,
    dp_charges: dpCharges,
    total,
    gross_pnl: grossPnl,
    net_pnl: netPnl
  };
}
