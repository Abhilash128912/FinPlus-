/**
 * risk_engine.js — All derived state for the Risk Desk.
 *
 * Pure functions over the stored collections. Runs locally so the Android build
 * keeps working offline; the backend re-computes the same numbers and owns the
 * audit log (see risk_storage.js).
 */

import {
  SEGMENTS,
  OPPORTUNITY_RESERVE,
  getSegment,
  currentMonthKey,
  plannedPriceRisk,
  plannedTotalRisk,
  grossPnl,
  netPnl,
  segmentRiskRemaining,
  monthlyRiskRemaining,
  brokerCashBalance,
  DEFAULT_CONFIG
} from './risk_model.js';
import { estimateCharges, sumChargeBreakdown } from './broker_profiles.js';

const r2 = n => Number((Number(n) || 0).toFixed(2));

export const isClosed = t => String(t?.status || '').toUpperCase() === 'CLOSED' && Number(t?.exit_price) > 0;
export const isOpen = t => !isClosed(t);

export function tradeMonthKey(t) {
  return String(t?.entry_date || t?.created_at || '').slice(0, 7);
}
export function tradeDayKey(t) {
  return String(t?.entry_date || t?.created_at || '').slice(0, 10);
}

/** Broker for a trade: explicit override, else the configured segment broker. */
export function resolveBroker(trade, config = DEFAULT_CONFIG) {
  if (trade?.broker) return trade.broker;
  const segId = trade?.segment;
  const configured = config?.segmentBroker?.[segId];
  if (configured) return configured;
  if (segId === 'LONG_TERM') return config?.longTermBroker || null;
  return null;
}

/** Configured planned stop-loss for a segment, if the user has set one. */
export function segmentPlannedSL(segId, config = DEFAULT_CONFIG) {
  const v = config?.segmentSL?.[segId];
  return Number(v) > 0 ? Number(v) : null;
}

/** Planned risk for a trade, using its stored SL or the segment default. */
export function computePlannedRisk(trade, profiles, config = DEFAULT_CONFIG) {
  const seg = getSegment(trade?.segment);
  const broker = resolveBroker(trade, config);
  const priceRisk = plannedPriceRisk(trade);

  const est = estimateCharges({
    profiles,
    broker,
    product: seg?.product,
    entryPrice: trade?.entry_price,
    exitPrice: trade?.stop_loss_price, // cost measured at the stop, the planned worst case
    quantity: trade?.quantity,
    lotSize: trade?.lot_size || 1,
    isShort: trade?.direction === 'SHORT',
    date: trade?.entry_date
  });

  return {
    priceRisk,
    estimatedCharges: est.total,
    estimatedBreakdown: est.breakdown,
    chargeProfileId: est.profileId,
    chargeError: est.error,
    totalRisk: plannedTotalRisk(priceRisk, est.total)
  };
}

/**
 * Risk actually committed by a trade.
 *
 * Once a trade is recorded, the risk it committed is locked to the figure stored
 * at entry — re-deriving it from current fields would let an edit silently free
 * up budget, and would disagree with the server's own re-validation.
 */
export function committedRiskOf(trade, profiles, config = DEFAULT_CONFIG) {
  const stored = Number(trade?.planned_total_risk);
  if (stored > 0) return r2(stored);
  return r2(computePlannedRisk(trade, profiles, config).totalRisk);
}

/** Realized or live P&L for one trade. `ltp` drives live P&L on open positions. */
export function computeTradePnl(trade, profiles, config = DEFAULT_CONFIG, ltp = null) {
  const seg = getSegment(trade?.segment);
  const broker = resolveBroker(trade, config);
  const closed = isClosed(trade);
  const markPrice = closed ? Number(trade.exit_price) : Number(ltp) || 0;

  const gross = markPrice > 0
    ? grossPnl({
        entry_price: trade.entry_price,
        exit_price: markPrice,
        quantity: trade.quantity,
        lot_size: trade.lot_size || 1,
        direction: trade.direction || 'LONG'
      })
    : 0;

  const est = estimateCharges({
    profiles,
    broker,
    product: seg?.product,
    entryPrice: trade?.entry_price,
    exitPrice: markPrice,
    quantity: trade?.quantity,
    lotSize: trade?.lot_size || 1,
    isShort: trade?.direction === 'SHORT',
    date: trade?.exit_date || trade?.entry_date
  });

  const hasActual = closed && trade.actual_charges && sumChargeBreakdown(trade.actual_charges) > 0;
  const actualCharges = hasActual ? sumChargeBreakdown(trade.actual_charges) : est.total;

  return {
    isLive: !closed && markPrice > 0,
    hasLivePrice: !closed && markPrice > 0,
    markPrice,
    gross,
    estimatedCharges: est.total,
    estimatedBreakdown: est.breakdown,
    actualCharges: r2(actualCharges),
    usingActual: hasActual,
    net: netPnl(gross, actualCharges),
    // Estimated-vs-actual variance is only meaningful once a contract note is in.
    chargeVariance: hasActual ? r2(actualCharges - est.total) : null,
    chargeVariancePct: hasActual && est.total > 0 ? r2(((actualCharges - est.total) / est.total) * 100) : null
  };
}

/**
 * Attach computed P&L to every trade, across all months.
 * The accrual counter runs continuously, so it needs the full history, not
 * just the selected month.
 */
export function enrichTrades({ trades = [], profiles = [], config = DEFAULT_CONFIG, ltps = {} }) {
  return trades.map(t => {
    const symbol = String(t.symbol || '').replace('.NS', '').trim().toUpperCase();
    const ltp = t.manual_ltp != null && Number(t.manual_ltp) > 0 ? Number(t.manual_ltp) : ltps?.[symbol];
    return {
      ...t,
      symbol,
      _planned: computePlannedRisk(t, profiles, config),
      _pnl: computeTradePnl(t, profiles, config, ltp),
      _committed: committedRiskOf(t, profiles, config),
      _closed: isClosed(t)
    };
  });
}

/** Peak-to-trough drawdown over a chronological series of net P&L values. */
function computeDrawdown(sortedNetPnls) {
  let cum = 0;
  let peak = 0;
  let maxDd = 0;
  for (const v of sortedNetPnls) {
    cum += Number(v) || 0;
    if (cum > peak) peak = cum;
    const dd = peak - cum;
    if (dd > maxDd) maxDd = dd;
  }
  return { cumulative: r2(cum), peak: r2(peak), maxDrawdown: r2(maxDd), currentDrawdown: r2(peak - cum) };
}

/**
 * Build the full derived view for one month.
 *
 * @param {object} args
 * @param {object} args.month        month record
 * @param {Array}  args.trades       all risk-desk trades
 * @param {Array}  args.reserveTransfers
 * @param {Array}  args.profiles     broker charge profiles
 * @param {object} args.config
 * @param {object} args.ltps         { SYMBOL: price } — live prices, read-only
 */
export function buildMonthView({ month, trades = [], reserveTransfers = [], profiles = [], config = DEFAULT_CONFIG, ltps = {} }) {
  const key = month?.month_key;
  const monthTrades = trades.filter(t => tradeMonthKey(t) === key);

  const enriched = monthTrades.map(t => {
    const symbol = String(t.symbol || '').replace('.NS', '').trim().toUpperCase();
    const ltp = t.manual_ltp != null && Number(t.manual_ltp) > 0 ? Number(t.manual_ltp) : ltps?.[symbol];
    const planned = computePlannedRisk(t, profiles, config);
    const pnl = computeTradePnl(t, profiles, config, ltp);
    return {
      ...t, symbol, _planned: planned, _pnl: pnl,
      _committed: committedRiskOf(t, profiles, config),
      _closed: isClosed(t)
    };
  });

  const transfersThisMonth = reserveTransfers.filter(x => String(x.month_key) === key);
  const reserveInBySegment = transfersThisMonth.reduce((acc, x) => {
    acc[x.to_segment] = (acc[x.to_segment] || 0) + (Number(x.amount) || 0);
    return acc;
  }, {});
  const reserveTransferredOut = r2(transfersThisMonth.reduce((s, x) => s + (Number(x.amount) || 0), 0));

  const segments = SEGMENTS.map(seg => {
    const segTrades = enriched.filter(t => t.segment === seg.id);
    const closedTrades = segTrades.filter(t => t._closed);

    const committed = r2(segTrades.reduce((s, t) => s + (t._committed || 0), 0));
    const reserveIn = r2(reserveInBySegment[seg.id] || 0);
    const bucket = month.buckets?.[seg.id] || {};
    const initial = bucket.initial_allocation; // null = uncapped

    const gross = r2(closedTrades.reduce((s, t) => s + t._pnl.gross, 0));
    const charges = r2(closedTrades.reduce((s, t) => s + t._pnl.actualCharges, 0));
    const net = r2(closedTrades.reduce((s, t) => s + t._pnl.net, 0));

    const openTrades = segTrades.filter(t => !t._closed);
    const liveGross = r2(openTrades.reduce((s, t) => s + t._pnl.gross, 0));
    const liveNet = r2(openTrades.reduce((s, t) => s + (t._pnl.hasLivePrice ? t._pnl.net : 0), 0));
    const liveCoverage = openTrades.length
      ? openTrades.filter(t => t._pnl.hasLivePrice).length / openTrades.length
      : 1;

    const ordered = closedTrades
      .slice()
      .sort((a, b) => String(a.exit_date || a.entry_date).localeCompare(String(b.exit_date || b.entry_date)));
    const dd = computeDrawdown(ordered.map(t => t._pnl.net));

    return {
      ...seg,
      broker: config?.segmentBroker?.[seg.id] || (seg.id === 'LONG_TERM' ? config?.longTermBroker : null) || null,
      plannedSL: segmentPlannedSL(seg.id, config),
      initialAllocation: initial,
      reserveReceived: reserveIn,
      committedRisk: committed,
      remainingRisk: segmentRiskRemaining({
        initial_allocation: initial,
        reserve_transferred_in: reserveIn,
        committed_planned_risk: committed
      }),
      tradeCount: segTrades.length,
      openCount: openTrades.length,
      closedCount: closedTrades.length,
      grossPnl: gross,
      actualCharges: charges,
      netPnl: net,
      liveGrossPnl: liveGross,
      liveNetPnl: liveNet,
      liveCoverage,
      avgCostPerTrade: closedTrades.length ? r2(charges / closedTrades.length) : 0,
      drawdown: dd,
      trades: segTrades
    };
  });

  const committedTotal = r2(segments.reduce((s, x) => s + x.committedRisk, 0));
  const closedAll = enriched.filter(t => t._closed);
  const openAll = enriched.filter(t => !t._closed);

  const grossTotal = r2(closedAll.reduce((s, t) => s + t._pnl.gross, 0));
  const chargesTotal = r2(closedAll.reduce((s, t) => s + t._pnl.actualCharges, 0));
  const netTotal = r2(closedAll.reduce((s, t) => s + t._pnl.net, 0));
  const wins = closedAll.filter(t => t._pnl.net > 0).length;

  const orderedAll = closedAll
    .slice()
    .sort((a, b) => String(a.exit_date || a.entry_date).localeCompare(String(b.exit_date || b.entry_date)));

  const varianceTrades = closedAll.filter(t => t._pnl.chargeVariance !== null);

  return {
    monthKey: key,
    mode: month.mode,
    monthlyRiskBudget: month.monthly_risk_budget,
    preexistingUsage: month.preexisting_usage || 0,
    preexistingSegment: month.preexisting_segment || null,
    enforceSegmentQuotas: month.enforce_segment_quotas !== false,
    committedRisk: committedTotal,
    remainingRisk: monthlyRiskRemaining({
      monthly_risk_budget: month.monthly_risk_budget,
      preexisting_usage: month.preexisting_usage || 0,
      committed_planned_risk: committedTotal
    }),
    reserve: {
      ...OPPORTUNITY_RESERVE,
      initialAllocation: month.reserve?.initial_allocation ?? 0,
      transferredOut: reserveTransferredOut,
      remaining: r2((month.reserve?.initial_allocation ?? 0) - reserveTransferredOut),
      transfers: transfersThisMonth
    },
    segments,
    trades: enriched,
    openTrades: openAll,
    closedTrades: closedAll,
    stats: {
      tradeCount: enriched.length,
      closedCount: closedAll.length,
      openCount: openAll.length,
      grossPnl: grossTotal,
      actualCharges: chargesTotal,
      netPnl: netTotal,
      liveGrossPnl: r2(openAll.reduce((s, t) => s + t._pnl.gross, 0)),
      liveNetPnl: r2(openAll.reduce((s, t) => s + (t._pnl.hasLivePrice ? t._pnl.net : 0), 0)),
      liveTrackedCount: openAll.filter(t => t._pnl.hasLivePrice).length,
      winRate: closedAll.length ? r2((wins / closedAll.length) * 100) : 0,
      avgCostPerTrade: closedAll.length ? r2(chargesTotal / closedAll.length) : 0,
      drawdown: computeDrawdown(orderedAll.map(t => t._pnl.net)),
      chargeVariance: varianceTrades.length
        ? r2(varianceTrades.reduce((s, t) => s + t._pnl.chargeVariance, 0))
        : 0,
      chargeVarianceCount: varianceTrades.length
    }
  };
}

/** Today's position count and planned risk versus the daily limit. */
export function buildDailySnapshot({ trades = [], profiles = [], config = DEFAULT_CONFIG, day = null }) {
  const today = day || new Date().toISOString().slice(0, 10);
  const todays = trades.filter(t => tradeDayKey(t) === today);
  const plannedRisk = r2(
    todays.reduce((s, t) => s + committedRiskOf(t, profiles, config), 0)
  );
  const limit = Number(config?.dailyRiskLimit ?? DEFAULT_CONFIG.dailyRiskLimit);
  return {
    day: today,
    positionCount: todays.length,
    maxPositions: config?.maxPositionsPerDay ?? DEFAULT_CONFIG.maxPositionsPerDay,
    maxPositionsExceptional: config?.maxPositionsExceptional ?? DEFAULT_CONFIG.maxPositionsExceptional,
    plannedRisk,
    dailyRiskLimit: limit,
    remaining: r2(limit - plannedRisk),
    trades: todays
  };
}

/** Cumulative view across every month — cash, growth reserve and lifetime P&L. */
export function buildAccountView({ trades = [], cashLedger = [], growthLedger = [], profiles = [], config = DEFAULT_CONFIG }) {
  const closed = trades.filter(isClosed);
  const realizedNet = r2(
    closed.reduce((s, t) => s + computeTradePnl(t, profiles, config).net, 0)
  );

  const sumBy = (rows, type) => r2(rows.filter(x => x.type === type).reduce((s, x) => s + (Number(x.amount) || 0), 0));

  const openingCash = r2(cashLedger.filter(x => x.type === 'OPENING').reduce((s, x) => s + (Number(x.amount) || 0), 0));
  const deposits = sumBy(cashLedger, 'DEPOSIT');
  const withdrawals = sumBy(cashLedger, 'WITHDRAWAL');
  const toGrowth = sumBy(growthLedger, 'TO_GROWTH');
  const fromGrowth = sumBy(growthLedger, 'FROM_GROWTH');

  const cash = brokerCashBalance({
    opening_cash: openingCash,
    deposits,
    realized_net_pnl: realizedNet,
    withdrawals,
    transfers_to_growth_reserve: toGrowth,
    releases_from_growth_reserve: fromGrowth
  });

  const ordered = closed
    .slice()
    .sort((a, b) => String(a.exit_date || a.entry_date).localeCompare(String(b.exit_date || b.entry_date)));

  return {
    openingCash,
    deposits,
    withdrawals,
    realizedNetPnl: realizedNet,
    growthReserve: r2(toGrowth - fromGrowth),
    transfersToGrowth: toGrowth,
    releasesFromGrowth: fromGrowth,
    brokerCash: cash,
    // Only realized profit is withdrawable; risk buckets are controls, never cash.
    withdrawableCash: r2(Math.max(0, cash)),
    lifetime: computeDrawdown(ordered.map(t => computeTradePnl(t, profiles, config).net))
  };
}

/** Symbols the Risk Desk needs live prices for (open trades only). */
export function liveSymbolsFor(trades = []) {
  return Array.from(
    new Set(
      trades
        .filter(isOpen)
        .filter(t => getSegment(t.segment)?.livePnlEligible)
        .map(t => String(t.live_symbol || t.symbol || '').replace('.NS', '').trim().toUpperCase())
        .filter(Boolean)
    )
  );
}
