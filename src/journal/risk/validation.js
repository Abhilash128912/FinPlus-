/**
 * validation.js — Brief §9. Hard blocks and soft warnings for trade entry.
 *
 * Blocks are refusals: the trade cannot be recorded as taken. Warnings are
 * surfaced but do not stop the user. Anything overridden must carry a reason,
 * which the caller writes to the audit log.
 */

import { getSegment, TRADE_INTENTS, DEFAULT_CONFIG } from './risk_model.js';
import { resolveBroker, isClosed } from './risk_engine.js';
import { resolveChargeProfile } from './broker_profiles.js';
import { checkAccrualGate } from './accrual_engine.js';

const block = (code, message) => ({ code, message, severity: 'BLOCK' });
const warn = (code, message) => ({ code, message, severity: 'WARN' });

/**
 * @returns {{ blocked: Array, warnings: Array, canOverride: boolean }}
 */
export function validateTradeEntry({
  trade,
  score,
  planned,
  correlation,
  segView,
  dailySnapshot,
  monthView,
  accrualState = null,
  profiles = [],
  config = DEFAULT_CONFIG,
  recentTrades = []
}) {
  const blocked = [];
  const warnings = [];
  const seg = getSegment(trade?.segment);

  /* ── Setup completeness ─────────────────────────────────────────────── */
  if (!seg) blocked.push(block('NO_SEGMENT', 'Segment is not recognised.'));
  if (!Number(trade?.entry_price)) blocked.push(block('NO_ENTRY', 'Entry price is required.'));
  if (!Number(trade?.stop_loss_price)) blocked.push(block('NO_SL', 'Stop-loss is required. A trade without a defined stop cannot be sized.'));
  if (!Number(trade?.target_price)) blocked.push(block('NO_TARGET', 'Target price is required.'));
  if (!Number(trade?.quantity)) blocked.push(block('NO_QTY', 'Quantity is required.'));
  if (seg?.lotBased && !Number(trade?.lot_size)) {
    blocked.push(block('NO_LOT', `${seg.label} is lot-based — lot size is required.`));
  }

  /* ── Grade ──────────────────────────────────────────────────────────── */
  if (score && !score.eligibleGrade) {
    blocked.push(block('GRADE', `Setup grade ${score.gradeLabel} (${score.total}/${score.max}). Only A (80+) and A+ (90+) are tradeable.`));
  }
  if (score?.incomplete?.length) {
    warnings.push(warn('SCORE_INCOMPLETE', `${score.incomplete.length} score categories left blank — they counted as zero.`));
  }

  /* ── Broker and charge profile ──────────────────────────────────────── */
  const broker = resolveBroker(trade, config);
  if (!broker) {
    blocked.push(block('NO_BROKER', seg?.id === 'LONG_TERM'
      ? 'Long Term has no default broker. Select one for this trade or set a default in settings.'
      : 'Broker is required.'));
  } else if (!resolveChargeProfile(profiles, broker, trade?.entry_date)) {
    blocked.push(block('NO_PROFILE', `No active charge profile for ${broker} on ${String(trade?.entry_date || '').slice(0, 10)}.`));
  }
  if (planned?.chargeError) {
    blocked.push(block('CHARGES_UNAVAILABLE', planned.chargeError));
  }

  /* ── Setup must be completed before anything can be traded ──────────── */
  if (!config?.configured) {
    blocked.push(block('NOT_CONFIGURED', 'Risk Desk setup is not complete. Enter your monthly risk budget and segment allocations on the Setup screen first.'));
  }
  if (!(Number(config?.monthlyRiskBudget) > 0)) {
    blocked.push(block('NO_BUDGET', 'Monthly risk budget is not set.'));
  }
  if (!(Number(config?.dailyRiskLimit) > 0)) {
    blocked.push(block('NO_DAILY_LIMIT', 'Daily risk limit is not set.'));
  }

  /* ── Every segment needs a defined stop, rupee or percentage ─────────── */
  if (seg) {
    const hasTradeSL = Number(trade?.stop_loss_price) > 0;
    const hasRupeeDefault = Number(config?.segmentSL?.[seg.id]) > 0;
    const hasPercentDefault = Number(config?.segmentSLPercent?.[seg.id]) > 0;
    if (!hasTradeSL && !hasRupeeDefault && !hasPercentDefault) {
      blocked.push(block('NO_SEGMENT_SL',
        `${seg.label} has no standard stop-loss. Set a rupee amount or a percentage on the Setup screen, or define this trade's stop directly.`));
    }
  }

  /* ── Daily risk counter ─────────────────────────────────────────────────
   * The segment must have accrued enough to cover its stop-loss before a trade
   * is allowed. The Opportunity Reserve can top up a shortfall for an A+ setup.
   */
  const risk = Number(planned?.totalRisk) || 0;
  const usingReserve = Number(trade?.reserve_risk_used) > 0;

  if (accrualState) {
    const fromCounter = usingReserve ? risk - Number(trade.reserve_risk_used) : risk;
    const gate = checkAccrualGate({
      laneId: trade?.segment,
      plannedTotalRisk: fromCounter,
      accrualState,
      config
    });
    if (!gate.ok) {
      for (const r of gate.reasons) {
        // A reserve-backed A+ trade may cover a counter shortfall, but never a
        // missing threshold or an unstarted accrual.
        if (usingReserve && r.code === 'COUNTER_LOCKED') continue;
        blocked.push(block(r.code, r.message));
      }
    }
    const lane = gate.lane;
    if (lane && lane.capital < 0) {
      warnings.push(warn('NEGATIVE_CAPITAL',
        `${lane.label} capital is ₹${lane.capital.toFixed(2)} — booked losses exceed what has accrued.`));
    }
  }

  /* ── Opportunity Reserve conditions §4 ──────────────────────────────── */
  if (usingReserve) {
    const amount = Number(trade.reserve_risk_used) || 0;
    if (score && score.grade !== 'A_PLUS') {
      blocked.push(block('RESERVE_GRADE', 'Opportunity Reserve is for A+ setups only.'));
    }
    const laneCounter = accrualState?.byId?.[trade?.segment]?.counter;
    if (laneCounter !== undefined && laneCounter >= risk - 0.001) {
      blocked.push(block('RESERVE_UNNECESSARY', `${seg?.label} has already accrued ₹${laneCounter.toFixed(2)} — the reserve may only be used when the segment counter is short.`));
    }
    const reserveAvailable = accrualState?.byId?.OPPORTUNITY_RESERVE?.capital
      ?? monthView?.reserve?.remaining ?? 0;
    if (amount > reserveAvailable + 0.001) {
      blocked.push(block('RESERVE_CAPACITY', `Opportunity Reserve has ₹${Number(reserveAvailable).toFixed(2)} accrued; ₹${amount.toFixed(2)} requested.`));
    }
    if (!String(trade?.reserve_reason || '').trim()) {
      blocked.push(block('RESERVE_REASON', 'A written reason is required for every Opportunity Reserve use.'));
    }
  }

  /* ── Monthly limit ──────────────────────────────────────────────────── */
  if (monthView && risk > (monthView.remainingRisk ?? 0) + 0.001) {
    blocked.push(block('MONTHLY_LIMIT',
      `Monthly risk remaining is ₹${(monthView.remainingRisk ?? 0).toFixed(2)}; this trade commits ₹${risk.toFixed(2)}.`));
  }

  /* ── Daily limit and position count ─────────────────────────────────── */
  if (dailySnapshot) {
    const projected = (dailySnapshot.plannedRisk || 0) + risk;
    if (projected > (dailySnapshot.dailyRiskLimit || 0) + 0.001) {
      blocked.push(block('DAILY_LIMIT',
        `Daily planned risk would be ₹${projected.toFixed(2)} against a ₹${(dailySnapshot.dailyRiskLimit || 0).toFixed(2)} limit.`));
    }

    const count = dailySnapshot.positionCount || 0;
    const maxDefault = dailySnapshot.maxPositions ?? 1;
    const maxExceptional = dailySnapshot.maxPositionsExceptional ?? 2;

    if (count >= maxExceptional) {
      blocked.push(block('POSITION_LIMIT', `Maximum ${maxExceptional} new positions per day already reached.`));
    } else if (count >= maxDefault) {
      // Second trade — exceptional path, extra conditions.
      if (score && score.grade !== 'A_PLUS' && score.grade !== 'A') {
        blocked.push(block('SECOND_TRADE_GRADE', 'A second position requires an A or A+ setup.'));
      }
      if (!trade?.independence_confirmed) {
        blocked.push(block('SECOND_TRADE_INDEPENDENCE', 'A second position requires explicit confirmation that it is independent of the first. Two correlated bets are not independent.'));
      }
      if (!String(trade?.second_trade_rationale || '').trim()) {
        blocked.push(block('SECOND_TRADE_RATIONALE', 'A second position requires a recorded rationale.'));
      }
      if (correlation && !correlation.independent) {
        blocked.push(block('SECOND_TRADE_CORRELATED', 'This candidate correlates with an open position, so it cannot qualify as an independent second trade.'));
      }
    }
  }

  /* ── Intent ─────────────────────────────────────────────────────────── */
  const intent = TRADE_INTENTS.find(i => i.id === trade?.trade_intent);
  if (intent?.blocked) {
    blocked.push(block('REVENGE_INTENT', 'Recovery / revenge trading is blocked. Losses stay recorded; the system will not chase them.'));
  }
  if (trade?.trade_intent === 'OTHER' && !String(trade?.intent_note || '').trim()) {
    blocked.push(block('INTENT_NOTE', 'Trade intent "Other" requires a note.'));
  }

  /* ── Correlation ────────────────────────────────────────────────────── */
  if (correlation?.conflict) {
    blocked.push(block('CORRELATION', `An open position already exists on ${correlation.sameUnderlying[0]?.symbol}. Same-underlying conflict.`));
  } else if (correlation?.warn) {
    warnings.push(warn('CORRELATION_SECTOR', `${correlation.sameSector.length} open position(s) in the same sector — check that this is a genuinely independent bet.`));
  }

  /* ── Soft warnings §9 ───────────────────────────────────────────────── */
  const priceRisk = Number(planned?.priceRisk) || 0;
  const estCharges = Number(planned?.estimatedCharges) || 0;
  if (priceRisk > 0 && estCharges / priceRisk > (config?.chargesWarnRatio ?? 0.25)) {
    warnings.push(warn('HIGH_CHARGES',
      `Estimated charges ₹${estCharges.toFixed(2)} are ${((estCharges / priceRisk) * 100).toFixed(0)}% of planned price risk — the cost base is heavy for this size.`));
  }

  const closedSorted = recentTrades
    .filter(isClosed)
    .slice()
    .sort((a, b) => String(b.exit_date || b.entry_date).localeCompare(String(a.exit_date || a.entry_date)));

  if (closedSorted[0] && Number(closedSorted[0]._netPnl ?? closedSorted[0].net_pnl) < 0) {
    warnings.push(warn('AFTER_LOSS', 'This trade follows a loss. Confirm the setup stands on its own merit.'));
  }

  const segLosses = closedSorted
    .filter(t => t.segment === trade?.segment)
    .slice(0, 3)
    .filter(t => Number(t._netPnl ?? t.net_pnl) < 0);
  if (segLosses.length >= 2) {
    warnings.push(warn('SEGMENT_LOSS_STREAK', `${segLosses.length} of the last 3 ${seg?.label} trades were losses.`));
  }

  return {
    blocked,
    warnings,
    ok: blocked.length === 0,
    // Grade, revenge intent and hard capacity limits are never overridable.
    canOverride: blocked.every(b => !['GRADE', 'REVENGE_INTENT', 'MONTHLY_LIMIT', 'COUNTER_LOCKED', 'RISK_EXCEEDS_COUNTER', 'RESERVE_CAPACITY', 'DAILY_LIMIT', 'POSITION_LIMIT', 'NOT_CONFIGURED'].includes(b.code))
  };
}

/** Withdrawals may only come from real cash — never from a risk bucket. */
export function validateWithdrawal({ amount, accountView }) {
  const blocked = [];
  const amt = Number(amount) || 0;
  if (amt <= 0) blocked.push(block('AMOUNT', 'Withdrawal amount must be greater than zero.'));
  if (amt > (accountView?.withdrawableCash ?? 0) + 0.001) {
    blocked.push(block('INSUFFICIENT_CASH',
      `Withdrawable broker cash is ₹${(accountView?.withdrawableCash ?? 0).toFixed(2)}. Risk buckets are controls, not cash, and cannot be withdrawn.`));
  }
  return { blocked, ok: blocked.length === 0, warnings: [] };
}

/** Releasing Growth Reserve after losses is allowed but flagged. */
export function validateGrowthRelease({ amount, accountView, monthView }) {
  const blocked = [];
  const warnings = [];
  const amt = Number(amount) || 0;
  if (amt <= 0) blocked.push(block('AMOUNT', 'Amount must be greater than zero.'));
  if (amt > (accountView?.growthReserve ?? 0) + 0.001) {
    blocked.push(block('INSUFFICIENT_GROWTH', `Growth Reserve holds ₹${(accountView?.growthReserve ?? 0).toFixed(2)}.`));
  }
  if ((monthView?.stats?.netPnl ?? 0) < 0) {
    warnings.push(warn('GROWTH_AFTER_LOSS',
      'You are drawing on the Growth Reserve in a losing month. This adds cash but does not raise any risk limit.'));
  }
  return { blocked, warnings, ok: blocked.length === 0 };
}
