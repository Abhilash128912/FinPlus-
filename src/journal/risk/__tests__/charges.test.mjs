/**
 * Statutory charge rates. These are legal figures, not preferences, so they get
 * pinned: a silent drift here misstates every planned risk and net P&L.
 */
import { calculateZerodhaCharges } from '../../journal_engine.js';

let pass = 0, fail = 0;
const ok = (n, c, x = '') => { if (c) { pass++; console.log(`  PASS  ${n}`); } else { fail++; console.log(`  FAIL  ${n} ${x}`); } };
const near = (a, b, t = 0.01) => Math.abs(a - b) <= t;

console.log('');
console.log('=== Equity F&O futures: STT is 0.02% of sell turnover ===');
// 1 lot, entry 100 -> exit 110, qty 100. Sell turnover = 11,000.
const fut = calculateZerodhaCharges({
  instrument_type: 'NIFTY Futures', entry_price: 100, exit_price: 110, quantity: 100
});
ok('futures STT = 11000 * 0.0002 = 2.20', near(fut.stt, 2.20), String(fut.stt));
ok('futures STT is NOT the old 0.05% (5.50)', !near(fut.stt, 5.50), String(fut.stt));

console.log('');
console.log('=== Equity F&O options: STT is 0.1% of sell premium ===');
const opt = calculateZerodhaCharges({
  instrument_type: 'NIFTY Options CE', entry_price: 100, exit_price: 110, quantity: 100
});
ok('options STT = 11000 * 0.001 = 11.00', near(opt.stt, 11.00), String(opt.stt));

console.log('');
console.log('=== MCX commodities keep CTT, not STT ===');
const cf = calculateZerodhaCharges({
  instrument_type: 'Crude Futures', symbol: 'CRUDEOIL', entry_price: 100, exit_price: 110, quantity: 100
});
ok('commodity futures CTT = 11000 * 0.0001 = 1.10', near(cf.stt, 1.10), String(cf.stt));

const co = calculateZerodhaCharges({
  instrument_type: 'Crude Options CE', symbol: 'CRUDEOIL', entry_price: 100, exit_price: 110, quantity: 100
});
ok('commodity options CTT = 11000 * 0.0005 = 5.50', near(co.stt, 5.50), String(co.stt));

console.log('');
console.log('=== Equity cash segment ===');
const intra = calculateZerodhaCharges({
  instrument_type: 'Intraday', entry_price: 100, exit_price: 110, quantity: 100
});
ok('intraday STT = 11000 * 0.00025 = 2.75', near(intra.stt, 2.75), String(intra.stt));

const deliv = calculateZerodhaCharges({
  instrument_type: 'Delivery', entry_price: 100, exit_price: 110, quantity: 100
});
ok('delivery STT = 21000 * 0.001 = 21.00', near(deliv.stt, 21.00), String(deliv.stt));

console.log('');
console.log('=== GST is 18% of brokerage + exchange + SEBI ===');
ok('GST composition', near(deliv.gst, (deliv.brokerage + deliv.exchange_txn + deliv.sebi) * 0.18));

console.log('');
console.log('='.repeat(52));
console.log('  ' + pass + ' passed, ' + fail + ' failed');
console.log('='.repeat(52));
process.exit(fail === 0 ? 0 : 1);
