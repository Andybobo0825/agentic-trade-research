import test from 'node:test';
import assert from 'node:assert/strict';
import { shouldExitR18S } from '../src/r18s-exit.js';

test('R18S does not exit before user-facing day 3', () => {
  assert.deepEqual(
    shouldExitR18S({ holdDays: 1, openRet: -0.08, row: { open: 92, close: 93, high: 94 }, previousClose: 100, maxClose: 100 }),
    { exit: false, reason: '未到第 3 個交易日續抱' },
  );
  assert.equal(shouldExitR18S({ holdDays: 1, openRet: 0.15, row: { open: 115 }, previousClose: 100, maxClose: 110 }).exit, false);
});

test('R18S starts checking continuation on user-facing day 3', () => {
  const decision = shouldExitR18S({ holdDays: 2, openRet: 0.02, row: { open: 102, close: 101, high: 103 }, previousClose: 103, maxClose: 106, breakoutHigh: 106 });
  assert.equal(decision.exit, true);
  assert.match(decision.reason, /第3天未續強/);
});

test('R18S holds from day 3 to day 6 when price keeps confirming strength', () => {
  const decision = shouldExitR18S({ holdDays: 2, openRet: 0.05, row: { open: 105, close: 108, high: 109 }, previousClose: 104, maxClose: 106, breakoutHigh: 106 });
  assert.equal(decision.exit, false);
});

test('R18S exits on stop or take-profit only from user-facing day 3 onward', () => {
  assert.equal(shouldExitR18S({ holdDays: 2, openRet: -0.061, row: { open: 93.9 }, previousClose: 100, maxClose: 100 }).reason, '停損 -6.1%');
  assert.equal(shouldExitR18S({ holdDays: 2, openRet: 0.132, row: { open: 113.2 }, previousClose: 100, maxClose: 110 }).reason, '停利 13.2%');
});

test('R18S forces exit on user-facing day 7', () => {
  const decision = shouldExitR18S({ holdDays: 6, openRet: 0.04, row: { open: 104, close: 106, high: 107 }, previousClose: 105, maxClose: 108 });
  assert.equal(decision.exit, true);
  assert.equal(decision.reason, '滿 7 個交易日出場');
});
