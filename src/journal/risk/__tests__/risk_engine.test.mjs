import {
  SEGMENTS, BRIEF_DEFAULTS, DEFAULT_CONFIG, generateMonths, allocationBalance,
  plannedPriceRisk, grossPnl, netPnl, monthlyRiskRemaining, brokerCashBalance, gradeFromScore
} from '../risk_model.js';
import { SEED_CHARGE_PROFILES, estimateCharges, resolveChargeProfile } from '../broker_profiles.js';
import { buildMonthView, buildDailySnapshot, buildAccountView, computePlannedRisk } from '../risk_engine.js';
import { validateTradeEntry } from '../validation.js';
import { scoreSetup, evaluateDay, assessCorrelation } from '../scoring.js';
import { buildAccrualState } from '../accrual_engine.js';

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => {
  if (cond) { pass++; console.log(`  PASS  ${name}`); }
  else { fail++; console.log(`  FAIL  ${name} ${extra}`); }
};
const near = (a, b, tol = 0.02) => Math.abs(a - b) <= tol;

console.log('\n=== 1. Fresh install starts at zero ===');
ok('config not configured', DEFAULT_CONFIG.configured === false);
ok('monthly budget is 0', DEFAULT_CONFIG.monthlyRiskBudget === 0);
ok('all allocations 0', SEGMENTS.every(s => DEFAULT_CONFIG.allocations[s.id] === 0));
ok('all SLs null', SEGMENTS.every(s => DEFAULT_CONFIG.segmentSL[s.id] === null));
ok('opening deductions all zero', SEGMENTS.every(x => DEFAULT_CONFIG.openingDeductions[x.id] === 0));
ok('daily limit 0', DEFAULT_CONFIG.dailyRiskLimit === 0);

const zeroMonths = generateMonths(DEFAULT_CONFIG);
ok('zero-config months all zero budget', zeroMonths.every(m => m.monthly_risk_budget === 0));

console.log('\n=== 2. Month generation (with brief values applied) ===');
const cfg = { ...DEFAULT_CONFIG, ...BRIEF_DEFAULTS, configured: true };
const months = generateMonths(cfg);
const standard = months.filter(m => m.mode === 'STANDARD');
ok('37 months total (Sep-2026 -> Sep-2029)', months.length === 37, `got ${months.length}`);
ok('all are ordinary reporting months', standard.length === 37, `got ${standard.length}`);
ok('no SPECIAL months remain', months.every(m => m.mode !== 'SPECIAL'));
ok('first month is 2026-09', standard[0].month_key === '2026-09', standard[0].month_key);
ok('last month is 2029-09', standard[36].month_key === '2029-09', standard[36].month_key);
ok('every month budget 7500', standard.every(m => m.monthly_risk_budget === 7500));
ok('September has no pre-existing usage now', standard[0].preexisting_usage === 0);
ok('September has normal buckets', standard[0].buckets.INTRADAY.initial_allocation === 750);

console.log('\n=== 3. Allocations balance to 7500, CRUDE gone, Swing present ===');
const bal = allocationBalance(cfg);
ok('allocations + reserve = 7500', bal.balanced, `sum=${bal.sum}`);
ok('eight segments (CRUDE + PENNY)', SEGMENTS.length === 8, `got ${SEGMENTS.length}`);
ok('CRUDE segment present', SEGMENTS.some(s => s.id === 'CRUDE'));
ok('SWING present', SEGMENTS.some(s => s.id === 'SWING'));
ok('Intraday alloc 750', cfg.allocations.INTRADAY === 750);
ok('Long Term alloc 1150 after Penny carve-out', cfg.allocations.LONG_TERM === 1150);
ok('Penny alloc 350', cfg.allocations.PENNY === 350);
ok('reserve halved to 500 to fund CRUDE', cfg.reserveAllocation === 500);
ok('CRUDE alloc 500', cfg.allocations.CRUDE === 500);
ok('Swing risk matches Intraday at 100', cfg.segmentSL.SWING === 100);
ok('Swing stop is percentage-based', cfg.segmentSLPercent.SWING === 5);
ok('Long Term broker unset', cfg.segmentBroker.LONG_TERM === null);
ok('Intraday/Index/Stock/NatGas -> INDMONEY',
  ['INTRADAY','INDEX_OPTIONS','STOCK_OPTIONS','NATURAL_GAS'].every(k => cfg.segmentBroker[k] === 'INDMONEY'));
ok('Swing -> ZERODHA', cfg.segmentBroker.SWING === 'ZERODHA');

console.log('\n=== 4. Broker charge profiles (effective dated) ===');
ok('INDmoney profile resolves', !!resolveChargeProfile(SEED_CHARGE_PROFILES, 'INDMONEY', '2026-09-04'));
ok('no profile before effective date', !resolveChargeProfile(SEED_CHARGE_PROFILES, 'INDMONEY', '2026-01-01'));
ok('unknown broker -> null', !resolveChargeProfile(SEED_CHARGE_PROFILES, 'UPSTOX', '2026-09-04'));

const intradayCharges = estimateCharges({
  profiles: SEED_CHARGE_PROFILES, broker: 'INDMONEY', product: 'EQ_INTRADAY',
  entryPrice: 100, exitPrice: 99, quantity: 100, lotSize: 1, date: '2026-09-04'
});
// buy 10000 -> brokerage min(3,20)=3 ; sell 9900 -> min(2.97,20)=2.97 ; total 5.97
ok('intraday brokerage capped by pct', near(intradayCharges.breakdown.brokerage, 5.97), JSON.stringify(intradayCharges.breakdown));
ok('intraday STT on sell only', near(intradayCharges.breakdown.stt, 9900 * 0.00025));
ok('GST is 18% of brokerage+exch+sebi',
  near(intradayCharges.breakdown.gst,
    (intradayCharges.breakdown.brokerage + intradayCharges.breakdown.exchange_txn + intradayCharges.breakdown.sebi) * 0.18));
ok('intraday has no DP charge', intradayCharges.breakdown.dp_charges === 0);

const optCharges = estimateCharges({
  profiles: SEED_CHARGE_PROFILES, broker: 'INDMONEY', product: 'INDEX_OPTION',
  entryPrice: 100, exitPrice: 90, quantity: 2, lotSize: 75, date: '2026-09-04'
});
ok('option brokerage flat 20 x 2 legs', near(optCharges.breakdown.brokerage, 40), String(optCharges.breakdown.brokerage));
ok('option lot size multiplies turnover', near(optCharges.breakdown.stt, 90 * 150 * 0.001), String(optCharges.breakdown.stt));

const zerDeliv = estimateCharges({
  profiles: SEED_CHARGE_PROFILES, broker: 'ZERODHA', product: 'EQ_DELIVERY',
  entryPrice: 500, exitPrice: 520, quantity: 10, date: '2026-09-04'
});
ok('zerodha delivery zero brokerage', zerDeliv.breakdown.brokerage === 0);
ok('zerodha delivery DP 15.34 on exit', near(zerDeliv.breakdown.dp_charges, 15.34));

const noProfile = estimateCharges({
  profiles: SEED_CHARGE_PROFILES, broker: null, product: 'EQ_INTRADAY',
  entryPrice: 100, quantity: 10, date: '2026-09-04'
});
ok('missing broker returns an error', !!noProfile.error && noProfile.total === 0);

console.log('\n=== 5. Formulas ===');
ok('planned price risk uses lot size', plannedPriceRisk({ entry_price: 100, stop_loss_price: 95, quantity: 2, lot_size: 75 }) === 750);
ok('gross pnl long', grossPnl({ entry_price: 100, exit_price: 110, quantity: 10, direction: 'LONG' }) === 100);
ok('gross pnl short', grossPnl({ entry_price: 100, exit_price: 90, quantity: 10, direction: 'SHORT' }) === 100);
ok('net = gross - charges', netPnl(100, 23.5) === 76.5);
ok('monthly remaining subtracts pre-existing',
  monthlyRiskRemaining({ monthly_risk_budget: 4000, preexisting_usage: 2000, committed_planned_risk: 500 }) === 1500);
ok('broker cash formula', brokerCashBalance({
  opening_cash: 1000, deposits: 500, realized_net_pnl: 200,
  withdrawals: 100, transfers_to_growth_reserve: 50, releases_from_growth_reserve: 25
}) === 1575);
ok('grade A+ at 90', gradeFromScore(90).id === 'A_PLUS');
ok('grade A at 80', gradeFromScore(80).id === 'A');
ok('grade B at 79 not eligible', gradeFromScore(79).eligible === false);

console.log('\n=== 6. Month view: committed risk, live P&L, drawdown ===');
const trades = [
  { id: 't1', segment: 'INTRADAY', symbol: 'SBIN', direction: 'LONG', entry_date: '2026-10-05T09:20:00Z',
    entry_price: 100, stop_loss_price: 99, target_price: 103, quantity: 100, lot_size: 1,
    status: 'CLOSED', exit_price: 102, exit_date: '2026-10-05T14:00:00Z', planned_total_risk: 106 },
  { id: 't2', segment: 'SWING', symbol: 'TCS', direction: 'LONG', entry_date: '2026-10-06T09:30:00Z',
    entry_price: 3000, stop_loss_price: 2950, target_price: 3150, quantity: 5, lot_size: 1,
    status: 'OPEN', planned_total_risk: 285 }
];
const octMonth = months.find(m => m.month_key === '2026-10');
const mv = buildMonthView({ month: octMonth, trades, reserveTransfers: [], profiles: SEED_CHARGE_PROFILES, config: cfg, ltps: { TCS: 3100 } });

ok('month view picks up 2 trades', mv.trades.length === 2);
ok('1 open, 1 closed', mv.openTrades.length === 1 && mv.closedTrades.length === 1);
const intraSeg = mv.segments.find(s => s.id === 'INTRADAY');
const swingSeg = mv.segments.find(s => s.id === 'SWING');
ok('intraday allocation 750', intraSeg.initialAllocation === 750);
ok('intraday committed > 0', intraSeg.committedRisk > 0, String(intraSeg.committedRisk));
ok('intraday remaining = 750 - committed', near(intraSeg.remainingRisk, 750 - intraSeg.committedRisk));
ok('closed trade gross = +200', near(mv.closedTrades[0]._pnl.gross, 200), String(mv.closedTrades[0]._pnl.gross));
ok('closed net < gross (charges applied)', mv.closedTrades[0]._pnl.net < 200);
ok('open trade has live price', mv.openTrades[0]._pnl.hasLivePrice === true);
ok('live gross on TCS = +500', near(mv.openTrades[0]._pnl.gross, 500), String(mv.openTrades[0]._pnl.gross));
ok('live net < live gross', mv.openTrades[0]._pnl.net < 500);
ok('swing live net rolls up', near(swingSeg.liveNetPnl, mv.openTrades[0]._pnl.net));
ok('win rate 100% (1 winner)', mv.stats.winRate === 100);
ok('monthly remaining reduced', mv.remainingRisk < 7500);
ok('reserve remaining 500 (untouched)', mv.reserve.remaining === 500, String(mv.reserve.remaining));

const noLtp = buildMonthView({ month: octMonth, trades, reserveTransfers: [], profiles: SEED_CHARGE_PROFILES, config: cfg, ltps: {} });
ok('no LTP -> open trade not priced', noLtp.openTrades[0]._pnl.hasLivePrice === false);
ok('no LTP -> live net excluded from total', noLtp.stats.liveNetPnl === 0);

console.log('');
console.log('=== 7. Opening deduction replaces the September pool ===');
ok('brief carries a 2000 Long Term opening deduction', BRIEF_DEFAULTS.openingDeductions.LONG_TERM === 2000);
ok('no september config remains', cfg.september === undefined);
ok('months carry no special mode', !months.some(m => m.mode === 'SPECIAL'));

console.log('\n=== 8. Scoring & grades ===');
const aPlus = scoreSetup({ trend: 20, levels: 20, rr: 15, liquidity: 15, htf: 10, event: 10, segment_rules: 5 });
ok('score sums to 95', aPlus.total === 95);
ok('95 => A+', aPlus.grade === 'A_PLUS' && aPlus.eligibleGrade);
const bGrade = scoreSetup({ trend: 15, levels: 15, rr: 10, liquidity: 10, htf: 8, event: 8, segment_rules: 8 });
ok('74 => B, not eligible', bGrade.total === 74 && bGrade.eligibleGrade === false);
ok('blank categories reported as incomplete', scoreSetup({ trend: 20 }).incomplete.length === 6);
ok('score clamped to category max', scoreSetup({ trend: 999 }).total === 20);

console.log('\n=== 9. Validation blocks ===');
const dailySnap = buildDailySnapshot({ trades: [], profiles: SEED_CHARGE_PROFILES, config: cfg, day: '2026-10-07' });
const baseTrade = {
  segment: 'INTRADAY', symbol: 'SBIN', broker: 'INDMONEY', direction: 'LONG',
  entry_date: '2026-10-07T09:20:00Z', entry_price: 100, stop_loss_price: 99,
  target_price: 103, quantity: 100, lot_size: 1, trade_intent: 'PLANNED_OPPORTUNITY'
};
const vBase = validateTradeEntry({
  trade: baseTrade, score: aPlus, planned: computePlannedRisk(baseTrade, SEED_CHARGE_PROFILES, cfg),
  correlation: { independent: true, conflict: false, warn: false, sameUnderlying: [], sameSector: [] },
  segView: mv.segments.find(s => s.id === 'INTRADAY'), dailySnapshot: dailySnap, monthView: mv,
  profiles: SEED_CHARGE_PROFILES, config: cfg, recentTrades: []
});
ok('valid A+ trade passes', vBase.ok, JSON.stringify(vBase.blocked.map(b => b.code)));

const mk = (patch, over = {}) => validateTradeEntry({
  trade: { ...baseTrade, ...patch }, score: over.score || aPlus,
  planned: computePlannedRisk({ ...baseTrade, ...patch }, SEED_CHARGE_PROFILES, over.config || cfg),
  correlation: over.correlation || { independent: true, conflict: false, warn: false, sameUnderlying: [], sameSector: [] },
  segView: over.segView || mv.segments.find(s => s.id === 'INTRADAY'),
  dailySnapshot: over.dailySnapshot || dailySnap, monthView: over.monthView || mv,
  profiles: SEED_CHARGE_PROFILES, config: over.config || cfg, recentTrades: over.recentTrades || []
});
const codes = v => v.blocked.map(b => b.code);

ok('missing SL blocked', codes(mk({ stop_loss_price: 0 })).includes('NO_SL'));
ok('missing target blocked', codes(mk({ target_price: 0 })).includes('NO_TARGET'));
ok('B grade blocked', codes(mk({}, { score: bGrade })).includes('GRADE'));
ok('missing broker blocked', codes(mk({ broker: null, segment: 'LONG_TERM' })).includes('NO_BROKER'));
ok('revenge intent blocked', codes(mk({ trade_intent: 'RECOVERY' })).includes('REVENGE_INTENT'));
ok('revenge is NOT overridable', mk({ trade_intent: 'RECOVERY' }).canOverride === false);
ok('unconfigured app blocked',
  codes(mk({}, { config: { ...cfg, configured: false } })).includes('NOT_CONFIGURED'));
ok('lot-based segment needs lot size',
  codes(mk({ segment: 'INDEX_OPTIONS', lot_size: 0 })).includes('NO_LOT'));
ok('same-underlying correlation blocked',
  codes(mk({}, { correlation: { independent: false, conflict: true, warn: false, sameUnderlying: [{ symbol: 'SBIN' }], sameSector: [] } })).includes('CORRELATION'));

const swingCfg = { ...cfg, segmentSL: { ...cfg.segmentSL, SWING: null } };
ok('swing with no SL config but explicit SL is fine',
  !codes(mk({ segment: 'SWING', broker: 'ZERODHA' }, { config: swingCfg, segView: mv.segments.find(s => s.id === 'SWING') })).includes('SWING_SL'));

const overDaily = buildDailySnapshot({
  trades: [{ ...baseTrade, id: 'x', planned_total_risk: 290, entry_date: '2026-10-07T09:00:00Z' }],
  profiles: SEED_CHARGE_PROFILES, config: cfg, day: '2026-10-07'
});
ok('daily snapshot honours risk stored at entry', near(overDaily.plannedRisk, 290), String(overDaily.plannedRisk));
ok('daily risk limit enforced', codes(mk({}, { dailySnapshot: overDaily })).includes('DAILY_LIMIT'));

const committedLock = buildMonthView({
  month: octMonth,
  trades: [{ ...baseTrade, id: 'lock', entry_date: '2026-10-08T09:20:00Z', planned_total_risk: 400 }],
  reserveTransfers: [], profiles: SEED_CHARGE_PROFILES, config: cfg, ltps: {}
});
ok('month view uses risk stored at entry, not recomputed',
  near(committedLock.segments.find(s => s.id === 'INTRADAY').committedRisk, 400),
  String(committedLock.segments.find(s => s.id === 'INTRADAY').committedRisk));
ok('second trade needs independence',
  codes(mk({}, { dailySnapshot: { ...overDaily, plannedRisk: 0, positionCount: 1 } })).includes('SECOND_TRADE_INDEPENDENCE'));
ok('third trade hard-blocked',
  codes(mk({}, { dailySnapshot: { ...dailySnap, positionCount: 2 } })).includes('POSITION_LIMIT'));

console.log('\n=== 10. Opportunity Reserve rules ===');
const tightSeg = { ...mv.segments.find(s => s.id === 'INTRADAY'), remainingRisk: 10 };
ok('reserve needs a reason',
  codes(mk({ reserve_risk_used: 200 }, { segView: tightSeg })).includes('RESERVE_REASON'));
ok('reserve is A+ only',
  codes(mk({ reserve_risk_used: 200, reserve_reason: 'exceptional' }, { score: scoreSetup({ trend: 20, levels: 20, rr: 15, liquidity: 15, htf: 5, event: 5, segment_rules: 5 }), segView: tightSeg })).includes('RESERVE_GRADE'));
// Reserve necessity is now judged on the accrual counter, not a monthly bucket.
const richState = buildAccrualState({ trades: [], config: { ...cfg, accrualStartDate: '2026-09-07' }, asOf: '2026-10-20' });
ok('reserve refused when the counter already covers it',
  validateTradeEntry({
    trade: { ...baseTrade, reserve_risk_used: 50, reserve_reason: 'x' },
    score: aPlus, planned: computePlannedRisk(baseTrade, SEED_CHARGE_PROFILES, cfg),
    correlation: { independent: true, conflict: false, warn: false, sameUnderlying: [], sameSector: [] },
    segView: mv.segments.find(s => s.id === 'INTRADAY'), dailySnapshot: dailySnap, monthView: mv,
    accrualState: richState, profiles: SEED_CHARGE_PROFILES, config: cfg, recentTrades: []
  }).blocked.map(b => b.code).includes('RESERVE_UNNECESSARY'));

const poorState = buildAccrualState({ trades: [], config: { ...cfg, accrualStartDate: '2026-09-07' }, asOf: '2026-09-08' });
const poorVerdict = validateTradeEntry({
  trade: { ...baseTrade, reserve_risk_used: 60, reserve_reason: 'exceptional A+ setup' },
  score: aPlus, planned: computePlannedRisk(baseTrade, SEED_CHARGE_PROFILES, cfg),
  correlation: { independent: true, conflict: false, warn: false, sameUnderlying: [], sameSector: [] },
  segView: mv.segments.find(s => s.id === 'INTRADAY'), dailySnapshot: dailySnap, monthView: mv,
  accrualState: poorState, profiles: SEED_CHARGE_PROFILES, config: cfg, recentTrades: []
});
ok('reserve allowed to cover a short counter (no RESERVE_UNNECESSARY)',
  !poorVerdict.blocked.map(b => b.code).includes('RESERVE_UNNECESSARY'));
ok('reserve-backed trade skips COUNTER_LOCKED',
  !poorVerdict.blocked.map(b => b.code).includes('COUNTER_LOCKED'),
  JSON.stringify(poorVerdict.blocked.map(b => b.code)));

const lockedVerdict = validateTradeEntry({
  trade: baseTrade, score: aPlus, planned: computePlannedRisk(baseTrade, SEED_CHARGE_PROFILES, cfg),
  correlation: { independent: true, conflict: false, warn: false, sameUnderlying: [], sameSector: [] },
  segView: mv.segments.find(s => s.id === 'INTRADAY'), dailySnapshot: dailySnap, monthView: mv,
  accrualState: poorState, profiles: SEED_CHARGE_PROFILES, config: cfg, recentTrades: []
});
ok('un-backed trade IS blocked by a short counter',
  lockedVerdict.blocked.map(b => b.code).includes('COUNTER_LOCKED'),
  JSON.stringify(lockedVerdict.blocked.map(b => b.code)));
ok('reserve capped by remaining reserve',
  codes(mk({ reserve_risk_used: 5000, reserve_reason: 'x' }, { segView: tightSeg })).includes('RESERVE_CAPACITY'));

console.log('\n=== 11. Correlation & NO TRADE ===');
const corr = assessCorrelation({ symbol: 'SBIN', sector: 'BANKING' },
  [{ symbol: 'SBIN', sector: 'BANKING' }], cfg);
ok('same underlying = conflict', corr.conflict === true && corr.independent === false);
const corr2 = assessCorrelation({ symbol: 'TCS', sector: 'BANKING' }, [{ symbol: 'SBIN', sector: 'BANKING' }], cfg);
ok('same sector = warn not conflict', corr2.warn === true && corr2.conflict === false);

const validateFn = args => validateTradeEntry({
  ...args, profiles: SEED_CHARGE_PROFILES, config: cfg,
  dailySnapshot: dailySnap, monthView: mv, recentTrades: []
});
const emptyDay = evaluateDay({ setups: [], monthView: mv, dailySnapshot: dailySnap, profiles: SEED_CHARGE_PROFILES, config: cfg, validate: validateFn });
ok('no setups => NO TRADE', emptyDay.noTrade === true && emptyDay.recommendation === null);
ok('NO TRADE message exact', emptyDay.noTradeMessage === 'NO TRADE — no A/A+ opportunity meets all risk rules.');

const bOnlyDay = evaluateDay({
  setups: [{ id: 'c1', ...baseTrade, scores: { trend: 15, levels: 15, rr: 10, liquidity: 10, htf: 8, event: 8, segment_rules: 8 } }],
  monthView: mv, dailySnapshot: dailySnap, profiles: SEED_CHARGE_PROFILES, config: cfg, validate: validateFn
});
ok('B-grade candidate => NO TRADE', bOnlyDay.noTrade === true);
ok('B-grade gives rejection reason', /below A/i.test(bOnlyDay.rejected[0].rejectionReason));

const goodScores = { trend: 20, levels: 20, rr: 15, liquidity: 15, htf: 10, event: 10, segment_rules: 5 };
const okScores = { trend: 18, levels: 18, rr: 12, liquidity: 12, htf: 8, event: 8, segment_rules: 6 };
const rankDay = evaluateDay({
  setups: [
    { id: 'c1', ...baseTrade, symbol: 'AAA', scores: okScores },
    { id: 'c2', ...baseTrade, segment: 'SWING', broker: 'ZERODHA', symbol: 'BBB', scores: goodScores }
  ],
  monthView: mv, dailySnapshot: dailySnap, profiles: SEED_CHARGE_PROFILES, config: cfg, validate: validateFn
});
ok('eligible candidates found', rankDay.eligible.length >= 1, `eligible=${rankDay.eligible.length}`);
ok('A+ ranked first', rankDay.recommendation?.symbol === 'BBB', rankDay.recommendation?.symbol);
ok('ranks are 1..n', rankDay.eligible.every((c, i) => c.rank === i + 1));

const noSetupDay = evaluateDay({
  setups: [{ id: 'c9', segment: 'INTRADAY', no_setup: true, symbol: '—', scores: {} }],
  monthView: mv, dailySnapshot: dailySnap, profiles: SEED_CHARGE_PROFILES, config: cfg, validate: validateFn
});
ok('No Setup is recorded but not eligible', noSetupDay.noTrade === true && noSetupDay.rejected.length === 1);
ok('No Setup has its own reason', /No setup recorded/.test(noSetupDay.rejected[0].rejectionReason));

console.log('\n=== 12. Cash: risk buckets are never cash ===');
const acct = buildAccountView({
  trades, cashLedger: [
    { id: 'c0', type: 'OPENING', amount: 10000 },
    { id: 'c1', type: 'DEPOSIT', amount: 5000 },
    { id: 'c2', type: 'WITHDRAWAL', amount: 2000 }
  ],
  growthLedger: [{ id: 'g1', type: 'TO_GROWTH', amount: 1000 }],
  profiles: SEED_CHARGE_PROFILES, config: cfg
});
ok('growth reserve = 1000', acct.growthReserve === 1000);
ok('cash excludes risk budget entirely', acct.brokerCash < 20000 && acct.brokerCash > 10000, String(acct.brokerCash));
ok('cash = opening+dep+realized-wd-growth',
  near(acct.brokerCash, 10000 + 5000 + acct.realizedNetPnl - 2000 - 1000), String(acct.brokerCash));
ok('withdrawable never negative', acct.withdrawableCash >= 0);

console.log(`\n${'='.repeat(52)}\n  ${pass} passed, ${fail} failed\n${'='.repeat(52)}\n`);
process.exit(fail === 0 ? 0 : 1);
