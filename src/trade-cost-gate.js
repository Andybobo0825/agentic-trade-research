function n(value, fallback = 0) {
  return Number.isFinite(value) ? value : fallback;
}

function round(value, digits = 2) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
}

export function roundTripCostPct({ feeRate = 0.001425, taxRate = 0.003 } = {}) {
  return round((feeRate * 2 + taxRate) * 100, 3);
}

export function estimateShortTermEdgePct({ ind = {}, hotScore = 0, combinedScore = 0 } = {}) {
  const volExpansion = Math.max(0, Math.min(n(ind.volRatio) - 1, 3));
  const turnoverExpansion = Math.max(0, Math.min(n(ind.turnoverRatio) - 1, 3));
  const priceImpulse = Math.max(0, Math.min(n(ind.dayReturnPct), 6));
  const closeStrength = Math.max(0, Math.min(n(ind.closePos), 1));
  const heatBonus = Math.max(0, Math.min(n(hotScore) - 220, 260)) / 260;
  const studyBonus = Math.max(0, Math.min(n(combinedScore) - 300, 260)) / 260;
  const atrPenalty = Math.max(0, n(ind.atrPct) - 4.2) * 0.28;

  return round(
    priceImpulse * 0.28 +
      volExpansion * 0.52 +
      turnoverExpansion * 0.42 +
      closeStrength * 0.72 +
      heatBonus * 0.75 +
      studyBonus * 0.45 -
      atrPenalty,
    3,
  );
}

export function costGateDecision({ ind = {}, hotScore = 0, combinedScore = 0 } = {}, options = {}) {
  const feeRate = options.feeRate ?? 0.001425;
  const taxRate = options.taxRate ?? 0.003;
  const minCostMultiple = options.minCostMultiple ?? 3;
  const costPct = roundTripCostPct({ feeRate, taxRate });
  const expectedEdgePct = estimateShortTermEdgePct({ ind, hotScore, combinedScore });
  const requiredEdgePct = round(costPct * minCostMultiple, 3);
  const costCushionPct = round(expectedEdgePct - costPct, 3);
  if (expectedEdgePct < requiredEdgePct) {
    return { allowed: false, reason: 'edge-below-cost', costPct, expectedEdgePct, requiredEdgePct, costCushionPct };
  }
  return { allowed: true, reason: 'cost-efficient', costPct, expectedEdgePct, requiredEdgePct, costCushionPct };
}

export function positionSizeMultiplier({ hotScore = 0, costCushionPct = 0 } = {}) {
  if (hotScore >= 390 && costCushionPct >= 2.2) return 1;
  if (hotScore >= 250 && costCushionPct >= 1) return 0.72;
  return 0.5;
}
