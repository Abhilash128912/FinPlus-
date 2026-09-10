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
 * Statutory rates for NSE equity DELIVERY, verified 10 Sep 2026 against
 * https://zerodha.com/charges/ . These are exchange/government charges: they do
 * not vary by broker, so both calculators below share them and only the DP fee
 * differs. Keeping two hand-maintained copies is how the exchange charge sat at
 * 0.00297% here while broker_profiles.js already used the correct 0.00307%.
 *
 * Bump DELIVERY_RATES.version whenever a number changes.
 */
export const DELIVERY_RATES = {
  version: '2026.09.1',
  stt_pct: 0.001,            // 0.1% on buy AND on sell
  exchange_txn_pct: 0.0000307, // 0.00307% of turnover (NSE)
  sebi_pct: 0.000001,        // Rs 10 per crore
  stamp_duty_buy_pct: 0.00015, // 0.015% on buy
  gst_pct: 0.18,
  dp_indmoney: 14.75,
  dp_zerodha: 15.34
};

/** Shared delivery charge maths. Only the DP fee differs between brokers. */
function deliveryCharges(trade, dpFee) {
  const R = DELIVERY_RATES;
  const entry = Number(trade?.entry_price) || 0;
  const exit = Number(trade?.exit_price) || 0;
  const qty = Number(trade?.quantity) || 0;

  const empty = {
    brokerage: 0, stt: 0, exchange_txn: 0, sebi: 0, stamp_duty: 0,
    gst: 0, dp_charges: 0, total: 0, gross_pnl: 0, net_pnl: 0,
    rates_version: R.version
  };
  if (entry <= 0 || qty <= 0) return empty;

  const isClosed = exit > 0;
  const buyTurnover = entry * qty;
  const sellTurnover = isClosed ? exit * qty : 0;
  const totalTurnover = buyTurnover + sellTurnover;

  const brokerage = 0;
  const stt = (buyTurnover * R.stt_pct) + (sellTurnover * R.stt_pct);
  const exchangeTxn = totalTurnover * R.exchange_txn_pct;
  const sebi = totalTurnover * R.sebi_pct;
  const stampDuty = buyTurnover * R.stamp_duty_buy_pct;
  const gst = (brokerage + exchangeTxn + sebi) * R.gst_pct;
  const dpCharges = isClosed ? dpFee : 0;

  const total = brokerage + stt + exchangeTxn + sebi + stampDuty + gst + dpCharges;
  const grossPnl = isClosed ? (exit - entry) * qty : 0;

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
    net_pnl: grossPnl - total,
    rates_version: R.version
  };
}

/**
 * INDmoney charges for delivery holdings (zero brokerage, Rs 14.75 DP on exit).
 */
export function calculateINDmoneyCharges(trade) {
  return deliveryCharges(trade, DELIVERY_RATES.dp_indmoney);
}

/**
 * Zerodha Kite charges for delivery holdings (zero brokerage, Rs 15.34 DP on exit).
 */
export function calculateKiteDeliveryCharges(trade) {
  return deliveryCharges(trade, DELIVERY_RATES.dp_zerodha);
}
