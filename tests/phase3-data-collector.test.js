import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  collectPhase3PointInTimeData,
  normalizeDailyMarketEvidence,
  normalizeInstitutionalEvidence,
} from '../src/phase3-data-collector.js';
import { readEvidenceManifest } from '../src/point-in-time-store.js';

test('daily market evidence is available only after market close', () => {
  const [row] = normalizeDailyMarketEvidence([{
    date: '2026-01-02',
    stock_id: '2330',
    close: 100,
    Trading_Volume: 2_000_000,
  }], { fetchedAt: '2026-01-03T00:00:00+08:00' });
  assert.equal(row.availableAt, '2026-01-02T13:30:00+08:00');
  assert.equal(row.dataQuality, 'accepted');
});

test('institutional evidence discloses inferred post-close availability', () => {
  const [row] = normalizeInstitutionalEvidence([{
    date: '2026-01-02',
    stock_id: '2330',
    name: 'Foreign_Investor',
    buy: 2000,
    sell: 1000,
  }], { fetchedAt: '2026-01-03T00:00:00+08:00' });
  assert.equal(row.availableAt, '2026-01-02T18:00:00+08:00');
  assert.equal(row.dataQuality, 'inferred_schedule');
});

test('collector persists accepted evidence and reports partial provider gaps', async () => {
  const root = await mkdtemp(join(tmpdir(), 'phase3-collector-'));
  const result = await collectPhase3PointInTimeData({
    tickers: ['2330'],
    startDate: '2026-01-01',
    endDate: '2026-01-31',
    evidenceRoot: root,
    fetchedAt: '2026-02-01T00:00:00+08:00',
  }, {
    getPrice: async () => ({ data: [{ date: '2026-01-02', stock_id: '2330', close: 100, Trading_Volume: 2_000_000 }] }),
    getInstitutional: async () => { throw new Error('provider unavailable'); },
  });

  assert.equal(result.recordsWritten, 1);
  assert.equal(result.coverage.market, 1);
  assert.equal(result.coverage.institutional, 0);
  assert.equal(result.executionMode, 'read_only');
  assert.equal(result.orderApiSafe, true);
  assert.deepEqual(result.excluded.map((row) => row.reason), ['provider_error']);
  assert.equal((await readEvidenceManifest(root)).length, 1);
});

test('collector records malformed provider timestamps without aborting other sources', async () => {
  const root = await mkdtemp(join(tmpdir(), 'phase3-malformed-'));
  const result = await collectPhase3PointInTimeData({
    tickers: ['2330'],
    evidenceRoot: root,
    fetchedAt: '2026-02-01T00:00:00+08:00',
  }, {
    getPrice: async () => ({ data: [{ date: 'not-a-date', stock_id: '2330', close: 100 }] }),
    getInstitutional: async () => ({ data: [] }),
  });
  assert.equal(result.recordsWritten, 0);
  assert.ok(result.excluded.some((row) => row.reason === 'normalization_error'));
});

test('collector limits Phase 3 evidence to market and institutional inputs', async () => {
  const root = await mkdtemp(join(tmpdir(), 'phase3-technical-only-'));
  let externalCalls = 0;
  const result = await collectPhase3PointInTimeData({
    tickers: ['2330'],
    evidenceRoot: root,
    collectNews: true,
  }, {
    getPrice: async () => ({ data: [] }),
    getInstitutional: async () => ({ data: [] }),
    getHolders: async () => { externalCalls += 1; return { data: [] }; },
    getNews: async () => { externalCalls += 1; return { data: [] }; },
  });

  assert.equal(externalCalls, 0);
  assert.deepEqual(Object.keys(result.coverage).sort(), ['institutional', 'market']);
});
