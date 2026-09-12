import React, { useState, useEffect, useMemo, useRef } from 'react';
import { C, inr, Modal, Field, Input, Select, Btn, Stat, Chip, Verdict } from './ui.jsx';
import { getSegment } from './risk_model.js';
import { calculateIntradayCharges, calculateOptionsCharges } from '../journal_engine.js';

const DEFAULT_LOT_SIZES = {
  NIFTY: 65,
  BANKNIFTY: 35,
  FINNIFTY: 65,
  MIDCPNIFTY: 120,
  CRUDEOIL: 100,
  NATURALGAS: 1250
};

export default function InWindowTradeModal({ segmentId, lane, desk, onClose }) {
  const seg = getSegment(segmentId) || { id: segmentId, label: segmentId, icon: '⚡' };
  const isIntraday = segmentId === 'INTRADAY';
  const isOptions = segmentId === 'INDEX_OPTIONS' || segmentId === 'STOCK_OPTIONS';
  const isCommodity = segmentId === 'CRUDE' || segmentId === 'NATURAL_GAS';

  const [symbol, setSymbol] = useState('');
  const [direction, setDirection] = useState('BUY'); // 'BUY' or 'SELL_SHORT'
  const [entryPrice, setEntryPrice] = useState('');
  const [quantity, setQuantity] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [target, setTarget] = useState('');
  const [intent, setIntent] = useState('COUNTER_UNLOCKED');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Options specific fields
  const [optionType, setOptionType] = useState('CE'); // 'CE' or 'PE'
  const [strikePrice, setStrikePrice] = useState('');
  const [lots, setLots] = useState('1');
  const [lotSize, setLotSize] = useState(() => {
    if (segmentId === 'INDEX_OPTIONS') return DEFAULT_LOT_SIZES.NIFTY;
    if (segmentId === 'NATURAL_GAS') return DEFAULT_LOT_SIZES.NATURALGAS;
    if (segmentId === 'CRUDE') return DEFAULT_LOT_SIZES.CRUDEOIL;
    return 1;
  });

  // Stock universe autocomplete
  const [stocks, setStocks] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const wrapperRef = useRef(null);

  useEffect(() => {
    fetch('/stock_universe.json')
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) setStocks(data);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    function handleClickOutside(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setShowSuggestions(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSymbolChange = (val) => {
    const query = val.toUpperCase();
    setSymbol(query);
    if (!query || query.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    const filtered = stocks
      .filter(s => s.s.startsWith(query) || (s.n && s.n.toUpperCase().includes(query)))
      .slice(0, 8);
    setSuggestions(filtered);
    setShowSuggestions(filtered.length > 0);
  };

  // If user changes index option instrument or lots
  const handleIndexSelect = (inst) => {
    setSymbol(inst);
    const sz = DEFAULT_LOT_SIZES[inst] || 1;
    setLotSize(sz);
    setQuantity(String((parseInt(lots, 10) || 1) * sz));
  };

  // Auto-calculate quantity for options based on lots
  useEffect(() => {
    if (isOptions || isCommodity) {
      const numLots = parseInt(lots, 10) || 1;
      const sz = parseInt(lotSize, 10) || 1;
      setQuantity(String(numLots * sz));
    }
  }, [lots, lotSize, isOptions, isCommodity]);

  // Suggested SL from lane threshold / percentage
  useEffect(() => {
    if (lane?.slPercent && entryPrice && Number(entryPrice) > 0) {
      const ep = Number(entryPrice);
      const slDist = ep * (lane.slPercent / 100);
      const computedSL = direction === 'BUY' ? ep - slDist : ep + slDist;
      setStopLoss(computedSL.toFixed(2));
    }
  }, [entryPrice, direction, lane?.slPercent]);

  // Auto-size quantity based on lane counter stop loss threshold if empty
  const handleAutoQty = () => {
    const ep = Number(entryPrice);
    const sl = Number(stopLoss);
    if (!ep || !sl || ep <= 0 || sl <= 0) return;
    const riskPerShare = Math.abs(ep - sl);
    if (riskPerShare <= 0) return;
    const availableRisk = lane?.threshold || lane?.counter || 100;
    const calculatedQty = Math.floor(availableRisk / riskPerShare);
    if (calculatedQty > 0) {
      setQuantity(String(calculatedQty));
    }
  };

  // Estimated charges and risk math
  const numQty = Number(quantity) || 0;
  const numEntry = Number(entryPrice) || 0;
  const numSl = Number(stopLoss) || 0;
  const priceRisk = (numEntry && numSl) ? Math.abs(numEntry - numSl) * numQty : 0;

  const estimatedCharges = useMemo(() => {
    if (numEntry <= 0 || numQty <= 0) return 0;
    if (isIntraday) {
      const chg = calculateIntradayCharges({ entry_price: numEntry, exit_price: numEntry, quantity: numQty, side: direction });
      return chg.total;
    }
    if (isOptions) {
      const chg = calculateOptionsCharges({ entry_premium: numEntry, exit_premium: numEntry, quantity: numQty });
      return chg.total;
    }
    return 20; // Default estimate
  }, [isIntraday, isOptions, numEntry, numQty, direction]);

  const totalRisk = priceRisk + estimatedCharges;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!symbol.trim()) {
      setError('Please enter a trading symbol.');
      return;
    }
    if (!numEntry || numEntry <= 0) {
      setError('Please enter a valid entry price.');
      return;
    }
    if (!numQty || numQty <= 0) {
      setError('Please enter a valid quantity.');
      return;
    }

    setBusy(true);
    setError(null);

    const fullSymbol = isOptions 
      ? `${symbol} ${strikePrice ? strikePrice + ' ' : ''}${optionType}`.trim()
      : symbol.trim();

    const tradePayload = {
      segment: segmentId,
      symbol: fullSymbol,
      underlying: isOptions ? symbol : null,
      direction: direction === 'BUY' ? 'LONG' : 'SHORT',
      entry_price: numEntry,
      quantity: numQty,
      stop_loss_price: numSl || (direction === 'BUY' ? numEntry * 0.98 : numEntry * 1.02),
      target_price: Number(target) || (direction === 'BUY' ? numEntry * 1.04 : numEntry * 0.96),
      lots: isOptions || isCommodity ? parseInt(lots, 10) || 1 : null,
      lot_size: isOptions || isCommodity ? parseInt(lotSize, 10) || 1 : null,
      option_type: isOptions ? optionType : null,
      strike_price: isOptions && strikePrice ? Number(strikePrice) : null,
      trade_intent: intent,
      notes: notes.trim(),
      broker: lane?.broker || 'ZERODHA',
      entry_date: new Date().toISOString()
    };

    try {
      if (desk?.actions?.recordTrade) {
        await desk.actions.recordTrade(tradePayload);
      }
      setBusy(false);
      onClose();
    } catch (err) {
      setBusy(false);
      setError(err?.message || 'Failed to record trade.');
    }
  };

  return (
    <Modal
      title={`${seg.icon} Take Trade — ${seg.label}`}
      subtitle={`Counter: ${inr(lane?.counter || 0)} available · ${lane?.unlocked ? '✓ Unlocked' : 'Risk rule check'}`}
      onClose={onClose}
      width="640px"
    >
      <form onSubmit={handleSubmit} style={{ display: 'grid', gap: '14px' }}>
        {error && (
          <div style={{ padding: '10px 14px', background: 'rgba(239,68,68,0.15)', border: '1px solid #ef4444', borderRadius: '8px', color: '#fca5a5', fontSize: '12px' }}>
            {error}
          </div>
        )}

        {/* ── Segment Quick Selector & Direction ── */}
        <div style={{ display: 'grid', gridTemplateColumns: isOptions ? '1fr 1fr' : '1.5fr 1fr', gap: '12px' }}>
          {isOptions ? (
            <Field label="Option Instrument">
              <Select value={symbol} onChange={e => handleIndexSelect(e.target.value)}>
                <option value="">Select Index / Stock</option>
                <option value="NIFTY">NIFTY (Lot 65)</option>
                <option value="BANKNIFTY">BANK NIFTY (Lot 35)</option>
                <option value="FINNIFTY">FIN NIFTY (Lot 65)</option>
                <option value="MIDCPNIFTY">MIDCP NIFTY (Lot 120)</option>
                <option value="STOCK_OPTION">Custom Stock Option</option>
              </Select>
            </Field>
          ) : (
            <div ref={wrapperRef} style={{ position: 'relative' }}>
              <Field label="Symbol / Script" required hint="NSE stock ticker (e.g. SBIN, TATAMOTORS)">
                <Input
                  value={symbol}
                  onChange={e => handleSymbolChange(e.target.value)}
                  placeholder="e.g. SBIN"
                  autoFocus
                />
              </Field>
              {showSuggestions && suggestions.length > 0 && (
                <div style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  background: '#0f172a',
                  border: '1px solid #38bdf8',
                  borderRadius: '8px',
                  zIndex: 100,
                  maxHeight: '180px',
                  overflowY: 'auto',
                  boxShadow: '0 8px 24px rgba(0,0,0,0.6)'
                }}>
                  {suggestions.map(s => (
                    <div
                      key={s.s}
                      onClick={() => {
                        setSymbol(s.s);
                        setShowSuggestions(false);
                      }}
                      style={{
                        padding: '8px 12px',
                        cursor: 'pointer',
                        borderBottom: '1px solid rgba(255,255,255,0.06)',
                        display: 'flex',
                        justifyContent: 'space-between'
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'rgba(56,189,248,0.15)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      <span style={{ fontWeight: 800, color: '#fff' }}>{s.s}</span>
                      <span style={{ fontSize: '11px', color: '#94a3b8' }}>{s.n}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          <Field label="Order Direction / Side" required>
            <Select value={direction} onChange={e => setDirection(e.target.value)}>
              <option value="BUY">🟢 BUY (Long Position)</option>
              <option value="SELL_SHORT">🔴 SELL (Short / MIS)</option>
            </Select>
          </Field>
        </div>

        {/* ── Options Details (if applicable) ── */}
        {isOptions && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '10px' }}>
            <Field label="Strike Price" hint="e.g. 24500">
              <Input
                type="number"
                value={strikePrice}
                onChange={e => setStrikePrice(e.target.value)}
                placeholder="24500"
              />
            </Field>
            <Field label="Type">
              <Select value={optionType} onChange={e => setOptionType(e.target.value)}>
                <option value="CE">Call (CE)</option>
                <option value="PE">Put (PE)</option>
              </Select>
            </Field>
            <Field label="Lots">
              <Input
                type="number"
                min="1"
                value={lots}
                onChange={e => setLots(e.target.value)}
              />
            </Field>
            <Field label="Total Qty">
              <Input
                type="number"
                value={quantity}
                readOnly
                style={{ background: 'rgba(255,255,255,0.05)', color: C.accent, fontWeight: 800 }}
              />
            </Field>
          </div>
        )}

        {/* ── Pricing & Quantity ── */}
        <div style={{ display: 'grid', gridTemplateColumns: isOptions ? '1fr 1fr 1fr' : '1fr 1fr 1fr', gap: '12px' }}>
          <Field label={isOptions ? "Entry Premium (₹)" : "Entry Price (₹)"} required>
            <Input
              type="number"
              step="0.05"
              value={entryPrice}
              onChange={e => setEntryPrice(e.target.value)}
              placeholder="0.00"
              required
            />
          </Field>

          {!isOptions && (
            <Field label="Quantity (Shares)" required hint={<span onClick={handleAutoQty} style={{ cursor: 'pointer', color: C.accent }}>Auto-size from risk</span>}>
              <Input
                type="number"
                min="1"
                value={quantity}
                onChange={e => setQuantity(e.target.value)}
                placeholder="Qty"
                required
              />
            </Field>
          )}

          <Field label="Stop-Loss Price (₹)" hint={lane?.slPercent ? `${lane.slPercent}% rule` : 'Risk boundary'}>
            <Input
              type="number"
              step="0.05"
              value={stopLoss}
              onChange={e => setStopLoss(e.target.value)}
              placeholder="0.00"
            />
          </Field>

          <Field label="Target Price (₹)" hint="Profit objective">
            <Input
              type="number"
              step="0.05"
              value={target}
              onChange={e => setTarget(e.target.value)}
              placeholder="0.00"
            />
          </Field>
        </div>

        {/* ── Risk & Capital Impact Preview ── */}
        <div style={{
          padding: '14px',
          background: 'rgba(15, 23, 42, 0.8)',
          border: '1px solid rgba(56, 189, 248, 0.25)',
          borderRadius: '10px',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
          gap: '12px'
        }}>
          <Stat label="Total Exposure" value={inr(numEntry * numQty)} size="15px" />
          <Stat label="Price Risk" value={inr(priceRisk)} size="15px" color={C.amber} />
          <Stat label="Est. Charges" value={inr(estimatedCharges)} size="15px" color={C.amber} sub={isIntraday ? "₹0 DP charge" : undefined} />
          <Stat label="Planned Risk" value={inr(totalRisk)} size="15px" color={totalRisk > (lane?.counter || 0) ? C.red : C.green} />
          <Stat label="Counter Capital" value={inr(lane?.capital || 0)} size="15px" />
        </div>

        {totalRisk > (lane?.counter || 0) && (
          <div style={{ fontSize: '11px', color: C.amber, fontWeight: 700 }}>
            ℹ Planned risk ({inr(totalRisk)}) exceeds current counter ({inr(lane?.counter || 0)}). It will draw against segment rollover capital.
          </div>
        )}

        <Field label="Trade Setup Notes" hint="Reason, pattern, or thesis">
          <Input
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="e.g. 15m breakout pullback, EMA bounce, VWAP rejection"
          />
        </Field>

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '10px' }}>
          <Btn tone="ghost" type="button" onClick={onClose}>Cancel</Btn>
          <Btn tone="good" type="submit" disabled={busy}>
            {busy ? 'Executing Trade…' : '✓ Execute & Open Trade'}
          </Btn>
        </div>
      </form>
    </Modal>
  );
}
