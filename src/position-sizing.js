export function positionBudget({ cash = 0, initialCapital = 0, maxPositions = 3, openPositions = 0, multiplier = 1 } = {}) {
  const remainingSlots = Math.max(1, maxPositions - openPositions);
  const perSlotCash = cash / remainingSlots;
  const initialCapPerSlot = initialCapital / Math.max(1, maxPositions);
  return Math.max(0, Math.floor(Math.min(cash, perSlotCash, initialCapPerSlot) * multiplier));
}
