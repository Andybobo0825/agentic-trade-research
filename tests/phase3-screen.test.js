import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  assertPhase3ScreenArgs,
  renderPhase3ScreenMarkdown,
  runPhase3Screen,
} from '../src/phase3-screen.js';

const FEATURES = Object.freeze({
  hma9SlopePct: 0.8,
  hma20SlopePct: 0.2,
  closeToHma9Pct: 2,
  averageTurnover: 50_000_000,
  averageTurnoverLog10: Math.log10(50_000_000),
  momentum5Pct: 8,
  closePosition: 0.6,
  volumeRatio: 1.2,
  relativeMomentum3Pct: 1,
  marketBreadth1d: 0.5,
  foreignBuyStreak: 1,
  foreignThreeDayIntensity: 0.02,
});

function candidate(ticker, decisionDate, overrides = {}) {
  const values = { ...FEATURES, ...overrides };
  return {
    ticker,
    decisionDate,
    decisionTime: `${decisionDate}T18:00:00+08:00`,
    decisionPrice: 100,
    featureNames: Object.keys(values),
    features: Object.values(values),
    evidenceAvailableAt: [`${decisionDate}T18:00:00+08:00`],
    technicalEvidenceHashes: [`hash-${ticker}-${decisionDate}`],
  };
}

function dependencies(rows) {
  return {
    ensureCandidateArtifact: async () => ({
      candidateArtifact: '/tmp/candidates.json',
      candidateHash: 'candidate-hash',
      evidenceManifestHash: 'evidence-hash',
      candidateCount: rows.length,
      created: false,
    }),
    readCandidates: async () => rows,
  };
}

test('rejects execution and unknown arguments', () => {
  for (const key of ['live', 'order', 'placeOrder']) {
    assert.throws(() => assertPhase3ScreenArgs({ [key]: true }), new RegExp(`forbids ${key}`));
  }
});

test('fails clearly when no point-in-time evidence produced candidates', async () => {
  await assert.rejects(
    () => runPhase3Screen({}, dependencies([])),
    /no Phase 3 candidates.*phase3-dataset/i,
  );
});

test('fails clearly when the requested window has no candidate observations', async () => {
  await assert.rejects(
    () => runPhase3Screen({ startDate: '2026-07-01' }, dependencies([
      candidate('2330', '2026-06-30'),
    ])),
    /no Phase 3 observations.*requested window/i,
  );
});

test('screens only the latest date by default and ranks eligible candidates deterministically', async () => {
  const rows = [
    candidate('OLD', '2026-06-29'),
    candidate('B', '2026-06-30', { foreignBuyStreak: 1 }),
    candidate('A', '2026-06-30', { foreignBuyStreak: 4, volumeRatio: 2 }),
    candidate('X', '2026-06-30', { momentum5Pct: 18.1 }),
  ];
  const result = await runPhase3Screen({}, dependencies(rows));

  assert.equal(result.executionMode, 'read_only');
  assert.equal(result.asOfDate, '2026-06-30');
  assert.equal(result.observationCount, 3);
  assert.equal(result.eligibleCount, 2);
  assert.equal(result.rejectedCount, 1);
  assert.deepEqual(result.candidates.map((row) => row.ticker), ['A', 'B']);
  assert.equal(result.candidates.some((row) => Object.hasOwn(row, 'probability')), false);
  assert.equal(result.resultHash.length, 64);
});

test('supports an explicit historical window and reports stable rejection reasons', async () => {
  const rows = [
    candidate('A', '2026-06-28'),
    candidate('B', '2026-06-29', { closePosition: 0.8 }),
    candidate('C', '2026-06-30'),
  ];
  const result = await runPhase3Screen({
    startDate: '2026-06-28',
    endDate: '2026-06-29',
    includeRejected: true,
  }, dependencies(rows));

  assert.equal(result.observationCount, 2);
  assert.deepEqual(result.candidates.map((row) => row.ticker), ['A']);
  assert.deepEqual(result.rejected.map((row) => ({ ticker: row.ticker, reasons: row.reasons })), [{
    ticker: 'B',
    reasons: ['close_position_above_maximum'],
  }]);
});

test('writes deterministic JSON and Markdown reports', async () => {
  const root = await mkdtemp(join(tmpdir(), 'phase3-screen-'));
  const reportJson = join(root, 'screen.json');
  const reportMarkdown = join(root, 'screen.md');
  const result = await runPhase3Screen({ reportJson, reportMarkdown }, dependencies([
    candidate('2330', '2026-06-30'),
  ]));

  assert.deepEqual(JSON.parse(await readFile(reportJson, 'utf8')), result);
  const markdown = await readFile(reportMarkdown, 'utf8');
  assert.equal(markdown, renderPhase3ScreenMarkdown(result));
  assert.match(markdown, /Phase 3 Screen/);
  assert.match(markdown, /2330/);
  assert.doesNotMatch(markdown, /probability|logistic|promotion/i);
});
