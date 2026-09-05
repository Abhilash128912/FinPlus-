import { DEFAULT_CONFIG, BRIEF_DEFAULTS } from '../risk_model.js';
import {
  buildAccrualState, dailyRateFor, checkAccrualGate, describeOutcome,
  accrualDays, addDays, addAccrualDays, isWeekendIso, unlockThresholdFor,
  ACCRUAL_LANES, openingDeductionFor, slPercentFor, targetPercentFor
} from '../accrual_engine.js';

let pass = 0, fail = 0;
const ok = (n, c, x = '') => { if (c) { pass++; console.log(`  PASS  ${n}`); } else { fail++; console.log(`  FAIL  ${n} ${x}`); } };
const near = (a, b, t = 0.02) => Math.abs(a - b) <= t;

const cfg = { ...DEFAULT_CONFIG, ...BRIEF_DEFAULTS, configured: true, accrualStartDate: '2026-09-07',
  accrualDivisor: 30, accrualBasis: 'CALENDAR',
  allocations: { ...BRIEF_DEFAULTS.allocations, CRUDE: 1000 }, reserveAllocation: 1000,
  openingDeductions: { INTRADAY: 0, LONG_TERM: 0, INDEX_OPTIONS: 0, NATURAL_GAS: 0, STOCK_OPTIONS: 0, SWING: 0, CRUDE: 0 } };
const trade = (o) => ({ status: 'CLOSED', exit_price: 1, ...o });
const loss = (seg, date, amt) => trade({ id: `L${seg}${date}`, segment: seg, exit_date: date, entry_date: date, _pnl: { net: -amt } });
const win = (seg, date, amt) => trade({ id: `W${seg}${date}`, segment: seg, exit_date: date, entry_date: date, _pnl: { net: amt } });

console.log('\n=== 1. Daily rates match the split ===');
ok('Intraday 750/30 = 25', dailyRateFor('INTRADAY', cfg) === 25);
ok('Long Term 1500/30 = 50', dailyRateFor('LONG_TERM', cfg) === 50);
ok('Index Options 1250/30 = 41.67', near(dailyRateFor('INDEX_OPTIONS', cfg), 41.67));
ok('Natural Gas 1000/30 = 33.33', near(dailyRateFor('NATURAL_GAS', cfg), 33.33));
ok('Swing 1000/30 = 33.33', near(dailyRateFor('SWING', cfg), 33.33));
ok('Reserve 1000/30 = 33.33', near(dailyRateFor('OPPORTUNITY_RESERVE', cfg), 33.33));
ok('8 lanes total (CRUDE added)', ACCRUAL_LANES.length === 8, String(ACCRUAL_LANES.length));
const dailyPot = ACCRUAL_LANES.reduce((s, id) => s + dailyRateFor(id, cfg), 0);
ok('pinned drip = 283.33/day', near(dailyPot, 8500/30, 0.05), String(dailyPot));

console.log('\n=== 2. Date maths ===');
ok('same day inclusive = 1', accrualDays('2026-09-07', '2026-09-07', true) === 1);
ok('same day exclusive = 0', accrualDays('2026-09-07', '2026-09-07', false) === 0);
ok('4 days inclusive', accrualDays('2026-09-07', '2026-09-10', true) === 4);
ok('never negative', accrualDays('2026-09-10', '2026-09-07', true) === 0);
ok('addDays crosses month', addDays('2026-09-30', 1) === '2026-10-01');

console.log('\n=== 3. Unlock timing matches the table ===');
const at = (d, trades = []) => buildAccrualState({ trades, config: cfg, asOf: d });

const d1 = at('2026-09-07');
ok('day 1: Intraday = 25', d1.byId.INTRADAY.counter === 25);
ok('day 1: Intraday locked (needs 100)', d1.byId.INTRADAY.unlocked === false);
ok('day 1: 3 more days to unlock', d1.byId.INTRADAY.daysToUnlock === 3, String(d1.byId.INTRADAY.daysToUnlock));
ok('day 1: unlock date 2026-09-10', d1.byId.INTRADAY.unlockDate === '2026-09-10', d1.byId.INTRADAY.unlockDate);

const d4 = at('2026-09-10');
ok('day 4: Intraday = 100', d4.byId.INTRADAY.counter === 100);
ok('day 4: Intraday UNLOCKED', d4.byId.INTRADAY.unlocked === true);
ok('day 4: Index Options still locked', d4.byId.INDEX_OPTIONS.unlocked === false);

const d5 = at('2026-09-11');
ok('day 5: Long Term = 250, unlocked', d5.byId.LONG_TERM.counter === 250 && d5.byId.LONG_TERM.unlocked === true);

const d6 = at('2026-09-12');
ok('day 6: Index Options = 250.02, unlocked', d6.byId.INDEX_OPTIONS.unlocked === true, String(d6.byId.INDEX_OPTIONS.counter));

const d8 = at('2026-09-14');
ok('day 8: Natural Gas unlocked', d8.byId.NATURAL_GAS.unlocked === true, String(d8.byId.NATURAL_GAS.counter));
ok('day 7: Natural Gas still locked', at('2026-09-13').byId.NATURAL_GAS.unlocked === false);

console.log('\n=== 4. WIN keeps the counter ===');
const afterWin = at('2026-09-14', [win('INTRADAY', '2026-09-10', 500)]);
ok('win does NOT reset counter', afterWin.byId.INTRADAY.counter === 200, String(afterWin.byId.INTRADAY.counter));
ok('win keeps it unlocked', afterWin.byId.INTRADAY.unlocked === true);
ok('win does not touch capital', afterWin.byId.INTRADAY.capital === 200, String(afterWin.byId.INTRADAY.capital));
ok('win counted in record', afterWin.byId.INTRADAY.winCount === 1 && afterWin.byId.INTRADAY.lossCount === 0);
ok('describeOutcome win = RETAINED', describeOutcome({ segment: 'INTRADAY', _pnl: { net: 500 } }, cfg).counterEffect === 'RETAINED');

console.log('\n=== 5. LOSS resets counter + hits capital ===');
const afterLoss = at('2026-09-14', [loss('INTRADAY', '2026-09-10', 120)]);
// lost on day 4; counter restarts day 5..8 = 4 days x 25 = 100
ok('counter restarts day AFTER the loss', afterLoss.byId.INTRADAY.counter === 100, String(afterLoss.byId.INTRADAY.counter));
ok('loss day itself credits nothing', at('2026-09-10', [loss('INTRADAY', '2026-09-10', 120)]).byId.INTRADAY.counter === 0);
ok('capital = accrued 200 - loss 120 = 80', afterLoss.byId.INTRADAY.capital === 80, String(afterLoss.byId.INTRADAY.capital));
ok('accrued total unaffected by loss', afterLoss.byId.INTRADAY.totalAccrued === 200);
ok('loss booked to segment', afterLoss.byId.INTRADAY.lossTotal === 120);
ok('lastLossDate recorded', afterLoss.byId.INTRADAY.lastLossDate === '2026-09-10');
ok('describeOutcome loss = RESET', describeOutcome({ segment: 'INTRADAY', _pnl: { net: -120 } }, cfg).counterEffect === 'RESET');
ok('capital effect is the ACTUAL net loss', describeOutcome({ segment: 'INTRADAY', _pnl: { net: -120 } }, cfg).capitalEffect === -120);

const twoLosses = at('2026-09-20', [loss('INTRADAY', '2026-09-10', 100), loss('INTRADAY', '2026-09-16', 90)]);
ok('most recent loss drives the reset', twoLosses.byId.INTRADAY.lastLossDate === '2026-09-16');
ok('counter = 4 days since 16th = 100', twoLosses.byId.INTRADAY.counter === 100, String(twoLosses.byId.INTRADAY.counter));
ok('both losses hit capital (350-190=160)', twoLosses.byId.INTRADAY.capital === 160, String(twoLosses.byId.INTRADAY.capital));

console.log('\n=== 6. Long Term is exempt ===');
const ltLoss = at('2026-09-20', [loss('LONG_TERM', '2026-09-12', 400)]);
ok('LT counter NOT reset by a loss', ltLoss.byId.LONG_TERM.counter === 700, String(ltLoss.byId.LONG_TERM.counter));
ok('LT capital NOT reduced', ltLoss.byId.LONG_TERM.capital === 700, String(ltLoss.byId.LONG_TERM.capital));
ok('LT booked losses = 0', ltLoss.byId.LONG_TERM.lossTotal === 0);
ok('LT loss still visible as unbooked', ltLoss.byId.LONG_TERM.unbookedLossTotal === 400);
ok('LT lastLossDate stays null', ltLoss.byId.LONG_TERM.lastLossDate === null);
ok('LT booksLosses flag false', ltLoss.byId.LONG_TERM.booksLosses === false);
ok('describeOutcome LT loss exempt', describeOutcome({ segment: 'LONG_TERM', _pnl: { net: -400 } }, cfg).counterEffect === 'RETAINED');
// contrast: same loss in a booking segment
ok('non-LT segment DOES reset', at('2026-09-20', [loss('SWING', '2026-09-12', 400)]).byId.SWING.lastLossDate === '2026-09-12');

console.log('\n=== 7. No monthly reset — accrual is continuous ===');
const oct = at('2026-10-07');
ok('31 days in: Intraday = 775', oct.byId.INTRADAY.counter === 775, String(oct.byId.INTRADAY.counter));
ok('crosses month boundary without reset', oct.byId.INTRADAY.totalDays === 31, String(oct.byId.INTRADAY.totalDays));
const nov = at('2026-11-07');
ok('62 days in: keeps growing', nov.byId.INTRADAY.counter === 1550, String(nov.byId.INTRADAY.counter));

console.log('\n=== 8. Before the start date nothing accrues ===');
const early = at('2026-09-01');
ok('not started', early.started === false);
ok('counter 0 before start', early.byId.INTRADAY.counter === 0);
ok('capital 0 before start', early.byId.INTRADAY.capital === 0);
const noStart = buildAccrualState({ trades: [], config: { ...cfg, accrualStartDate: null }, asOf: '2026-09-20' });
ok('no start date = not started', noStart.started === false);

console.log('\n=== 9. The trade gate ===');
const g4 = checkAccrualGate({ laneId: 'INTRADAY', plannedTotalRisk: 100, accrualState: d4, config: cfg });
ok('unlocked + risk within counter => allowed', g4.ok, JSON.stringify(g4.reasons.map(r => r.code)));

const g1 = checkAccrualGate({ laneId: 'INTRADAY', plannedTotalRisk: 100, accrualState: d1, config: cfg });
ok('locked counter blocks', !g1.ok && g1.reasons.some(r => r.code === 'COUNTER_LOCKED'));
ok('block message names the shortfall', /₹75\.00 short/.test(g1.reasons.find(r => r.code === 'COUNTER_LOCKED').message),
  g1.reasons.find(r => r.code === 'COUNTER_LOCKED')?.message);

const gBig = checkAccrualGate({ laneId: 'INTRADAY', plannedTotalRisk: 500, accrualState: d4, config: cfg });
ok('cannot risk more than accrued', !gBig.ok && gBig.reasons.some(r => r.code === 'RISK_EXCEEDS_COUNTER'));

// Neither a rupee stop nor a percentage stop: nothing to unlock against.
const bareCfg = {
  ...cfg,
  segmentSL: { ...cfg.segmentSL, SWING: null },
  segmentSLPercent: { ...(cfg.segmentSLPercent || {}), SWING: null }
};
const gNoSL = checkAccrualGate({
  laneId: 'SWING', plannedTotalRisk: 50,
  accrualState: buildAccrualState({ trades: [], config: bareCfg, asOf: '2026-09-20' }),
  config: bareCfg
});
ok('no stop-loss at all => cannot unlock', !gNoSL.ok && gNoSL.reasons.some(r => r.code === 'NO_THRESHOLD'));

const gEarly = checkAccrualGate({ laneId: 'INTRADAY', plannedTotalRisk: 10, accrualState: early, config: cfg });
ok('before start date => blocked', !gEarly.ok && gEarly.reasons.some(r => r.code === 'ACCRUAL_NOT_STARTED'));

console.log('\n=== 10. Loss locks you out for exactly the right number of days ===');
const lossDay = '2026-09-20';
const relock = at(lossDay, [loss('INTRADAY', lossDay, 100)]);
ok('day of loss: counter 0, locked', relock.byId.INTRADAY.counter === 0 && relock.byId.INTRADAY.unlocked === false);
ok('needs 4 days again', relock.byId.INTRADAY.daysToUnlock === 4, String(relock.byId.INTRADAY.daysToUnlock));
const relock4 = at('2026-09-24', [loss('INTRADAY', lossDay, 100)]);
ok('4 days later: unlocked again', relock4.byId.INTRADAY.unlocked === true && relock4.byId.INTRADAY.counter === 100);

console.log('\n=== 11. Capital can go negative and is flagged ===');
const deep = at('2026-09-10', [loss('INTRADAY', '2026-09-09', 500)]);
ok('capital negative after a big loss', deep.byId.INTRADAY.capital < 0, String(deep.byId.INTRADAY.capital));
ok('accrued still positive', deep.byId.INTRADAY.totalAccrued === 100);



console.log('');
console.log('=== 12. Opening deduction (the old September 2,000) ===');
const briefCfg = { ...DEFAULT_CONFIG, ...BRIEF_DEFAULTS, configured: true, accrualStartDate: '2026-09-07',
  accrualDivisor: 30, accrualBasis: 'CALENDAR' };
ok('brief puts 2000 on Long Term', openingDeductionFor('LONG_TERM', briefCfg) === 2000);
ok('other segments have none', openingDeductionFor('INTRADAY', briefCfg) === 0);

const od = buildAccrualState({ trades: [], config: briefCfg, asOf: '2026-09-11' });
ok('LT counter ignores the deduction', od.byId.LONG_TERM.counter === 250, String(od.byId.LONG_TERM.counter));
ok('LT still unlocks normally', od.byId.LONG_TERM.unlocked === true);
ok('LT capital = 250 - 2000 = -1750', od.byId.LONG_TERM.capital === -1750, String(od.byId.LONG_TERM.capital));
ok('LT accrued total unchanged', od.byId.LONG_TERM.totalAccrued === 250);
ok('deduction exposed on the lane', od.byId.LONG_TERM.openingDeduction === 2000);
ok('total deductions rolled up', od.totalOpeningDeductions === 2000);
ok('Intraday untouched by LT deduction', od.byId.INTRADAY.capital === od.byId.INTRADAY.totalAccrued);
ok('deduction does NOT reset the counter', od.byId.LONG_TERM.lastLossDate === null);

const worked = buildAccrualState({ trades: [], config: briefCfg, asOf: '2026-10-16' });
ok('LT capital reaches zero after 40 days of accrual', worked.byId.LONG_TERM.capital === 0, String(worked.byId.LONG_TERM.capital));

console.log('');
console.log('=== 13. Weekday-only accrual (Sat/Sun skipped) ===');
ok('2026-09-05 is a Saturday', isWeekendIso('2026-09-05'));
ok('2026-09-06 is a Sunday', isWeekendIso('2026-09-06'));
ok('2026-09-04 is a weekday', !isWeekendIso('2026-09-04'));
ok('Fri start, same day = 1', accrualDays('2026-09-04', '2026-09-04', true, 'WEEKDAYS') === 1);
ok('Saturday adds nothing', accrualDays('2026-09-04', '2026-09-05', true, 'WEEKDAYS') === 1);
ok('Sunday adds nothing', accrualDays('2026-09-04', '2026-09-06', true, 'WEEKDAYS') === 1);
ok('Monday is day 2', accrualDays('2026-09-04', '2026-09-07', true, 'WEEKDAYS') === 2);
ok('Fri->Fri = 6 trading days', accrualDays('2026-09-04', '2026-09-11', true, 'WEEKDAYS') === 6);
ok('a full week = 5', accrualDays('2026-09-07', '2026-09-13', true, 'WEEKDAYS') === 5);
ok('calendar basis still counts weekends', accrualDays('2026-09-04', '2026-09-07', true, 'CALENDAR') === 4);
ok('addAccrualDays skips the weekend', addAccrualDays('2026-09-04', 1, 'WEEKDAYS') === '2026-09-07', addAccrualDays('2026-09-04', 1, 'WEEKDAYS'));
ok('addAccrualDays 5 = next Friday', addAccrualDays('2026-09-04', 5, 'WEEKDAYS') === '2026-09-11', addAccrualDays('2026-09-04', 5, 'WEEKDAYS'));

const wkCfg = { ...DEFAULT_CONFIG, ...BRIEF_DEFAULTS, configured: true, accrualStartDate: '2026-09-04' };
const wkSat = buildAccrualState({ trades: [], config: wkCfg, asOf: '2026-09-05' });
const wkMon = buildAccrualState({ trades: [], config: wkCfg, asOf: '2026-09-07' });
ok('weekend flagged', wkSat.isWeekendToday === true);
const wkFri = buildAccrualState({ trades: [], config: wkCfg, asOf: '2026-09-04' });
const wkSun = buildAccrualState({ trades: [], config: wkCfg, asOf: '2026-09-06' });
ok('Saturday counter equals Friday', wkSat.byId.INTRADAY.counter === wkFri.byId.INTRADAY.counter, `${wkSat.byId.INTRADAY.counter} vs ${wkFri.byId.INTRADAY.counter}`);
ok('Sunday counter equals Friday', wkSun.byId.INTRADAY.counter === wkFri.byId.INTRADAY.counter);
ok('weekend days do not increment totalDays', wkSat.byId.INTRADAY.totalDays === 1 && wkSun.byId.INTRADAY.totalDays === 1);
ok('Monday advances the counter', wkMon.byId.INTRADAY.totalDays === 2, String(wkMon.byId.INTRADAY.totalDays));
ok('basis reported', wkMon.basis === 'WEEKDAYS');

console.log('');
console.log('=== 14. Live config: 7500 over 22 trading days, CRUDE included ===');
const liveCfg = { ...DEFAULT_CONFIG, ...BRIEF_DEFAULTS, configured: true };
ok('divisor is 22', liveCfg.accrualDivisor === 22);
ok('basis is WEEKDAYS', liveCfg.accrualBasis === 'WEEKDAYS');
ok('starts today 2026-09-04', liveCfg.accrualStartDate === '2026-09-04');
ok('CRUDE allocation 500', liveCfg.allocations.CRUDE === 500);
ok('Reserve halved to 500', liveCfg.reserveAllocation === 500);
ok('CRUDE SL 250', liveCfg.segmentSL.CRUDE === 250);
ok('CRUDE broker INDmoney', liveCfg.segmentBroker.CRUDE === 'INDMONEY');
ok('CRUDE books losses', liveCfg.booksLosses.CRUDE === true);
const liveTotal = ACCRUAL_LANES.reduce((s2, id) => s2 + dailyRateFor(id, liveCfg), 0);
ok('daily drip 340.91 (7500/22)', near(liveTotal, 7500 / 22, 0.01), String(liveTotal));
ok('Intraday 34.09/day', near(dailyRateFor('INTRADAY', liveCfg), 34.09));
ok('Long Term 68.18/day', near(dailyRateFor('LONG_TERM', liveCfg), 68.18));
ok('CRUDE 22.73/day', near(dailyRateFor('CRUDE', liveCfg), 22.73));

const L = (d) => buildAccrualState({ trades: [], config: liveCfg, asOf: d });
ok('Fri 04 Sep: Intraday locked', L('2026-09-04').byId.INTRADAY.unlocked === false);
ok('Mon 07 Sep: still locked (68.18)', L('2026-09-07').byId.INTRADAY.unlocked === false, String(L('2026-09-07').byId.INTRADAY.counter));
ok('Tue 08 Sep: Intraday UNLOCKS (102.27)', L('2026-09-08').byId.INTRADAY.unlocked === true, String(L('2026-09-08').byId.INTRADAY.counter));
ok('Intraday needs 3 trading days', Math.ceil(100 / dailyRateFor('INTRADAY', liveCfg)) === 3);
ok('Long Term needs 4', Math.ceil(250 / dailyRateFor('LONG_TERM', liveCfg)) === 4);
ok('Index Options needs 5', Math.ceil(250 / dailyRateFor('INDEX_OPTIONS', liveCfg)) === 5);
ok('Natural Gas needs 6', Math.ceil(250 / dailyRateFor('NATURAL_GAS', liveCfg)) === 6);
ok('CRUDE needs 11', Math.ceil(250 / dailyRateFor('CRUDE', liveCfg)) === 11);
ok('CRUDE lane exists in state', !!L('2026-09-08').byId.CRUDE);
ok('unlock date skips the weekend', L('2026-09-04').byId.INTRADAY.unlockDate === '2026-09-08', L('2026-09-04').byId.INTRADAY.unlockDate);

console.log('');
console.log('');
console.log('=== 15. Swing: percentage stop-loss and target ===');
ok('Swing SL is 5%', slPercentFor('SWING', liveCfg) === 5);
ok('Swing target is 5%', targetPercentFor('SWING', liveCfg) === 5);
ok('Swing has no rupee SL', liveCfg.segmentSL.SWING === null);
ok('rupee segments have no percentage', slPercentFor('INTRADAY', liveCfg) === null);

const sw = L('2026-09-04').byId.SWING;
ok('Swing has no fixed threshold', sw.threshold === null);
ok('Swing unlocks on any accrual', sw.unlocked === true);
ok('Swing needs no waiting days', sw.daysToUnlock === 0);
ok('Swing exposes slPercent', sw.slPercent === 5);
// 45.45 accrued at a 5% stop supports a 45.45 / 0.05 = 909.09 position
ok('max position = counter / 5%', near(sw.maxPositionValue, sw.counter / 0.05, 0.05), String(sw.maxPositionValue));

const swDay3 = L('2026-09-08').byId.SWING;
ok('bigger counter allows a bigger position', swDay3.maxPositionValue > sw.maxPositionValue);
ok('Swing gate passes within the counter',
  checkAccrualGate({ laneId: 'SWING', plannedTotalRisk: sw.counter - 1, accrualState: L('2026-09-04'), config: liveCfg }).ok);
ok('Swing gate blocks beyond the counter',
  !checkAccrualGate({ laneId: 'SWING', plannedTotalRisk: sw.counter + 500, accrualState: L('2026-09-04'), config: liveCfg }).ok);
ok('Swing never reports NO_THRESHOLD',
  !checkAccrualGate({ laneId: 'SWING', plannedTotalRisk: 10, accrualState: L('2026-09-04'), config: liveCfg })
    .reasons.some(r => r.code === 'NO_THRESHOLD'));

// A 5% stop on a 100 entry sits at 95 long / 105 short; target mirrors it.
const entry = 100;
ok('long stop = entry - 5%', Number((entry * (1 - 5 / 100)).toFixed(2)) === 95);
ok('long target = entry + 5%', Number((entry * (1 + 5 / 100)).toFixed(2)) === 105);
ok('short stop = entry + 5%', Number((entry * (1 + 5 / 100)).toFixed(2)) === 105);

console.log('');
console.log('=== 16. A future trade must not affect an earlier day ===');
const futureLoss = [{
  id: 'F', segment: 'INTRADAY', status: 'CLOSED', exit_price: 1,
  entry_date: '2026-09-09', exit_date: '2026-09-09', _pnl: { net: -118.40 }
}];
const beforeIt = buildAccrualState({ trades: futureLoss, config: liveCfg, asOf: '2026-09-08' }).byId.INTRADAY;
const onIt = buildAccrualState({ trades: futureLoss, config: liveCfg, asOf: '2026-09-09' }).byId.INTRADAY;
const afterIt = buildAccrualState({ trades: futureLoss, config: liveCfg, asOf: '2026-09-10' }).byId.INTRADAY;

ok('counter unaffected the day before the loss', near(beforeIt.counter, 102.27), String(beforeIt.counter));
ok('capital unaffected the day before the loss', near(beforeIt.capital, 102.27), String(beforeIt.capital));
ok('segment is unlocked before the loss', beforeIt.unlocked === true);
ok('no lastLossDate before the loss', beforeIt.lastLossDate === null);
ok('booked losses are zero before the loss', beforeIt.lossTotal === 0);

ok('counter resets on the loss day', onIt.counter === 0, String(onIt.counter));
ok('capital drops on the loss day', near(onIt.capital, 136.36 - 118.40), String(onIt.capital));
ok('loss is booked from that day', near(onIt.lossTotal, 118.40));
ok('accrual restarts the next day', near(afterIt.counter, 34.09), String(afterIt.counter));

console.log('='.repeat(52));
console.log('  ' + pass + ' passed, ' + fail + ' failed');
console.log('='.repeat(52));
process.exit(fail === 0 ? 0 : 1);