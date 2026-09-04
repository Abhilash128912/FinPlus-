import React, { useState } from 'react';
import { C, inr, pnlColor, Panel, Stat, StatGrid, Bar, Chip, Btn, Field, Input, Select, TextArea, Modal, Empty, Verdict } from './ui.jsx';
import { monthLabel } from './risk_model.js';
import { sumChargeBreakdown } from './broker_profiles.js';
import Counters from './Counters.jsx';

/** Dashboard: decision banner, risk counters, cash, performance and open-position live P&L. */
export default function RiskDashboard({ desk, onOpenDaily }) {
  const { monthView, dailySnapshot, accountView, months, monthKey, setMonthKey, ltpUpdatedAt, trackedSymbols, syncState, actions, dayDecision, accrualState } = desk;
  const [closing, setClosing] = useState(null);
  const [charging, setCharging] = useState(null);

  if (!monthView) return <Empty>No month record found.</Empty>;

  const s = monthView.stats;
  const budgetUsedPct = monthView.monthlyRiskBudget > 0
    ? (monthView.committedRisk / monthView.monthlyRiskBudget) * 100
    : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {/* ── Header: month picker + sync + live status ── */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          <Select value={monthKey} onChange={e => setMonthKey(e.target.value)} style={{ width: 'auto', minWidth: '190px' }}>
            {months.map(m => (
              <option key={m.month_key} value={m.month_key}>
                {monthLabel(m.month_key)}
              </option>
            ))}
          </Select>
          <Chip tone="info">REPORTING MONTH</Chip>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <Chip tone={trackedSymbols.length ? 'good' : 'muted'}>
            {trackedSymbols.length ? `🟢 Live P&L: ${trackedSymbols.length} symbol${trackedSymbols.length > 1 ? 's' : ''}${ltpUpdatedAt ? ` · ${ltpUpdatedAt}` : ''}` : 'No open positions to track'}
          </Chip>
          <Chip tone={syncState.status === 'synced' ? 'good' : syncState.status === 'offline' ? 'warn' : 'muted'}>
            {syncState.status === 'synced' ? '☁ Synced' : syncState.status === 'offline' ? '⚠ Local only' : '… Syncing'}
          </Chip>
        </div>
      </div>

      {/* ── Recommendation / NO TRADE ── */}
      <Panel
        accent={dayDecision.noTrade ? 'rgba(148,163,184,0.25)' : 'rgba(16,185,129,0.45)'}
        style={{ background: dayDecision.noTrade ? 'rgba(148,163,184,0.05)' : 'rgba(16,185,129,0.07)' }}
      >
        {dayDecision.noTrade ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontSize: '19px', fontWeight: 900, color: C.muted, letterSpacing: '0.5px' }}>NO TRADE</div>
              <div style={{ fontSize: '12px', color: C.dim, marginTop: '5px' }}>
                No A/A+ opportunity meets all risk rules.
                {desk.todaySetups.length === 0 && ' No setups reviewed today yet.'}
              </div>
            </div>
            <Btn tone="ghost" onClick={onOpenDaily}>Review today's segments →</Btn>
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontSize: '10px', color: C.green, fontWeight: 800, letterSpacing: '0.5px' }}>RECOMMENDED TRADE</div>
              <div style={{ fontSize: '19px', fontWeight: 900, color: '#fff', marginTop: '4px' }}>
                {dayDecision.recommendation.symbol}{' '}
                <span style={{ fontSize: '12px', color: C.muted, fontWeight: 700 }}>· {dayDecision.recommendation.segmentLabel}</span>
              </div>
              <div style={{ display: 'flex', gap: '7px', marginTop: '8px', flexWrap: 'wrap' }}>
                <Chip tone="good">{dayDecision.recommendation.score.gradeLabel} · {dayDecision.recommendation.score.total}/100</Chip>
                {dayDecision.recommendation.riskReward && <Chip tone="info">R:R {dayDecision.recommendation.riskReward}</Chip>}
                <Chip tone="muted">Risk {inr(dayDecision.recommendation.planned.totalRisk)}</Chip>
              </div>
            </div>
            <Btn onClick={onOpenDaily}>Open daily review →</Btn>
          </div>
        )}
      </Panel>

      {/* ── Today's limits (the monthly bucket panel is gone; counters rule now) ── */}
      <Panel
        title="Today"
        subtitle="Position and daily-risk limits still apply on top of the counters."
      >
        <StatGrid min="170px">
          <Stat
            label="Today's positions"
            value={`${dailySnapshot.positionCount} / ${dailySnapshot.maxPositions}`}
            sub={dailySnapshot.positionCount >= dailySnapshot.maxPositions ? `Exceptional cap ${dailySnapshot.maxPositionsExceptional}` : 'Default limit'}
            color={dailySnapshot.positionCount >= dailySnapshot.maxPositionsExceptional ? C.red : '#fff'}
          />
          <Stat
            label="Today's planned risk"
            value={inr(dailySnapshot.plannedRisk)}
            sub={`Limit ${inr(dailySnapshot.dailyRiskLimit)} · ${inr(dailySnapshot.remaining)} left`}
            color={dailySnapshot.remaining < 0 ? C.red : '#fff'}
          />
          <Stat
            label="Opportunity Reserve"
            value={inr(accrualState?.byId?.OPPORTUNITY_RESERVE?.capital ?? 0)}
            sub="A+ top-ups only"
            color={C.violet}
          />
          <Stat
            label="Segments unlocked"
            value={`${accrualState?.unlockedLanes?.length ?? 0}`}
            sub="counter has reached the stop-loss"
            color={(accrualState?.unlockedLanes?.length ?? 0) > 0 ? C.green : C.muted}
          />
        </StatGrid>
      </Panel>

      {/* ── Daily risk counters (replaces monthly buckets) ── */}
      <Counters accrualState={accrualState} monthView={monthView} />

      {/* ── Cash & performance ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
        <Panel title="Cash position" subtitle="Actual money. Risk buckets never appear here.">
          <StatGrid min="130px">
            <Stat label="Broker cash" value={inr(accountView.brokerCash)} color={C.accent} />
            <Stat label="Withdrawable" value={inr(accountView.withdrawableCash)} color={C.green} />
            <Stat label="Growth Reserve" value={inr(accountView.growthReserve)} color={C.violet} sub="Does not raise risk limits" />
            <Stat label="Deposits" value={inr(accountView.deposits)} size="16px" />
            <Stat label="Withdrawals" value={inr(accountView.withdrawals)} size="16px" />
          </StatGrid>
        </Panel>

        <Panel title="Performance" subtitle={`${s.closedCount} closed · ${s.openCount} open this month`}>
          <StatGrid min="130px">
            <Stat label="Gross P&L" value={inr(s.grossPnl)} color={pnlColor(s.grossPnl)} />
            <Stat label="Charges" value={inr(s.actualCharges)} color={C.amber} />
            <Stat label="Net P&L" value={inr(s.netPnl)} color={pnlColor(s.netPnl)} />
            <Stat label="Win rate" value={`${s.winRate}%`} size="16px" />
            <Stat label="Avg cost / trade" value={inr(s.avgCostPerTrade)} size="16px" />
            <Stat label="Month drawdown" value={inr(s.drawdown.maxDrawdown)} size="16px" color={s.drawdown.maxDrawdown > 0 ? C.red : C.muted} />
          </StatGrid>
          {s.openCount > 0 && (
            <div style={{ marginTop: '14px', paddingTop: '14px', borderTop: `1px solid ${C.border}` }}>
              <StatGrid min="130px">
                <Stat label="Live gross (open)" value={inr(s.liveGrossPnl)} color={pnlColor(s.liveGrossPnl)} size="17px" />
                <Stat label="Live net (open)" value={inr(s.liveNetPnl)} color={pnlColor(s.liveNetPnl)} size="17px"
                  sub={s.liveTrackedCount < s.openCount ? `${s.openCount - s.liveTrackedCount} without a price` : 'All positions priced'} />
              </StatGrid>
            </div>
          )}
          {s.chargeVarianceCount > 0 && (
            <div style={{ marginTop: '12px', fontSize: '11px', color: s.chargeVariance > 0 ? C.amber : C.green, fontWeight: 700 }}>
              Estimate vs actual variance: {inr(s.chargeVariance)} across {s.chargeVarianceCount} reconciled trade{s.chargeVarianceCount > 1 ? 's' : ''}
            </div>
          )}
        </Panel>
      </div>

      {/* ── Open positions with live P&L ── */}
      <Panel
        title="Open positions — live P&L"
        subtitle="Live prices come from the existing price feed; options contracts accept a manual mark."
      >
        {monthView.openTrades.length === 0 ? (
          <Empty>No open positions. Nothing to mark.</Empty>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', minWidth: '820px' }}>
              <thead>
                <tr style={{ color: C.muted, textAlign: 'left', fontSize: '10px', textTransform: 'uppercase' }}>
                  <th style={{ padding: '9px 10px' }}>Symbol</th>
                  <th style={{ padding: '9px 10px' }}>Segment</th>
                  <th style={{ padding: '9px 10px' }}>Entry / SL</th>
                  <th style={{ padding: '9px 10px' }}>Qty</th>
                  <th style={{ padding: '9px 10px' }}>Mark</th>
                  <th style={{ padding: '9px 10px' }}>Live gross</th>
                  <th style={{ padding: '9px 10px' }}>Live net</th>
                  <th style={{ padding: '9px 10px' }}>Planned risk</th>
                  <th style={{ padding: '9px 10px' }} />
                </tr>
              </thead>
              <tbody>
                {monthView.openTrades.map(t => (
                  <tr key={t.id} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: '10px', fontWeight: 900, color: '#fff' }}>
                      {t.symbol}
                      <div style={{ fontSize: '10px', color: C.dim, fontWeight: 600 }}>{t.direction || 'LONG'}</div>
                    </td>
                    <td style={{ padding: '10px', color: C.muted }}>{t.segment}</td>
                    <td style={{ padding: '10px', color: C.muted }}>{inr(t.entry_price)} / {inr(t.stop_loss_price)}</td>
                    <td style={{ padding: '10px', color: C.muted }}>{t.quantity}{t.lot_size > 1 ? ` × ${t.lot_size}` : ''}</td>
                    <td style={{ padding: '10px' }}>
                      {t._pnl.hasLivePrice ? (
                        <span style={{ color: C.accent, fontWeight: 800 }}>{inr(t._pnl.markPrice)}</span>
                      ) : (
                        <Input
                          type="number"
                          placeholder="Mark"
                          defaultValue={t.manual_ltp || ''}
                          onBlur={e => e.target.value && actions.setManualLtp(t.id, e.target.value)}
                          style={{ width: '92px', padding: '5px 7px', fontSize: '11px' }}
                        />
                      )}
                    </td>
                    <td style={{ padding: '10px', fontWeight: 800, color: pnlColor(t._pnl.gross) }}>
                      {t._pnl.hasLivePrice ? inr(t._pnl.gross) : '—'}
                    </td>
                    <td style={{ padding: '10px', fontWeight: 900, color: pnlColor(t._pnl.net) }}>
                      {t._pnl.hasLivePrice ? inr(t._pnl.net) : '—'}
                    </td>
                    <td style={{ padding: '10px', color: C.amber, fontWeight: 700 }}>{inr(t.planned_total_risk)}</td>
                    <td style={{ padding: '10px' }}>
                      <Btn tone="ghost" onClick={() => setClosing(t)} style={{ padding: '6px 11px' }}>Close</Btn>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {/* ── Reserve audit trail ── */}
      {monthView.reserve.transfers.length > 0 && (
        <Panel title="Opportunity Reserve audit trail" subtitle="Reserve → Segment → Trade. Every release is recorded.">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '9px' }}>
            {monthView.reserve.transfers.map(x => (
              <div key={x.id} style={{ background: 'rgba(167,139,250,0.07)', border: '1px solid rgba(167,139,250,0.22)', borderRadius: '9px', padding: '11px 13px' }}>
                <div style={{ fontSize: '12px', fontWeight: 800, color: '#fff' }}>
                  💠 Reserve → {x.to_segment} → {x.trade_id} · {inr(x.amount)}
                </div>
                <div style={{ fontSize: '11px', color: C.muted, marginTop: '4px' }}>{x.reason || 'No reason recorded'}</div>
                <div style={{ fontSize: '10px', color: C.dim, marginTop: '3px' }}>{new Date(x.at).toLocaleString('en-IN')}</div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {/* ── Closed trades ── */}
      <Panel title="Closed trades this month" subtitle="Net P&L uses actual contract-note charges when entered, otherwise the estimate.">
        {monthView.closedTrades.length === 0 ? (
          <Empty>No closed trades yet this month.</Empty>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', minWidth: '780px' }}>
              <thead>
                <tr style={{ color: C.muted, textAlign: 'left', fontSize: '10px', textTransform: 'uppercase' }}>
                  <th style={{ padding: '9px 10px' }}>Symbol</th>
                  <th style={{ padding: '9px 10px' }}>Segment</th>
                  <th style={{ padding: '9px 10px' }}>Entry → Exit</th>
                  <th style={{ padding: '9px 10px' }}>Gross</th>
                  <th style={{ padding: '9px 10px' }}>Charges</th>
                  <th style={{ padding: '9px 10px' }}>Net</th>
                  <th style={{ padding: '9px 10px' }}>Exit reason</th>
                  <th style={{ padding: '9px 10px' }} />
                </tr>
              </thead>
              <tbody>
                {monthView.closedTrades.map(t => (
                  <tr key={t.id} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: '10px', fontWeight: 900, color: '#fff' }}>{t.symbol}</td>
                    <td style={{ padding: '10px', color: C.muted }}>{t.segment}</td>
                    <td style={{ padding: '10px', color: C.muted }}>{inr(t.entry_price)} → {inr(t.exit_price)}</td>
                    <td style={{ padding: '10px', fontWeight: 800, color: pnlColor(t._pnl.gross) }}>{inr(t._pnl.gross)}</td>
                    <td style={{ padding: '10px', color: C.amber }}>
                      {inr(t._pnl.actualCharges)}
                      <div style={{ fontSize: '9px', color: t._pnl.usingActual ? C.green : C.dim }}>
                        {t._pnl.usingActual ? 'actual' : 'estimated'}
                      </div>
                    </td>
                    <td style={{ padding: '10px', fontWeight: 900, color: pnlColor(t._pnl.net) }}>{inr(t._pnl.net)}</td>
                    <td style={{ padding: '10px', color: C.muted, fontSize: '11px' }}>{t.exit_reason || '—'}</td>
                    <td style={{ padding: '10px' }}>
                      <Btn tone="ghost" onClick={() => setCharging(t)} style={{ padding: '6px 10px' }}>
                        {t._pnl.usingActual ? 'Edit charges' : 'Add actual'}
                      </Btn>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {closing && <CloseTradeModal trade={closing} onClose={() => setClosing(null)} onSubmit={(payload) => { actions.closeTrade(closing.id, payload); setClosing(null); }} />}
      {charging && <ActualChargesModal trade={charging} onClose={() => setCharging(null)} onSubmit={(b, ref) => { actions.setActualCharges(charging.id, b, ref); setCharging(null); }} />}
    </div>
  );
}

function CloseTradeModal({ trade, onClose, onSubmit }) {
  const [exitPrice, setExitPrice] = useState(trade._pnl?.hasLivePrice ? String(trade._pnl.markPrice) : '');
  const [exitReason, setExitReason] = useState('');
  const [exitDate, setExitDate] = useState(new Date().toISOString().slice(0, 16));

  return (
    <Modal title={`Close ${trade.symbol}`} subtitle={`${trade.segment} · entry ${inr(trade.entry_price)} · SL ${inr(trade.stop_loss_price)}`} onClose={onClose} width="520px">
      <div style={{ display: 'grid', gap: '14px' }}>
        <Field label="Exit price" required>
          <Input type="number" step="0.01" value={exitPrice} onChange={e => setExitPrice(e.target.value)} />
        </Field>
        <Field label="Exit date/time">
          <Input type="datetime-local" value={exitDate} onChange={e => setExitDate(e.target.value)} />
        </Field>
        <Field label="Exit reason" required hint="Target hit, stop hit, time stop, thesis invalidated…">
          <Input value={exitReason} onChange={e => setExitReason(e.target.value)} placeholder="Why you came out" />
        </Field>
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <Btn tone="ghost" onClick={onClose}>Cancel</Btn>
          <Btn
            disabled={!Number(exitPrice) || !exitReason.trim()}
            onClick={() => onSubmit({ exit_price: exitPrice, exit_date: new Date(exitDate).toISOString(), exit_reason: exitReason })}
          >
            Close trade
          </Btn>
        </div>
      </div>
    </Modal>
  );
}

const CHARGE_FIELDS = [
  ['brokerage', 'Brokerage'],
  ['stt', 'STT / CTT'],
  ['exchange_txn', 'Exchange txn'],
  ['sebi', 'SEBI / regulatory'],
  ['stamp_duty', 'Stamp duty'],
  ['gst', 'GST'],
  ['dp_charges', 'DP / clearing'],
  ['other', 'Other']
];

function ActualChargesModal({ trade, onClose, onSubmit }) {
  const [vals, setVals] = useState(() => {
    const base = trade.actual_charges || trade._pnl?.estimatedBreakdown || {};
    return CHARGE_FIELDS.reduce((a, [k]) => ({ ...a, [k]: String(base[k] ?? '') }), {});
  });
  const [ref, setRef] = useState(trade.contract_note_ref || '');

  const breakdown = CHARGE_FIELDS.reduce((a, [k]) => ({ ...a, [k]: Number(vals[k]) || 0 }), {});
  const total = sumChargeBreakdown(breakdown);
  const estimated = trade._pnl?.estimatedCharges || 0;
  const variance = total - estimated;

  return (
    <Modal
      title={`Actual charges — ${trade.symbol}`}
      subtitle="Enter the contract-note figures. Net P&L switches from estimate to actual."
      onClose={onClose}
      width="620px"
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '13px' }}>
        {CHARGE_FIELDS.map(([k, label]) => (
          <Field key={k} label={label}>
            <Input type="number" step="0.01" value={vals[k]} onChange={e => setVals(v => ({ ...v, [k]: e.target.value }))} />
          </Field>
        ))}
      </div>
      <div style={{ marginTop: '14px' }}>
        <Field label="Contract note reference" hint="Optional">
          <Input value={ref} onChange={e => setRef(e.target.value)} placeholder="e.g. CN-2026-09-04-001" />
        </Field>
      </div>
      <div style={{ marginTop: '16px', padding: '13px', background: 'rgba(0,0,0,0.3)', borderRadius: '10px', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
        <Stat label="Estimated" value={inr(estimated)} size="15px" />
        <Stat label="Actual" value={inr(total)} size="15px" color={C.accent} />
        <Stat label="Variance" value={inr(variance)} size="15px" color={variance > 0 ? C.red : C.green}
          sub={estimated > 0 ? `${((variance / estimated) * 100).toFixed(1)}%` : ''} />
      </div>
      {estimated > 0 && Math.abs(variance) / estimated > 0.2 && (
        <div style={{ marginTop: '12px' }}>
          <Verdict warnings={[{ message: `Actual charges differ from the estimate by ${((variance / estimated) * 100).toFixed(1)}%. Check the charge profile rates.` }]} compact />
        </div>
      )}
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '16px' }}>
        <Btn tone="ghost" onClick={onClose}>Cancel</Btn>
        <Btn onClick={() => onSubmit(breakdown, ref)}>Save actual charges</Btn>
      </div>
    </Modal>
  );
}
