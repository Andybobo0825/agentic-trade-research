import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { recordExperience, recallExperience } from '../src/experience-store.js';

function newRoot() {
  return mkdtempSync(join(tmpdir(), 'experience-'));
}

test('recalling a regime with no history returns nothing rather than failing', () => {
  assert.deepEqual(recallExperience(newRoot(), { regime: 'spike' }), []);
});

test('an experience is filed under its regime and read back intact', () => {
  const root = newRoot();
  const entry = recordExperience(root, {
    regime: 'trading_range',
    date: '2026-08-11',
    ticker: 'TAIEX',
    judgment: { diagnosis: { regime: 'trading_range', direction: 'neutral' } },
    note: '量縮等邊界',
  });

  assert.ok(existsSync(join(root, entry.path)));
  assert.match(entry.path, /\.omx\/experience\/trading_range\/2026-08-11-TAIEX\.json$/);

  const [recalled] = recallExperience(root, { regime: 'trading_range' });
  assert.equal(recalled.ticker, 'TAIEX');
  assert.equal(recalled.note, '量縮等邊界');
  assert.equal(recalled.judgment.diagnosis.direction, 'neutral');
  assert.equal(JSON.parse(readFileSync(join(root, entry.path), 'utf8')).regime, 'trading_range');
});

test('recall returns the newest entries first and honours the limit', () => {
  const root = newRoot();
  for (const date of ['2026-08-01', '2026-08-05', '2026-08-11', '2026-07-20']) {
    recordExperience(root, { regime: 'spike', date, ticker: 'TAIEX', judgment: {} });
  }
  const recalled = recallExperience(root, { regime: 'spike', limit: 2 });
  assert.deepEqual(recalled.map((row) => row.date), ['2026-08-11', '2026-08-05']);
  assert.equal(recallExperience(root, { regime: 'spike' }).length, 4);
});

test('recall never reaches into another regime', () => {
  const root = newRoot();
  recordExperience(root, { regime: 'spike', date: '2026-08-11', ticker: 'AAA', judgment: {} });
  recordExperience(root, { regime: 'trading_range', date: '2026-08-11', ticker: 'BBB', judgment: {} });
  const recalled = recallExperience(root, { regime: 'spike' });
  assert.equal(recalled.length, 1);
  assert.equal(recalled[0].ticker, 'AAA');
});

test('re-filing the same day for the same ticker replaces it instead of duplicating', () => {
  const root = newRoot();
  recordExperience(root, { regime: 'spike', date: '2026-08-11', ticker: 'TAIEX', judgment: {}, note: 'first' });
  recordExperience(root, { regime: 'spike', date: '2026-08-11', ticker: 'TAIEX', judgment: {}, note: 'second' });
  const recalled = recallExperience(root, { regime: 'spike' });
  assert.equal(recalled.length, 1);
  assert.equal(recalled[0].note, 'second');
});

test('an unknown regime is refused so the library cannot grow stray folders', () => {
  assert.throws(() => recordExperience(newRoot(), { regime: 'moon_shot', date: '2026-08-11', ticker: 'X', judgment: {} }), /regime/);
});
