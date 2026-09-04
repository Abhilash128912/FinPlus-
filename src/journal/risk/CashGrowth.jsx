import React, { useState, useMemo } from 'react';
import { C, inr, pnlColor, Panel, Stat, StatGrid, Chip, Btn, Field, Input, Select, TextArea, Empty, Verdict } from './ui.jsx';

/** Cash and Growth Reserve. Risk buckets never appear here — they are controls, not cash. */
export default function CashGrowth({ desk }) {
  const { accountView, store, actions } = desk;
  const [form, setForm] = useState({ type: 'DEPOSIT', amount: '', note: '', at: new Date().toISOString().slice(0, 10) });
  const [verdict, setVerdict] = useState({ blocked: [], warnings: [] });

  const activity = useMemo(() => {
    const rows = [
      ...(store.broker_cash_ledger || []).map(x => ({ ...x, ledger: 'CASH' })),
      ...(store.growth_reserve_ledger || []).map(x => ({ ...x, ledger: 'GROWTH' }))
    ];
    return rows.sort((a, b) => String(b.at).localeCompare(String(a.at)));
  }, [store.broker_cash_ledger, store.growth_reserve_ledger]);

  const submit = () => {
    const amount = Number(form.amount) || 0;
    const entry = { type: form.type, amount, note: form.note, at: new Date(form.at).toISOString() };
    const res = ['TO_GROWTH', 'FROM_GROWTH'].includes(form.type)
      ? actions.addGrowthEntry(entry)
      : actions.addCashEntry(entry);
    setVerdict({ blocked: res.blocked || [], warnings: res.warnings || [] });
    if (res.ok) setForm(f => ({ ...f, amount: '', note: '' }));
  };

  const TYPES = [
    { id: 'OPENING', label: 'Opening balance', hint: 'Set your starting broker cash' },
    { id: 'DEPOSIT', label: 'Deposit', hint: 'Money moved into the broker account' },
    { id: 'WITHDRAWAL', label: 'Withdrawal', hint: 'Money taken out — from real cash only' },
    { id: 'TO_GROWTH', label: 'Retain profit → Growth Reserve', hint: 'Manually keep realized profit for future capital' },
    { id: 'FROM_GROWTH', label: 'Release Growth Reserve → cash', hint: 'Does not raise any risk limit' }
  ];
  const selected = TYPES.find(t => t.id === form.type);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

      <Panel title="Cash position" subtitle="Actual money in the trading account. A risk allocation is never cash and can never be withdrawn.">
        <StatGrid min="145px">
          <Stat label="Broker cash" value={inr(accountView.brokerCash)} color={C.accent} />
          <Stat label="Withdrawable" value={inr(accountView.withdrawableCash)} color={C.green} />
          <Stat label="Growth Reserve" value={inr(accountView.growthReserve)} color={C.violet} sub="Does not refill losses" />
          <Stat label="Opening" value={inr(accountView.openingCash)} size="16px" />
          <Stat label="Deposits" value={inr(accountView.deposits)} size="16px" />
          <Stat label="Withdrawals" value={inr(accountView.withdrawals)} size="16px" />
          <Stat label="Realized net P&L" value={inr(accountView.realizedNetPnl)} size="16px" color={pnlColor(accountView.realizedNetPnl)} />
        </StatGrid>
      </Panel>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
        <Panel title="Record cash activity">
          <div style={{ display: 'grid', gap: '13px' }}>
            <Field label="Type" hint={selected?.hint}>
              <Select value={form.type} onChange={e => { setForm(f => ({ ...f, type: e.target.value })); setVerdict({ blocked: [], warnings: [] }); }}>
                {TYPES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
              </Select>
            </Field>
            <Field label="Amount" required>
              <Input type="number" step="0.01" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} placeholder="0.00" />
            </Field>
            <Field label="Date">
              <Input type="date" value={form.at} onChange={e => setForm(f => ({ ...f, at: e.target.value }))} />
            </Field>
            <Field label="Note">
              <Input value={form.note} onChange={e => setForm(f => ({ ...f, note: e.target.value }))} placeholder="Optional" />
            </Field>
            <Verdict blocked={verdict.blocked} warnings={verdict.warnings} compact />
            <Btn disabled={!Number(form.amount)} onClick={submit}>Record</Btn>
          </div>
        </Panel>

        <Panel title="Month-end policy" subtitle="What the app will and will not do for you.">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '12px' }}>
            {[
              ['Unused segment allocation', 'Expires unused. Never rolls forward.', C.muted],
              ['Unused Opportunity Reserve', 'Expires at month-end. Never rolls forward.', C.muted],
              ['Realized profit', 'Withdrawable by default.', C.green],
              ['Profit you retain', 'Moves to Growth Reserve only when you choose.', C.violet],
              ['Growth Reserve', 'Never raises a risk limit or refills a loss.', C.violet],
              ['Losses', 'Stay recorded. No replenishment, no recovery trading.', C.red],
              ['Next month', 'Opens with a fresh risk budget.', C.accent]
            ].map(([k, v, color]) => (
              <div key={k} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', paddingBottom: '9px', borderBottom: `1px solid ${C.border}` }}>
                <div style={{ minWidth: '150px', fontWeight: 800, color: '#fff', fontSize: '11px' }}>{k}</div>
                <div style={{ color, fontSize: '11px', fontWeight: 600 }}>{v}</div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="All cash and reserve activity">
        {activity.length === 0 ? (
          <Empty>No cash activity recorded yet.</Empty>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', minWidth: '560px' }}>
              <thead>
                <tr style={{ color: C.muted, textAlign: 'left', fontSize: '10px', textTransform: 'uppercase' }}>
                  <th style={{ padding: '9px 10px' }}>Date</th>
                  <th style={{ padding: '9px 10px' }}>Ledger</th>
                  <th style={{ padding: '9px 10px' }}>Type</th>
                  <th style={{ padding: '9px 10px' }}>Amount</th>
                  <th style={{ padding: '9px 10px' }}>Note</th>
                </tr>
              </thead>
              <tbody>
                {activity.map(x => (
                  <tr key={x.id} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={{ padding: '10px', color: C.muted }}>{new Date(x.at).toLocaleDateString('en-IN')}</td>
                    <td style={{ padding: '10px' }}>
                      <Chip tone={x.ledger === 'GROWTH' ? 'violet' : 'info'}>{x.ledger === 'GROWTH' ? 'Growth' : 'Cash'}</Chip>
                    </td>
                    <td style={{ padding: '10px', color: '#fff', fontWeight: 700 }}>{x.type.replace(/_/g, ' ')}</td>
                    <td style={{
                      padding: '10px', fontWeight: 900,
                      color: ['WITHDRAWAL', 'TO_GROWTH'].includes(x.type) ? C.red : C.green
                    }}>
                      {['WITHDRAWAL', 'TO_GROWTH'].includes(x.type) ? '−' : '+'}{inr(x.amount)}
                    </td>
                    <td style={{ padding: '10px', color: C.muted }}>{x.note || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
