/**
 * broker_profiles.js — Effective-dated, configurable broker charge profiles.
 *
 * Brief §5: "The exact broker rate tables must be configurable by effective date,
 * not embedded in code." Rates therefore live in DATA below and can be overridden
 * at runtime (persisted to the risk-desk store), never in the calculation logic.
 *
 * Seed rates are lifted verbatim from the already-audited calculators in
 * journal_engine.js so Risk Desk numbers agree with the existing journal.
 */

export const BROKERS = {
  INDMONEY: { id: 'INDMONEY', label: 'INDmoney' },
  ZERODHA: { id: 'ZERODHA', label: 'Zerodha' }
};

/** Product types a segment can map onto. */
export const PRODUCTS = {
  EQ_INTRADAY: 'EQ_INTRADAY',
  EQ_DELIVERY: 'EQ_DELIVERY',
  INDEX_OPTION: 'INDEX_OPTION',
  STOCK_OPTION: 'STOCK_OPTION',
  MCX_FUTURE: 'MCX_FUTURE',
  MCX_OPTION: 'MCX_OPTION'
};

/**
 * A rule is one of:
 *   { type: 'none' }
 *   { type: 'flat_per_order', amount }                 — charged per executed order (leg)
 *   { type: 'min_of_pct_or_flat', pct, cap }           — per leg: min(turnover*pct, cap)
 *   { type: 'pct', pct, on: 'buy'|'sell'|'total' }
 *   { type: 'flat_on_exit', amount }                   — e.g. DP charges on sell
 */
const GST_RATE = 0.18;
const SEBI_RULE = { type: 'pct', pct: 0.000001, on: 'total' }; // Rs.10 per crore

const NSE_EQ_INTRADAY = {
  brokerage: { type: 'min_of_pct_or_flat', pct: 0.0003, cap: 20 },
  stt: { type: 'pct', pct: 0.00025, on: 'sell' },
  exchange_txn: { type: 'pct', pct: 0.0000297, on: 'total' },
  sebi: SEBI_RULE,
  stamp_duty: { type: 'pct', pct: 0.00003, on: 'buy' },
  dp_charges: { type: 'none' }
};

const NSE_OPTION = {
  brokerage: { type: 'flat_per_order', amount: 20 },
  stt: { type: 'pct', pct: 0.001, on: 'sell' },
  exchange_txn: { type: 'pct', pct: 0.0003553, on: 'total' },
  sebi: SEBI_RULE,
  stamp_duty: { type: 'pct', pct: 0.00003, on: 'buy' },
  dp_charges: { type: 'none' }
};

const MCX_FUTURE = {
  brokerage: { type: 'min_of_pct_or_flat', pct: 0.0003, cap: 20 },
  stt: { type: 'pct', pct: 0.0001, on: 'sell' }, // CTT
  exchange_txn: { type: 'pct', pct: 0.000021, on: 'total' },
  sebi: SEBI_RULE,
  stamp_duty: { type: 'pct', pct: 0.00002, on: 'buy' },
  dp_charges: { type: 'none' }
};

const MCX_OPTION = {
  brokerage: { type: 'flat_per_order', amount: 20 },
  stt: { type: 'pct', pct: 0.0005, on: 'sell' }, // CTT
  exchange_txn: { type: 'pct', pct: 0.000418, on: 'total' },
  sebi: SEBI_RULE,
  stamp_duty: { type: 'pct', pct: 0.00003, on: 'buy' },
  dp_charges: { type: 'none' }
};

/**
 * Seed profiles. `effective_from` is inclusive, `effective_to` null = still current.
 * To change rates later, append a new profile with a later effective_from rather
 * than editing an existing one — history stays reproducible.
 */
export const SEED_CHARGE_PROFILES = [
  {
    id: 'indmoney_v1',
    broker: 'INDMONEY',
    label: 'INDmoney (zero-brokerage delivery)',
    effective_from: '2026-04-01',
    effective_to: null,
    products: {
      [PRODUCTS.EQ_INTRADAY]: NSE_EQ_INTRADAY,
      [PRODUCTS.EQ_DELIVERY]: {
        brokerage: { type: 'none' },
        stt: { type: 'pct', pct: 0.001, on: 'total' },
        exchange_txn: { type: 'pct', pct: 0.0000297, on: 'total' },
        sebi: SEBI_RULE,
        stamp_duty: { type: 'pct', pct: 0.00015, on: 'buy' },
        dp_charges: { type: 'flat_on_exit', amount: 14.75 }
      },
      [PRODUCTS.INDEX_OPTION]: NSE_OPTION,
      [PRODUCTS.STOCK_OPTION]: NSE_OPTION,
      [PRODUCTS.MCX_FUTURE]: MCX_FUTURE,
      [PRODUCTS.MCX_OPTION]: MCX_OPTION
    }
  },
  {
    id: 'zerodha_v1',
    broker: 'ZERODHA',
    label: 'Zerodha Kite',
    effective_from: '2026-04-01',
    effective_to: null,
    products: {
      [PRODUCTS.EQ_INTRADAY]: NSE_EQ_INTRADAY,
      [PRODUCTS.EQ_DELIVERY]: {
        brokerage: { type: 'none' },
        stt: { type: 'pct', pct: 0.001, on: 'total' },
        exchange_txn: { type: 'pct', pct: 0.0000307, on: 'total' },
        sebi: SEBI_RULE,
        stamp_duty: { type: 'pct', pct: 0.00015, on: 'buy' },
        dp_charges: { type: 'flat_on_exit', amount: 15.34 }
      },
      [PRODUCTS.INDEX_OPTION]: NSE_OPTION,
      [PRODUCTS.STOCK_OPTION]: NSE_OPTION,
      [PRODUCTS.MCX_FUTURE]: MCX_FUTURE,
      [PRODUCTS.MCX_OPTION]: MCX_OPTION
    }
  }
];

/** Pick the profile in force for a broker on a given ISO date. */
export function resolveChargeProfile(profiles, broker, isoDate) {
  if (!broker) return null;
  const day = String(isoDate || new Date().toISOString()).slice(0, 10);
  const candidates = (profiles || [])
    .filter(p => p.broker === broker)
    .filter(p => String(p.effective_from || '') <= day)
    .filter(p => !p.effective_to || String(p.effective_to) >= day)
    .sort((a, b) => String(b.effective_from).localeCompare(String(a.effective_from)));
  return candidates[0] || null;
}

function applyRule(rule, ctx) {
  if (!rule || rule.type === 'none') return 0;
  const { buyTurnover, sellTurnover, totalTurnover, legs, isClosed } = ctx;
  switch (rule.type) {
    case 'flat_per_order':
      return (Number(rule.amount) || 0) * legs;
    case 'min_of_pct_or_flat': {
      const pct = Number(rule.pct) || 0;
      const cap = Number(rule.cap) || 0;
      const buyLeg = Math.min(buyTurnover * pct, cap);
      const sellLeg = isClosed ? Math.min(sellTurnover * pct, cap) : 0;
      return buyLeg + sellLeg;
    }
    case 'pct': {
      const pct = Number(rule.pct) || 0;
      const base =
        rule.on === 'buy' ? buyTurnover : rule.on === 'sell' ? sellTurnover : totalTurnover;
      return base * pct;
    }
    case 'flat_on_exit':
      return isClosed ? Number(rule.amount) || 0 : 0;
    default:
      return 0;
  }
}

const EMPTY_BREAKDOWN = {
  brokerage: 0,
  stt: 0,
  exchange_txn: 0,
  sebi: 0,
  stamp_duty: 0,
  gst: 0,
  dp_charges: 0,
  other: 0,
  total: 0
};

/**
 * Estimate the full charge breakdown for a trade.
 *
 * For an OPEN trade both legs are still estimated (round-trip cost), because
 * planned_total_risk must include the cost of getting out. `isClosed` only
 * governs charges that genuinely cannot apply until exit (DP charges).
 *
 * @returns {{ breakdown, total, profileId, error }}
 */
export function estimateCharges({
  profiles,
  broker,
  product,
  entryPrice,
  exitPrice,
  quantity,
  lotSize = 1,
  isShort = false,
  date
}) {
  const profile = resolveChargeProfile(profiles, broker, date);
  if (!profile) {
    return {
      breakdown: { ...EMPTY_BREAKDOWN },
      total: 0,
      profileId: null,
      error: `No active charge profile for broker "${broker || '—'}" on ${String(date || '').slice(0, 10)}.`
    };
  }
  const rules = profile.products?.[product];
  if (!rules) {
    return {
      breakdown: { ...EMPTY_BREAKDOWN },
      total: 0,
      profileId: profile.id,
      error: `Profile "${profile.label}" has no rates for product ${product}.`
    };
  }

  const entry = Number(entryPrice) || 0;
  const exit = Number(exitPrice) || 0;
  const units = (Number(quantity) || 0) * (Number(lotSize) || 1);
  if (entry <= 0 || units <= 0) {
    return { breakdown: { ...EMPTY_BREAKDOWN }, total: 0, profileId: profile.id, error: null };
  }

  const isClosed = exit > 0;
  // Unknown exit -> assume a round trip at entry price so cost is never understated.
  const assumedExit = isClosed ? exit : entry;
  const buyTurnover = (isShort ? assumedExit : entry) * units;
  const sellTurnover = (isShort ? entry : assumedExit) * units;
  const ctx = {
    buyTurnover,
    sellTurnover,
    totalTurnover: buyTurnover + sellTurnover,
    legs: 2, // both legs always priced in
    isClosed: true // both legs assumed executed for cost purposes
  };

  const brokerage = applyRule(rules.brokerage, ctx);
  const stt = applyRule(rules.stt, ctx);
  const exchangeTxn = applyRule(rules.exchange_txn, ctx);
  const sebi = applyRule(rules.sebi, ctx);
  const stampDuty = applyRule(rules.stamp_duty, ctx);
  const dpCharges = applyRule(rules.dp_charges, { ...ctx, isClosed });
  const gst = (brokerage + exchangeTxn + sebi) * GST_RATE;

  const round = n => Number((Number(n) || 0).toFixed(2));
  const breakdown = {
    brokerage: round(brokerage),
    stt: round(stt),
    exchange_txn: round(exchangeTxn),
    sebi: round(sebi),
    stamp_duty: round(stampDuty),
    gst: round(gst),
    dp_charges: round(dpCharges),
    other: 0,
    total: 0
  };
  breakdown.total = round(
    breakdown.brokerage +
      breakdown.stt +
      breakdown.exchange_txn +
      breakdown.sebi +
      breakdown.stamp_duty +
      breakdown.gst +
      breakdown.dp_charges
  );

  return { breakdown, total: breakdown.total, profileId: profile.id, error: null };
}

/** actual_total_charges — sums a manually entered / imported contract-note breakdown. */
export function sumChargeBreakdown(b) {
  if (!b) return 0;
  const keys = ['brokerage', 'stt', 'exchange_txn', 'sebi', 'stamp_duty', 'gst', 'dp_charges', 'other'];
  return Number(keys.reduce((s, k) => s + (Number(b[k]) || 0), 0).toFixed(2));
}
