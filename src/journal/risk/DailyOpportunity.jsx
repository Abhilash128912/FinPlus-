import React, { useState, useMemo } from 'react';
import { C, inr, Panel, Stat, StatGrid, Chip, Btn, Field, Input, Select, TextArea, Modal, Empty, Verdict } from './ui.jsx';
import { SEGMENTS, SCORE_CATEGORIES, TRADE_INTENTS, getSegment } from './risk_model.js';
import { scoreSetup, riskReward } from './scoring.js';
import { computePlannedRisk } from './risk_engine.js';
import { BROKERS } from './broker_profiles.js';
import { slPercentFor, targetPercentFor } from './accrual_engine.js';

/** Daily review: every segment gets a verdict, including "No Setup". */
export default function DailyOpportunity({ desk }) {
  const { dayDecision, todaySetups, monthView, dailySnapshot, actions, config, profiles, validate } = desk;
  const [editing, setEditing] = useState(null);
  const [taking, setTaking] = useState(null);

  const bySegment = useMemo(() => {
    const map = {};
    for (const c of dayDecision.candidates) {
      (map[c.segment] = map[c.segment] || []).push(c);
    }
    return map;
  }, [dayDecision.candidates]);

  const reviewed = SEGMENTS.filter(s => (bySegment[s.id] || []).length > 0).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

      <Panel
        title={`Daily review — ${new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}`}
        subtitle="Record a candidate or an explicit 'No Setup' for each segment. Rejections are part of the record."
        right={<Chip tone={reviewed === SEGMENTS.length ? 'good' : 'warn'}>{reviewed}/{SEGMENTS.length} segments reviewed</Chip>}
      >
        <StatGrid min="150px">
          <Stat label="Candidates" value={dayDecision.candidates.length} />
          <Stat label="Eligible A/A+" value={dayDecision.eligible.length} color={dayDecision.eligible.length ? C.green : C.muted} />
          <Stat label="Rejected" value={dayDecision.rejected.length} color={C.muted} />
          <Stat label="Positions today" value={`${dailySnapshot.positionCount} / ${dailySnapshot.maxPositions}`}
            color={dailySnapshot.positionCount >= dailySnapshot.maxPositionsExceptional ? C.red : '#fff'} />
          <Stat label="Daily risk used" value={inr(dailySnapshot.plannedRisk)} sub={`of ${inr(dailySnapshot.dailyRiskLimit)}`}
            color={dailySnapshot.remaining < 0 ? C.red : '#fff'} />
        </StatGrid>
      </Panel>

      {/* ── The decision ── */}
      {dayDecision.noTrade ? (
        <Panel accent="rgba(148,163,184,0.3)" style={{ background: 'rgba(148,163,184,0.05)', textAlign: 'center', padding: '30px' }}>
          <div style={{ fontSize: '24px', fontWeight: 900, color: C.muted, letterSpacing: '1px' }}>NO TRADE</div>
          <div style={{ fontSize: '13px', color: C.dim, marginTop: '9px' }}>{dayDecision.noTradeMessage}</div>
          <div style={{ fontSize: '11px', color: C.dim, marginTop: '14px', maxWidth: '440px', margin: '14px auto 0' }}>
            Sitting out is a valid outcome. Unused capacity expires; it is not a target to hit.
          </div>
        </Panel>
      ) : (
        <Panel accent="rgba(16,185,129,0.45)" style={{ background: 'rgba(16,185,129,0.07)' }}>
          <div style={{ fontSize: '10px', color: C.green, fontWeight: 800, letterSpacing: '0.6px', marginBottom: '10px' }}>
            BEST ELIGIBLE OPPORTUNITY
          </div>
          <CandidateBody c={dayDecision.recommendation} big />
          <div style={{ display: 'flex', gap: '10px', marginTop: '15px', flexWrap: 'wrap' }}>
            <Btn tone="good" onClick={() => setTaking(dayDecision.recommendation)}>Take this trade</Btn>
            <Btn tone="ghost" onClick={() => setEditing(dayDecision.recommendation)}>Edit setup</Btn>
          </div>
        </Panel>
      )}

      {/* ── Per-segment breakdown ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '16px' }}>
        {SEGMENTS.map(seg => {
          const cands = bySegment[seg.id] || [];
          const segView = monthView?.segments?.find(s => s.id === seg.id);
          return (
            <Panel key={seg.id} accent={cands.some(c => c.eligible) ? 'rgba(16,185,129,0.35)' : C.border}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 900, color: '#fff' }}>{seg.icon} {seg.label}</div>
                  <div style={{ fontSize: '10px', color: C.muted, marginTop: '3px' }}>
                    Capacity {segView?.remainingRisk === null ? 'flexible' : inr(segView?.remainingRisk || 0)}
                  </div>
                </div>
                <Btn tone="ghost" onClick={() => setEditing({ segment: seg.id })} style={{ padding: '6px 11px' }}>+ Setup</Btn>
              </div>

              {cands.length === 0 ? (
                <div style={{ padding: '16px', textAlign: 'center', border: `1px dashed ${C.border}`, borderRadius: '9px' }}>
                  <div style={{ fontSize: '11px', color: C.dim, fontWeight: 700 }}>Not reviewed today</div>
                  <Btn
                    tone="ghost"
                    onClick={() => actions.saveSetup({ segment: seg.id, no_setup: true, symbol: '—', notes: 'No setup' })}
                    style={{ marginTop: '9px', padding: '5px 11px', fontSize: '11px' }}
                  >
                    Mark "No Setup"
                  </Btn>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {cands.map(c => (
                    <div
                      key={c.id}
                      style={{
                        background: c.eligible ? 'rgba(16,185,129,0.07)' : 'rgba(255,255,255,0.02)',
                        border: `1px solid ${c.eligible ? 'rgba(16,185,129,0.28)' : C.border}`,
                        borderRadius: '10px',
                        padding: '12px'
                      }}
                    >
                      <CandidateBody c={c} />
                      <div style={{ display: 'flex', gap: '7px', marginTop: '10px', flexWrap: 'wrap' }}>
                        {c.eligible && <Btn tone="good" onClick={() => setTaking(c)} style={{ padding: '5px 11px', fontSize: '11px' }}>Take</Btn>}
                        <Btn tone="ghost" onClick={() => setEditing(c)} style={{ padding: '5px 11px', fontSize: '11px' }}>Edit</Btn>
                        <Btn tone="danger" onClick={() => actions.deleteSetup(c.id)} style={{ padding: '5px 11px', fontSize: '11px' }}>Remove</Btn>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          );
        })}
      </div>

      {editing && (
        <SetupModal
          initial={editing}
          config={config}
          profiles={profiles}
          monthView={monthView}
          validate={validate}
          onClose={() => setEditing(null)}
          onSave={(setup) => { actions.saveSetup(setup); setEditing(null); }}
        />
      )}
      {taking && (
        <TakeTradeModal
          candidate={taking}
          desk={desk}
          onClose={() => setTaking(null)}
        />
      )}
    </div>
  );
}

function CandidateBody({ c, big }) {
  if (c.no_setup) {
    return <div style={{ fontSize: '12px', color: C.dim, fontWeight: 700 }}>No setup recorded — segment reviewed and skipped.</div>;
  }
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '10px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: big ? '19px' : '14px', fontWeight: 900, color: '#fff' }}>
            {c.symbol}
            {c.rank && <span style={{ fontSize: '11px', color: C.accent, marginLeft: '8px' }}>#{c.rank}</span>}
          </div>
          <div style={{ fontSize: '10px', color: C.muted, marginTop: '3px' }}>{c.segmentLabel} · {c.direction || 'LONG'}</div>
        </div>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          <Chip tone={c.score.eligibleGrade ? 'good' : 'bad'}>{c.score.gradeLabel} · {c.score.total}/{c.score.max}</Chip>
          {c.riskReward && <Chip tone="info">R:R {c.riskReward}</Chip>}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(88px, 1fr))', gap: '9px', marginTop: '11px' }}>
        <Stat label="Entry" value={inr(c.entry_price)} size="13px" />
        <Stat label="Stop" value={inr(c.stop_loss_price)} size="13px" color={C.red} />
        <Stat label="Target" value={inr(c.target_price)} size="13px" color={C.green} />
        <Stat label="Price risk" value={inr(c.planned.priceRisk)} size="13px" color={C.amber} />
        <Stat label="Est. charges" value={inr(c.planned.estimatedCharges)} size="13px" color={C.amber} />
        <Stat label="Total risk" value={inr(c.planned.totalRisk)} size="13px" color={C.amber} />
      </div>

      {c.rejectionReason && !c.eligible && (
        <div style={{ marginTop: '10px', fontSize: '11px', color: '#fca5a5', fontWeight: 700 }}>
          ✕ {c.rejectionReason}
        </div>
      )}
      {(c.blocked?.length > 1 || c.warnings?.length > 0) && (
        <div style={{ marginTop: '10px' }}>
          <Verdict blocked={c.blocked?.slice(c.eligible ? 0 : 1) || []} warnings={c.warnings || []} compact />
        </div>
      )}
    </div>
  );
}

const emptyScores = () => SCORE_CATEGORIES.reduce((a, c) => ({ ...a, [c.id]: '' }), {});

function SetupModal({ initial, config, profiles, monthView, validate, onClose, onSave }) {
  const seg = getSegment(initial.segment);
  const [f, setF] = useState(() => ({
    id: initial.id,
    segment: initial.segment,
    symbol: initial.symbol && initial.symbol !== '—' ? initial.symbol : '',
    underlying: initial.underlying || '',
    sector: initial.sector || '',
    direction: initial.direction || 'LONG',
    entry_price: initial.entry_price || '',
    stop_loss_price: initial.stop_loss_price || '',
    planned_sl_hint: Number(config?.segmentSL?.[initial.segment]) || null,
    target_price: initial.target_price || '',
    quantity: initial.quantity || '',
    lot_size: initial.lot_size || (seg?.lotBased ? '' : 1),
    broker: initial.broker || config?.segmentBroker?.[initial.segment] || (initial.segment === 'LONG_TERM' ? config.longTermBroker || '' : ''),
    notes: initial.notes || '',
    no_setup: !!initial.no_setup,
    scores: { ...emptyScores(), ...(initial.scores || {}) },
    entry_date: initial.entry_date || new Date().toISOString()
  }));

  const slPct = slPercentFor(f.segment, config);
  const tgtPct = targetPercentFor(f.segment, config);

  /**
   * Percentage segments (e.g. Swing at 5%) derive the stop and target from the
   * entry price, so the user only types entry, direction and quantity.
   */
  const set = (k, v) => setF(p => {
    const next = { ...p, [k]: v };
    if ((k === 'entry_price' || k === 'direction') && (slPct || tgtPct)) {
      const entry = Number(k === 'entry_price' ? v : next.entry_price) || 0;
      const short = (k === 'direction' ? v : next.direction) === 'SHORT';
      if (entry > 0) {
        if (slPct) {
          next.stop_loss_price = Number((short ? entry * (1 + slPct / 100) : entry * (1 - slPct / 100)).toFixed(2));
        }
        if (tgtPct) {
          next.target_price = Number((short ? entry * (1 - tgtPct / 100) : entry * (1 + tgtPct / 100)).toFixed(2));
        }
      }
    }
    return next;
  });
  const setScore = (k, v) => setF(p => ({ ...p, scores: { ...p.scores, [k]: v } }));

  const score = scoreSetup(f.scores);
  const planned = computePlannedRisk(f, profiles, config);
  const rr = riskReward(f);
  const segView = monthView?.segments?.find(s => s.id === f.segment);
  const verdict = validate ? validate({ trade: f, score, planned, correlation: null, segView }) : { blocked: [], warnings: [] };

  return (
    <Modal
      title={`${initial.id ? 'Edit' : 'New'} setup — ${seg?.label || f.segment}`}
      subtitle="Sub-scores are your judgement. The app owns the threshold, ranking and audit trail."
      onClose={onClose}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))', gap: '13px' }}>
        <Field label="Symbol" required><Input value={f.symbol} onChange={e => set('symbol', e.target.value.toUpperCase())} placeholder="RELIANCE" /></Field>
        <Field label="Underlying" hint="For options"><Input value={f.underlying} onChange={e => set('underlying', e.target.value.toUpperCase())} placeholder="NIFTY" /></Field>
        <Field label="Sector" hint="Drives correlation checks"><Input value={f.sector} onChange={e => set('sector', e.target.value.toUpperCase())} placeholder="BANKING" /></Field>
        <Field label="Direction">
          <Select value={f.direction} onChange={e => set('direction', e.target.value)}>
            <option value="LONG">Long</option>
            <option value="SHORT">Short</option>
          </Select>
        </Field>
        <Field label="Broker" required>
          <Select value={f.broker} onChange={e => set('broker', e.target.value)}>
            <option value="">Select…</option>
            {Object.values(BROKERS).map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
          </Select>
        </Field>
        <Field label="Entry price" required><Input type="number" step="0.01" value={f.entry_price} onChange={e => set('entry_price', e.target.value)} /></Field>
        <Field label="Stop loss" required hint={slPct ? `auto: ${slPct}% from entry` : undefined}>
          <Input type="number" step="0.01" value={f.stop_loss_price} onChange={e => set('stop_loss_price', e.target.value)} />
        </Field>
        <Field label="Target" required hint={tgtPct ? `auto: ${tgtPct}% from entry` : undefined}>
          <Input type="number" step="0.01" value={f.target_price} onChange={e => set('target_price', e.target.value)} />
        </Field>
        <Field label="Quantity" required><Input type="number" value={f.quantity} onChange={e => set('quantity', e.target.value)} /></Field>
        <Field label="Lot size" required={seg?.lotBased}><Input type="number" value={f.lot_size} onChange={e => set('lot_size', e.target.value)} /></Field>
      </div>

      <div style={{ marginTop: '18px' }}>
        <div style={{ fontSize: '12px', fontWeight: 900, color: '#fff', marginBottom: '10px' }}>
          Setup score
          <span style={{ marginLeft: '10px' }}>
            <Chip tone={score.eligibleGrade ? 'good' : 'bad'}>{score.gradeLabel} · {score.total}/{score.max}</Chip>
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(175px, 1fr))', gap: '11px' }}>
          {SCORE_CATEGORIES.map(cat => (
            <Field key={cat.id} label={`${cat.label} (max ${cat.max})`}>
              <Input type="number" min="0" max={cat.max} value={f.scores[cat.id]} onChange={e => setScore(cat.id, e.target.value)} />
            </Field>
          ))}
        </div>
      </div>

      <div style={{ marginTop: '16px', padding: '13px', background: 'rgba(0,0,0,0.3)', borderRadius: '10px' }}>
        <StatGrid min="105px">
          <Stat label="Price risk" value={inr(planned.priceRisk)} size="15px" color={C.amber} />
          <Stat label="Est. charges" value={inr(planned.estimatedCharges)} size="15px" color={C.amber} />
          <Stat label="Total risk" value={inr(planned.totalRisk)} size="15px" color={C.amber} />
          <Stat label="R:R" value={rr ?? '—'} size="15px" />
          <Stat label="Segment left" value={segView?.remainingRisk === null ? 'Flexible' : inr(segView?.remainingRisk || 0)} size="15px" />
        </StatGrid>
      </div>

      <div style={{ marginTop: '14px' }}>
        <Field label="Notes / rationale"><TextArea value={f.notes} onChange={e => set('notes', e.target.value)} placeholder="Why this setup, and what would invalidate it" /></Field>
      </div>

      {(verdict.blocked.length > 0 || verdict.warnings.length > 0) && (
        <div style={{ marginTop: '14px' }}>
          <Verdict blocked={verdict.blocked} warnings={verdict.warnings} compact />
        </div>
      )}

      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '18px', flexWrap: 'wrap' }}>
        <Btn tone="ghost" onClick={onClose}>Cancel</Btn>
        <Btn tone="ghost" onClick={() => onSave({ ...f, no_setup: true, symbol: '—' })}>Save as "No Setup"</Btn>
        <Btn disabled={!f.symbol} onClick={() => onSave({ ...f, no_setup: false })}>Save setup</Btn>
      </div>
    </Modal>
  );
}

function TakeTradeModal({ candidate, desk, onClose }) {
  const { monthView, dailySnapshot, actions } = desk;
  const [intent, setIntent] = useState('PLANNED_OPPORTUNITY');
  const [intentNote, setIntentNote] = useState('');
  const [useReserve, setUseReserve] = useState(false);
  const [reserveAmount, setReserveAmount] = useState('');
  const [reserveReason, setReserveReason] = useState('');
  const [independence, setIndependence] = useState(false);
  const [secondRationale, setSecondRationale] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const isSecond = (dailySnapshot?.positionCount || 0) >= (dailySnapshot?.maxPositions ?? 1);

  const draft = {
    ...candidate,
    trade_intent: intent,
    intent_note: intentNote,
    reserve_risk_used: useReserve ? Number(reserveAmount) || 0 : 0,
    reserve_reason: reserveReason,
    independence_confirmed: independence,
    second_trade_rationale: secondRationale,
    grade: candidate.score?.grade
  };

  const verdict = desk.validate({
    trade: draft,
    score: candidate.score,
    planned: candidate.planned,
    correlation: candidate.correlation
  });

  const submit = async () => {
    setBusy(true);
    const res = await actions.recordTrade(draft);
    setBusy(false);
    setResult(res);
  };

  if (result) {
    return (
      <Modal title="Trade recorded" onClose={onClose} width="520px">
        <div style={{ fontSize: '13px', color: C.text, marginBottom: '14px' }}>
          {candidate.symbol} recorded with {inr(result.planned.totalRisk)} of planned risk committed to {candidate.segmentLabel}.
        </div>
        {result.server?.available === false && (
          <Verdict warnings={[{ message: 'Saved locally. The backend was unreachable, so server-side validation and the authoritative audit entry will sync when it comes back.' }]} compact />
        )}
        {result.server?.available && !result.server.agrees && (
          <Verdict blocked={result.server.blocked?.length ? result.server.blocked : [{ message: 'The server disagreed with the local validation. Review this trade.' }]} compact />
        )}
        {result.server?.available && result.server.agrees && (
          <div style={{ fontSize: '12px', color: C.green, fontWeight: 700 }}>✓ Server validation agrees. Audit entry confirmed.</div>
        )}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '18px' }}>
          <Btn onClick={onClose}>Done</Btn>
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      title={`Take trade — ${candidate.symbol}`}
      subtitle={`${candidate.segmentLabel} · ${candidate.score.gradeLabel} · planned risk ${inr(candidate.planned.totalRisk)}`}
      onClose={onClose}
      width="620px"
    >
      <div style={{ display: 'grid', gap: '14px' }}>
        <Field label="Trade intent" required>
          <Select value={intent} onChange={e => setIntent(e.target.value)}>
            {TRADE_INTENTS.map(i => <option key={i.id} value={i.id}>{i.label}</option>)}
          </Select>
        </Field>
        {intent === 'OTHER' && (
          <Field label="Intent note" required><Input value={intentNote} onChange={e => setIntentNote(e.target.value)} /></Field>
        )}

        <div style={{ padding: '13px', background: 'rgba(167,139,250,0.06)', border: '1px solid rgba(167,139,250,0.2)', borderRadius: '10px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '9px', cursor: 'pointer', fontSize: '12px', fontWeight: 800, color: '#fff' }}>
            <input type="checkbox" checked={useReserve} onChange={e => setUseReserve(e.target.checked)} />
            Use Opportunity Reserve ({inr(monthView?.reserve?.remaining || 0)} available)
          </label>
          {useReserve && (
            <div style={{ display: 'grid', gap: '11px', marginTop: '12px' }}>
              <Field label="Amount from reserve" required>
                <Input type="number" step="0.01" value={reserveAmount} onChange={e => setReserveAmount(e.target.value)} />
              </Field>
              <Field label="Reason" required hint="Recorded permanently as Reserve → Segment → Trade">
                <TextArea value={reserveReason} onChange={e => setReserveReason(e.target.value)} placeholder="Why this exceptional opportunity justifies reserve risk" />
              </Field>
            </div>
          )}
        </div>

        {isSecond && (
          <div style={{ padding: '13px', background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.25)', borderRadius: '10px', display: 'grid', gap: '11px' }}>
            <div style={{ fontSize: '12px', fontWeight: 900, color: C.amber }}>Second position today — exceptional case</div>
            <label style={{ display: 'flex', alignItems: 'center', gap: '9px', cursor: 'pointer', fontSize: '12px', color: '#fff', fontWeight: 700 }}>
              <input type="checkbox" checked={independence} onChange={e => setIndependence(e.target.checked)} />
              I confirm this is independent of my other open position(s)
            </label>
            <Field label="Rationale" required>
              <TextArea value={secondRationale} onChange={e => setSecondRationale(e.target.value)} placeholder="Why a second position is justified today" />
            </Field>
          </div>
        )}

        <Verdict blocked={verdict.blocked} warnings={verdict.warnings} compact />

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <Btn tone="ghost" onClick={onClose}>Cancel</Btn>
          <Btn tone="good" disabled={!verdict.ok || busy} onClick={submit}>
            {busy ? 'Recording…' : 'Record trade'}
          </Btn>
        </div>
      </div>
    </Modal>
  );
}
