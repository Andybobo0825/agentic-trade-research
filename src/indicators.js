function toFiniteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function round(value, digits = 4) {
  if (!Number.isFinite(value)) return null;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function calculateWeightedMovingAverage(values, period) {
  const window = Math.floor(Number(period));
  if (!Number.isInteger(window) || window < 1) throw new Error('WMA period must be a positive integer');
  const numbers = values.map(toFiniteNumber);
  return numbers.map((_, index) => {
    if (index < window - 1) return null;
    let weightedSum = 0;
    let weightSum = 0;
    for (let offset = 0; offset < window; offset += 1) {
      const value = numbers[index - window + 1 + offset];
      if (value === null) return null;
      const weight = offset + 1;
      weightedSum += value * weight;
      weightSum += weight;
    }
    return weightedSum / weightSum;
  });
}

export function calculateHullMovingAverage(values, period = 20) {
  const length = Math.floor(Number(period));
  if (!Number.isInteger(length) || length < 1) throw new Error('HMA period must be a positive integer');
  const half = Math.max(1, Math.floor(length / 2));
  const sqrt = Math.max(1, Math.floor(Math.sqrt(length)));
  const shortWma = calculateWeightedMovingAverage(values, half);
  const fullWma = calculateWeightedMovingAverage(values, length);
  const raw = values.map((_, index) => {
    if (shortWma[index] === null || fullWma[index] === null) return null;
    return 2 * shortWma[index] - fullWma[index];
  });
  return calculateWeightedMovingAverage(raw, sqrt);
}

export function normalizeCandleRows(rows = []) {
  return rows.map((row) => {
    const close = toFiniteNumber(row.close ?? row.Close ?? row.ClosingPrice ?? row.lastPrice ?? row.price);
    return {
      date: row.date ?? row.Date ?? row.time ?? row.timestamp ?? null,
      open: toFiniteNumber(row.open ?? row.Open ?? row.OpeningPrice),
      high: toFiniteNumber(row.high ?? row.High ?? row.max ?? row.HighestPrice),
      low: toFiniteNumber(row.low ?? row.Low ?? row.min ?? row.LowestPrice),
      close,
      volume: toFiniteNumber(row.volume ?? row.Trading_Volume ?? row.trading_volume ?? row.TradeVolume ?? row.TradingShares),
      raw: row,
    };
  }).filter((row) => row.close !== null);
}

export function evaluateHmaTrendSignal(candles = [], options = {}) {
  const period = Math.floor(Number(options.period ?? 20));
  if (!Number.isInteger(period) || period < 1) throw new Error('HMA period must be a positive integer');
  const normalized = normalizeCandleRows(candles);
  const closes = normalized.map((row) => row.close);
  const hma = calculateHullMovingAverage(closes, period);
  const enriched = normalized.map((row, index) => ({
    ...row,
    hma: hma[index] === null ? null : round(hma[index]),
  }));
  const latestIndex = findLatestValidIndex(enriched);
  if (latestIndex < 1) {
    return {
      indicator: 'hma',
      period,
      trend: 'insufficient_data',
      action: 'watch',
      suggestion: '資料不足，先觀察',
      reason: `Need at least ${period} closes plus smoothing history to compute HMA.`,
      latest: null,
      previous: null,
      candles: enriched,
    };
  }

  const latest = enriched[latestIndex];
  const previous = enriched[latestIndex - 1];
  const hmaSlope = latest.hma - previous.hma;
  const closeAbove = latest.close >= latest.hma;
  const closeBelow = latest.close <= latest.hma;
  const crossedAbove = previous.close <= previous.hma && latest.close > latest.hma;
  const crossedBelow = previous.close >= previous.hma && latest.close < latest.hma;

  let trend = 'neutral';
  let action = 'watch';
  let suggestion = '觀察，訊號尚未一致';
  let reason = 'Price and HMA direction are mixed.';

  if (crossedAbove && hmaSlope > 0) {
    trend = 'bullish_reversal';
    action = 'buy_watch';
    suggestion = '偏多買進觀察：收盤站上且 HMA 上彎';
    reason = 'Close crossed above a rising HMA.';
  } else if (crossedBelow && hmaSlope < 0) {
    trend = 'bearish_reversal';
    action = 'sell_watch';
    suggestion = '偏空賣出/避開觀察：收盤跌破且 HMA 下彎';
    reason = 'Close crossed below a falling HMA.';
  } else if (closeAbove && hmaSlope > 0) {
    trend = 'bullish';
    action = 'hold_long';
    suggestion = '偏多續抱：價格在或貼近上升 HMA 之上';
    reason = 'Close is at or above a rising HMA.';
  } else if (closeBelow && hmaSlope < 0) {
    trend = 'bearish';
    action = 'avoid_or_reduce';
    suggestion = '偏空減碼/避開：價格在下降 HMA 之下';
    reason = 'Close is below a falling HMA.';
  } else if (closeAbove) {
    trend = 'weak_bullish';
    action = 'watch';
    suggestion = '弱多觀察：價格在 HMA 上方，但 HMA 斜率未轉強';
    reason = 'Close is above HMA, but HMA is not rising.';
  } else if (closeBelow) {
    trend = 'weak_bearish';
    action = 'watch';
    suggestion = '弱空觀察：價格在 HMA 下方，但 HMA 斜率未轉弱';
    reason = 'Close is below HMA, but HMA is not falling.';
  }

  return {
    indicator: 'hma',
    period,
    trend,
    action,
    suggestion,
    reason,
    latest: compactSignalPoint(latest),
    previous: compactSignalPoint(previous),
    stats: {
      hmaSlope: round(hmaSlope),
      closeMinusHma: round(latest.close - latest.hma),
      closeAboveHma: closeAbove,
      crossedAbove,
      crossedBelow,
    },
    candles: enriched,
    disclaimer: 'Technical signal only; not personalized investment advice. Confirm with volume, risk controls, and broader evidence.',
  };
}

export function buildHmaSeries(candles = [], options = {}) {
  const period = Math.floor(Number(options.period ?? 20));
  if (!Number.isInteger(period) || period < 1) throw new Error('HMA period must be a positive integer');
  const normalized = normalizeCandleRows(candles);
  const hma = calculateHullMovingAverage(normalized.map((row) => row.close), period);
  return normalized.map((row, index) => ({
    ...row,
    hma: hma[index] === null ? null : round(hma[index]),
  }));
}

export function detectHmaSignals(candles = [], options = {}) {
  const series = buildHmaSeries(candles, options);
  const signals = [];
  for (let index = 1; index < series.length; index += 1) {
    const previous = series[index - 1];
    const current = series[index];
    if (previous.hma === null || current.hma === null) continue;
    const hmaSlope = current.hma - previous.hma;
    const crossedAbove = previous.close <= previous.hma && current.close > current.hma;
    const crossedBelow = previous.close >= previous.hma && current.close < current.hma;
    if (crossedAbove && hmaSlope > 0) {
      signals.push({ type: 'buy', index, date: current.date, close: current.close, hma: current.hma, hmaSlope: round(hmaSlope), reason: 'Close crossed above a rising HMA.' });
    } else if (crossedBelow && hmaSlope < 0) {
      signals.push({ type: 'sell', index, date: current.date, close: current.close, hma: current.hma, hmaSlope: round(hmaSlope), reason: 'Close crossed below a falling HMA.' });
    }
  }
  return { period: Math.floor(Number(options.period ?? 20)), series, signals };
}

function findLatestValidIndex(rows) {
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (rows[index].hma !== null && rows[index].close !== null) return index;
  }
  return -1;
}

function compactSignalPoint(row) {
  return {
    date: row.date,
    close: row.close,
    hma: row.hma,
  };
}
