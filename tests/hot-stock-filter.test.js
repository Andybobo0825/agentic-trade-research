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


test('hot-stock filter rejects attempts to exclude electronic components industry 28', () => {
  const meta = { code: '2478', name: '大毅', industry: '28' };
  const row = { close: 234, amount: 8_470_000_000 };
  const ind = { volRatio: 3.2, turnoverRatio: 4.45, dayReturnPct: 2.86, closePos: 0.94, atrPct: 4.2 };

  assert.throws(
    () => isHotStockCandidate({ meta, row, ind }, { excludedIndustries: new Set(['17', '28']) }),
    /Protected Taiwan industry code 28.*電子零組件/
  );
});

test('hot-stock filter normalizes electronic components code 28 as a protected tradable industry', () => {
  const meta = { code: '2327', name: '國巨', industry: 28 };
  const row = { close: 1080, amount: 97_896_000_000 };
  const ind = { volRatio: 1.93, turnoverRatio: 2.51, dayReturnPct: 9.76, closePos: 1, atrPct: 4.8 };

  const decision = isHotStockCandidate({ meta, row, ind });
  assert.equal(decision.allowed, true);
  assert.equal(decision.reason, 'hot');
});
