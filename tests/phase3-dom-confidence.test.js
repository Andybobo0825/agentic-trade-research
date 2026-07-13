import test from 'node:test';
import assert from 'node:assert/strict';

import {
  PHASE3_DOM_CONFIG,
  evaluateDomConfidence,
  evaluateDomSnapshot,
} from '../src/phase3-dom-confidence.js';

function book(overrides = {}) {
  return {
    code: '2330',
    date: '2026-07-13',
    time: '10:00:00',
    suspend: false,
    bids: [
      { price: 100, volume: 100, diffVolume: 10 },
      { price: 99.5, volume: 80, diffVolume: 5 },
    ],
    asks: [
      { price: 100.5, volume: 20, diffVolume: -5 },
      { price: 101, volume: 10, diffVolume: 0 },
    ],
    ...overrides,
  };
}

function bearishBook() {
  return book({
    bids: [
      { price: 100, volume: 20, diffVolume: -5 },
      { price: 99.5, volume: 10, diffVolume: 0 },
    ],
    asks: [
      { price: 100.5, volume: 100, diffVolume: 10 },
      { price: 101, volume: 80, diffVolume: 5 },
    ],
  });
}

function evaluated(orderBook, capturedAt = '2026-07-13T02:00:00.000Z') {
  return evaluateDomSnapshot(orderBook, { ticker: '2330', capturedAt });
}

test('freezes the approved three-sample DOM defaults', () => {
  assert.deepEqual(PHASE3_DOM_CONFIG, {
    samples: 3,
    intervalMs: 5000,
    timeoutMs: 3000,
    levelWeights: [5, 4, 3, 2, 1],
    activeEntryMinimumScore: 65,
  });
  assert.equal(Object.isFrozen(PHASE3_DOM_CONFIG), true);
  assert.equal(Object.isFrozen(PHASE3_DOM_CONFIG.levelWeights), true);
});

test('weights near DOM levels and calculates bounded buy pressure', () => {
  const result = evaluated(book());

  assert.equal(result.valid, true);
  assert.equal(result.weightedBidDepth, 820);
  assert.equal(result.weightedAskDepth, 140);
  assert.equal(result.depthImbalance, 0.70833333);
  assert.equal(result.changePressure, 1);
  assert.equal(result.pressure, 0.76666667);
});

test('fails closed on malformed DOM snapshots with stable reasons', () => {
  const cases = [
    [book({ code: '2317' }), 'ticker_mismatch'],
    [book({ suspend: true }), 'suspended'],
    [book({ asks: [] }), 'missing_ask_depth'],
    [book({ bids: [] }), 'missing_bid_depth'],
    [book({ bids: [{ price: 101, volume: 10, diffVolume: 0 }] }), 'crossed_or_locked_book'],
    [book({ bids: [{ price: 100, volume: -1, diffVolume: 0 }] }), 'invalid_bid_level'],
    [book({ asks: [{ price: '100.5', volume: 10, diffVolume: 0 }] }), 'invalid_ask_level'],
  ];

  for (const [input, reason] of cases) {
    const result = evaluated(input);
    assert.equal(result.valid, false, reason);
    assert.equal(result.error, reason);
  }
});

test('scores persistent bullish, bearish, and mixed DOM pressure', () => {
  const bullish = evaluateDomConfidence([
    evaluated(book(), '2026-07-13T02:00:00.000Z'),
    evaluated(book(), '2026-07-13T02:00:05.000Z'),
    evaluated(book(), '2026-07-13T02:00:10.000Z'),
  ]);
  assert.equal(bullish.pressureLabel, 'strong_buy_pressure');
  assert.equal(bullish.persistence, 1);
  assert.equal(bullish.domConfidenceScore, 91);
  assert.equal(bullish.domConfidenceAdjustment, 8);
  assert.equal(bullish.reliability, 'high');

  const bearish = evaluateDomConfidence([
    evaluated(bearishBook()),
    evaluated(bearishBook()),
    evaluated(bearishBook()),
  ]);
  assert.equal(bearish.pressureLabel, 'strong_sell_pressure');
  assert.equal(bearish.persistence, -1);
  assert.equal(bearish.domConfidenceScore, 9);
  assert.equal(bearish.domConfidenceAdjustment, -5);

  const mixed = evaluateDomConfidence([
    evaluated(book()),
    evaluated(bearishBook()),
    evaluated(book({
      bids: [{ price: 100, volume: 10, diffVolume: 0 }],
      asks: [{ price: 100.5, volume: 10, diffVolume: 0 }],
    })),
  ]);
  assert.equal(mixed.pressureLabel, 'balanced');
  assert.equal(mixed.persistence, 0);
  assert.equal(mixed.domConfidenceScore, 50);
  assert.equal(mixed.domConfidenceAdjustment, 0);
});

test('reports low reliability for one valid sample and unavailable for none', () => {
  const low = evaluateDomConfidence([evaluated(book())]);
  assert.equal(low.reliability, 'low');
  assert.equal(Number.isFinite(low.domConfidenceScore), true);

  const unavailable = evaluateDomConfidence([
    { valid: false, error: 'timeout' },
    { valid: false, error: 'timeout' },
  ]);
  assert.deepEqual(unavailable, {
    validSampleCount: 0,
    meanPressure: null,
    persistence: 0,
    domConfidenceScore: null,
    domConfidenceAdjustment: 0,
    pressureLabel: 'unavailable',
    reliability: 'unavailable',
  });
});
