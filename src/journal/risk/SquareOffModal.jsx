import React, { useState, useMemo } from 'react';
import { C, inr, pnlColor, Modal, Field, Input, Select, Btn, Stat, Chip } from './ui.jsx';
import { calculateIntradayCharges, calculateOptionsCharges, calculateKiteDeliveryCharges } from '../journal_engine.js';

export default function SquareOffModal({ trade, lane, desk, onClose }) {
  const isIntraday = trade.segment === 'INTRADAY';
  const isOptions = trade.segment === 'INDEX_OPTIONS' || trade.segment === 'STOCK_OPTIONS';
  const isShort = String(trade.direction || '').toUpperCase() === 'SHORT';

  const defaultExit = trade._pnl?.hasLivePrice 
    ? String(trade._pnl.markPrice) 
    : String(trade.entry_price || '');

  const [exitPrice, setExitPrice] = useState(defaultExit);
  const [exitReason, setExitReason] = useState('TARGET_REACHED');
  const [customReason, setCustomReason] = useState('');
  const [exitDate, setExitDate] = useState(() => new Date().toISOString().slice(0, 16));
  const [busy, setBusy] = useState(false);

  const numExit = Number(exitPrice) || 0;
  const numEntry = Number(trade.entry_price) || 0;
  const numQty = Number(trade.quantity) || 0;

  // Real-time calculation
  const { grossPnl, charges, netPnl } = useMemo(() => {
    if (!numExit || numExit <= 0 || !numEntry || numEntry <= 0 || !numQty || numQty <= 0) {
      return { grossPnl: 0, charges: { total: 0, brokerage: 0, stt: 0, gst: 0, exchange_txn: 0 }, netPnl: 0 };
    }

    let chgResult;
    if (isIntraday) {
      chgResult = calculateIntradayCharges({
        entry_price: numEntry,
        exit_price: numExit,
        quantity: numQty,
        side: isShort ? 'SELL_SHORT' : 'BUY'
      });
    } else if (isOptions) {
      chgResult = calculateOptionsCharges({
        entry_premium: numEntry,
        exit_premium: numExit,
        quantity: numQty,
        side: isShort ? 'SELL' : 'BUY'
      });
    } else {
      chgResult = calculateKiteDeliveryCharges({
        entry_price: numEntry,
        exit_price: numExit,
        quantity: numQty
      });
    }

    return {
      grossPnl: chgResult.gross_pnl,
      charges: chgResult,
      netPnl: chgResult.net_pnl
    };
  }, [numExit, numEntry, numQty, isIntraday, isOptions, isShort]);

  // Capital & Rollover impact
  const currentCapital = lane?.capital || 0;
  const newCapital = currentCapital + netPnl;
  const isWin = netPnl >= 0;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!numExit || numExit <= 0) return;

    setBusy(true);
    const reasonText = exitReason === 'OTHER' ? customReason : exitReason;

    try {
      if (desk?.actions?.closeTrade) {
        await desk.actions.closeTrade(trade.id, {
          exit_price: numExit,
          exit_date: new Date(exitDate).toISOString(),
          exit_reason: reasonText || 'Square Off',
          actual_charges: {
            brokerage: charges.brokerage,
            stt: charges.stt,
            exchange_txn: charges.exchange_txn,
            sebi: charges.sebi,
            stamp_duty: charges.stamp_duty,
            gst: charges.gst,
            dp_charges: charges.dp_charges || 0,
            total: charges.total
          }
        });
      }
      setBusy(false);
      onClose();
    } catch (err) {
      setBusy(false);
      alert('Error closing trade: ' + (err?.message || err));
    }
  };

  return (
    <Modal
      title={`Square Off / Exit — ${trade.symbol}`}
      subtitle={`${trade.segment} · ${isShort ? '🔴 SHORT' : '🟢 LONG'} · ${numQty} qty @ entry ${inr(numEntry)}`}
      onClose={onClose}
      width="600px"
    >
      <form onSubmit={handleSubmit} style={{ display: 'grid', gap: '15px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <Field label="Exit Price (₹)" required hint={trade._pnl?.hasLivePrice ? `Live LTP: ₹${trade._pnl.markPrice}` : 'Current price'}>
            <Input
              type="number"
              step="0.05"
              value={exitPrice}
              onChange={e => setExitPrice(e.target.value)}
              placeholder="0.00"
              autoFocus
              required
            />
          </Field>

          <Field label="Exit Date & Time">
            <Input
              type="datetime-local"
              value={exitDate}
              onChange={e => setExitDate(e.target.value)}
            />
          </Field>
        </div>

        <Field label="Exit Reason / Trigger" required>
          <Select value={exitReason} onChange={e => setExitReason(e.target.value)}>
            <option value="TARGET_REACHED">🎯 Target Hit / Profit Booked</option>
            <option value="STOP_LOSS_HIT">🛑 Stop Loss Hit</option>
            <option value="INTRADAY_EOD_SQUARE_OFF">⏰ End of Day 3:15 PM Square-Off</option>
            <option value="TRAILING_STOP_HIT">📉 Trailing Stop-Loss Hit</option>
            <option value="THESIS_INVALIDATED">⚠️ Technical Setup Invalidated</option>
            <option value="MANUAL_SQUARE_OFF">⚡ Discretionary Manual Exit</option>
            <option value="OTHER">Other Reason</option>
          </Select>
        </Field>

        {exitReason === 'OTHER' && (
          <Field label="Specify Reason">
            <Input
              value={customReason}
              onChange={e => setCustomReason(e.target.value)}
              placeholder="Describe your exit rationale"
              required
            />
          </Field>
        )}

        {/* ── Real-Time P&L Breakdown Card ── */}
        <div style={{
          padding: '16px',
          background: 'rgba(15, 23, 42, 0.85)',
          border: `1.5px solid ${netPnl >= 0 ? 'rgba(16,185,129,0.45)' : 'rgba(239,68,68,0.45)'}`,
          borderRadius: '12px',
          display: 'grid',
          gap: '12px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '13px', fontWeight: 800, color: '#94a3b8' }}>Realized P&L Calculation:</span>
            <Chip tone={netPnl >= 0 ? 'good' : 'bad'}>
              {netPnl >= 0 ? '✓ WINNING TRADE' : '✕ BOOKED LOSS'}
            </Chip>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px' }}>
            <Stat label="Gross P&L" value={inr(grossPnl)} size="16px" color={pnlColor(grossPnl)} />
            <Stat label="Taxes & Charges" value={inr(charges.total)} size="16px" color={C.amber} sub={isIntraday ? "₹0 DP charge" : undefined} />
            <Stat label="Net Realized P&L" value={inr(netPnl)} size="18px" color={pnlColor(netPnl)} />
          </div>

          {/* Detailed Taxes Accordion / Line items */}
          <div style={{
            fontSize: '10px',
            color: '#94a3b8',
            background: 'rgba(0,0,0,0.25)',
            padding: '8px 12px',
            borderRadius: '8px',
            display: 'flex',
            flexWrap: 'wrap',
            gap: '12px',
            justifyContent: 'space-between'
          }}>
            <span>Brokerage: {inr(charges.brokerage)}</span>
            <span>STT: {inr(charges.stt)}</span>
            <span>Exchange: {inr(charges.exchange_txn)}</span>
            <span>GST: {inr(charges.gst)}</span>
            <span>Stamp Duty: {inr(charges.stamp_duty)}</span>
            <span>DP: {inr(charges.dp_charges || 0)}</span>
          </div>

          {/* ── Impact on Remaining Rollover Capital ── */}
          <div style={{
            padding: '10px 12px',
            background: isWin ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
            border: `1px solid ${isWin ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
            borderRadius: '8px',
            fontSize: '11px',
            lineHeight: 1.5
          }}>
            <div style={{ fontWeight: 900, color: isWin ? C.green : '#fca5a5', marginBottom: '4px' }}>
              Impact on {trade.segment} Rollover Capital:
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', color: '#fff' }}>
              <span>Capital before trade: <b>{inr(currentCapital)}</b></span>
              <span>➔</span>
              <span>Capital after exit: <b style={{ color: newCapital >= 0 ? C.green : C.red }}>{inr(newCapital)}</b></span>
            </div>
            <div style={{ marginTop: '4px', color: '#94a3b8' }}>
              {isWin 
                ? '✓ Profit adds to your capital. Risk counter is preserved for continued trading.' 
                : '⚠ Loss is deducted from capital. Daily counter resets to zero and requires new daily drip.'}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '10px' }}>
          <Btn tone="ghost" type="button" onClick={onClose}>Cancel</Btn>
          <Btn tone={netPnl >= 0 ? "good" : "danger"} type="submit" disabled={busy || !numExit}>
            {busy ? 'Processing Exit…' : `Square Off & Book ${inr(netPnl)}`}
          </Btn>
        </div>
      </form>
    </Modal>
  );
}
