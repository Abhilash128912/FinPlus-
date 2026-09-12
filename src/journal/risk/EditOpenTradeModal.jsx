import React, { useState } from 'react';
import { C, inr, Modal, Field, Input, Select, Btn } from './ui.jsx';

export default function EditOpenTradeModal({ trade, onClose, onSubmit, onDelete }) {
  const [entryPrice, setEntryPrice] = useState(String(trade.entry_price ?? ''));
  const [quantity, setQuantity] = useState(String(trade.quantity ?? ''));
  const [direction, setDirection] = useState(trade.direction || 'LONG');
  const [stopLoss, setStopLoss] = useState(trade.stop_loss_price != null ? String(trade.stop_loss_price) : '');
  const [targetPrice, setTargetPrice] = useState(trade.target_price != null ? String(trade.target_price) : '');
  const [notes, setNotes] = useState(trade.notes || '');
  const [confirmDelete, setConfirmDelete] = useState(false);

  const numEntry = Number(entryPrice) || 0;
  const numQty = Number(quantity) || 0;
  const numSL = Number(stopLoss) || 0;
  const numTarget = Number(targetPrice) || 0;

  const totalValue = numEntry * numQty;
  const plannedRisk = numSL > 0 ? Math.abs(numEntry - numSL) * numQty : 0;
  const plannedReward = numTarget > 0 ? Math.abs(numTarget - numEntry) * numQty : 0;
  const rrRatio = plannedRisk > 0 && plannedReward > 0 ? (plannedReward / plannedRisk).toFixed(2) : null;

  const isValid = numEntry > 0 && numQty > 0;

  return (
    <Modal
      title={`Edit Open Position — ${trade.symbol}`}
      subtitle={`${trade.segment} · Current: ${trade.quantity} units @ ${inr(trade.entry_price)}`}
      onClose={onClose}
      width="520px"
    >
      <div style={{ display: 'grid', gap: '14px' }}>
        {confirmDelete ? (
          <div style={{
            background: 'rgba(239,68,68,0.12)',
            border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: '12px',
            padding: '16px',
            textAlign: 'center'
          }}>
            <div style={{ fontSize: '14px', fontWeight: 900, color: C.red, marginBottom: '6px' }}>
              Delete this open position?
            </div>
            <div style={{ fontSize: '11px', color: C.muted, marginBottom: '14px', lineHeight: 1.5 }}>
              This will completely remove <strong>{trade.symbol}</strong> ({trade.quantity} qty) from your active positions without booking any loss or charge to your capital.
            </div>
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
              <Btn tone="ghost" onClick={() => setConfirmDelete(false)}>Cancel</Btn>
              <Btn
                tone="danger"
                onClick={() => {
                  if (onDelete) onDelete(trade.id);
                  onClose();
                }}
              >
                Confirm Delete
              </Btn>
            </div>
          </div>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <Field label="Order Side / Direction" required>
                <Select value={direction} onChange={e => setDirection(e.target.value)}>
                  <option value="LONG">🟢 LONG (Bought First)</option>
                  <option value="SHORT">🔴 SHORT (Sold First / MIS)</option>
                </Select>
              </Field>
              <Field label="Quantity" required>
                <Input
                  type="number"
                  min="1"
                  step="1"
                  value={quantity}
                  onChange={e => setQuantity(e.target.value)}
                  placeholder="Qty"
                  required
                />
              </Field>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <Field label="Buy / Entry Price (₹)" required hint="Correct your trade entry price">
                <Input
                  type="number"
                  step="0.05"
                  autoFocus
                  value={entryPrice}
                  onChange={e => setEntryPrice(e.target.value)}
                  placeholder="0.00"
                  required
                  style={{ borderColor: numEntry > 0 ? C.accent : undefined }}
                />
              </Field>
              <Field label="Stop-Loss Price (₹)" hint="Planned risk boundary">
                <Input
                  type="number"
                  step="0.05"
                  value={stopLoss}
                  onChange={e => setStopLoss(e.target.value)}
                  placeholder="Optional"
                />
              </Field>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <Field label="Target Price (₹)" hint="Planned take-profit level">
                <Input
                  type="number"
                  step="0.05"
                  value={targetPrice}
                  onChange={e => setTargetPrice(e.target.value)}
                  placeholder="Optional"
                />
              </Field>
              <Field label="Notes / Reason">
                <Input
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  placeholder="e.g. Corrected price"
                />
              </Field>
            </div>

            {/* Live recalculation preview */}
            {isValid && (
              <div style={{
                background: 'rgba(255,255,255,0.03)',
                border: `1px solid ${C.border}`,
                borderRadius: '10px',
                padding: '12px',
                display: 'grid',
                gridTemplateColumns: numSL > 0 ? (numTarget > 0 ? '1fr 1fr 1fr' : '1fr 1fr') : '1fr',
                gap: '10px'
              }}>
                <div>
                  <div style={{ fontSize: '10px', color: C.muted, fontWeight: 700, textTransform: 'uppercase' }}>New Position Value</div>
                  <div style={{ fontSize: '14px', fontWeight: 900, color: '#fff', marginTop: '2px' }}>
                    {inr(totalValue)}
                  </div>
                  <div style={{ fontSize: '10px', color: C.dim }}>{numQty} × {inr(numEntry)}</div>
                </div>

                {numSL > 0 && (
                  <div>
                    <div style={{ fontSize: '10px', color: C.muted, fontWeight: 700, textTransform: 'uppercase' }}>Planned Risk</div>
                    <div style={{ fontSize: '14px', fontWeight: 900, color: C.amber, marginTop: '2px' }}>
                      {inr(plannedRisk)}
                    </div>
                    <div style={{ fontSize: '10px', color: C.dim }}>
                      {inr(Math.abs(numEntry - numSL))} / unit
                    </div>
                  </div>
                )}

                {numTarget > 0 && (
                  <div>
                    <div style={{ fontSize: '10px', color: C.muted, fontWeight: 700, textTransform: 'uppercase' }}>Target Reward</div>
                    <div style={{ fontSize: '14px', fontWeight: 900, color: C.green, marginTop: '2px' }}>
                      {inr(plannedReward)}
                    </div>
                    {rrRatio && <div style={{ fontSize: '10px', color: C.accent }}>1 : {rrRatio} R:R</div>}
                  </div>
                )}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '10px' }}>
              <div>
                {onDelete && (
                  <Btn
                    tone="ghost"
                    onClick={() => setConfirmDelete(true)}
                    style={{ color: C.red, fontSize: '11px', padding: '6px 10px' }}
                  >
                    🗑️ Delete Trade
                  </Btn>
                )}
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                <Btn tone="ghost" onClick={onClose}>Cancel</Btn>
                <Btn
                  disabled={!isValid}
                  onClick={() => {
                    const updates = {
                      entry_price: numEntry,
                      quantity: numQty,
                      direction,
                      stop_loss_price: numSL > 0 ? numSL : null,
                      target_price: numTarget > 0 ? numTarget : null,
                      notes: notes.trim() || undefined
                    };
                    if (numSL > 0) {
                      updates.planned_total_risk = plannedRisk;
                    }
                    onSubmit(updates);
                    onClose();
                  }}
                >
                  Save Changes
                </Btn>
              </div>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
