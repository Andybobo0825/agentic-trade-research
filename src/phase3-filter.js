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

const SOFT_FEATURES = Object.freeze([
  'volumeRatio',
  'relativeMomentum3Pct',
  'marketBreadth1d',
  'foreignBuyStreak',
  'foreignThreeDayIntensity',
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

function adjustment(features, name, calculate) {
  const value = features.get(name);
  return Number.isFinite(value) ? round(calculate(value)) : 0;
}

function scoreAdjustments(features) {
  return {
    volume: adjustment(features, 'volumeRatio', (value) => clamp((value - 1) * 5, -5, 5)),
    relativeMomentum: adjustment(
      features,
      'relativeMomentum3Pct',
      (value) => clamp(value * 0.75, -5, 5),
    ),
    marketBreadth: adjustment(
      features,
      'marketBreadth1d',
      (value) => clamp((value - 0.5) * 10, -5, 5),
    ),
    foreignStreak: adjustment(
      features,
      'foreignBuyStreak',
      (value) => clamp(value * 1.5, 0, 6),
    ),
    foreignIntensity: adjustment(
      features,
      'foreignThreeDayIntensity',
      (value) => clamp(value * 20, -4, 4),
    ),
  };
}

function softFeatureCoverage(features) {
  const missing = SOFT_FEATURES.filter((name) => !Number.isFinite(features.get(name)));
  const available = SOFT_FEATURES.length - missing.length;
  return {
    available,
    expected: SOFT_FEATURES.length,
    coveragePct: round(available / SOFT_FEATURES.length * 100),
    missing,
  };
}

function volumeConfirmation(features) {
  const ratio = features.get('volumeRatio');
  if (!Number.isFinite(ratio)) {
    return { volumeConfirmed: false, volumeConfirmationLevel: 'unavailable' };
  }
  if (ratio < 0.8) return { volumeConfirmed: false, volumeConfirmationLevel: 'weak' };
  if (ratio < 1) return { volumeConfirmed: false, volumeConfirmationLevel: 'below_average' };
  if (ratio < 1.5) return { volumeConfirmed: true, volumeConfirmationLevel: 'confirmed' };
  return { volumeConfirmed: true, volumeConfirmationLevel: 'strong' };
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
  if (Number.isFinite(averageTurnover) && averageTurnover < config.minimumAverageTurnover) {
    reasons.push('average_turnover_below_minimum');
  }
  if (Number.isFinite(momentum5Pct) && momentum5Pct > config.maximumMomentum5Pct) {
    reasons.push('momentum_5d_above_maximum');
  }
  if (Number.isFinite(closePosition) && closePosition > config.maximumClosePosition) {
    reasons.push('close_position_above_maximum');
  }

  const adjustments = scoreAdjustments(features);
  const technicalEligible = reasons.length === 0;
  return {
    technicalEligible,
    executionEligible: technicalEligible,
    reasons,
    warnings: [],
    hardGateDiagnostics: {
      hma9SlopePct: Number.isFinite(hma9SlopePct) ? hma9SlopePct : null,
      hma20SlopePct: Number.isFinite(hma20SlopePct) ? hma20SlopePct : null,
      closeToHma9Pct: Number.isFinite(closeToHma9Pct) ? closeToHma9Pct : null,
      averageTurnover: Number.isFinite(averageTurnover) ? averageTurnover : null,
      momentum5Pct: Number.isFinite(momentum5Pct) ? momentum5Pct : null,
      closePosition: Number.isFinite(closePosition) ? closePosition : null,
    },
    phase3RankScore: round(clamp(
      50 + Object.values(adjustments).reduce((sum, value) => sum + value, 0),
      0,
      100,
    )),
    softAdjustments: adjustments,
    softFeatureCoverage: softFeatureCoverage(features),
    ...volumeConfirmation(features),
  };
}
