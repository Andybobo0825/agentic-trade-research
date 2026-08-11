import test from 'node:test';
import assert from 'node:assert/strict';

import {
  PHASE3_DOM_CONFIG,
  assertPhase3DomArgs,
  evaluateDomConfidence,
  evaluateDomSnapshot,
  renderPhase3DomConfidenceMarkdown,
  runPhase3DomConfidence,
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
    [book({ bids: [{ price: 100, volume: 0, diffVolume: 0 }] }), 'missing_positive_bid_depth'],
    [book({ asks: [{ price: 100.5, volume: 0, diffVolume: 0 }] }), 'missing_positive_ask_depth'],
  ];

  for (const [input, reason] of cases) {
    const result = evaluated(input);
    assert.equal(result.valid, false, reason);
    assert.equal(result.error, reason);
  }
});

test('ignores zero-volume placeholders before deriving visible-book prices', () => {
  const result = evaluated(book({
    bids: [
      { price: 100, volume: 0, diffVolume: 0 },
      { price: 99.5, volume: 50, diffVolume: 1 },
    ],
    asks: [
      { price: 100.5, volume: 0, diffVolume: 0 },
      { price: 101, volume: 40, diffVolume: 1 },
    ],
  }));

  assert.equal(result.valid, true);
  assert.deepEqual(result.bids.map((level) => level.price), [99.5]);
  assert.deepEqual(result.asks.map((level) => level.price), [101]);
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

test('always derives all reference prices from the latest valid DOM snapshot', () => {
  const wallBook = book({
    bids: [
      { price: 100, volume: 10, diffVolume: 5 },
      { price: 99.5, volume: 100, diffVolume: 10 },
      { price: 99, volume: 5, diffVolume: 0 },
    ],
    asks: [
      { price: 100.5, volume: 10, diffVolume: -5 },
      { price: 101, volume: 20, diffVolume: 0 },
      { price: 101.5, volume: 100, diffVolume: 0 },
    ],
  });
  const result = evaluateDomConfidence([
    evaluated(wallBook, '2026-07-13T02:00:00.000Z'),
    evaluated(wallBook, '2026-07-13T02:00:05.000Z'),
    evaluated(wallBook, '2026-07-13T02:00:10.000Z'),
  ]);

  assert.deepEqual(result.referencePrices, {
    activeEntryLimit: 100.5,
    patientEntryPrice: 99.5,
    takeProfitPrice: 101,
    stopLossPrice: 99,
    stopReliability: 'normal',
  });
  assert.deepEqual(result.referencePriceSources, {
    activeEntrySide: 'ask',
    activeEntryLevelIndex: 0,
    bidWallLevelIndex: 1,
    bidWallVolume: 100,
    askWallLevelIndex: 2,
    askWallVolume: 100,
    takeProfitLevelIndex: 1,
    stopLossLevelIndex: 2,
    snapshotCapturedAt: '2026-07-13T02:00:10.000Z',
  });
});

test('weak DOM uses best bid for active entry without withholding other prices', () => {
  const result = evaluateDomConfidence([
    evaluated(bearishBook()),
    evaluated(bearishBook()),
    evaluated(bearishBook()),
  ]);

  assert.equal(result.domConfidenceScore < PHASE3_DOM_CONFIG.activeEntryMinimumScore, true);
  assert.deepEqual(result.referencePrices, {
    activeEntryLimit: 100,
    patientEntryPrice: 100,
    takeProfitPrice: 100.5,
    stopLossPrice: 99.5,
    stopReliability: 'normal',
  });
});

test('uses lowest visible support with low stop reliability instead of inventing a price', () => {
  const finalBook = book({
    bids: [
      { price: 100, volume: 10, diffVolume: 0 },
      { price: 99.5, volume: 20, diffVolume: 0 },
      { price: 99, volume: 100, diffVolume: 0 },
    ],
  });
  const result = evaluateDomConfidence([evaluated(finalBook)]);

  assert.equal(result.referencePrices.patientEntryPrice, 99);
  assert.equal(result.referencePrices.stopLossPrice, 99);
  assert.equal(result.referencePrices.stopReliability, 'low');
  assert.equal(result.referencePriceSources.bidWallLevelIndex, 2);
  assert.equal(result.referencePriceSources.stopLossLevelIndex, 2);
});

test('samples DOM three times with two fixed waits and keeps read-only audit rows', async () => {
  const orderCalls = [];
  const waits = [];
  const snapshots = [book(), book(), book()];
  let timeIndex = 0;
  let elapsedMs = 0;
  const times = [
    '2026-07-13T02:00:00.000Z',
    '2026-07-13T02:00:05.000Z',
    '2026-07-13T02:00:10.000Z',
  ];

  const result = await runPhase3DomConfidence({ ticker: '2330' }, {
    getOrderBook: async (args) => {
      orderCalls.push(args);
      return { readOnly: true, data: snapshots[orderCalls.length - 1] };
    },
    sleep: async (milliseconds) => {
      waits.push(milliseconds);
      elapsedMs += milliseconds;
    },
    clockMs: () => elapsedMs,
    now: () => new Date(times[timeIndex++]),
  });

  assert.equal(orderCalls.length, 3);
  assert.deepEqual(waits, [5000, 5000]);
  assert.equal(result.requestedSampleCount, 3);
  assert.equal(result.validSampleCount, 3);
  assert.equal(result.readOnly, true);
  assert.equal(result.executionMode, 'read_only');
  assert.equal(result.source, 'shioaji');
  assert.equal(result.endpoint, '/api/v1/stream/data/bidask_stk');
  assert.equal(result.interpretation, 'active_entry_supported');
  assert.deepEqual(result.risks, [
    'visible_depth_can_change_before_manual_entry',
    'reference_prices_are_not_guaranteed_fills',
  ]);
  assert.equal(result.samples.length, 3);
  assert.equal(result.resultHash.length, 64);
  assert.deepEqual(result.referencePrices, {
    activeEntryLimit: 100.5,
    patientEntryPrice: 100,
    takeProfitPrice: 100.5,
    stopLossPrice: 99.5,
    stopReliability: 'normal',
  });
});

test('anchors sample starts near 0, 5, and 10 seconds despite slow reads', async () => {
  let elapsedMs = 0;
  const starts = [];
  const waits = [];
  const result = await runPhase3DomConfidence({ ticker: '2330' }, {
    getOrderBook: async () => {
      starts.push(elapsedMs);
      elapsedMs += 3000;
      return { readOnly: true, data: book() };
    },
    sleep: async (milliseconds) => {
      waits.push(milliseconds);
      elapsedMs += milliseconds;
    },
    clockMs: () => elapsedMs,
    now: () => new Date(1_700_000_000_000 + elapsedMs),
  });

  assert.deepEqual(starts, [0, 5000, 10000]);
  assert.deepEqual(waits, [2000, 2000]);
  assert.equal(result.validSampleCount, 3);
});

test('keeps two valid samples when one Shioaji read times out', async () => {
  let call = 0;
  const result = await runPhase3DomConfidence({ ticker: '2330' }, {
    getOrderBook: async () => {
      call += 1;
      if (call === 2) throw new Error('stream timeout');
      return { readOnly: true, data: book() };
    },
    sleep: async () => undefined,
    now: () => new Date('2026-07-13T02:00:00.000Z'),
  });

  assert.equal(result.validSampleCount, 2);
  assert.equal(result.reliability, 'medium');
  assert.equal(result.samples[1].valid, false);
  assert.equal(result.samples[1].error, 'order_book_error');
  assert.match(result.samples[1].message, /timeout/);
  assert.notEqual(result.referencePrices.activeEntryLimit, null);
});

test('returns unavailable with null prices when every DOM sample fails', async () => {
  const result = await runPhase3DomConfidence({ ticker: '2330' }, {
    getOrderBook: async () => { throw new Error('offline'); },
    sleep: async () => undefined,
    now: () => new Date('2026-07-13T02:00:00.000Z'),
  });

  assert.equal(result.domConfidenceScore, null);
  assert.equal(result.pressureLabel, 'unavailable');
  assert.equal(result.interpretation, 'unavailable');
  assert.equal(result.risks.includes('no_valid_dom_sample'), true);
  assert.deepEqual(result.referencePrices, {
    activeEntryLimit: null,
    patientEntryPrice: null,
    takeProfitPrice: null,
    stopLossPrice: null,
    stopReliability: 'unavailable',
  });
  assert.equal(result.samples.every((sample) => sample.error === 'order_book_error'), true);
});

test('rejects unknown or order-capable arguments before reading Shioaji', async () => {
  let calls = 0;
  const dependencies = {
    getOrderBook: async () => {
      calls += 1;
      return { readOnly: true, data: book() };
    },
  };

  for (const args of [
    { ticker: '2330', live: true },
    { ticker: '2330', order: 'buy' },
    { ticker: '2330', quantity: 1000 },
    { ticker: '2330', exchange: 'TAIFEX' },
    { ticker: '2330', samples: true },
    { ticker: '2330', intervalMs: false },
    { ticker: '2330', timeoutMs: true },
  ]) {
    await assert.rejects(
      runPhase3DomConfidence(args, dependencies),
      /forbids|exchange must|samples must|intervalMs must|timeoutMs must/,
    );
  }
  assert.equal(calls, 0);
  assert.throws(() => assertPhase3DomArgs({}), /ticker is required/);
  assert.throws(() => assertPhase3DomArgs({ ticker: 2330 }), /ticker must be a string/);
  assert.throws(
    () => assertPhase3DomArgs({ ticker: '2330', reportJson: true }),
    /reportJson must be a string/,
  );
});

test('renders every mandatory DOM price and the read-only status', async () => {
  const result = await runPhase3DomConfidence({ ticker: '2330' }, {
    getOrderBook: async () => ({ readOnly: true, data: book() }),
    sleep: async () => undefined,
    now: () => new Date('2026-07-13T02:00:00.000Z'),
  });
  const markdown = renderPhase3DomConfidenceMarkdown(result);

  assert.match(markdown, /Read only: true/);
  assert.match(markdown, /Source: shioaji/);
  assert.match(markdown, /Endpoint: \/api\/v1\/stream\/data\/bidask_stk/);
  assert.match(markdown, /Interpretation: active_entry_supported/);
  assert.match(markdown, /visible_depth_can_change_before_manual_entry/);
  assert.match(markdown, /Active entry limit: 100\.5/);
  assert.match(markdown, /Patient entry price: 100/);
  assert.match(markdown, /Take-profit price: 100\.5/);
  assert.match(markdown, /Stop-loss price: 99\.5/);
});
