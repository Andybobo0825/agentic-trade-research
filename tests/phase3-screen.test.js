import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import {
  applyPhase3DomGuidance,
  assertPhase3ScreenArgs,
  comparePhase3ScreenResults,
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
  assert.doesNotThrow(() => assertPhase3ScreenArgs({
    asOfTime: '2026-06-30T18:00:00+08:00',
  }));
  assert.throws(() => assertPhase3ScreenArgs({ asOfTime: 'not-a-time' }), /asOfTime/);
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
  assert.deepEqual(result.candidates.map((row) => row.rank), [1, 2]);
  assert.deepEqual(result.candidates.map((row) => row.eligibleCount), [2, 2]);
  assert.deepEqual(result.candidates.map((row) => row.rankPercentile), [1, 0.5]);
  assert.equal(result.candidates.every((row) => row.technicalEligible), true);
  assert.equal(result.candidates.every((row) => row.executionEligible), true);
  assert.equal(result.candidates.every((row) => Object.hasOwn(row, 'phase3RankScore')), true);
  assert.equal(result.candidates.every((row) => !Object.hasOwn(row, 'softScore')), true);
  assert.equal(result.candidates.some((row) => Object.hasOwn(row, 'probability')), false);
  assert.equal(result.resultHash.length, 64);
});

test('enforces an explicit point-in-time cutoff and hashes it deterministically', async () => {
  const rows = [
    candidate('A', '2026-06-30'),
    candidate('FUTURE', '2026-07-01'),
  ];
  const args = { asOfTime: '2026-06-30T18:00:00+08:00' };
  const first = await runPhase3Screen(args, dependencies(rows));
  const second = await runPhase3Screen(args, dependencies([...rows].reverse()));

  assert.equal(first.asOfTime, args.asOfTime);
  assert.equal(first.dataFreshnessPassed, true);
  assert.deepEqual(first.candidates.map((row) => row.ticker), ['A']);
  assert.equal(first.candidates[0].asOfTime, args.asOfTime);
  assert.equal(first.observationCount, 1);
  assert.equal(first.resultHash, second.resultHash);
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
  assert.deepEqual(result.rejectionSummary, { close_position_above_maximum: 1 });
  assert.deepEqual(result.exclusiveRejectionSummary, { close_position_above_maximum: 1 });
  assert.deepEqual(result.sequentialFunnel.map((row) => row.stage), [
    'required_features_complete',
    'average_turnover',
    'hma20_regime',
    'hma9_rising',
    'close_above_hma9',
    'hma_distance',
    'momentum5',
    'close_position',
  ]);
  assert.equal(result.sequentialFunnel.at(-1).remainingCount, 1);
});

test('counts overlapping rejection reasons and only-reason failures', async () => {
  const result = await runPhase3Screen({ includeRejected: true }, dependencies([
    candidate('PASS', '2026-06-30'),
    candidate('ONE', '2026-06-30', { closePosition: 0.8 }),
    candidate('TWO', '2026-06-30', { closePosition: 0.8, momentum5Pct: 19 }),
  ]));

  assert.deepEqual(result.rejectionSummary, {
    momentum_5d_above_maximum: 1,
    close_position_above_maximum: 2,
  });
  assert.deepEqual(result.exclusiveRejectionSummary, {
    close_position_above_maximum: 1,
  });
  const momentumStage = result.sequentialFunnel.find((row) => row.stage === 'momentum5');
  const closeStage = result.sequentialFunnel.find((row) => row.stage === 'close_position');
  assert.equal(momentumStage.rejectedCount, 1);
  assert.equal(closeStage.rejectedCount, 1);
});

test('breaks rank ties by soft feature coverage and then ticker', async () => {
  const neutral = {
    volumeRatio: 1,
    relativeMomentum3Pct: 0,
    marketBreadth1d: 0.5,
    foreignBuyStreak: 0,
    foreignThreeDayIntensity: 0,
  };
  const complete = candidate('B', '2026-06-30', neutral);
  const incomplete = candidate('A', '2026-06-30', neutral);
  const missingIndex = incomplete.featureNames.indexOf('foreignThreeDayIntensity');
  incomplete.features[missingIndex] = null;
  const result = await runPhase3Screen({}, dependencies([incomplete, complete]));

  assert.deepEqual(result.candidates.map((row) => row.ticker), ['B', 'A']);
  assert.equal(result.candidates[0].phase3RankScore, result.candidates[1].phase3RankScore);
  assert.equal(result.candidates[0].softFeatureCoverage.coveragePct, 100);
  assert.equal(result.candidates[1].softFeatureCoverage.coveragePct, 80);
});

function eligibleScreenCandidate(overrides = {}) {
  return {
    ticker: '2330',
    technicalEligible: true,
    executionEligible: true,
    phase3RankScore: 64,
    hardGateDiagnostics: { averageTurnover: 50_000_000 },
    warnings: [],
    ...overrides,
  };
}

function validDom(overrides = {}) {
  return {
    ticker: '2330',
    validSampleCount: 1,
    reliability: 'high',
    samples: [{
      valid: true,
      capturedAt: '2026-07-14T01:00:00.000Z',
      bids: [{ price: 100, volume: 100 }],
      asks: [{ price: 100.5, volume: 80 }],
      depthImbalance: 0.11111111,
    }],
    referencePrices: {
      patientEntryPrice: 100,
      activeEntryLimit: 100.5,
      takeProfitPrice: 101,
      stopLossPrice: 99.5,
    },
    referencePriceSources: {
      snapshotCapturedAt: '2026-07-14T01:00:00.000Z',
    },
    ...overrides,
  };
}

test('DOM unavailable keeps technical eligibility and emits no fabricated prices', () => {
  const candidateRow = eligibleScreenCandidate();
  const result = applyPhase3DomGuidance(candidateRow, null, {
    asOfTime: '2026-07-14T01:00:10.000Z',
    maxAgeSeconds: 30,
  });

  assert.equal(result.technicalEligible, true);
  assert.equal(result.phase3RankScore, 64);
  assert.equal(result.executionEligible, false);
  assert.deepEqual(result.dom, {
    available: false,
    observedAt: null,
    sampleAgeSeconds: null,
    bestBid: null,
    bestAsk: null,
    spreadPct: null,
    bidDepth: null,
    askDepth: null,
    imbalance: null,
    suggestedPassiveBid: null,
    suggestedAggressiveBid: null,
    doNotChaseAbove: null,
    cancelOrWaitBelow: null,
    confidence: 'none',
    warnings: ['dom_unavailable'],
  });
});

test('DOM rejects ticker mismatch, stale samples, and invalid spreads', () => {
  const options = { asOfTime: '2026-07-14T01:00:10.000Z', maxAgeSeconds: 30 };
  const cases = [
    [validDom({ ticker: '2317' }), 'dom_ticker_mismatch'],
    [validDom({
      samples: [{
        valid: true,
        capturedAt: '2026-07-14T00:59:00.000Z',
        bids: [{ price: 100, volume: 100 }],
        asks: [{ price: 100.5, volume: 80 }],
      }],
      referencePriceSources: { snapshotCapturedAt: '2026-07-14T00:59:00.000Z' },
    }), 'stale_dom'],
    [validDom({
      samples: [{
        valid: true,
        capturedAt: '2026-07-14T01:00:00.000Z',
        bids: [{ price: 101, volume: 100 }],
        asks: [{ price: 100.5, volume: 80 }],
      }],
    }), 'invalid_dom_spread'],
  ];

  for (const [dom, warning] of cases) {
    const result = applyPhase3DomGuidance(eligibleScreenCandidate(), dom, options);
    assert.equal(result.technicalEligible, true, warning);
    assert.equal(result.phase3RankScore, 64, warning);
    assert.equal(result.executionEligible, false, warning);
    assert.equal(result.dom.available, false, warning);
    assert.equal(result.dom.warnings.includes(warning), true, warning);
    assert.equal(result.dom.suggestedPassiveBid, null, warning);
    assert.equal(result.dom.suggestedAggressiveBid, null, warning);
  }
});

test('DOM freshness is bound to the selected sample rather than a conflicting reference timestamp', () => {
  const result = applyPhase3DomGuidance(eligibleScreenCandidate(), validDom({
    samples: [{
      valid: true,
      capturedAt: '2026-07-14T00:59:00.000Z',
      bids: [{ price: 100, volume: 100 }],
      asks: [{ price: 100.5, volume: 80 }],
    }],
    referencePriceSources: { snapshotCapturedAt: '2026-07-14T01:00:09.000Z' },
  }), {
    asOfTime: '2026-07-14T01:00:10.000Z',
    maxAgeSeconds: 30,
  });

  assert.equal(result.executionEligible, false);
  assert.equal(result.dom.available, false);
  assert.deepEqual(result.dom.warnings, ['stale_dom']);
  assert.equal(result.dom.observedAt, '2026-07-14T00:59:00.000Z');
});

test('DOM rejects a non-finite spread percentage', () => {
  const dom = validDom({
    samples: [{
      valid: true,
      capturedAt: '2026-07-14T01:00:00.000Z',
      bids: [{ price: Number.MIN_VALUE, volume: 100 }],
      asks: [{ price: Number.MAX_VALUE, volume: 80 }],
    }],
  });
  const result = applyPhase3DomGuidance(eligibleScreenCandidate(), dom, {
    asOfTime: '2026-07-14T01:00:10.000Z',
    maxAgeSeconds: 30,
  });

  assert.equal(result.executionEligible, false);
  assert.equal(result.dom.available, false);
  assert.deepEqual(result.dom.warnings, ['invalid_dom_spread']);
});

test('valid DOM provides bounded guidance without changing Phase 3 qualification', () => {
  const base = eligibleScreenCandidate();
  const result = applyPhase3DomGuidance(base, validDom(), {
    asOfTime: '2026-07-14T01:00:10.000Z',
    maxAgeSeconds: 30,
  });

  assert.equal(result.technicalEligible, base.technicalEligible);
  assert.equal(result.phase3RankScore, base.phase3RankScore);
  assert.equal(result.executionEligible, true);
  assert.equal(result.dom.available, true);
  assert.equal(result.dom.source, 'shioaji');
  assert.equal(result.dom.ticker, '2330');
  assert.equal(result.dom.bidLevels.length, 1);
  assert.equal(result.dom.askLevels.length, 1);
  assert.ok(result.dom.suggestedPassiveBid <= result.dom.doNotChaseAbove);
  assert.ok(result.dom.suggestedAggressiveBid <= result.dom.doNotChaseAbove);
});

test('DOM cannot promote a technically rejected candidate', () => {
  const rejected = eligibleScreenCandidate({ technicalEligible: false, executionEligible: false });
  const result = applyPhase3DomGuidance(rejected, validDom(), {
    asOfTime: '2026-07-14T01:00:10.000Z',
    maxAgeSeconds: 30,
  });

  assert.equal(result.technicalEligible, false);
  assert.equal(result.executionEligible, false);
  assert.equal(result.dom.available, false);
  assert.equal(result.dom.warnings.includes('technical_ineligible'), true);
});

test('DOM cannot re-promote an execution-ineligible technical candidate', () => {
  const blocked = eligibleScreenCandidate({ executionEligible: false });
  const result = applyPhase3DomGuidance(blocked, validDom(), {
    asOfTime: '2026-07-14T01:00:10.000Z',
    maxAgeSeconds: 30,
  });

  assert.equal(result.technicalEligible, true);
  assert.equal(result.executionEligible, false);
  assert.equal(result.dom.available, false);
  assert.deepEqual(result.dom.warnings, ['preexisting_execution_ineligible']);
});

test('produces a row-level before and after difference report', () => {
  const before = {
    candidates: [{ ticker: 'A', decisionDate: '2026-06-30', softScore: 60 }],
    rejected: [{ ticker: 'B', decisionDate: '2026-06-30', eligible: false }],
  };
  const after = {
    candidates: [{
      ticker: 'B',
      decisionDate: '2026-06-30',
      technicalEligible: true,
      phase3RankScore: 62,
      marketContext: { available: true },
      foreignContext: { available: false },
    }],
    rejected: [{
      ticker: 'A',
      decisionDate: '2026-06-30',
      technicalEligible: false,
      phase3RankScore: 59,
      marketContext: { available: false },
      foreignContext: { available: true },
    }],
  };
  const report = comparePhase3ScreenResults(before, after);

  assert.deepEqual(report.addedCandidates.map((row) => row.ticker), ['B']);
  assert.deepEqual(report.removedCandidates.map((row) => row.ticker), ['A']);
  assert.equal(report.eligibilityChanged.length, 2);
  assert.equal(report.scoreChanged.length, 1);
  assert.equal(report.marketContextChanged.length, 1);
  assert.equal(report.foreignContextChanged.length, 1);
  for (const rows of Object.values(report)) {
    assert.equal(rows.every((row) => typeof row.reason === 'string' && row.reason.length > 0), true);
  }
});

test('difference report includes context-only changes when rank score is unchanged', () => {
  const before = {
    candidates: [{
      ticker: 'C',
      decisionDate: '2026-06-30',
      softScore: 50,
      marketContext: { available: false },
      foreignContext: { coverage3d: 0 },
    }],
  };
  const after = {
    candidates: [{
      ticker: 'C',
      decisionDate: '2026-06-30',
      phase3RankScore: 50,
      marketContext: { available: true },
      foreignContext: { coverage3d: 1 },
    }],
  };
  const report = comparePhase3ScreenResults(before, after);

  assert.equal(report.scoreChanged.length, 0);
  assert.equal(report.marketContextChanged.length, 1);
  assert.equal(report.foreignContextChanged.length, 1);
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
  assert.match(markdown, /Rank Score.*not.*probability/i);
  assert.doesNotMatch(markdown, /logistic|promotion/i);
  assert.equal((await readdir(root)).some((file) => file.endsWith('.tmp')), false);
});
