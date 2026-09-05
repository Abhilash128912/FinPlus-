/**
 * accrual_engine.js — Daily risk-counter engine.
 *
 * Replaces the monthly draw-down bucket with a continuous daily accrual:
 *
 *   • Every segment accrues (monthly allocation / accrualDivisor) per day,
 *     continuously from the start date. There is no month-end reset.
 *   • A segment unlocks for trading once its counter reaches that segment's
 *     planned stop-loss.
 *   • A WIN leaves the counter untouched — risk was never spent.
 *   • A LOSS resets the counter to zero and reduces that segment's capital by
 *     the ACTUAL net loss. The loss is booked against the segment.
 *   • Long Term is exempt from the capital hit, the loss booking and the reset
 *     (config.booksLosses.LONG_TERM === false) — its drawdowns are holds, not
 *     failed trades.
 */

import { SEGMENTS, OPPORTUNITY_RESERVE, DEFAULT_CONFIG } from './risk_model.js';

const r2 = n => Number((Number(n) || 0).toFixed(2));
const DAY_MS = 86400000;

/** All accruing lanes: the six segments plus the Opportunity Reserve. */
export const ACCRUAL_LANES = [...SEGMENTS.map(s => s.id), OPPORTUNITY_RESERVE.id];

export function toDayNumber(value) {
  if (!value) return null;
  const iso = String(value).slice(0, 10);
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return null;
  return Math.floor(Date.UTC(y, m - 1, d) / DAY_MS);
}

export function todayIso(now = new Date()) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

/** Day-of-week for a day number. 1970-01-01 (day 0) was a Thursday. 0=Sun, 6=Sat. */
export function dayOfWeek(dayNumber) {
  return (((dayNumber + 4) % 7) + 7) % 7;
}

export function isWeekend(dayNumber) {
  const d = dayOfWeek(dayNumber);
  return d === 0 || d === 6;
}

export function isWeekendIso(iso) {
  const n = toDayNumber(iso);
  return n === null ? false : isWeekend(n);
}

/** Weekdays in the inclusive day-number range [a, b]. */
function countWeekdays(a, b) {
  if (b < a) return 0;
  const total = b - a + 1;
  const fullWeeks = Math.floor(total / 7);
  let count = fullWeeks * 5;
  const start = a + fullWeeks * 7;
  for (let d = start; d <= b; d++) {
    if (!isWeekend(d)) count += 1;
  }
  return count;
}

/**
 * Days of accrual credited between two dates.
 * `inclusive` credits the from-date itself (used for the very first day).
 * After a loss the reset day credits nothing; accrual restarts the next day.
 * Under the WEEKDAYS basis, Saturdays and Sundays credit nothing at all.
 */
export function accrualDays(fromIso, toIso, inclusive, basis = 'CALENDAR') {
  const a = toDayNumber(fromIso);
  const b = toDayNumber(toIso);
  if (a === null || b === null) return 0;
  if (basis === 'WEEKDAYS') {
    return countWeekdays(inclusive ? a : a + 1, b);
  }
  return Math.max(0, b - a + (inclusive ? 1 : 0));
}

/** Advance a date by n accrual days, skipping weekends when required. */
export function addAccrualDays(iso, n, basis = 'CALENDAR') {
  const base = toDayNumber(iso);
  if (base === null) return null;
  if (basis !== 'WEEKDAYS') return addDays(iso, n);
  let d = base;
  let left = n;
  while (left > 0) {
    d += 1;
    if (!isWeekend(d)) left -= 1;
  }
  return dayNumberToIso(d);
}

function dayNumberToIso(n) {
  const d = new Date(n * DAY_MS);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
}

/** Per-day accrual for one lane, derived from its monthly allocation. */
export function dailyRateFor(laneId, config = DEFAULT_CONFIG) {
  const divisor = Number(config?.accrualDivisor) > 0 ? Number(config.accrualDivisor) : 22;
  const allocation =
    laneId === OPPORTUNITY_RESERVE.id
      ? Number(config?.reserveAllocation) || 0
      : Number(config?.allocations?.[laneId]) || 0;
  // Deliberately NOT rounded — rounding each lane to paise makes the daily drip
  // fall short of the budget (e.g. 249.99 instead of 250) and drifts over time.
  // Rounding happens on the accumulated figures below.
  return allocation / divisor;
}

/** Stop-loss that unlocks a lane. Null means the user has not set one yet. */
export function unlockThresholdFor(laneId, config = DEFAULT_CONFIG) {
  if (laneId === OPPORTUNITY_RESERVE.id) return null;
  const v = Number(config?.segmentSL?.[laneId]);
  return v > 0 ? v : null;
}

/**
 * Percentage stop-loss for a lane, e.g. Swing at 5% of entry.
 * A percentage segment has no fixed rupee threshold — the position is sized to
 * whatever the counter currently holds, so any accrual at all unlocks it.
 */
export function slPercentFor(laneId, config = DEFAULT_CONFIG) {
  const v = Number(config?.segmentSLPercent?.[laneId]);
  return v > 0 ? v : null;
}

export function targetPercentFor(laneId, config = DEFAULT_CONFIG) {
  const v = Number(config?.segmentTargetPercent?.[laneId]);
  return v > 0 ? v : null;
}

/**
 * Risk already committed to a lane before the counters started.
 * Charged against capital once, up front. It never touches the counter, because
 * it is spent capital rather than a loss.
 */
export function openingDeductionFor(laneId, config = DEFAULT_CONFIG) {
  return Number(config?.openingDeductions?.[laneId]) || 0;
}

/** Whether losses in this lane hit segment capital and get booked. LT: false. */
export function booksLosses(laneId, config = DEFAULT_CONFIG) {
  const flag = config?.booksLosses?.[laneId];
  return flag === undefined ? true : !!flag;
}

const isClosedTrade = t =>
  String(t?.status || '').toUpperCase() === 'CLOSED' && Number(t?.exit_price) > 0;

/**
 * Build the counter state for every lane.
 *
 * @param {Array}  trades    all risk-desk trades, each carrying `_pnl.net` from risk_engine
 * @param {object} config
 * @param {string} asOf      ISO date to evaluate at (defaults to today)
 */
export function buildAccrualState({ trades = [], config = DEFAULT_CONFIG, asOf = null }) {
  const today = asOf || todayIso();
  const startDate = String(config?.accrualStartDate || '').slice(0, 10);
  const basis = config?.accrualBasis === 'WEEKDAYS' ? 'WEEKDAYS' : 'CALENDAR';
  const started = !!startDate && toDayNumber(startDate) !== null;
  const startedYet = started && toDayNumber(today) >= toDayNumber(startDate);

  // Only trades already closed ON OR BEFORE the evaluation date may affect it.
  // Without this, a later loss would retroactively reset an earlier day's counter
  // and deduct its capital, making any back-dated view wrong.
  const closed = trades.filter(t => {
    if (!isClosedTrade(t)) return false;
    const closedOn = String(t.exit_date || t.entry_date || '').slice(0, 10);
    if (!closedOn) return false;
    return toDayNumber(closedOn) <= toDayNumber(today);
  });

  const lanes = ACCRUAL_LANES.map(laneId => {
    const seg = SEGMENTS.find(s => s.id === laneId) || null;
    const rate = dailyRateFor(laneId, config);
    const slPercent = slPercentFor(laneId, config);
    const targetPercent = targetPercentFor(laneId, config);
    // A percentage segment is sized to the counter, so it has no fixed threshold.
    const threshold = slPercent ? null : unlockThresholdFor(laneId, config);
    const books = booksLosses(laneId, config);

    const laneTrades = closed.filter(t => t.segment === laneId);
    // A loss is judged on ACTUAL net P&L after charges.
    const losing = laneTrades
      .filter(t => Number(t?._pnl?.net ?? t?.net_pnl ?? 0) < 0)
      .sort((a, b) =>
        String(a.exit_date || a.entry_date).localeCompare(String(b.exit_date || b.entry_date))
      );

    // LT never resets and never books, so its loss list is informational only.
    const resettingLosses = books ? losing : [];
    const lastLoss = resettingLosses[resettingLosses.length - 1] || null;
    const lastLossDate = lastLoss ? String(lastLoss.exit_date || lastLoss.entry_date).slice(0, 10) : null;

    const totalDays = startedYet ? accrualDays(startDate, today, true, basis) : 0;
    const totalAccrued = r2(rate * totalDays);

    const lossTotal = r2(
      resettingLosses.reduce((s, t) => s + Math.abs(Number(t?._pnl?.net ?? t?.net_pnl ?? 0)), 0)
    );
    // Losses recorded but deliberately NOT charged to capital (Long Term).
    const unbookedLossTotal = books
      ? 0
      : r2(losing.reduce((s, t) => s + Math.abs(Number(t?._pnl?.net ?? t?.net_pnl ?? 0)), 0));

    const openingDeduction = openingDeductionFor(laneId, config);
    const capital = r2(totalAccrued - lossTotal - openingDeduction);

    // Counter restarts the day AFTER a booked loss; otherwise runs from day one.
    const counterDays = !startedYet
      ? 0
      : lastLossDate
        ? accrualDays(lastLossDate, today, false, basis)
        : accrualDays(startDate, today, true, basis);
    const counter = r2(rate * counterDays);

    const unlocked = slPercent
      ? counter > 0.001                       // sized to the counter, so any accrual works
      : threshold === null
        ? null
        : counter + 0.001 >= threshold;
    const shortfall = slPercent || threshold === null ? null : r2(Math.max(0, threshold - counter));
    const daysToUnlock =
      slPercent || threshold === null || unlocked || rate <= 0 ? 0 : Math.ceil(shortfall / rate);
    // Largest position the counter can carry at this percentage stop.
    const maxPositionValue = slPercent ? r2(counter / (slPercent / 100)) : null;

    const wins = laneTrades.filter(t => Number(t?._pnl?.net ?? t?.net_pnl ?? 0) > 0).length;

    return {
      id: laneId,
      label: seg?.label || OPPORTUNITY_RESERVE.label,
      icon: seg?.icon || OPPORTUNITY_RESERVE.icon,
      isReserve: laneId === OPPORTUNITY_RESERVE.id,
      rate,
      threshold,
      slPercent,
      targetPercent,
      maxPositionValue,
      booksLosses: books,
      startDate,
      started: startedYet,
      basis,
      totalDays,
      totalAccrued,
      counter,
      counterDays,
      capital,
      openingDeduction,
      lossTotal,
      unbookedLossTotal,
      lastLossDate,
      unlocked,
      shortfall,
      daysToUnlock,
      unlockDate: daysToUnlock > 0 ? addAccrualDays(today, daysToUnlock, basis) : null,
      tradeCount: laneTrades.length,
      winCount: wins,
      lossCount: losing.length,
      progressPct: threshold ? Math.min(100, (counter / threshold) * 100) : slPercent ? 100 : 0
    };
  });

  const byId = lanes.reduce((a, l) => ({ ...a, [l.id]: l }), {});

  return {
    today,
    startDate,
    basis,
    isWeekendToday: isWeekendIso(today),
    started: startedYet,
    dailyPot: r2(lanes.reduce((s, l) => s + l.rate, 0)),
    lanes,
    byId,
    totalAccrued: r2(lanes.reduce((s, l) => s + l.totalAccrued, 0)),
    totalCapital: r2(lanes.reduce((s, l) => s + l.capital, 0)),
    totalBookedLosses: r2(lanes.reduce((s, l) => s + l.lossTotal, 0)),
    totalOpeningDeductions: r2(lanes.reduce((s, l) => s + l.openingDeduction, 0)),
    unlockedLanes: lanes.filter(l => l.unlocked === true).map(l => l.id)
  };
}

export function addDays(iso, n) {
  const base = toDayNumber(iso);
  if (base === null) return null;
  const d = new Date((base + n) * DAY_MS);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
}

/**
 * Can this lane take a trade of the given planned risk right now?
 * Two gates: the stop-loss unlock the user described, and a hard rule that you
 * cannot risk more than you have actually accrued.
 */
export function checkAccrualGate({ laneId, plannedTotalRisk, accrualState, config = DEFAULT_CONFIG }) {
  const lane = accrualState?.byId?.[laneId];
  const reasons = [];
  if (!lane) return { ok: false, lane: null, reasons: [{ code: 'NO_LANE', message: 'Unknown segment.' }] };

  if (!lane.started) {
    reasons.push({
      code: 'ACCRUAL_NOT_STARTED',
      message: `Accrual has not started yet — it begins ${lane.startDate || '(no start date set)'}.`
    });
  }
  if (lane.slPercent) {
    if (!(lane.counter > 0.001)) {
      reasons.push({
        code: 'COUNTER_EMPTY',
        message: `${lane.label} has nothing accrued yet.`
      });
    }
  } else if (lane.threshold === null) {
    reasons.push({
      code: 'NO_THRESHOLD',
      message: `${lane.label} has no stop-loss set, so there is nothing to unlock against. Set it on the Setup screen.`
    });
  } else if (!lane.unlocked) {
    reasons.push({
      code: 'COUNTER_LOCKED',
      message: `${lane.label} counter is ₹${lane.counter.toFixed(2)} of the ₹${lane.threshold.toFixed(2)} needed — ₹${lane.shortfall.toFixed(2)} short, about ${lane.daysToUnlock} more day${lane.daysToUnlock === 1 ? '' : 's'}.`
    });
  }

  const risk = Number(plannedTotalRisk) || 0;
  if (risk > 0 && risk > lane.counter + 0.001) {
    reasons.push({
      code: 'RISK_EXCEEDS_COUNTER',
      message: `Planned risk ₹${risk.toFixed(2)} is more than the ₹${lane.counter.toFixed(2)} accrued in ${lane.label}.`
    });
  }

  return { ok: reasons.length === 0, lane, reasons };
}

/**
 * What a closed trade does to its lane — used for the ledger view and to
 * explain the mechanism back to the user.
 */
export function describeOutcome(trade, config = DEFAULT_CONFIG) {
  const net = Number(trade?._pnl?.net ?? trade?.net_pnl ?? 0);
  const books = booksLosses(trade?.segment, config);
  if (net > 0) {
    return { kind: 'WIN', counterEffect: 'RETAINED', capitalEffect: 0, note: 'Counter retained — risk was not spent.' };
  }
  if (net < 0) {
    if (!books) {
      return {
        kind: 'LOSS',
        counterEffect: 'RETAINED',
        capitalEffect: 0,
        note: 'Long Term is exempt — counter kept, no capital deduction, not booked against the segment.'
      };
    }
    return {
      kind: 'LOSS',
      counterEffect: 'RESET',
      capitalEffect: r2(net),
      note: `Counter reset to zero; ₹${Math.abs(net).toFixed(2)} deducted from segment capital.`
    };
  }
  return { kind: 'FLAT', counterEffect: 'RETAINED', capitalEffect: 0, note: 'Break-even — counter retained.' };
}
