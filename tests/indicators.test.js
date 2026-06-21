import test from 'node:test';
import assert from 'node:assert/strict';
import { calculateHullMovingAverage, calculateWeightedMovingAverage, evaluateHmaTrendSignal } from '../src/indicators.js';

test('weighted moving average applies ascending weights to the newest values', () => {
  const result = calculateWeightedMovingAverage([1, 2, 3, 4], 3);
  assert.equal(result[0], null);
  assert.equal(result[1], null);
  assert.equal(result[2], 14 / 6);
  assert.equal(result[3], 20 / 6);
});

test('Hull MA matches Pine formula using floor half-period and sqrt-period windows', () => {
  const closes = Array.from({ length: 30 }, (_, index) => index + 1);
  const hma = calculateHullMovingAverage(closes, 9);
  assert.equal(hma[9], null);
  assert.equal(hma[10], 11);
  assert.equal(hma[11], 12);
  assert.equal(hma[14], 15);
});

test('HMA trend signal reports bullish continuation when price is above a rising HMA', () => {
  const candles = Array.from({ length: 30 }, (_, index) => {
    const close = index + 1;
    return { date: `2026-01-${String(index + 1).padStart(2, '0')}`, close };
  });
  const signal = evaluateHmaTrendSignal(candles, { period: 9 });
  assert.equal(signal.trend, 'bullish');
  assert.equal(signal.action, 'hold_long');
  assert.equal(signal.latest.close, 30);
  assert.equal(signal.latest.hma, 30);
  assert.match(signal.reason, /above a rising HMA/);
});
