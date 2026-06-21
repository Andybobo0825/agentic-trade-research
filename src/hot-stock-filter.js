const DEFAULT_EXCLUDED_INDUSTRIES = new Set(['17']); // finance/insurance: usually liquid but not short-term theme heat.

function number(value, fallback = 0) {
  return Number.isFinite(value) ? value : fallback;
}

export function hotStockScore({ row = {}, ind = {} } = {}) {
  const tradeValueMillion = number(row.amount) / 1_000_000;
  const vol = Math.min(number(ind.volRatio), 5);
  const turnover = Math.min(number(ind.turnoverRatio), 5);
  const dayReturn = Math.max(0, Math.min(number(ind.dayReturnPct), 8));
  const closePos = Math.max(0, Math.min(number(ind.closePos), 1));
  const atrPenalty = Math.max(0, number(ind.atrPct) - 3.5) * 8;
  return Number((vol * 42 + turnover * 46 + dayReturn * 16 + closePos * 42 + Math.min(tradeValueMillion, 600) / 10 - atrPenalty).toFixed(2));
}

export function isHotStockCandidate({ meta = {}, row = {}, ind = {} } = {}, options = {}) {
  const excludedIndustries = options.excludedIndustries ?? DEFAULT_EXCLUDED_INDUSTRIES;
  const industry = String(meta.industry ?? '').padStart(2, '0');
  if (excludedIndustries.has(industry)) {
    return { allowed: false, reason: 'excluded-industry', score: 0 };
  }

  const minVolRatio = options.minVolRatio ?? 1.9;
  const minTurnoverRatio = options.minTurnoverRatio ?? 1.7;
  const minDayReturnPct = options.minDayReturnPct ?? 1.8;
  const minClosePos = options.minClosePos ?? 0.7;
  const minTradeValue = options.minTradeValue ?? 30_000_000;
  const maxAtrPct = options.maxAtrPct ?? 6.5;

  const hotEnough =
    number(ind.volRatio) >= minVolRatio &&
    number(ind.turnoverRatio) >= minTurnoverRatio &&
    number(ind.dayReturnPct) >= minDayReturnPct &&
    number(ind.closePos) >= minClosePos &&
    number(row.amount) >= minTradeValue &&
    number(ind.atrPct, Infinity) <= maxAtrPct;

  if (!hotEnough) {
    return { allowed: false, reason: 'insufficient-heat', score: hotStockScore({ row, ind }) };
  }
  return { allowed: true, reason: 'hot', score: hotStockScore({ row, ind }) };
}
