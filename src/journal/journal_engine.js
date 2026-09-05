/**
 * journal_engine.js - broker charge calculators and cloud server discovery.
 *
 * This module previously carried a full trade-journal implementation: local
 * storage load/save, CSV and JSON import/export, cloud push/fetch, dedupe
 * helpers and a generic Zerodha charge calculator. None of it was reachable -
 * every one of those thirteen exports had zero call sites, so the bundler
 * dropped them and they quietly diverged from the code that actually runs.
 *
 * That dead weight twice produced audit findings that read as urgent but
 * changed nothing: a wrong equity-futures STT rate, and a missing auth header
 * on a sync call that never fired. Only the three live exports remain.
 *
 * Charge rates for the Risk Desk live in risk/broker_profiles.js, which is
 * effective-dated and configurable. The two calculators below serve the
 * 3-Pillar delivery holdings and are called from App.jsx.
 */

/**
 * Cloud & LAN server discovery. Ordered by preference: an explicit override,
 * the serving host, localhost for desktop, then the Render deployment.
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

/**
 * INDmoney charges for delivery holdings (zero brokerage, Rs 14.75 DP on exit).
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
 * Zerodha Kite charges for delivery holdings (zero brokerage, Rs 15.34 DP on exit).
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
