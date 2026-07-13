import test from 'node:test';
import assert from 'node:assert/strict';

import {
  PHASE3_FILTER_CONFIG,
  evaluatePhase3Filter,
} from '../src/phase3-filter.js';

const BASE_FEATURES = Object.freeze({
  hma9SlopePct: 0.8,
  hma20SlopePct: 0.2,
  closeToHma9Pct: 2,
  averageTurnoverLog10: Math.log10(50_000_000),
  momentum5Pct: 8,
  closePosition: 0.6,
  volumeRatio: 1.4,
  relativeMomentum3Pct: 2,
  marketBreadth1d: 0.6,
  foreignBuyStreak: 3,
  foreignThreeDayIntensity: 0.08,
});

function candidateFromValues(values) {
  return {
    ticker: '2330',
    decisionDate: '2026-06-30',
    featureNames: Object.keys(values),
    features: Object.values(values),
  };
}

function candidate(overrides = {}) {
  return candidateFromValues({ ...BASE_FEATURES, ...overrides });
}

test('freezes the approved Phase 3 hard-gate thresholds', () => {
  assert.deepEqual(PHASE3_FILTER_CONFIG, {
    minimumAverageTurnover: 20_000_000,
    minimumHma9SlopePct: 0,
    minimumHma20SlopePct: 0,
    minimumCloseToHma9Pct: 0,
    maximumHmaDistancePct: 6,
    maximumMomentum5Pct: 18,
    maximumClosePosition: 0.72,
  });
  assert.equal(Object.isFrozen(PHASE3_FILTER_CONFIG), true);
});

test('accepts an observation that passes every approved technical gate', () => {
  const result = evaluatePhase3Filter(candidate());
  assert.equal(result.eligible, true);
  assert.deepEqual(result.reasons, []);
  assert.equal(Number.isFinite(result.softScore), true);
  assert.equal(result.diagnostics.averageTurnover, 50_000_000);
});

test('fails each approved technical boundary with stable reason codes', () => {
  const cases = [
    ['hma9SlopePct', 0, 'hma9_not_rising'],
    ['hma20SlopePct', -0.001, 'hma20_regime_not_bullish'],
    ['closeToHma9Pct', -0.001, 'close_below_hma9'],
    ['closeToHma9Pct', 6.001, 'close_too_far_above_hma9'],
    ['averageTurnoverLog10', Math.log10(19_999_999), 'average_turnover_below_minimum'],
    ['momentum5Pct', 18.001, 'momentum_5d_above_maximum'],
    ['closePosition', 0.721, 'close_position_above_maximum'],
  ];

  for (const [name, value, reason] of cases) {
    const result = evaluatePhase3Filter(candidate({ [name]: value }));
    assert.equal(result.eligible, false, name);
    assert.deepEqual(result.reasons, [reason], name);
  }
});

test('accepts exact inclusive upper boundaries', () => {
  const result = evaluatePhase3Filter(candidate({
    averageTurnoverLog10: Math.log10(20_000_000),
    hma20SlopePct: 0,
    closeToHma9Pct: 6,
    momentum5Pct: 18,
    closePosition: 0.72,
  }));
  assert.equal(result.eligible, true);
  assert.deepEqual(result.reasons, []);
});

test('fails closed when a required decision-time feature is missing', () => {
  const row = candidate();
  const index = row.featureNames.indexOf('momentum5Pct');
  row.featureNames.splice(index, 1);
  row.features.splice(index, 1);
  const result = evaluatePhase3Filter(row);
  assert.equal(result.eligible, false);
  assert.deepEqual(result.reasons, ['missing_momentum5Pct']);
});

test('keeps optional context soft and unable to override a hard failure', () => {
  const strongContext = candidate({
    hma9SlopePct: 0,
    volumeRatio: 10,
    relativeMomentum3Pct: 20,
    marketBreadth1d: 1,
    foreignBuyStreak: 20,
    foreignThreeDayIntensity: 1,
  });
  const result = evaluatePhase3Filter(strongContext);
  assert.equal(result.eligible, false);
  assert.deepEqual(result.reasons, ['hma9_not_rising']);
  assert.ok(result.softScore <= 100);
  assert.ok(result.softScore >= 0);
});

test('uses neutral deterministic adjustments when optional context is absent', () => {
  const requiredOnly = Object.fromEntries(Object.entries(BASE_FEATURES).filter(([name]) =>
    !['volumeRatio', 'relativeMomentum3Pct', 'marketBreadth1d',
      'foreignBuyStreak', 'foreignThreeDayIntensity'].includes(name)));
  const first = evaluatePhase3Filter(candidateFromValues(requiredOnly));
  const second = evaluatePhase3Filter(candidateFromValues(requiredOnly));
  assert.deepEqual(first, second);
  assert.equal(first.eligible, true);
});
