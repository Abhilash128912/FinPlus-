import React, { useState, useEffect } from 'react';
import { C, inr, Panel, Stat, StatGrid, Chip, Btn, Field, Input, Select, Empty, Verdict } from './ui.jsx';
import { SEGMENTS, BRIEF_DEFAULTS, allocationBalance, monthLabel } from './risk_model.js';
import { dailyRateFor, ACCRUAL_LANES } from './accrual_engine.js';
import { BROKERS } from './broker_profiles.js';

/**
 * Setup — every rupee figure in the Risk Desk is entered here.
 * Nothing is pre-filled; "Apply brief values" fills the spec's numbers on request.
 */
export default function RiskSetup({ desk, onReset }) {
  const { config, actions, store } = desk;
  const [f, setF] = useState(config);
  const [saved, setSaved] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => { setF(config); }, [config]);

  const set = (k, v) => { setF(p => ({ ...p, [k]: v })); setSaved(false); };
  const setAlloc = (id, v) => { setF(p => ({ ...p, allocations: { ...p.allocations, [id]: v } })); setSaved(false); };
  const setSL = (id, v) => { setF(p => ({ ...p, segmentSL: { ...p.segmentSL, [id]: v } })); setSaved(false); };
  const setSLPct = (id, v) => { setF(p => ({ ...p, segmentSLPercent: { ...(p.segmentSLPercent || {}), [id]: v } })); setSaved(false); };
  const setTgtPct = (id, v) => { setF(p => ({ ...p, segmentTargetPercent: { ...(p.segmentTargetPercent || {}), [id]: v } })); setSaved(false); };
  const setBroker = (id, v) => { setF(p => ({ ...p, segmentBroker: { ...p.segmentBroker, [id]: v || null } })); setSaved(false); };
  const setOpening = (id, v) => { setF(p => ({ ...p, openingDeductions: { ...(p.openingDeductions || {}), [id]: v } })); setSaved(false); };

  const numeric = obj => Object.fromEntries(Object.entries(obj || {}).map(([k, v]) => [k, v === '' || v === null ? null : Number(v)]));

  const normalized = {
    ...f,
    monthlyRiskBudget: Number(f.monthlyRiskBudget) || 0,
    reserveAllocation: Number(f.reserveAllocation) || 0,
    dailyRiskLimit: Number(f.dailyRiskLimit) || 0,
    maxPositionsPerDay: Number(f.maxPositionsPerDay) || 1,
    maxPositionsExceptional: Number(f.maxPositionsExceptional) || 2,
    allocations: Object.fromEntries(SEGMENTS.map(s => [s.id, Number(f.allocations?.[s.id]) || 0])),
    segmentSL: numeric(f.segmentSL),
    segmentSLPercent: numeric(f.segmentSLPercent),
    segmentTargetPercent: numeric(f.segmentTargetPercent),
    openingDeductions: Object.fromEntries(SEGMENTS.map(s => [s.id, Number(f.openingDeductions?.[s.id]) || 0])),
    accrualStartDate: f.accrualStartDate || null,
    accrualDivisor: Number(f.accrualDivisor) > 0 ? Number(f.accrualDivisor) : 22,
    accrualBasis: f.accrualBasis === 'CALENDAR' ? 'CALENDAR' : 'WEEKDAYS',
    booksLosses: { ...(f.booksLosses || {}) }
  };

  const balance = allocationBalance(normalized);
  const openingTotal = SEGMENTS.reduce((s, x) => s + (Number(normalized.openingDeductions?.[x.id]) || 0), 0);

  const problems = [];
  if (!(normalized.monthlyRiskBudget > 0)) problems.push({ message: 'Monthly risk budget must be greater than zero.' });
  if (!balance.balanced && normalized.monthlyRiskBudget > 0) {
    problems.push({ message: `Segment allocations plus reserve total ${inr(balance.sum)} — ${inr(Math.abs(balance.difference))} ${balance.difference > 0 ? 'more' : 'less'} than the ${inr(balance.budget)} budget. Use "Auto-split budget" to divide it up, or "Apply brief values" for the full recommended setup.` });
  }
  if (!(normalized.dailyRiskLimit > 0)) problems.push({ message: 'Daily risk limit must be greater than zero.' });

  if (!normalized.accrualStartDate) problems.push({ message: 'Pick a counter start date — nothing accrues until you do.' });

  const warnings = [];
  const noSL = SEGMENTS.filter(x => !(Number(normalized.segmentSL?.[x.id]) > 0) && !(Number(normalized.segmentSLPercent?.[x.id]) > 0));
  if (noSL.length) {
    warnings.push({ message: `${noSL.map(x => x.label).join(', ')} ${noSL.length === 1 ? 'has' : 'have'} no stop-loss, so ${noSL.length === 1 ? 'it' : 'they'} can never unlock.` });
  }
  if (!normalized.segmentBroker?.LONG_TERM) warnings.push({ message: 'Long Term has no default broker. You will be asked to pick one on each Long Term trade.' });

  const save = () => {
    actions.updateConfig({ ...normalized, configured: true });
    setSaved(true);
  };

  const applyBrief = () => {
    setF(p => ({
      ...p,
      ...BRIEF_DEFAULTS,
      allocations: { ...BRIEF_DEFAULTS.allocations },
      segmentSL: { ...BRIEF_DEFAULTS.segmentSL },
      segmentBroker: { ...BRIEF_DEFAULTS.segmentBroker },
      openingDeductions: { ...BRIEF_DEFAULTS.openingDeductions }
    }));
    setSaved(false);
  };

  /**
   * Spread whatever monthly budget is typed across the lanes, keeping the
   * brief's proportions. Rounded to whole rupees with the remainder pushed into
   * the Opportunity Reserve so the split always sums exactly to the budget.
   */
  const autoSplit = () => {
    const budget = Number(f.monthlyRiskBudget) || 0;
    if (budget <= 0) return;
    const weights = { ...BRIEF_DEFAULTS.allocations, OPPORTUNITY_RESERVE: BRIEF_DEFAULTS.reserveAllocation };
    const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0);
    const alloc = {};
    let used = 0;
    for (const seg of SEGMENTS) {
      const v = Math.round((budget * (weights[seg.id] || 0)) / totalWeight);
      alloc[seg.id] = v;
      used += v;
    }
    setF(p => ({ ...p, allocations: alloc, reserveAllocation: Math.round((budget - used) * 100) / 100 }));
    setSaved(false);
  };

  const clearAll = () => {
    setF(p => ({
      ...p,
      monthlyRiskBudget: 0,
      reserveAllocation: 0,
      dailyRiskLimit: 0,
      allocations: Object.fromEntries(SEGMENTS.map(s => [s.id, 0])),
      segmentSL: Object.fromEntries(SEGMENTS.map(s => [s.id, null])),
      segmentBroker: Object.fromEntries(SEGMENTS.map(s => [s.id, null])),
      openingDeductions: Object.fromEntries(SEGMENTS.map(s => [s.id, 0]))
    }));
    setSaved(false);
  };

  const dataCounts = {
    trades: store.trades?.length || 0,
    setups: store.trade_setups?.length || 0,
    cash: store.broker_cash_ledger?.length || 0,
    growth: store.growth_reserve_ledger?.length || 0,
    reserve: store.opportunity_reserve_transfers?.length || 0,
    audit: store.audit_log?.length || 0
  };
  const hasData = Object.values(dataCounts).some(n => n > 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

      {!config.configured && (
        <Panel accent="rgba(245,158,11,0.4)" style={{ background: 'rgba(245,158,11,0.07)' }}>
          <div style={{ fontSize: '14px', fontWeight: 900, color: C.amber }}>Setup not complete</div>
          <div style={{ fontSize: '12px', color: C.text, marginTop: '6px' }}>
            Every figure starts at zero. Enter your budget and allocations below — trade entry stays blocked until you do.
          </div>
        </Panel>
      )}

      <Panel
        title="Monthly risk budget"
        subtitle="A maximum planned loss per month. Not a spending target, and it never grows from unused allocation or profit."
        right={
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            <Btn onClick={applyBrief}>Apply brief values</Btn>
            <Btn tone="ghost" onClick={autoSplit} disabled={!(Number(f.monthlyRiskBudget) > 0)}>Auto-split budget</Btn>
            <Btn tone="ghost" onClick={clearAll}>Clear to zero</Btn>
          </div>
        }
      >
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '14px' }}>
          <Field label="Monthly risk budget (₹)" required>
            <Input type="number" step="0.01" value={f.monthlyRiskBudget ?? ''} onChange={e => set('monthlyRiskBudget', e.target.value)} placeholder="0" />
          </Field>
          <Field label="Opportunity Reserve (₹)" hint="Flexible risk for exceptional A+ trades">
            <Input type="number" step="0.01" value={f.reserveAllocation ?? ''} onChange={e => set('reserveAllocation', e.target.value)} placeholder="0" />
          </Field>
          <Field label="Daily risk limit (₹)" required hint="Planned risk per day, before charges">
            <Input type="number" step="0.01" value={f.dailyRiskLimit ?? ''} onChange={e => set('dailyRiskLimit', e.target.value)} placeholder="0" />
          </Field>
          <Field label="Max positions / day">
            <Input type="number" value={f.maxPositionsPerDay ?? 1} onChange={e => set('maxPositionsPerDay', e.target.value)} />
          </Field>
          <Field label="Exceptional max / day" hint="Second trade requires independence + rationale">
            <Input type="number" value={f.maxPositionsExceptional ?? 2} onChange={e => set('maxPositionsExceptional', e.target.value)} />
          </Field>
        </div>

        <div style={{ marginTop: '16px', padding: '13px', background: 'rgba(0,0,0,0.3)', borderRadius: '10px' }}>
          <StatGrid min="140px">
            <Stat label="Allocations + reserve" value={inr(balance.sum)} size="16px" color={balance.balanced ? C.green : C.amber} />
            <Stat label="Monthly budget" value={inr(balance.budget)} size="16px" />
            <Stat label="Difference" value={inr(balance.difference)} size="16px" color={balance.balanced ? C.green : C.red} />
          </StatGrid>
        </div>
      </Panel>

      <Panel title="Segments" subtitle="Allocation, planned stop-loss and broker for each of the seven active segments. A segment can use a rupee stop OR a percentage stop, not both.">
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '620px' }}>
            <thead>
              <tr style={{ color: C.muted, textAlign: 'left', fontSize: '10px', textTransform: 'uppercase' }}>
                <th style={{ padding: '8px 10px' }}>Segment</th>
                <th style={{ padding: '8px 10px', width: '160px' }}>Monthly allocation (₹)</th>
                <th style={{ padding: '8px 10px', width: '150px' }}>Planned SL per trade (₹)</th>
                <th style={{ padding: '8px 10px', width: '95px' }}>SL %</th>
                <th style={{ padding: '8px 10px', width: '95px' }}>Target %</th>
                <th style={{ padding: '8px 10px', width: '170px' }}>Broker</th>
              </tr>
            </thead>
            <tbody>
              {SEGMENTS.map(s => (
                <tr key={s.id} style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: '10px', fontWeight: 800, color: '#fff', fontSize: '12px' }}>
                    {s.icon} {s.label}
                    {s.lotBased && <div style={{ fontSize: '9px', color: C.dim, fontWeight: 600 }}>Lot-based</div>}
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <Input type="number" step="0.01" value={f.allocations?.[s.id] ?? ''} onChange={e => setAlloc(s.id, e.target.value)} placeholder="0" />
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <Input type="number" step="0.01" value={f.segmentSL?.[s.id] ?? ''} onChange={e => setSL(s.id, e.target.value)}
                      placeholder={Number(f.segmentSLPercent?.[s.id]) > 0 ? '— % used' : '0'}
                      disabled={Number(f.segmentSLPercent?.[s.id]) > 0} />
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <Input type="number" step="0.1" value={f.segmentSLPercent?.[s.id] ?? ''} onChange={e => setSLPct(s.id, e.target.value)} placeholder="—" />
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <Input type="number" step="0.1" value={f.segmentTargetPercent?.[s.id] ?? ''} onChange={e => setTgtPct(s.id, e.target.value)} placeholder="—" />
                  </td>
                  <td style={{ padding: '8px 10px' }}>
                    <Select value={f.segmentBroker?.[s.id] || ''} onChange={e => setBroker(s.id, e.target.value)}>
                      <option value="">Not set</option>
                      {Object.values(BROKERS).map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
                    </Select>
                  </td>
                </tr>
              ))}
              <tr style={{ borderTop: `1px solid ${C.border}`, background: 'rgba(167,139,250,0.05)' }}>
                <td style={{ padding: '10px', fontWeight: 800, color: C.violet, fontSize: '12px' }}>💠 Opportunity Reserve</td>
                <td style={{ padding: '8px 10px' }}>
                  <Input type="number" step="0.01" value={f.reserveAllocation ?? ''} onChange={e => set('reserveAllocation', e.target.value)} placeholder="0" />
                </td>
                <td style={{ padding: '10px', color: C.dim, fontSize: '11px' }}>N/A</td>
                <td style={{ padding: '10px', color: C.dim, fontSize: '11px' }}>N/A</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        title="Daily risk counter"
        subtitle="Each segment drips its allocation every day. Reaching the segment stop-loss unlocks a trade. A win keeps the counter; a loss resets it to zero and takes the actual net loss out of that segment's capital."
      >
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: '14px' }}>
          <Field label="Counter start date" required hint="Accrual begins on this day">
            <Input type="date" value={f.accrualStartDate || ''} onChange={e => set('accrualStartDate', e.target.value)} />
          </Field>
          <Field label="Spread allocation over (days)" hint="22 = a month of trading days">
            <Input type="number" min="1" value={f.accrualDivisor ?? 22} onChange={e => set('accrualDivisor', e.target.value)} />
          </Field>
          <Field label="Accrue on" hint="Weekdays skips Saturday and Sunday entirely">
            <Select value={f.accrualBasis || 'WEEKDAYS'} onChange={e => set('accrualBasis', e.target.value)}>
              <option value="WEEKDAYS">Trading days (Mon–Fri)</option>
              <option value="CALENDAR">Every calendar day</option>
            </Select>
          </Field>
        </div>

        <div style={{ marginTop: '16px', overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '560px' }}>
            <thead>
              <tr style={{ color: C.muted, textAlign: 'left', fontSize: '10px', textTransform: 'uppercase' }}>
                <th style={{ padding: '8px 10px' }}>Lane</th>
                <th style={{ padding: '8px 10px' }}>Accrues / day</th>
                <th style={{ padding: '8px 10px' }}>Unlocks at</th>
                <th style={{ padding: '8px 10px' }}>{normalized.accrualBasis === 'WEEKDAYS' ? 'Trading days to unlock' : 'Days to unlock'}</th>
                <th style={{ padding: '8px 10px' }}>Losses hit capital?</th>
              </tr>
            </thead>
            <tbody>
              {SEGMENTS.map(seg => {
                const rate = dailyRateFor(seg.id, normalized);
                const sl = Number(normalized.segmentSL?.[seg.id]) || 0;
                const days = rate > 0 && sl > 0 ? Math.ceil(sl / rate) : null;
                const books = normalized.booksLosses?.[seg.id] !== false;
                return (
                  <tr key={seg.id} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: '10px', fontWeight: 800, color: '#fff', fontSize: '12px' }}>{seg.icon} {seg.label}</td>
                    <td style={{ padding: '10px', color: C.accent, fontWeight: 800, fontSize: '12px' }}>{inr(rate)}</td>
                    <td style={{ padding: '10px', color: sl ? C.text : C.amber, fontSize: '12px' }}>{sl ? inr(sl) : 'no SL set'}</td>
                    <td style={{ padding: '10px', color: C.muted, fontSize: '12px' }}>{days ? `${days} ${normalized.accrualBasis === 'WEEKDAYS' ? 'trading days' : 'days'}` : '—'}</td>
                    <td style={{ padding: '10px' }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '7px', cursor: 'pointer', fontSize: '11px', color: books ? C.text : C.violet, fontWeight: 700 }}>
                        <input
                          type="checkbox"
                          checked={books}
                          onChange={e => { setF(p => ({ ...p, booksLosses: { ...(p.booksLosses || {}), [seg.id]: e.target.checked } })); setSaved(false); }}
                        />
                        {books ? 'Yes' : 'Exempt'}
                      </label>
                    </td>
                  </tr>
                );
              })}
              <tr style={{ borderTop: `1px solid ${C.border}`, background: 'rgba(167,139,250,0.05)' }}>
                <td style={{ padding: '10px', fontWeight: 800, color: C.violet, fontSize: '12px' }}>💠 Opportunity Reserve</td>
                <td style={{ padding: '10px', color: C.accent, fontWeight: 800, fontSize: '12px' }}>{inr(dailyRateFor('OPPORTUNITY_RESERVE', normalized))}</td>
                <td colSpan={5} style={{ padding: '10px', color: C.dim, fontSize: '11px' }}>Tops up a short counter for A+ setups only</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: '14px', padding: '12px', background: 'rgba(0,0,0,0.3)', borderRadius: '10px', fontSize: '11px', color: C.muted }}>
          Total drip: <strong style={{ color: C.accent }}>{inr(ACCRUAL_LANES.reduce((sum, id) => sum + dailyRateFor(id, normalized), 0))}/{normalized.accrualBasis === 'WEEKDAYS' ? 'trading day' : 'day'}</strong>
          {'  ·  '}Long Term is exempt from loss booking by default — its drawdowns are holds, not failed trades.
        </div>
      </Panel>

      <Panel
        title="Opening deductions"
        subtitle="Risk already committed to a segment before the counters started. Charged against that segment's capital once — it does not reset the counter, because it is spent capital, not a loss."
      >
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '420px' }}>
            <thead>
              <tr style={{ color: C.muted, textAlign: 'left', fontSize: '10px', textTransform: 'uppercase' }}>
                <th style={{ padding: '8px 10px' }}>Segment</th>
                <th style={{ padding: '8px 10px', width: '190px' }}>Already committed (₹)</th>
              </tr>
            </thead>
            <tbody>
              {SEGMENTS.map(seg => (
                <tr key={seg.id} style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: '10px', fontWeight: 800, color: '#fff', fontSize: '12px' }}>{seg.icon} {seg.label}</td>
                  <td style={{ padding: '8px 10px' }}>
                    <Input
                      type="number"
                      step="0.01"
                      value={f.openingDeductions?.[seg.id] ?? ''}
                      onChange={e => setOpening(seg.id, e.target.value)}
                      placeholder="0"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ marginTop: '14px', padding: '12px', background: 'rgba(0,0,0,0.3)', borderRadius: '10px' }}>
          <StatGrid min="160px">
            <Stat label="Total deducted" value={inr(openingTotal)} size="16px" color={openingTotal > 0 ? C.violet : C.muted} />
            <Stat
              label="Effect"
              value={openingTotal > 0 ? 'Reduces capital' : 'None'}
              size="16px"
              sub="Counters are unaffected"
            />
          </StatGrid>
        </div>
      </Panel>

      <Panel title="Reporting months" subtitle={`Monthly P&L periods from ${monthLabel('2026-09')} through ${monthLabel('2029-09')}. The daily counter is the risk control; months are reporting only.`}>
        <StatGrid min="150px">
          <Stat label="Total months" value={store.months?.length || 0} size="17px" />
          <Stat label="First month" value={monthLabel((store.months || [])[0]?.month_key || '')} size="17px" />
          <Stat label="Last month" value={monthLabel((store.months || [])[(store.months || []).length - 1]?.month_key || '')} size="17px" />
        </StatGrid>
      </Panel>

      <Verdict blocked={problems} warnings={warnings} />

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        {saved && <Chip tone="good">Saved — months rebuilt</Chip>}
        <Btn disabled={problems.length > 0} onClick={save}>Save setup</Btn>
      </div>

      {/* ── Danger zone ── */}
      <Panel title="Reset" subtitle="Wipes Risk Desk data only. Your existing portfolio, holdings and P&L ledger are untouched." accent="rgba(239,68,68,0.3)">
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '14px' }}>
          {Object.entries(dataCounts).map(([k, v]) => (
            <Chip key={k} tone={v > 0 ? 'info' : 'muted'}>{k}: {v}</Chip>
          ))}
        </div>
        {!hasData ? (
          <Empty>Nothing recorded yet — you are already starting from scratch.</Empty>
        ) : confirmReset ? (
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '12px', color: '#fca5a5', fontWeight: 700 }}>
              Delete all {dataCounts.trades} trades, {dataCounts.setups} setups and every ledger entry? This cannot be undone.
            </span>
            <Btn tone="danger" onClick={() => { onReset(); setConfirmReset(false); }}>Yes, erase everything</Btn>
            <Btn tone="ghost" onClick={() => setConfirmReset(false)}>Cancel</Btn>
          </div>
        ) : (
          <Btn tone="danger" onClick={() => setConfirmReset(true)}>Erase all Risk Desk data</Btn>
        )}
      </Panel>
    </div>
  );
}
