import React from 'react';
import { C, inr, pnlColor, Panel, Stat, StatGrid, Bar, Chip, Empty } from './ui.jsx';

/**
 * Daily risk counters — the core of the accrual model.
 *
 * Each lane drips its allocation daily. Reaching the segment stop-loss unlocks
 * trading. A win leaves the counter alone; a booked loss resets it to zero and
 * takes the actual net loss out of that segment's capital.
 */
export default function Counters({ accrualState, monthView }) {
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <Panel
        title="Daily risk counters"
        subtitle={`${inr(accrualState.dailyPot)} per ${accrualState.basis === 'WEEKDAYS' ? 'trading day' : 'day'} since ${accrualState.startDate} · ${lanes[0]?.totalDays || 0} ${accrualState.basis === 'WEEKDAYS' ? 'trading days' : 'days'} in. A win keeps the counter; a loss resets it to zero.`}
        right={
          <div style={{ display: 'flex', gap: '7px', flexWrap: 'wrap' }}>
            {accrualState.isWeekendToday && <Chip tone="warn">weekend — no accrual today</Chip>}
            <Chip tone={unlocked.length ? 'good' : 'muted'}>
              {unlocked.length ? `${unlocked.length} unlocked` : 'none unlocked'}
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

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px' }}>
        {lanes.map(l => {
          const segView = monthView?.segments?.find(s => s.id === l.id);
          const locked = l.unlocked === false;
          const noThreshold = l.threshold === null && !l.slPercent && !l.isReserve;

          const accent = l.isReserve
            ? 'rgba(167,139,250,0.35)'
            : l.unlocked
              ? 'rgba(16,185,129,0.4)'
              : noThreshold
                ? 'rgba(245,158,11,0.35)'
                : C.border;

          return (
            <Panel key={l.id} accent={accent}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px', gap: '10px' }}>
                <div>
                  <div style={{ fontSize: '14px', fontWeight: 900, color: '#fff' }}>{l.icon} {l.label}</div>
                  <div style={{ fontSize: '10px', color: C.muted, marginTop: '3px' }}>
                    {inr(l.rate)}/{l.basis === 'WEEKDAYS' ? 'trading day' : 'day'}
                    {!l.booksLosses && <span style={{ color: C.violet, fontWeight: 800 }}> · losses not booked</span>}
                  </div>
                </div>
                {l.isReserve ? (
                  <Chip tone="violet">reserve</Chip>
                ) : l.slPercent && l.threshold === null ? (
                  <Chip tone={l.unlocked ? 'good' : 'muted'}>{l.slPercent}% SL{l.unlocked ? ' · ready' : ''}</Chip>
                ) : noThreshold ? (
                  <Chip tone="warn">no SL set</Chip>
                ) : l.unlocked ? (
                  <Chip tone="good">✓ UNLOCKED</Chip>
                ) : (
                  <Chip tone="muted">{l.daysToUnlock} trading day{l.daysToUnlock === 1 ? '' : 's'}</Chip>
                )}
              </div>

              {/* Counter progress toward the stop-loss */}
              {!l.isReserve && (
                <div style={{ marginBottom: '14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
                    <span style={{ fontSize: '21px', fontWeight: 900, color: l.unlocked ? C.green : '#fff' }}>
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
                    color={l.unlocked ? C.green : C.accent}
                    height={9}
                  />
                  <div style={{ fontSize: '10px', color: C.dim, marginTop: '6px' }}>
                    {l.slPercent
                      ? (l.cappedRisk
                          ? `Risk capped at ${inr(l.cappedRisk)} per trade — supports a position up to ${inr(l.maxPositionValue)} at a ${l.slPercent}% stop${l.targetPercent ? `, target +${l.targetPercent}%` : ''}.`
                          : `Sized to the counter — supports a position up to ${inr(l.maxPositionValue)} at a ${l.slPercent}% stop${l.targetPercent ? `, target +${l.targetPercent}%` : ''}.`)
                      : noThreshold
                        ? 'Set a stop-loss for this segment to enable the unlock.'
                        : l.unlocked
                          ? 'Ready to trade — an A/A+ setup and the daily rules still apply.'
                          : `${inr(l.shortfall)} short · unlocks ${l.unlockDate || 'soon'}`}
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
                <Stat label="Capital" value={inr(l.capital)} size="14px" color={l.capital >= 0 ? C.green : C.red} />
                <Stat
                  label={l.booksLosses ? 'Booked losses' : 'Losses (not booked)'}
                  value={inr(l.booksLosses ? l.lossTotal : l.unbookedLossTotal)}
                  size="14px"
                  color={l.booksLosses ? (l.lossTotal > 0 ? C.red : C.muted) : C.violet}
                />
                <Stat
                  label="Record"
                  value={`${l.winCount}W / ${l.lossCount}L`}
                  size="14px"
                  color={l.tradeCount ? '#fff' : C.muted}
                />
              </div>

              {l.openingDeduction > 0 && (
                <div style={{ marginTop: '10px', fontSize: '10px', color: C.violet, fontWeight: 700 }}>
                  Less {inr(l.openingDeduction)} committed before the counter started
                </div>
              )}

              {l.lastLossDate && (
                <div style={{ marginTop: '10px', fontSize: '10px', color: C.red, fontWeight: 700 }}>
                  Counter last reset {l.lastLossDate}
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
    </div>
  );
}
