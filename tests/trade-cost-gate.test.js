import test from 'node:test';
import assert from 'node:assert/strict';
import { roundTripCostPct, estimateShortTermEdgePct, costGateDecision, positionSizeMultiplier } from '../src/trade-cost-gate.js';

test('roundTripCostPct includes buy fee, sell fee, and transaction tax', () => {
  assert.equal(roundTripCostPct({ feeRate: 0.001425, taxRate: 0.003 }), 0.585);
});

test('cost gate rejects weak edges that cannot pay trading costs', () => {
  const ind = { dayReturnPct: 1.5, volRatio: 1.6, turnoverRatio: 1.3, closePos: 0.72, atrPct: 4.8 };
  const decision = costGateDecision({ ind, hotScore: 180, combinedScore: 260 }, { minCostMultiple: 3 });
  assert.equal(decision.allowed, false);
  assert.equal(decision.reason, 'edge-below-cost');
  assert.ok(decision.requiredEdgePct > decision.expectedEdgePct);
});

test('cost gate accepts strong hot momentum with enough cushion over costs', () => {
  const ind = { dayReturnPct: 4.2, volRatio: 2.8, turnoverRatio: 3.0, closePos: 0.88, atrPct: 2.7 };
  const decision = costGateDecision({ ind, hotScore: 420, combinedScore: 500 }, { minCostMultiple: 3 });
  assert.equal(decision.allowed, true);
  assert.equal(decision.reason, 'cost-efficient');
  assert.ok(decision.expectedEdgePct >= decision.requiredEdgePct);
});

test('position sizing gives full size only to high heat and high edge signals', () => {
  assert.equal(positionSizeMultiplier({ hotScore: 430, costCushionPct: 2.8 }), 1);
  assert.equal(positionSizeMultiplier({ hotScore: 260, costCushionPct: 1.2 }), 0.72);
  assert.equal(positionSizeMultiplier({ hotScore: 210, costCushionPct: 0.6 }), 0.5);
});
