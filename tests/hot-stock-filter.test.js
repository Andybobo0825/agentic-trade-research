import test from 'node:test';
import assert from 'node:assert/strict';
import { isHotStockCandidate, hotStockScore } from '../src/hot-stock-filter.js';

test('hot-stock filter rejects financial stocks before study scoring', () => {
  const meta = { code: '2889', name: '國票金', industry: '17' };
  const row = { close: 17.4, amount: 500_000_000 };
  const ind = { volRatio: 3.3, turnoverRatio: 3.4, dayReturnPct: 3.5, closePos: 0.9, atrPct: 2.4 };
  const decision = isHotStockCandidate({ meta, row, ind });
  assert.equal(decision.allowed, false);
  assert.equal(decision.reason, 'excluded-industry');
});

test('hot-stock filter rejects quiet stocks with poor volume and liquidity', () => {
  const meta = { code: '1234', name: '冷門股', industry: '28' };
  const row = { close: 50, amount: 8_000_000 };
  const ind = { volRatio: 1.2, turnoverRatio: 1.1, dayReturnPct: 0.8, closePos: 0.75, atrPct: 2.5 };
  const decision = isHotStockCandidate({ meta, row, ind });
  assert.equal(decision.allowed, false);
  assert.equal(decision.reason, 'insufficient-heat');
});

test('hot-stock filter accepts liquid high-volume momentum stocks and scores heat', () => {
  const meta = { code: '3042', name: '晶技', industry: '28' };
  const row = { close: 100, amount: 450_000_000 };
  const ind = { volRatio: 2.7, turnoverRatio: 3.1, dayReturnPct: 4.2, closePos: 0.86, atrPct: 3.2 };
  const decision = isHotStockCandidate({ meta, row, ind });
  assert.equal(decision.allowed, true);
  assert.equal(decision.reason, 'hot');
  assert.equal(decision.score, hotStockScore({ row, ind }));
  assert.ok(decision.score > 200);
});
