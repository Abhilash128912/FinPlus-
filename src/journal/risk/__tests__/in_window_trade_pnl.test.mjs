import test from 'node:test';
import assert from 'node:assert/strict';
import { calculateIntradayCharges, calculateOptionsCharges } from '../../journal_engine.js';

test('Intraday equity buy and sell charges match statutory rates with zero DP', () => {
  // Long 100 shares of SBIN @ 800, exit @ 810
  const result = calculateIntradayCharges({
    entry_price: 800,
    exit_price: 810,
    quantity: 100,
    side: 'BUY'
  });

  // Gross PnL = (810 - 800) * 100 = 1000
  assert.equal(result.gross_pnl, 1000);

  // Buy turnover = 80,000, Sell turnover = 81,000, Total = 161,000
  // Buy brokerage: min(80000 * 0.0003, 20) = 20
  // Exit brokerage: min(81000 * 0.0003, 20) = 20
  assert.equal(result.brokerage, 40);

  // STT: 0.025% on sell turnover (81000 * 0.00025 = 20.25)
  assert.equal(result.stt, 20.25);

  // DP charges: strictly 0 for intraday
  assert.equal(result.dp_charges, 0);

  // Total charges > 0 and net PnL = gross - total
  assert.ok(result.total > 0);
  assert.equal(result.net_pnl, result.gross_pnl - result.total);
});

test('Intraday short trade (sell high, buy low) calculates positive gross PnL', () => {
  // Short 50 shares @ 1000, buy cover @ 980
  const result = calculateIntradayCharges({
    entry_price: 1000,
    exit_price: 980,
    quantity: 50,
    side: 'SELL_SHORT'
  });

  // Gross PnL for Short = (1000 - 980) * 50 = +1000
  assert.equal(result.gross_pnl, 1000);
  assert.equal(result.dp_charges, 0);
  assert.ok(result.net_pnl > 0 && result.net_pnl < 1000);
});

test('Options trade charges calculate flat brokerage and premium STT', () => {
  // 1 lot of Nifty = 65 qty @ 100, exit @ 130
  const result = calculateOptionsCharges({
    entry_premium: 100,
    exit_premium: 130,
    quantity: 65
  });

  // Gross PnL = (130 - 100) * 65 = 1950
  assert.equal(result.gross_pnl, 1950);

  // Flat brokerage = 20 x 2 = 40
  assert.equal(result.brokerage, 40);

  // STT on sell premium: 130 * 65 * 0.0015 = 12.675
  assert.equal(result.stt, 12.675);
  assert.equal(result.dp_charges, 0);
  assert.equal(result.net_pnl, result.gross_pnl - result.total);
});
