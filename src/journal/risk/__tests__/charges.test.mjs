/**
 * Statutory charge rates on the paths that actually execute.
 *
 * These are legal figures rather than preferences, so they are pinned: a silent
 * drift misstates every planned risk and net P&L. An earlier generic calculator
 * carried a wrong equity-futures STT for months without anyone noticing, purely
 * because nothing called it — so these tests deliberately target only live code:
 *
 *   • risk/broker_profiles.js  — the Risk Desk charge engine
 *   • journal_engine.js        — the two 3-Pillar delivery calculators
 */
import { SEED_CHARGE_PROFILES, estimateCharges, PRODUCTS } from '../broker_profiles.js';
import { calculateINDmoneyCharges, calculateKiteDeliveryCharges } from '../../journal_engine.js';

let pass = 0, fail = 0;
const ok = (n, c, x = '') => { if (c) { pass++; console.log(`  PASS  ${n}`); } else { fail++; console.log(`  FAIL  ${n} ${x}`); } };
const near = (a, b, t = 0.01) => Math.abs(a - b) <= t;

// entry 100 -> exit 110, qty 100.  buy 10,000 · sell 11,000 · total 21,000
const est = (broker, product) => estimateCharges({
  profiles: SEED_CHARGE_PROFILES, broker, product,
  entryPrice: 100, exitPrice: 110, quantity: 100, lotSize: 1, date: '2026-09-04'
}).breakdown;

console.log('');
console.log('=== Risk Desk engine: STT / CTT by product ===');
ok('equity intraday STT = 11,000 x 0.025% = 2.75',
  near(est('INDMONEY', PRODUCTS.EQ_INTRADAY).stt, 2.75), String(est('INDMONEY', PRODUCTS.EQ_INTRADAY).stt));
ok('equity delivery STT = 21,000 x 0.1% = 21.00',
  near(est('INDMONEY', PRODUCTS.EQ_DELIVERY).stt, 21.00), String(est('INDMONEY', PRODUCTS.EQ_DELIVERY).stt));
ok('index options STT = 11,000 x 0.15% = 16.50',
  near(est('INDMONEY', PRODUCTS.INDEX_OPTION).stt, 16.50), String(est('INDMONEY', PRODUCTS.INDEX_OPTION).stt));
ok('stock options STT = 11,000 x 0.15% = 16.50',
  near(est('INDMONEY', PRODUCTS.STOCK_OPTION).stt, 16.50), String(est('INDMONEY', PRODUCTS.STOCK_OPTION).stt));
ok('MCX futures CTT = 11,000 x 0.01% = 1.10  (Natural Gas, Crude)',
  near(est('INDMONEY', PRODUCTS.MCX_FUTURE).stt, 1.10), String(est('INDMONEY', PRODUCTS.MCX_FUTURE).stt));
ok('MCX options CTT = 11,000 x 0.05% = 5.50',
  near(est('INDMONEY', PRODUCTS.MCX_OPTION).stt, 5.50), String(est('INDMONEY', PRODUCTS.MCX_OPTION).stt));

console.log('');
console.log('=== No equity-futures product exists, so the old 0.05% bug cannot recur ===');
const products = new Set(Object.values(PRODUCTS));
ok('product list is exactly the six supported types', products.size === 6, [...products].join(','));
ok('no EQ_FUTURE product', !products.has('EQ_FUTURE'));

console.log('');
console.log('=== Brokerage and statutory add-ons ===');
const intraday = est('INDMONEY', PRODUCTS.EQ_INTRADAY);
ok('intraday brokerage = min(0.03%, 20) per leg = 6.30', near(intraday.brokerage, 6.30), String(intraday.brokerage));
ok('SEBI = 21,000 x Rs10/crore = 0.02', near(intraday.sebi, 0.02), String(intraday.sebi));
ok('GST = 18% of brokerage + exchange + SEBI',
  near(intraday.gst, (intraday.brokerage + intraday.exchange_txn + intraday.sebi) * 0.18));

const opt = est('INDMONEY', PRODUCTS.INDEX_OPTION);
ok('options brokerage = flat Rs20 x 2 legs = 40', near(opt.brokerage, 40), String(opt.brokerage));

console.log('');
console.log('=== Delivery DP charges differ by broker ===');
ok('INDmoney delivery DP = 14.75', near(est('INDMONEY', PRODUCTS.EQ_DELIVERY).dp_charges, 14.75));
ok('Zerodha delivery DP = 15.34', near(est('ZERODHA', PRODUCTS.EQ_DELIVERY).dp_charges, 15.34));
// The exchange charge is set by NSE, not the broker, so it must be IDENTICAL.
// The old assertion demanded they differ, which locked in a wrong INDmoney rate.
ok('exchange charge is broker-independent (NSE sets it)',
  near(est('ZERODHA', PRODUCTS.EQ_DELIVERY).exchange_txn, est('INDMONEY', PRODUCTS.EQ_DELIVERY).exchange_txn),
  `${est('ZERODHA', PRODUCTS.EQ_DELIVERY).exchange_txn} vs ${est('INDMONEY', PRODUCTS.EQ_DELIVERY).exchange_txn}`);

console.log('');
console.log('=== 3-Pillar delivery calculators (App.jsx) ===');
const ind = calculateINDmoneyCharges({ entry_price: 100, exit_price: 110, quantity: 100 });
const kite = calculateKiteDeliveryCharges({ entry_price: 100, exit_price: 110, quantity: 100 });
ok('INDmoney STT = 0.1% buy + 0.1% sell = 21.00', near(ind.stt, 21.00), String(ind.stt));
ok('INDmoney zero brokerage', ind.brokerage === 0);
ok('INDmoney DP 14.75 charged only on exit', near(ind.dp_charges, 14.75));
ok('Kite STT = 21.00', near(kite.stt, 21.00), String(kite.stt));
ok('Kite DP 15.34', near(kite.dp_charges, 15.34));
ok('open position charges no DP',
  calculateINDmoneyCharges({ entry_price: 100, exit_price: 0, quantity: 100 }).dp_charges === 0);
ok('net = gross - total charges', near(ind.net_pnl, ind.gross_pnl - ind.total));

console.log('');
console.log('='.repeat(56));
console.log('  ' + pass + ' passed, ' + fail + ' failed');
console.log('='.repeat(56));
process.exit(fail === 0 ? 0 : 1);
