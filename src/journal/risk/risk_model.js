/**
 * risk_model.js — Segments, budgets, month generation and the core formulas.
 *
 * Nothing here is pre-filled with money. Every rupee figure starts at zero and is
 * entered by the user on the Setup screen; BRIEF_DEFAULTS holds the spec's numbers
 * so they can be applied in one click, but they are never seeded automatically.
 *
 * Design rule from the brief §3: a risk allocation is NEVER cash. Nothing in this
 * file may be added to, or subtracted from, a broker cash balance.
 */

import { PRODUCTS } from './broker_profiles.js';

export const STANDARD_START = '2026-09';
export const STANDARD_END = '2029-09';

/**
 * The seven active trading segments. Allocations, stop-losses and brokers all
 * live in config, not here.
 */
export const SEGMENTS = [
  { id: 'INTRADAY',      label: 'Intraday',           icon: '⚡',  product: PRODUCTS.EQ_INTRADAY, lotBased: false, livePnlEligible: true },
  { id: 'LONG_TERM',     label: 'Long Term',          icon: '🛡️', product: PRODUCTS.EQ_DELIVERY, lotBased: false, livePnlEligible: true },
  { id: 'INDEX_OPTIONS', label: 'Index Options',      icon: '📈', product: PRODUCTS.INDEX_OPTION, lotBased: true,  livePnlEligible: true },
  { id: 'NATURAL_GAS',   label: 'Natural Gas (NATU)', icon: '🔥', product: PRODUCTS.MCX_FUTURE,   lotBased: true,  livePnlEligible: true },
  { id: 'STOCK_OPTIONS', label: 'Stock Options',      icon: '🎯', product: PRODUCTS.STOCK_OPTION, lotBased: true,  livePnlEligible: true },
  { id: 'SWING',         label: 'Swing',              icon: '🌊', product: PRODUCTS.EQ_DELIVERY,  lotBased: false, livePnlEligible: true },
  { id: 'CRUDE',         label: 'Crude Oil',          icon: '🛢️', product: PRODUCTS.MCX_FUTURE,   lotBased: true,  livePnlEligible: true },
  { id: 'PENNY',         label: 'Quality Penny SIP',  icon: '💎', product: PRODUCTS.EQ_DELIVERY,  lotBased: false, livePnlEligible: true }
];

export const OPPORTUNITY_RESERVE = { id: 'OPPORTUNITY_RESERVE', label: 'Opportunity Reserve', icon: '💠' };

export const SEGMENT_IDS = SEGMENTS.map(s => s.id);
export const getSegment = id => SEGMENTS.find(s => s.id === id) || null;

const zeroBySegment = () => SEGMENTS.reduce((a, s) => ({ ...a, [s.id]: 0 }), {});
const nullBySegment = () => SEGMENTS.reduce((a, s) => ({ ...a, [s.id]: null }), {});

/**
 * Everything starts empty. The app blocks trades until the user fills these in,
 * which is the intended "start from scratch" state.
 */
export const DEFAULT_CONFIG = {
  configured: false,           // flips true once the user completes setup
  monthlyRiskBudget: 0,
  allocations: zeroBySegment(),
  reserveAllocation: 0,
  segmentSL: nullBySegment(),  // planned stop-loss per trade, in rupees
  // Percentage-based segments size the stop from the entry price instead of a
  // fixed rupee figure. When set, this overrides segmentSL for that segment.
  segmentSLPercent: nullBySegment(),
  segmentTargetPercent: nullBySegment(),
  segmentBroker: nullBySegment(),
  // Risk already spent before the counters started, charged to a lane's capital.
  // It does NOT reset that lane's counter — it is spent capital, not a loss.
  openingDeductions: zeroBySegment(),
  dailyRiskLimit: 0,
  maxPositionsPerDay: 1,
  maxPositionsExceptional: 2,
  swingDefaultSL: null,
  longTermBroker: null,

  // ── Daily risk-counter engine ──────────────────────────────────────────
  // Each segment accrues (allocation / accrualDivisor) per day, continuously.
  // A segment unlocks once its counter reaches that segment's stop-loss.
  accrualStartDate: null,   // no accrual until the user picks a start date
  accrualDivisor: 22,       // trading days a monthly allocation is spread over
  accrualBasis: 'WEEKDAYS', // 'WEEKDAYS' skips Sat/Sun; 'CALENDAR' accrues daily
  // Losses reduce segment capital and are booked to the segment — except LT.
  booksLosses: {
    INTRADAY: true,
    LONG_TERM: false,
    INDEX_OPTIONS: true,
    NATURAL_GAS: true,
    STOCK_OPTIONS: true,
    SWING: true,
    CRUDE: true,
    PENNY: true,
    OPPORTUNITY_RESERVE: true
  },
  chargesWarnRatio: 0.25,
  actualVsEstimateWarnRatio: 0.2,
  correlationBlockSameUnderlying: true
};

/** The brief's numbers, available as a one-click apply — never auto-seeded. */
export const BRIEF_DEFAULTS = {
  monthlyRiskBudget: 7500,
  allocations: {
    INTRADAY: 750,
    LONG_TERM: 1150,   // 1,500 less the 350 carved out for Penny
    INDEX_OPTIONS: 1250,
    NATURAL_GAS: 1000,
    STOCK_OPTIONS: 1000,
    SWING: 1000,
    CRUDE: 500,         // funded by halving the Opportunity Reserve
    PENNY: 350          // deliberately small - highest risk per rupee
  },
  reserveAllocation: 500,
  segmentSL: {
    INTRADAY: 100,
    LONG_TERM: 250,
    INDEX_OPTIONS: 250,
    NATURAL_GAS: 250,
    STOCK_OPTIONS: 250,
    SWING: 100,  // same per-trade risk as Intraday; the 5% below sets the stop PRICE
    CRUDE: 250,
    PENNY: 100   // small stop keeps penny position sizes contained
  },
  segmentSLPercent: {
    INTRADAY: null,
    LONG_TERM: null,
    INDEX_OPTIONS: null,
    NATURAL_GAS: null,
    STOCK_OPTIONS: null,
    SWING: 5,
    CRUDE: null,
    PENNY: null
  },
  segmentTargetPercent: {
    INTRADAY: null,
    LONG_TERM: null,
    INDEX_OPTIONS: null,
    NATURAL_GAS: null,
    STOCK_OPTIONS: null,
    SWING: 5,
    CRUDE: null,
    PENNY: null
  },
  segmentBroker: {
    INTRADAY: 'INDMONEY',
    LONG_TERM: null, // user-selectable
    INDEX_OPTIONS: 'INDMONEY',
    NATURAL_GAS: 'INDMONEY',
    STOCK_OPTIONS: 'INDMONEY',
    SWING: 'ZERODHA',
    CRUDE: 'INDMONEY',
    PENNY: 'INDMONEY'
  },
  // The 2,000 already committed to Long Term before the counters began.
  openingDeductions: {
    INTRADAY: 0,
    LONG_TERM: 2000,
    INDEX_OPTIONS: 0,
    NATURAL_GAS: 0,
    STOCK_OPTIONS: 0,
    SWING: 0,
    CRUDE: 0,
    PENNY: 0
  },
  dailyRiskLimit: 300,
  maxPositionsPerDay: 1,
  maxPositionsExceptional: 2,
  accrualStartDate: '2026-09-04',
  accrualDivisor: 22,        // ~22 trading days a month, so 7,500 still lands monthly
  accrualBasis: 'WEEKDAYS',
  booksLosses: {
    INTRADAY: true,
    LONG_TERM: false,
    INDEX_OPTIONS: true,
    NATURAL_GAS: true,
    STOCK_OPTIONS: true,
    SWING: true,
    CRUDE: true,
    PENNY: true,
    OPPORTUNITY_RESERVE: true
  }
};

/** Allocations + reserve should equal the monthly budget. Surfaced, never enforced silently. */
export function allocationBalance(config) {
  const alloc = config?.allocations || {};
  const sum = SEGMENT_IDS.reduce((s, id) => s + (Number(alloc[id]) || 0), 0) + (Number(config?.reserveAllocation) || 0);
  const budget = Number(config?.monthlyRiskBudget) || 0;
  return { sum, budget, balanced: Math.abs(sum - budget) < 0.001, difference: Number((sum - budget).toFixed(2)) };
}

export const TRADE_INTENTS = [
  { id: 'PLANNED_OPPORTUNITY', label: 'Planned opportunity', blocked: false },
  { id: 'LONG_TERM_INVESTMENT', label: 'Long-term investment', blocked: false },
  { id: 'RESERVE_EXCEPTIONAL', label: 'Reserve-backed exceptional opportunity', blocked: false },
  { id: 'RECOVERY', label: 'Recovery / revenge trade', blocked: true },
  { id: 'OTHER', label: 'Other (note required)', blocked: false }
];

export const GRADES = [
  { id: 'A_PLUS', label: 'A+', min: 90, max: 100, eligible: true },
  { id: 'A', label: 'A', min: 80, max: 89, eligible: true },
  { id: 'B', label: 'B', min: 70, max: 79, eligible: false },
  { id: 'C', label: 'Below B', min: 0, max: 69, eligible: false }
];

/** Score categories and weights per brief §4 — structural, not user data. */
export const SCORE_CATEGORIES = [
  { id: 'trend', label: 'Trend / market structure', max: 20 },
  { id: 'levels', label: 'Defined entry, SL and target', max: 20 },
  { id: 'rr', label: 'Risk / reward', max: 15 },
  { id: 'liquidity', label: 'Liquidity / execution', max: 15 },
  { id: 'htf', label: 'Higher-timeframe confirmation', max: 10 },
  { id: 'event', label: 'Event / news suitability', max: 10 },
  { id: 'segment_rules', label: 'Segment-specific rule compliance', max: 10 }
];

/* ────────────────────────────── Month records ────────────────────────────── */

function addMonths(key, n) {
  const [y, m] = key.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

export function monthLabel(key) {
  const [y, m] = String(key).split('-').map(Number);
  const names = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  return `${names[(m || 1) - 1]} ${y}`;
}

export function currentMonthKey(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function buildStandardMonth(key, config) {
  const alloc = config?.allocations || {};
  return {
    month_key: key,
    mode: 'STANDARD',
    monthly_risk_budget: Number(config?.monthlyRiskBudget) || 0,
    preexisting_usage: 0,
    enforce_segment_quotas: true,
    buckets: SEGMENTS.reduce((acc, s) => {
      acc[s.id] = { segment_id: s.id, initial_allocation: Number(alloc[s.id]) || 0, reserve_transferred_in: 0 };
      return acc;
    }, {}),
    reserve: { initial_allocation: Number(config?.reserveAllocation) || 0, transferred_out: 0 },
    closed_out: false
  };
}

/**
 * Ordinary month records from Sep-2026 → Sep-2029, used for P&L reporting.
 * The daily counter is the risk control; months are just reporting periods.
 */
export function generateMonths(config = DEFAULT_CONFIG) {
  const months = [];
  let key = STANDARD_START;
  let guard = 0;
  while (key <= STANDARD_END && guard < 500) {
    months.push(buildStandardMonth(key, config));
    key = addMonths(key, 1);
    guard += 1;
  }
  return months;
}

/**
 * Re-apply config to month records without touching trades or history.
 * Months already closed out keep the budget they were run under.
 */
export function reapplyConfigToMonths(months, config) {
  return (months || []).map(m => {
    if (m.closed_out) return m;
    return { ...buildStandardMonth(m.month_key, config), closed_out: m.closed_out };
  });
}

/* ────────────────────────────── Formulas §6 ────────────────────────────── */

export function plannedPriceRisk({ entry_price, stop_loss_price, quantity, lot_size = 1 }) {
  const e = Number(entry_price) || 0;
  const sl = Number(stop_loss_price) || 0;
  const q = Number(quantity) || 0;
  const l = Number(lot_size) || 1;
  if (!e || !sl || !q) return 0;
  return Number((Math.abs(e - sl) * q * l).toFixed(2));
}

export function plannedTotalRisk(priceRisk, estimatedCharges) {
  return Number(((Number(priceRisk) || 0) + (Number(estimatedCharges) || 0)).toFixed(2));
}

export function grossPnl({ entry_price, exit_price, quantity, lot_size = 1, direction = 'LONG' }) {
  const e = Number(entry_price) || 0;
  const x = Number(exit_price) || 0;
  const q = Number(quantity) || 0;
  const l = Number(lot_size) || 1;
  if (!e || !x || !q) return 0;
  const diff = direction === 'SHORT' ? e - x : x - e;
  return Number((diff * q * l).toFixed(2));
}

export function netPnl(gross, actualCharges) {
  return Number(((Number(gross) || 0) - (Number(actualCharges) || 0)).toFixed(2));
}

export function segmentRiskRemaining({ initial_allocation, reserve_transferred_in, committed_planned_risk }) {
  if (initial_allocation === null || initial_allocation === undefined) return null; // uncapped
  return Number(
    (
      (Number(initial_allocation) || 0) +
      (Number(reserve_transferred_in) || 0) -
      (Number(committed_planned_risk) || 0)
    ).toFixed(2)
  );
}

export function monthlyRiskRemaining({ monthly_risk_budget, preexisting_usage, committed_planned_risk }) {
  return Number(
    (
      (Number(monthly_risk_budget) || 0) -
      (Number(preexisting_usage) || 0) -
      (Number(committed_planned_risk) || 0)
    ).toFixed(2)
  );
}

export function brokerCashBalance({
  opening_cash = 0,
  deposits = 0,
  realized_net_pnl = 0,
  withdrawals = 0,
  transfers_to_growth_reserve = 0,
  releases_from_growth_reserve = 0
}) {
  return Number(
    (
      (Number(opening_cash) || 0) +
      (Number(deposits) || 0) +
      (Number(realized_net_pnl) || 0) -
      (Number(withdrawals) || 0) -
      (Number(transfers_to_growth_reserve) || 0) +
      (Number(releases_from_growth_reserve) || 0)
    ).toFixed(2)
  );
}

export function gradeFromScore(score) {
  const s = Number(score) || 0;
  return GRADES.find(g => s >= g.min && s <= g.max) || GRADES[GRADES.length - 1];
}

export function maxScore() {
  return SCORE_CATEGORIES.reduce((s, c) => s + c.max, 0);
}
