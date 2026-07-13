function deepFreeze(value) {
  Object.freeze(value);
  for (const child of Object.values(value)) {
    if (child && typeof child === 'object' && !Object.isFrozen(child)) deepFreeze(child);
  }
  return value;
}

export const PHASE3_FILTER_CONFIG = deepFreeze({
  minimumAverageTurnover: 20_000_000,
  minimumHma9SlopePct: 0,
  minimumHma20SlopePct: 0,
  minimumCloseToHma9Pct: 0,
  maximumHmaDistancePct: 6,
  maximumMomentum5Pct: 18,
  maximumClosePosition: 0.72,
});

const REQUIRED_FEATURES = Object.freeze([
  'hma9SlopePct',
  'hma20SlopePct',
  'closeToHma9Pct',
  'averageTurnover',
  'momentum5Pct',
  'closePosition',
]);

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function round(value, digits = 8) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function featureMap(candidate) {
  const names = candidate?.featureNames;
  const values = candidate?.features;
  if (!Array.isArray(names) || !Array.isArray(values) || names.length !== values.length) {
    return new Map();
  }
  return new Map(names.map((name, index) => {
    const value = values[index];
    return [String(name), typeof value === 'number' && Number.isFinite(value) ? value : Number.NaN];
  }));
}

function optionalFeature(features, name, fallback = 0) {
  const value = features.get(name);
  return Number.isFinite(value) ? value : fallback;
}

function scoreAdjustments(features) {
  return {
    volume: round(clamp((optionalFeature(features, 'volumeRatio', 1) - 1) * 5, -5, 5)),
    relativeMomentum: round(clamp(optionalFeature(features, 'relativeMomentum3Pct') * 0.75, -5, 5)),
    marketBreadth: round(clamp((optionalFeature(features, 'marketBreadth1d', 0.5) - 0.5) * 10, -5, 5)),
    foreignStreak: round(clamp(optionalFeature(features, 'foreignBuyStreak') * 1.5, 0, 6)),
    foreignIntensity: round(clamp(optionalFeature(features, 'foreignThreeDayIntensity') * 20, -4, 4)),
  };
}

export function evaluatePhase3Filter(candidate, config = PHASE3_FILTER_CONFIG) {
  const features = featureMap(candidate);
  const reasons = [];
  for (const name of REQUIRED_FEATURES) {
    if (!Number.isFinite(features.get(name))) reasons.push(`missing_${name}`);
  }

  const hma9SlopePct = features.get('hma9SlopePct');
  const hma20SlopePct = features.get('hma20SlopePct');
  const closeToHma9Pct = features.get('closeToHma9Pct');
  const averageTurnover = features.get('averageTurnover');
  const momentum5Pct = features.get('momentum5Pct');
  const closePosition = features.get('closePosition');

  if (Number.isFinite(hma9SlopePct) && !(hma9SlopePct > config.minimumHma9SlopePct)) {
    reasons.push('hma9_not_rising');
  }
  if (Number.isFinite(hma20SlopePct) && hma20SlopePct < config.minimumHma20SlopePct) {
    reasons.push('hma20_regime_not_bullish');
  }
  if (Number.isFinite(closeToHma9Pct) && closeToHma9Pct < config.minimumCloseToHma9Pct) {
    reasons.push('close_below_hma9');
  }
  if (Number.isFinite(closeToHma9Pct) && closeToHma9Pct > config.maximumHmaDistancePct) {
    reasons.push('close_too_far_above_hma9');
  }
  if (Number.isFinite(averageTurnover)
    && averageTurnover < config.minimumAverageTurnover) {
    reasons.push('average_turnover_below_minimum');
  }
  if (Number.isFinite(momentum5Pct) && momentum5Pct > config.maximumMomentum5Pct) {
    reasons.push('momentum_5d_above_maximum');
  }
  if (Number.isFinite(closePosition) && closePosition > config.maximumClosePosition) {
    reasons.push('close_position_above_maximum');
  }

  const softAdjustments = scoreAdjustments(features);
  const softScore = round(clamp(
    50 + Object.values(softAdjustments).reduce((sum, value) => sum + value, 0),
    0,
    100,
  ));
  return {
    eligible: reasons.length === 0,
    reasons,
    diagnostics: {
      hma9SlopePct: Number.isFinite(hma9SlopePct) ? hma9SlopePct : null,
      hma20SlopePct: Number.isFinite(hma20SlopePct) ? hma20SlopePct : null,
      closeToHma9Pct: Number.isFinite(closeToHma9Pct) ? closeToHma9Pct : null,
      averageTurnover,
      momentum5Pct: Number.isFinite(momentum5Pct) ? momentum5Pct : null,
      closePosition: Number.isFinite(closePosition) ? closePosition : null,
    },
    softScore,
    softAdjustments,
  };
}
