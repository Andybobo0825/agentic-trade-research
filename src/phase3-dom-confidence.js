import { createHash, randomUUID } from 'node:crypto';
import { mkdir, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';

import { getShioajiOrderBook } from './shioaji-market.js';

const CONFIG = {
  samples: 3,
  intervalMs: 5000,
  timeoutMs: 3000,
  levelWeights: Object.freeze([5, 4, 3, 2, 1]),
  activeEntryMinimumScore: 65,
};

export const PHASE3_DOM_CONFIG = Object.freeze(CONFIG);

export const PHASE3_DOM_INPUTS = Object.freeze([
  'ticker',
  'exchange',
  'samples',
  'intervalMs',
  'timeoutMs',
  'reportJson',
  'reportMarkdown',
]);

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function round(value, digits = 8) {
  const scale = 10 ** digits;
  return Math.round((value + Number.EPSILON) * scale) / scale;
}

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function sha256(value) {
  return createHash('sha256').update(stableJson(value)).digest('hex');
}

function boundedInteger(value, name, fallback, minimum, maximum) {
  if (value === undefined) return fallback;
  const number = Number(value);
  if (!Number.isInteger(number) || number < minimum || number > maximum) {
    throw new TypeError(`${name} must be an integer from ${minimum} to ${maximum}`);
  }
  return number;
}

export function assertPhase3DomArgs(args = {}) {
  const allowed = new Set(PHASE3_DOM_INPUTS);
  for (const key of Object.keys(args)) {
    if (!allowed.has(key)) throw new Error(`phase3-dom-confidence forbids ${key}`);
  }
  if (!String(args.ticker || '').trim()) throw new TypeError('ticker is required');
  boundedInteger(args.samples, 'samples', PHASE3_DOM_CONFIG.samples, 1, 5);
  boundedInteger(args.intervalMs, 'intervalMs', PHASE3_DOM_CONFIG.intervalMs, 0, 60_000);
  boundedInteger(args.timeoutMs, 'timeoutMs', PHASE3_DOM_CONFIG.timeoutMs, 1, 30_000);
  return args;
}

async function writeAtomic(file, content) {
  await mkdir(dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, content, { flag: 'wx' });
  await rename(temporary, file);
}

function isValidLevel(level) {
  return level
    && isFiniteNumber(level.price)
    && level.price > 0
    && isFiniteNumber(level.volume)
    && level.volume >= 0
    && (level.diffVolume === undefined
      || (isFiniteNumber(level.diffVolume)));
}

function invalid(error, capturedAt) {
  return { valid: false, error, capturedAt };
}

export function evaluateDomSnapshot(orderBook, { ticker, capturedAt } = {}) {
  if (!orderBook || String(orderBook.code) !== String(ticker)) {
    return invalid('ticker_mismatch', capturedAt);
  }
  if (orderBook.suspend === true) {
    return invalid('suspended', capturedAt);
  }
  if (!Array.isArray(orderBook.asks) || orderBook.asks.length === 0) {
    return invalid('missing_ask_depth', capturedAt);
  }
  if (!Array.isArray(orderBook.bids) || orderBook.bids.length === 0) {
    return invalid('missing_bid_depth', capturedAt);
  }

  const bids = orderBook.bids.slice(0, PHASE3_DOM_CONFIG.levelWeights.length);
  const asks = orderBook.asks.slice(0, PHASE3_DOM_CONFIG.levelWeights.length);
  if (!bids.every(isValidLevel)) return invalid('invalid_bid_level', capturedAt);
  if (!asks.every(isValidLevel)) return invalid('invalid_ask_level', capturedAt);
  if (bids[0].price >= asks[0].price) {
    return invalid('crossed_or_locked_book', capturedAt);
  }

  const weightedDepth = (levels) => levels.reduce(
    (sum, level, index) => sum + level.volume * PHASE3_DOM_CONFIG.levelWeights[index],
    0,
  );
  const weightedDiff = (levels) => levels.reduce(
    (sum, level, index) => sum + (level.diffVolume ?? 0) * PHASE3_DOM_CONFIG.levelWeights[index],
    0,
  );
  const weightedBidDepth = weightedDepth(bids);
  const weightedAskDepth = weightedDepth(asks);
  const totalDepth = weightedBidDepth + weightedAskDepth;
  const depthImbalance = totalDepth === 0
    ? 0
    : (weightedBidDepth - weightedAskDepth) / totalDepth;
  const weightedBidDiff = weightedDiff(bids);
  const weightedAskDiff = weightedDiff(asks);
  const totalChange = Math.abs(weightedBidDiff) + Math.abs(weightedAskDiff);
  const changePressure = totalChange === 0
    ? 0
    : (weightedBidDiff - weightedAskDiff) / totalChange;
  const pressure = clamp(0.8 * depthImbalance + 0.2 * changePressure, -1, 1);

  return {
    valid: true,
    capturedAt,
    code: String(orderBook.code),
    bids,
    asks,
    weightedBidDepth: round(weightedBidDepth),
    weightedAskDepth: round(weightedAskDepth),
    weightedBidDiff: round(weightedBidDiff),
    weightedAskDiff: round(weightedAskDiff),
    depthImbalance: round(depthImbalance),
    changePressure: round(changePressure),
    pressure: round(pressure),
  };
}

function confidenceLabel(score) {
  if (score >= 70) return 'strong_buy_pressure';
  if (score >= 58) return 'buy_pressure';
  if (score > 42) return 'balanced';
  if (score > 30) return 'sell_pressure';
  return 'strong_sell_pressure';
}

function confidenceAdjustment(score) {
  if (score >= 70) return 8;
  if (score >= 58) return 4;
  if (score > 42) return 0;
  if (score > 30) return -2;
  return -5;
}

function reliability(validSampleCount) {
  if (validSampleCount >= 3) return 'high';
  if (validSampleCount === 2) return 'medium';
  if (validSampleCount === 1) return 'low';
  return 'unavailable';
}

function indexOfStrongestWall(levels) {
  let strongestIndex = 0;
  let strongestWeightedVolume = -Infinity;
  levels.forEach((level, index) => {
    const weightedVolume = level.volume * PHASE3_DOM_CONFIG.levelWeights[index];
    if (weightedVolume > strongestWeightedVolume) {
      strongestWeightedVolume = weightedVolume;
      strongestIndex = index;
    }
  });
  return strongestIndex;
}

function deriveReferencePrices(snapshot, score) {
  const bidWallLevelIndex = indexOfStrongestWall(snapshot.bids);
  const askWallLevelIndex = indexOfStrongestWall(snapshot.asks);
  const takeProfitLevelIndex = Math.max(0, askWallLevelIndex - 1);
  const hasLowerVisibleBid = bidWallLevelIndex < snapshot.bids.length - 1;
  const stopLossLevelIndex = hasLowerVisibleBid
    ? bidWallLevelIndex + 1
    : snapshot.bids.length - 1;
  const activeEntryOnAsk = score >= PHASE3_DOM_CONFIG.activeEntryMinimumScore;

  return {
    referencePrices: {
      activeEntryLimit: activeEntryOnAsk ? snapshot.asks[0].price : snapshot.bids[0].price,
      patientEntryPrice: snapshot.bids[bidWallLevelIndex].price,
      takeProfitPrice: snapshot.asks[takeProfitLevelIndex].price,
      stopLossPrice: snapshot.bids[stopLossLevelIndex].price,
      stopReliability: hasLowerVisibleBid ? 'normal' : 'low',
    },
    referencePriceSources: {
      activeEntrySide: activeEntryOnAsk ? 'ask' : 'bid',
      activeEntryLevelIndex: 0,
      bidWallLevelIndex,
      bidWallVolume: snapshot.bids[bidWallLevelIndex].volume,
      askWallLevelIndex,
      askWallVolume: snapshot.asks[askWallLevelIndex].volume,
      takeProfitLevelIndex,
      stopLossLevelIndex,
      snapshotCapturedAt: snapshot.capturedAt,
    },
  };
}

export function evaluateDomConfidence(samples) {
  const validSamples = (Array.isArray(samples) ? samples : [])
    .filter((sample) => sample?.valid === true && isFiniteNumber(sample.pressure));
  const validSampleCount = validSamples.length;
  if (validSampleCount === 0) {
    return {
      validSampleCount: 0,
      meanPressure: null,
      persistence: 0,
      domConfidenceScore: null,
      domConfidenceAdjustment: 0,
      pressureLabel: 'unavailable',
      reliability: 'unavailable',
    };
  }

  const meanPressure = validSamples.reduce((sum, sample) => sum + sample.pressure, 0)
    / validSampleCount;
  const persistence = validSampleCount >= 2 && validSamples.every((sample) => sample.pressure > 0.05)
    ? 1
    : validSampleCount >= 2 && validSamples.every((sample) => sample.pressure < -0.05)
      ? -1
      : 0;
  const domConfidenceScore = clamp(Math.round(50 + 40 * meanPressure + 10 * persistence), 0, 100);

  const latestValidSnapshot = validSamples.at(-1);

  return {
    validSampleCount,
    meanPressure: round(meanPressure),
    persistence,
    domConfidenceScore,
    domConfidenceAdjustment: confidenceAdjustment(domConfidenceScore),
    pressureLabel: confidenceLabel(domConfidenceScore),
    reliability: reliability(validSampleCount),
    ...deriveReferencePrices(latestValidSnapshot, domConfidenceScore),
  };
}

function unavailableReferencePrices() {
  return {
    activeEntryLimit: null,
    patientEntryPrice: null,
    takeProfitPrice: null,
    stopLossPrice: null,
    stopReliability: 'unavailable',
  };
}

function defaultSleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export async function runPhase3DomConfidence(args = {}, dependencies = {}) {
  assertPhase3DomArgs(args);
  const ticker = String(args.ticker).trim();
  const exchange = String(args.exchange || 'TSE').trim().toUpperCase();
  const requestedSampleCount = boundedInteger(
    args.samples,
    'samples',
    PHASE3_DOM_CONFIG.samples,
    1,
    5,
  );
  const intervalMs = boundedInteger(
    args.intervalMs,
    'intervalMs',
    PHASE3_DOM_CONFIG.intervalMs,
    0,
    60_000,
  );
  const timeoutMs = boundedInteger(
    args.timeoutMs,
    'timeoutMs',
    PHASE3_DOM_CONFIG.timeoutMs,
    1,
    30_000,
  );
  const getOrderBook = dependencies.getOrderBook || getShioajiOrderBook;
  const sleep = dependencies.sleep || defaultSleep;
  const now = dependencies.now || (() => new Date());
  const samples = [];

  for (let index = 0; index < requestedSampleCount; index += 1) {
    try {
      const response = await getOrderBook({ ticker, exchange, timeoutMs });
      if (response?.readOnly !== true) throw new Error('Shioaji response is not read-only');
      const capturedAt = now().toISOString();
      samples.push(evaluateDomSnapshot(response.data, { ticker, capturedAt }));
    } catch (error) {
      samples.push({
        valid: false,
        error: 'order_book_error',
        message: error instanceof Error ? error.message : String(error),
        capturedAt: now().toISOString(),
      });
    }
    if (index < requestedSampleCount - 1) await sleep(intervalMs);
  }

  const confidence = evaluateDomConfidence(samples);
  const core = {
    strategy: 'phase3_stability',
    command: 'phase3-dom-confidence',
    overlay: 'post_research_dom_confidence',
    executionMode: 'read_only',
    readOnly: true,
    ticker,
    exchange,
    requestedSampleCount,
    intervalMs,
    timeoutMs,
    samples,
    ...confidence,
    referencePrices: confidence.referencePrices || unavailableReferencePrices(),
    referencePriceSources: confidence.referencePriceSources || null,
  };
  const result = { ...core, resultHash: sha256(core) };

  if (args.reportJson) await writeAtomic(args.reportJson, `${JSON.stringify(result, null, 2)}\n`);
  if (args.reportMarkdown) {
    await writeAtomic(args.reportMarkdown, renderPhase3DomConfidenceMarkdown(result));
  }
  return result;
}

function printablePrice(value) {
  return value === null || value === undefined ? 'unavailable' : value;
}

export function renderPhase3DomConfidenceMarkdown(result) {
  const prices = result.referencePrices || unavailableReferencePrices();
  const lines = [
    '# Phase 3 DOM Confidence',
    '',
    `- Strategy: ${result.strategy}`,
    `- Ticker: ${result.ticker}`,
    `- Execution mode: ${result.executionMode}`,
    `- Read only: ${result.readOnly}`,
    `- Valid samples: ${result.validSampleCount}/${result.requestedSampleCount}`,
    `- Reliability: ${result.reliability}`,
    `- DOM confidence score: ${result.domConfidenceScore ?? 'unavailable'}`,
    `- DOM confidence adjustment: ${result.domConfidenceAdjustment}`,
    `- Pressure: ${result.pressureLabel}`,
    '',
    '## Reference prices',
    '',
    `- Active entry limit: ${printablePrice(prices.activeEntryLimit)}`,
    `- Patient entry price: ${printablePrice(prices.patientEntryPrice)}`,
    `- Take-profit price: ${printablePrice(prices.takeProfitPrice)}`,
    `- Stop-loss price: ${printablePrice(prices.stopLossPrice)}`,
    `- Stop reliability: ${prices.stopReliability}`,
    '',
    'These are read-only visible-book references for manual decision-making, not orders.',
    '',
    `Result hash: ${result.resultHash}`,
  ];
  return `${lines.join('\n')}\n`;
}
