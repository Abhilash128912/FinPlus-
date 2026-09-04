/**
 * scoring.js — Setup scoring, eligibility, ranking and the NO TRADE decision.
 *
 * The app never invents a score. Sub-scores are entered by the user (there is no
 * data feed that could judge "higher-timeframe confirmation"); the app owns the
 * arithmetic, the A/A+ threshold, the ranking and the audit trail.
 */

import { SCORE_CATEGORIES, gradeFromScore, maxScore, getSegment } from './risk_model.js';
import { computePlannedRisk } from './risk_engine.js';

export function scoreSetup(scores = {}) {
  let total = 0;
  const detail = SCORE_CATEGORIES.map(c => {
    const raw = Number(scores[c.id]);
    const value = Number.isFinite(raw) ? Math.max(0, Math.min(c.max, raw)) : 0;
    total += value;
    return { ...c, value, complete: Number.isFinite(raw) };
  });
  const grade = gradeFromScore(total);
  return {
    total,
    max: maxScore(),
    detail,
    grade: grade.id,
    gradeLabel: grade.label,
    eligibleGrade: grade.eligible,
    incomplete: detail.filter(d => !d.complete).map(d => d.id)
  };
}

export function riskReward(setup) {
  const entry = Number(setup?.entry_price) || 0;
  const sl = Number(setup?.stop_loss_price) || 0;
  const target = Number(setup?.target_price) || 0;
  if (!entry || !sl || !target) return null;
  const risk = Math.abs(entry - sl);
  const reward = Math.abs(target - entry);
  if (!risk) return null;
  return Number((reward / risk).toFixed(2));
}

/**
 * Rank eligible candidates per brief §4.
 * A+ first, then score, R:R, confirmation, cost ratio, segment capacity, correlation.
 */
export function rankCandidates(candidates) {
  return candidates
    .slice()
    .sort((a, b) => {
      const aPlus = (x) => (x.score?.grade === 'A_PLUS' ? 1 : 0);
      if (aPlus(b) !== aPlus(a)) return aPlus(b) - aPlus(a);
      if ((b.score?.total || 0) !== (a.score?.total || 0)) return (b.score?.total || 0) - (a.score?.total || 0);
      if ((b.riskReward || 0) !== (a.riskReward || 0)) return (b.riskReward || 0) - (a.riskReward || 0);
      const conf = (x) => Number(x.score?.detail?.find(d => d.id === 'htf')?.value || 0);
      if (conf(b) !== conf(a)) return conf(b) - conf(a);
      // Lower estimated cost relative to planned risk wins.
      const costRatio = (x) => (x.planned?.priceRisk ? x.planned.estimatedCharges / x.planned.priceRisk : 99);
      if (costRatio(a) !== costRatio(b)) return costRatio(a) - costRatio(b);
      // More available segment capacity wins.
      const cap = (x) => (x.segmentRemaining === null ? Number.MAX_SAFE_INTEGER : x.segmentRemaining || 0);
      if (cap(b) !== cap(a)) return cap(b) - cap(a);
      return (a.correlationScore || 0) - (b.correlationScore || 0);
    })
    .map((c, i) => ({ ...c, rank: i + 1 }));
}

/**
 * Correlation against currently open trades.
 * Same underlying = conflict (blocking by default). Same sector/index = warning.
 */
export function assessCorrelation(candidate, openTrades = [], config = {}) {
  const sym = String(candidate?.symbol || '').toUpperCase().trim();
  const underlying = String(candidate?.underlying || sym).toUpperCase().trim();
  const sector = String(candidate?.sector || '').toUpperCase().trim();

  const sameUnderlying = openTrades.filter(t => {
    const tu = String(t.underlying || t.symbol || '').toUpperCase().trim();
    return tu && (tu === underlying || tu === sym);
  });
  const sameSector = openTrades.filter(t => {
    const ts = String(t.sector || '').toUpperCase().trim();
    return sector && ts && ts === sector && !sameUnderlying.includes(t);
  });

  return {
    sameUnderlying,
    sameSector,
    conflict: config?.correlationBlockSameUnderlying !== false && sameUnderlying.length > 0,
    warn: sameSector.length > 0,
    correlationScore: sameUnderlying.length * 10 + sameSector.length,
    independent: sameUnderlying.length === 0 && sameSector.length === 0
  };
}

/**
 * Evaluate every candidate setup for a day and produce the recommendation
 * (or an explicit NO TRADE).
 *
 * @param {Function} args.validate  validateTradeEntry bound to current state
 */
export function evaluateDay({ setups = [], monthView, dailySnapshot, profiles, config, validate }) {
  const openTrades = monthView?.openTrades || [];

  const evaluated = setups.map(setup => {
    const seg = getSegment(setup.segment);
    const score = scoreSetup(setup.scores);
    const planned = computePlannedRisk(setup, profiles, config);
    const rr = riskReward(setup);
    const correlation = assessCorrelation(setup, openTrades, config);
    const segView = monthView?.segments?.find(s => s.id === setup.segment);

    const verdict = validate
      ? validate({ trade: setup, score, planned, correlation, segView, dailySnapshot, monthView })
      : { blocked: [], warnings: [] };

    const noSetup = !!setup.no_setup;
    const eligible =
      !noSetup && score.eligibleGrade && verdict.blocked.length === 0;

    return {
      ...setup,
      segmentLabel: seg?.label || setup.segment,
      score,
      planned,
      riskReward: rr,
      correlation,
      correlationScore: correlation.correlationScore,
      segmentRemaining: segView?.remainingRisk ?? null,
      eligible,
      blocked: verdict.blocked,
      warnings: verdict.warnings,
      rejectionReason: noSetup
        ? 'No setup recorded for this segment today.'
        : !score.eligibleGrade
          ? `Grade ${score.gradeLabel} (${score.total}/${score.max}) — below A.`
          : verdict.blocked[0]?.message || null
    };
  });

  const eligible = rankCandidates(evaluated.filter(c => c.eligible));
  const rejected = evaluated.filter(c => !c.eligible);

  return {
    candidates: [...eligible, ...rejected],
    eligible,
    rejected,
    recommendation: eligible[0] || null,
    noTrade: eligible.length === 0,
    noTradeMessage: 'NO TRADE — no A/A+ opportunity meets all risk rules.'
  };
}
