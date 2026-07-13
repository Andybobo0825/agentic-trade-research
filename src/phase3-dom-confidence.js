const CONFIG = {
  samples: 3,
  intervalMs: 5000,
  timeoutMs: 3000,
  levelWeights: Object.freeze([5, 4, 3, 2, 1]),
  activeEntryMinimumScore: 65,
};

export const PHASE3_DOM_CONFIG = Object.freeze(CONFIG);

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

  return {
    validSampleCount,
    meanPressure: round(meanPressure),
    persistence,
    domConfidenceScore,
    domConfidenceAdjustment: confidenceAdjustment(domConfidenceScore),
    pressureLabel: confidenceLabel(domConfidenceScore),
    reliability: reliability(validSampleCount),
  };
}
