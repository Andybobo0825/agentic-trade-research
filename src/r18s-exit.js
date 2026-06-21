function round(value, digits = 2) {
  return Number.isFinite(value) ? Number(value.toFixed(digits)) : null;
}

export function shouldExitR18S({
  holdDays = 0,
  openRet = 0,
  row = {},
  previousClose,
  maxClose,
  breakoutHigh,
  stop = -0.055,
  takeProfit = 0.13,
  continuationDrawdown = 0.035,
} = {}) {
  const tradeDay = holdDays + 1; // buy day counts as day 1; next trading day is day 2.
  if (tradeDay < 3) return { exit: false, reason: '未到第 3 個交易日續抱' };
  if (openRet <= stop) return { exit: true, reason: `停損 ${round(openRet * 100, 2)}%` };
  if (openRet >= takeProfit) return { exit: true, reason: `停利 ${round(openRet * 100, 2)}%` };
  if (tradeDay >= 7) return { exit: true, reason: '滿 7 個交易日出場' };

  const close = row.close;
  const high = row.high;
  const referenceHigh = Number.isFinite(breakoutHigh) ? breakoutHigh : maxClose;
  const keepsHigherClose = Number.isFinite(close) && Number.isFinite(previousClose) && close >= previousClose;
  const challengesHigh = Number.isFinite(high) && Number.isFinite(referenceHigh) && high >= referenceHigh;
  const notTooFarFromHigh = Number.isFinite(close) && Number.isFinite(maxClose) && close >= maxClose * (1 - continuationDrawdown);
  const stillPositive = openRet > 0;

  if ((keepsHigherClose || challengesHigh) && notTooFarFromHigh && stillPositive) {
    return { exit: false, reason: '第3天後仍續強' };
  }
  return { exit: true, reason: `第${tradeDay}天未續強出場` };
}
