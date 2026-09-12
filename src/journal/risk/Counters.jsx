import React, { useState } from 'react';
import { C, inr, pnlColor, Panel, Stat, StatGrid, Bar, Chip, Btn, Empty } from './ui.jsx';
import InWindowTradeModal from './InWindowTradeModal.jsx';
import SquareOffModal from './SquareOffModal.jsx';
import EditOpenTradeModal from './EditOpenTradeModal.jsx';

/**
 * Daily risk counters — the core of the accrual model.
 *
 * Each lane drips its allocation daily. Reaching the segment stop-loss unlocks
 * trading. A win leaves the counter alone; a booked loss resets it to zero and
 * takes the actual net loss out of that segment's capital.
 */
export default function Counters({ accrualState, monthView, desk }) {
  const [tradingSegment, setTradingSegment] = useState(null);
  const [squaringOffTrade, setSquaringOffTrade] = useState(null);
  const [editingOpenTrade, setEditingOpenTrade] = useState(null);

  if (!accrualState) return null;

  if (!accrualState.started) {
    return (
      <Panel title="Daily risk counters" accent="rgba(245,158,11,0.35)">
        <Empty>
          {accrualState.startDate
            ? `Accrual begins ${accrualState.startDate}. Counters start ticking that day.`
            : 'No accrual start date set. Add one on the Setup screen to start the counters.'}
        </Empty>
      </Panel>
    );
  }

  const lanes = accrualState.lanes;
  const unlocked = lanes.filter(l => l.unlocked === true);
  const allOpenTrades = (desk?.allTrades || monthView?.openTrades || [])
    .filter(t => !t._closed && String(t.status || '').toUpperCase() !== 'CLOSED' && Number(t.exit_price || 0) === 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <Panel
        title="Daily risk counters"
        subtitle={`${inr(accrualState.dailyPot)} per ${accrualState.basis === 'WEEKDAYS' ? 'trading day' : 'day'} since ${accrualState.startDate} · ${lanes[0]?.totalDays || 0} ${accrualState.basis === 'WEEKDAYS' ? 'trading days' : 'days'} in. A win keeps the counter; a loss resets it to zero.`}
        right={
          <div style={{ display: 'flex', gap: '7px', flexWrap: 'wrap', alignItems: 'center' }}>
            {accrualState.isWeekendToday && <Chip tone="warn">weekend — no accrual today</Chip>}
            <Chip tone="good">
              ✓ All {lanes.filter(l => !l.isReserve).length} segments unlocked ({unlocked.length} on target)
            </Chip>
          </div>
        }
      >
        <StatGrid min="150px">
          <Stat label="Accrued to date" value={inr(accrualState.totalAccrued)} />
          {accrualState.totalOpeningDeductions > 0 && (
            <Stat label="Opening deductions" value={inr(accrualState.totalOpeningDeductions)} color={C.violet} sub="committed before day 1" />
          )}
          <Stat label="Booked losses" value={inr(accrualState.totalBookedLosses)} color={accrualState.totalBookedLosses > 0 ? C.red : C.muted} />
          <Stat label="Total capital" value={inr(accrualState.totalCapital)} color={accrualState.totalCapital >= 0 ? C.green : C.red} />
          <Stat label="Daily drip" value={inr(accrualState.dailyPot)} sub={accrualState.basis === 'WEEKDAYS' ? 'weekdays only' : 'every day'} />
        </StatGrid>
      </Panel>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '16px' }}>
        {lanes.map(l => {
          const segView = monthView?.segments?.find(s => s.id === l.id);
          const noThreshold = l.threshold === null && !l.slPercent && !l.isReserve;
          const openTrades = allOpenTrades.filter(t => t.segment === l.id);

          const accent = l.isReserve
            ? 'rgba(167,139,250,0.35)'
            : l.unlocked
              ? 'rgba(16,185,129,0.45)'
              : noThreshold
                ? 'rgba(245,158,11,0.4)'
                : 'rgba(239,68,68,0.45)';

          return (
            <Panel key={l.id} accent={accent}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px', gap: '10px' }}>
                <div>
                  <div style={{ fontSize: '14px', fontWeight: 900, color: '#fff' }}>{l.icon} {l.label}</div>
                  <div style={{ fontSize: '10px', color: C.muted, marginTop: '3px' }}>
                    {inr(l.rate)}/{l.basis === 'WEEKDAYS' ? 'trading day' : 'day'}
                    {!l.booksLosses && <span style={{ color: C.violet, fontWeight: 800 }}> · assets hold</span>}
                    {l.investedAmount > 0 && <span style={{ color: C.accent, fontWeight: 800 }}> · Invested: {inr(l.investedAmount)}</span>}
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
                  {l.isReserve ? (
                    <Chip tone="violet">reserve</Chip>
                  ) : noThreshold ? (
                    <Chip tone="warn">⚠ NO SL SET</Chip>
                  ) : l.unlocked ? (
                    <Chip tone="good">✓ READY TO TRADE</Chip>
                  ) : (
                    <Chip tone="bad">⚠ SHORTFALL ({l.daysToUnlock}D)</Chip>
                  )}

                  {!l.isReserve && (
                    <Btn
                      tone={l.unlocked ? "good" : noThreshold ? "warn" : "bad"}
                      onClick={() => setTradingSegment({ segmentId: l.id, lane: l })}
                      style={{
                        padding: '4px 10px',
                        fontSize: '11px',
                        fontWeight: 900,
                        border: l.unlocked 
                          ? '1px solid #10b981' 
                          : noThreshold 
                            ? '1px solid #f59e0b' 
                            : '1px solid #ef4444'
                      }}
                    >
                      + Trade
                    </Btn>
                  )}
                </div>
              </div>

              {/* Unmistakable trading state - Unlocked with warning rather than locked */}
              {!l.isReserve && (
                <div style={{
                  background: noThreshold ? 'rgba(245,158,11,0.14)' : l.unlocked ? 'rgba(16,185,129,0.14)' : 'rgba(239,68,68,0.14)',
                  border: `1px solid ${noThreshold ? 'rgba(245,158,11,0.4)' : l.unlocked ? 'rgba(16,185,129,0.45)' : 'rgba(239,68,68,0.45)'}`,
                  borderRadius: '8px',
                  padding: '8px 11px',
                  marginBottom: '13px',
                  fontSize: '11px',
                  fontWeight: 900,
                  letterSpacing: '0.3px',
                  color: noThreshold ? C.amber : l.unlocked ? C.green : '#fca5a5',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                  <span>
                    {noThreshold
                      ? '⚠ UNLOCKED — NO STANDARD STOP-LOSS SET (DISCRETIONARY RISK)'
                      : l.unlocked
                        ? '✓ TRADING UNLOCKED — ON TARGET'
                        : `⚠ UNLOCKED (WARNING) — ${inr(l.shortfall)} SHORT (${l.daysToUnlock} TRADING DAY${l.daysToUnlock === 1 ? '' : 'S'} TO TARGET)`}
                  </span>
                  <span
                    onClick={() => setTradingSegment({ segmentId: l.id, lane: l })}
                    style={{
                      background: l.unlocked ? '#10b981' : noThreshold ? '#f59e0b' : '#ef4444',
                      color: '#090d16',
                      padding: '2px 8px',
                      borderRadius: '6px',
                      fontSize: '10px',
                      fontWeight: 900,
                      cursor: 'pointer',
                      whiteSpace: 'nowrap',
                      marginLeft: '8px'
                    }}
                  >
                    TRADE NOW →
                  </span>
                </div>
              )}

              {/* Counter progress toward the stop-loss */}
              {!l.isReserve && (
                <div style={{ marginBottom: '14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
                    <span style={{ fontSize: '21px', fontWeight: 900, color: l.unlocked ? C.green : '#fca5a5' }}>
                      {inr(l.counter)}
                    </span>
                    <span style={{ fontSize: '11px', color: C.muted, fontWeight: 700 }}>
                      {l.threshold !== null
                        ? `of ${inr(l.threshold)}${l.slPercent ? ` · ${l.slPercent}% stop` : ''}`
                        : l.slPercent ? `${l.slPercent}% stop` : 'no target'}
                    </span>
                  </div>
                  <Bar
                    used={l.counter}
                    total={l.threshold || (l.slPercent ? l.counter || 1 : 1)}
                    color={l.unlocked ? C.green : noThreshold ? C.amber : C.red}
                    height={9}
                  />
                  <div style={{ fontSize: '10px', color: C.dim, marginTop: '6px' }}>
                    {l.slPercent
                      ? (l.cappedRisk
                          ? `Risk capped at ${inr(l.cappedRisk)} per trade — supports a position up to ${inr(l.maxPositionValue)} at a ${l.slPercent}% stop${l.targetPercent ? `, target +${l.targetPercent}%` : ''}.`
                          : `Sized to the counter — supports a position up to ${inr(l.maxPositionValue)} at a ${l.slPercent}% stop${l.targetPercent ? `, target +${l.targetPercent}%` : ''}.`)
                      : noThreshold
                        ? 'No stop-loss set for this segment. Trading is fully unlocked with discretionary sizing.'
                        : l.unlocked
                          ? 'Ready to trade — an A/A+ setup and the daily rules still apply.'
                          : `Warning: counter is ${inr(l.shortfall)} short of standard threshold. Trading is unlocked with capital drawdown.`}
                  </div>
                </div>
              )}

              {l.isReserve && (
                <div style={{ marginBottom: '14px' }}>
                  <div style={{ fontSize: '21px', fontWeight: 900, color: C.violet }}>{inr(l.capital)}</div>
                  <div style={{ fontSize: '10px', color: C.dim, marginTop: '5px' }}>
                    Available to top up a short counter — A+ setups only, reason required.
                  </div>
                </div>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '11px', paddingTop: '12px', borderTop: `1px solid ${C.border}` }}>
                <Stat label="Accrued total" value={inr(l.totalAccrued)} size="14px" />
                <Stat
                  label={l.id === 'LONG_TERM' ? "Invested Capital" : "Capital"}
                  value={inr(l.capital)}
                  size="14px"
                  color={l.capital >= 0 ? C.green : C.red}
                  sub={l.id === 'LONG_TERM' && l.investedAmount > 0 ? "deployed in assets" : undefined}
                />
                <Stat
                  label={l.booksLosses ? 'Losses + Charges' : 'Losses (not booked)'}
                  value={inr(l.booksLosses ? l.lossTotal : l.unbookedLossTotal)}
                  size="14px"
                  color={l.booksLosses ? (l.lossTotal > 0 ? C.red : C.muted) : C.violet}
                  sub={l.booksLosses && l.lossTotal > 0 ? "deducted from capital" : undefined}
                />
                <Stat
                  label="Record"
                  value={`${l.winCount}W / ${l.lossCount}L`}
                  size="14px"
                  color={l.tradeCount ? '#fff' : C.muted}
                />
              </div>

              {/* ── ACTIVE OPEN POSITIONS IN THIS SEGMENT ── */}
              {openTrades.length > 0 && (
                <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: `1px dashed ${C.border}` }}>
                  <div style={{ fontSize: '11px', fontWeight: 800, color: C.accent, marginBottom: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span>⚡ OPEN POSITIONS ({openTrades.length})</span>
                    <span style={{ fontSize: '10px', color: C.muted }}>Live MTM</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {openTrades.map(t => {
                      const netMtm = t._pnl?.liveNet ?? 0;
                      return (
                        <div
                          key={t.id}
                          style={{
                            background: 'rgba(0, 0, 0, 0.4)',
                            border: '1px solid rgba(255, 255, 255, 0.08)',
                            borderRadius: '8px',
                            padding: '9px 11px',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            gap: '8px',
                            flexWrap: 'wrap'
                          }}
                        >
                          <div>
                            <div style={{ fontWeight: 900, color: '#fff', fontSize: '12px' }}>
                              {t.symbol}
                              <span style={{
                                fontSize: '10px',
                                color: t.direction === 'SHORT' ? C.red : C.green,
                                marginLeft: '6px',
                                fontWeight: 800,
                                padding: '1px 5px',
                                background: t.direction === 'SHORT' ? 'rgba(239,68,68,0.15)' : 'rgba(16,185,129,0.15)',
                                borderRadius: '4px'
                              }}>
                                {t.direction || 'LONG'}
                              </span>
                            </div>
                            <div style={{ fontSize: '10px', color: C.muted, marginTop: '2px' }}>
                              {t.quantity} qty @ {inr(t.entry_price)}
                              {t._pnl?.hasLivePrice && <span> · LTP: {inr(t._pnl.markPrice)}</span>}
                            </div>
                          </div>

                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <div style={{ textAlign: 'right' }}>
                              <div style={{ fontSize: '12px', fontWeight: 900, color: pnlColor(netMtm) }}>
                                {netMtm >= 0 ? '+' : ''}{inr(netMtm)}
                              </div>
                              <div style={{ fontSize: '9px', color: C.dim }}>Net MTM</div>
                            </div>
                            <Btn
                              tone="ghost"
                              onClick={() => setEditingOpenTrade(t)}
                              style={{ padding: '4px 8px', fontSize: '10px', fontWeight: 800 }}
                              title="Edit buy price, quantity, SL or target"
                            >
                              ✏️ Edit
                            </Btn>
                            <Btn
                              tone="danger"
                              onClick={() => setSquaringOffTrade({ trade: t, lane: l })}
                              style={{ padding: '4px 10px', fontSize: '10px', fontWeight: 900 }}
                            >
                              Square Off
                            </Btn>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {l.openingDeduction > 0 && (
                <div style={{ marginTop: '10px', fontSize: '10px', color: C.violet, fontWeight: 700 }}>
                  Less {inr(l.openingDeduction)} committed before the counter started
                </div>
              )}

              {l.booksLosses && l.lossTotal > 0 && (
                <div style={{ marginTop: '10px', fontSize: '10px', color: C.red, fontWeight: 700 }}>
                  Outflows deducted: {inr(l.lossTotal)} (losses + charges)
                </div>
              )}

              {segView && segView.netPnl !== 0 && (
                <div style={{ marginTop: '9px', fontSize: '11px', color: pnlColor(segView.netPnl), fontWeight: 800 }}>
                  Net P&L this month: {inr(segView.netPnl)}
                </div>
              )}
            </Panel>
          );
        })}
      </div>

      {/* ── In-Window Trade Execution Modal ── */}
      {tradingSegment && (
        <InWindowTradeModal
          segmentId={tradingSegment.segmentId}
          lane={tradingSegment.lane}
          desk={desk}
          onClose={() => setTradingSegment(null)}
        />
      )}

      {/* ── In-Window Square-Off Modal ── */}
      {squaringOffTrade && (
        <SquareOffModal
          trade={squaringOffTrade.trade}
          lane={squaringOffTrade.lane}
          desk={desk}
          onClose={() => setSquaringOffTrade(null)}
        />
      )}

      {/* ── Edit Open Position Modal ── */}
      {editingOpenTrade && (
        <EditOpenTradeModal
          trade={editingOpenTrade}
          onClose={() => setEditingOpenTrade(null)}
          onSubmit={(updates) => {
            desk?.actions?.updateTrade(editingOpenTrade.id, updates);
            setEditingOpenTrade(null);
          }}
          onDelete={(id) => {
            desk?.actions?.deleteTrade(id);
            setEditingOpenTrade(null);
          }}
        />
      )}
    </div>
  );
}
