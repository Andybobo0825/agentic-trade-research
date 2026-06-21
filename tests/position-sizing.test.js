import test from 'node:test';
import assert from 'node:assert/strict';
import { positionBudget } from '../src/position-sizing.js';

test('positionBudget can concentrate into a single best idea without exceeding cash', () => {
  assert.equal(positionBudget({ cash: 500000, initialCapital: 500000, maxPositions: 1, openPositions: 0 }), 500000);
});

test('positionBudget splits remaining cash across remaining slots', () => {
  assert.equal(positionBudget({ cash: 400000, initialCapital: 500000, maxPositions: 2, openPositions: 1 }), 250000);
});

test('positionBudget applies risk multiplier and initial capital cap', () => {
  assert.equal(positionBudget({ cash: 500000, initialCapital: 500000, maxPositions: 2, openPositions: 0, multiplier: 0.5 }), 125000);
});
