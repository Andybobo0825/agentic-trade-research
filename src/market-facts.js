import { toMarkdownTable } from './format.js';

const DEFAULT_WINDOWS = { background: 60, structure: 20, immediate: 5 };
const MIN_ROWS = 25;

const PLAYBOOK = {
  spike: {
    guidance: '推進中不追價;等第一次回檔出現、且回檔結束後才評估順向參與。',
    refs: ['docs/standard-workflow-v1.md'],
  },
  tight_channel: {
    guidance: '順結構方向;回測均線區且量能不背離時才是可觀察的位置,不在推進段追價。',
    refs: ['docs/standard-workflow-v1.md'],
  },
  normal_channel: {
    guidance: '順結構方向,但回檔較深,等回測到均線密集帶止穩再評估,分批優於一次到位。',
    refs: ['docs/standard-workflow-v1.md'],
  },
  trading_range: {
    guidance: '只有邊界附近有意義;區間中間不動作,突破需回測確認後才談方向。',
    refs: ['docs/standard-workflow-v1.md'],
  },
  insufficient_data: {
    guidance: '資料不足以判讀結構;先補資料,不得用不足的樣本給位置結論。',
    refs: ['docs/standard-workflow-v1.md'],
  },
};

export function computeMarketFacts(rows = [], options = {}) {
  const windows = { ...DEFAULT_WINDOWS, ...(options.windows || {}) };
  const ticker = options.ticker ? String(options.ticker) : 'unknown';
  const bars = normalizeBars(rows);
  const windowMeta = {
    background: { bars: windows.background, role: 'risk-context' },
    structure: { bars: windows.structure, role: 'direction' },
    immediate: { bars: windows.immediate, role: 'signal-quality' },
  };
  const builder = createFactBuilder();

  if (bars.length < MIN_ROWS) {
    builder.add('insufficient', 'background', bars.length, `只有 ${bars.length} 根有效日線,少於判讀下限 ${MIN_ROWS} 根`);
    return {
      ticker,
      asOf: bars.length ? bars[bars.length - 1].date : null,
      factTableVersion: 1,
      windows: windowMeta,
      facts: builder.facts,
      regime: { label: 'insufficient_data', alternative: null, direction: 'neutral', evidence: builder.idsFor('insufficient'), confidence: 10 },
      playbook: { regime: 'insufficient_data', ...PLAYBOOK.insufficient_data },
    };
  }

  const last = bars[bars.length - 1];
  const closes = bars.map((b) => b.close);
  const turnovers = bars.map((b) => b.turnover);

  builder.add('close', 'immediate', last.close, `${last.date} 收盤`);
  builder.add('prevClose', 'immediate', bars[bars.length - 2].close, '前一交易日收盤');
  builder.add('changePct', 'immediate', pct(last.close / bars[bars.length - 2].close - 1), '當日漲跌幅 %');

  const ma5 = mean(closes.slice(-5));
  const ma10 = mean(closes.slice(-10));
  const ma20 = mean(closes.slice(-windows.structure));
  const ma60 = bars.length >= windows.background ? mean(closes.slice(-windows.background)) : null;
  builder.add('ma5', 'immediate', round2(ma5), '5 日均價');
  builder.add('ma10', 'structure', round2(ma10), '10 日均價');
  builder.add('ma20', 'structure', round2(ma20), `${windows.structure} 日均價(structure 視窗)`);
  if (ma60 !== null) builder.add('ma60', 'background', round2(ma60), `${windows.background} 日均價(background 視窗)`);
  builder.add('closeVsMa20', 'structure', last.close >= ma20 ? 'above' : 'below', '收盤相對 structure 均線位置');
  if (ma60 !== null) builder.add('closeVsMa60', 'background', last.close >= ma60 ? 'above' : 'below', '收盤相對 background 均線位置');

  const avgTurnover20 = mean(turnovers.slice(-windows.structure));
  const avgTurnover5 = mean(turnovers.slice(-windows.immediate));
  builder.add('turnover', 'immediate', last.turnover, '當日成交金額');
  builder.add('avgTurnover20', 'structure', round2(avgTurnover20), `${windows.structure} 日均成交金額`);
  builder.add('turnoverRatio', 'immediate', avgTurnover20 ? last.turnover / avgTurnover20 : null, '當日成交金額 / structure 均量');
  builder.add('avgTurnover5over20', 'immediate', avgTurnover20 ? avgTurnover5 / avgTurnover20 : null, 'immediate 均量 / structure 均量');

  const backgroundBars = bars.slice(-windows.background);
  const high = backgroundBars.reduce((acc, b) => (b.high > acc.high ? { high: b.high, date: b.date } : acc), { high: -Infinity, date: null });
  const low = backgroundBars.reduce((acc, b) => (b.low < acc.low ? { low: b.low, date: b.date } : acc), { low: Infinity, date: null });
  builder.add('swingHigh60', 'background', round2(high.high), `background 視窗最高價(${high.date})`);
  builder.add('swingLow60', 'background', round2(low.low), `background 視窗最低價(${low.date})`);
  const span = high.high - low.low;
  builder.add('retracementPct', 'background', span > 0 ? pct((last.close - low.low) / span) : null, '收盤位於 background 高低區間的位置 %');
  builder.add('drawdownFromHighPct', 'background', high.high > 0 ? pct(last.close / high.high - 1) : null, '收盤距 background 高點的幅度 %');

  const run = trendBarRun(bars);
  builder.add('trendBarRun', 'immediate', run.count, `最近連續同向實體 K 數(方向 ${run.direction})`);
  builder.add('trendBarRunDirection', 'immediate', run.direction, '連續同向實體 K 的方向');
  builder.add('avgBodyOverlap5', 'immediate', round2(avgBodyOverlap(bars.slice(-windows.immediate))), 'immediate 視窗相鄰實體平均重疊比');
  const depth = pullbackDepthPct(bars.slice(-windows.structure));
  builder.add('pullbackDepthPct', 'structure', depth === null ? null : round2(depth), 'structure 視窗內主波段的最大回撤深度 %');
  builder.add('lastBars', 'immediate', bars.slice(-windows.immediate).map(describeBar), 'immediate 視窗逐棒幾何');

  const regime = classifyRegime({ bars, builder, ma5, ma20, depth, run, windows });
  return {
    ticker,
    asOf: last.date,
    factTableVersion: 1,
    windows: windowMeta,
    facts: builder.facts,
    regime,
    playbook: { regime: regime.label, ...PLAYBOOK[regime.label] },
  };
}

function classifyRegime({ bars, builder, ma5, ma20, depth, run, windows }) {
  const last = bars[bars.length - 1];
  const spikeRun = spikeCandidate(bars.slice(-windows.immediate));
  let label;
  let direction;
  let evidence;

  if (spikeRun) {
    label = 'spike';
    direction = spikeRun.direction === 'up' ? 'bullish' : 'bearish';
    evidence = builder.idsFor('trendBarRun', 'avgBodyOverlap5', 'close');
  } else if (depth !== null && trending(last.close, ma5, ma20) && depth < 30) {
    label = 'tight_channel';
    direction = ma5 >= ma20 ? 'bullish' : 'bearish';
    evidence = builder.idsFor('pullbackDepthPct', 'ma5', 'ma20', 'closeVsMa20');
  } else if (depth !== null && trending(last.close, ma5, ma20) && depth <= 50) {
    label = 'normal_channel';
    direction = ma5 >= ma20 ? 'bullish' : 'bearish';
    evidence = builder.idsFor('pullbackDepthPct', 'ma5', 'ma20', 'closeVsMa20');
  } else {
    label = 'trading_range';
    direction = rangeDirection(builder);
    evidence = builder.idsFor('closeVsMa20', 'closeVsMa60', 'pullbackDepthPct');
  }

  return {
    label,
    alternative: alternativeFor(label, depth, spikeRun, bars, windows),
    direction,
    evidence,
    confidence: confidenceFor({ label, depth, bars, windows, direction }),
  };
}

function trending(close, ma5, ma20) {
  if (ma5 >= ma20) return close >= ma20;
  return close <= ma20;
}

function rangeDirection(builder) {
  const vs20 = builder.valueOf('closeVsMa20');
  const vs60 = builder.valueOf('closeVsMa60');
  if (vs60 && vs20 === vs60) return vs20 === 'above' ? 'bullish' : 'bearish';
  return 'neutral';
}

function spikeCandidate(bars) {
  const run = trendBarRun(bars);
  if (run.count < 3 || run.direction === 'flat') return null;
  const runBars = bars.slice(-run.count);
  if (avgBodyOverlap(runBars) >= 0.3) return null;
  if (mean(runBars.map(bodyRatio)) <= 0.5) return null;
  return run;
}

function alternativeFor(label, depth, spikeRun, bars, windows) {
  if (label === 'spike') return 'tight_channel';
  if (depth !== null && (label === 'tight_channel' || label === 'normal_channel' || label === 'trading_range')) {
    if (Math.abs(depth - 30) <= 5) return label === 'tight_channel' ? 'normal_channel' : 'tight_channel';
    if (Math.abs(depth - 50) <= 5) return label === 'normal_channel' ? 'trading_range' : 'normal_channel';
  }
  if (!spikeRun && trendBarRun(bars.slice(-windows.immediate)).count === 2) return label === 'tight_channel' ? 'spike' : null;
  return null;
}

function confidenceFor({ label, depth, bars, windows, direction }) {
  let score = 80;
  if (depth !== null && (Math.abs(depth - 30) <= 5 || Math.abs(depth - 50) <= 5)) score -= 15;
  const immediate = trendBarRun(bars.slice(-windows.immediate));
  if (direction !== 'neutral' && immediate.direction !== 'flat') {
    const immediateDirection = immediate.direction === 'up' ? 'bullish' : 'bearish';
    if (immediateDirection !== direction) score -= 10;
  }
  if (bars.length < windows.background) score -= 20;
  if (label === 'trading_range' && direction === 'neutral') score -= 5;
  return Math.max(10, Math.min(95, score));
}

function trendBarRun(bars) {
  let count = 0;
  let direction = 'flat';
  for (let i = bars.length - 1; i >= 0; i -= 1) {
    const dir = bodyDirection(bars[i]);
    if (dir === 'flat') break;
    if (direction === 'flat') direction = dir;
    else if (dir !== direction) break;
    count += 1;
  }
  return { count, direction };
}

function bodyDirection(bar) {
  const range = bar.high - bar.low;
  const body = bar.close - bar.open;
  if (range <= 0 || Math.abs(body) / range < 0.1) return 'flat';
  return body > 0 ? 'up' : 'down';
}

function bodyRatio(bar) {
  const range = bar.high - bar.low;
  return range > 0 ? Math.abs(bar.close - bar.open) / range : 0;
}

function avgBodyOverlap(bars) {
  if (bars.length < 2) return 0;
  const overlaps = [];
  for (let i = 1; i < bars.length; i += 1) {
    const a = bodyRange(bars[i - 1]);
    const b = bodyRange(bars[i]);
    const overlap = Math.min(a.top, b.top) - Math.max(a.bottom, b.bottom);
    const smaller = Math.min(a.top - a.bottom, b.top - b.bottom);
    overlaps.push(smaller > 0 ? Math.max(0, overlap) / smaller : 0);
  }
  return mean(overlaps);
}

function bodyRange(bar) {
  return { top: Math.max(bar.open, bar.close), bottom: Math.min(bar.open, bar.close) };
}

// Brooks measures a pullback against the leg it retraces, not against the whole
// window: in a long trend the window span is the trend itself, which would make
// every pullback look shallow and the 30/50 thresholds meaningless.
// The ratio is deliberately uncapped: above 100 the counter-move was larger than
// the leg it retraced, which is no longer a pullback, and the tree is meant to
// drop those windows through to trading_range.
function pullbackDepthPct(bars, minMovePct = 0.5) {
  if (bars.length < 3) return null;
  const legs = swingLegs(bars.map((b) => b.close), minMovePct);
  if (legs.length < 1) return null;
  const dominant = bars[bars.length - 1].close >= bars[0].close ? 'up' : 'down';
  const ratios = [];
  for (let i = 1; i < legs.length; i += 1) {
    if (legs[i].dir !== dominant && legs[i - 1].dir === dominant && legs[i - 1].size > 0) {
      ratios.push((legs[i].size / legs[i - 1].size) * 100);
    }
  }
  if (!ratios.length) return 0;
  const recent = ratios.slice(-3).sort((a, b) => a - b);
  return recent[Math.floor(recent.length / 2)];
}

function swingLegs(closes, minMovePct) {
  const pivots = [closes[0]];
  let direction = null;
  let extreme = closes[0];
  for (const close of closes.slice(1)) {
    if (direction === null) {
      if (Math.abs(close - extreme) / extreme * 100 >= minMovePct) {
        direction = close > extreme ? 'up' : 'down';
        extreme = close;
      }
      continue;
    }
    const extending = direction === 'up' ? close > extreme : close < extreme;
    if (extending) {
      extreme = close;
      continue;
    }
    if (Math.abs(close - extreme) / extreme * 100 >= minMovePct) {
      pivots.push(extreme);
      direction = direction === 'up' ? 'down' : 'up';
      extreme = close;
    }
  }
  pivots.push(extreme);
  const legs = [];
  for (let i = 1; i < pivots.length; i += 1) {
    const size = Math.abs(pivots[i] - pivots[i - 1]);
    if (size > 0) legs.push({ dir: pivots[i] > pivots[i - 1] ? 'up' : 'down', size });
  }
  return legs;
}

function describeBar(bar) {
  const range = bar.high - bar.low;
  const dir = bar.close > bar.open ? 'up' : bar.close < bar.open ? 'down' : 'flat';
  return {
    date: bar.date,
    dir,
    bodyRatio: round2(bodyRatio(bar)),
    upperWickRatio: round2(range > 0 ? (bar.high - Math.max(bar.open, bar.close)) / range : 0),
    lowerWickRatio: round2(range > 0 ? (Math.min(bar.open, bar.close) - bar.low) / range : 0),
  };
}

function createFactBuilder() {
  const facts = [];
  return {
    facts,
    add(key, window, value, desc) {
      if (value === undefined) return;
      facts.push({ id: `F${facts.length + 1}`, key, window, value, desc });
    },
    idsFor(...keys) {
      return keys.map((key) => facts.find((f) => f.key === key)?.id).filter(Boolean);
    },
    valueOf(key) {
      return facts.find((f) => f.key === key)?.value;
    },
  };
}

function normalizeBars(rows) {
  const list = Array.isArray(rows) ? rows : [];
  return list
    .map((row) => ({
      date: String(row.date ?? row.Date ?? '').slice(0, 10),
      open: num(row.open ?? row.Open),
      high: num(row.max ?? row.high ?? row.High),
      low: num(row.min ?? row.low ?? row.Low),
      close: num(row.close ?? row.Close),
      turnover: num(row.Trading_money ?? row.turnover ?? row.trading_money ?? 0),
    }))
    .filter((bar) => bar.date && Number.isFinite(bar.close) && Number.isFinite(bar.high) && Number.isFinite(bar.low))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function num(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : NaN;
}

function mean(values) {
  const list = values.filter((v) => Number.isFinite(v));
  if (!list.length) return 0;
  return list.reduce((sum, v) => sum + v, 0) / list.length;
}

function pct(value) {
  return Number.isFinite(value) ? round2(value * 100) : null;
}

function round2(value) {
  return Number.isFinite(value) ? Math.round(value * 100) / 100 : null;
}

export function renderMarketDiagnosisMarkdown(result) {
  const printable = (value) => (Array.isArray(value) ? `${value.length} bars` : value === null || value === undefined ? '—' : String(value));
  const lines = [
    `# Market diagnosis: ${result.ticker}`,
    '',
    `- As of: ${result.asOf || '—'}`,
    `- Fact table version: ${result.factTableVersion}`,
    `- Windows: background ${result.windows.background.bars} (${result.windows.background.role}) / structure ${result.windows.structure.bars} (${result.windows.structure.role}) / immediate ${result.windows.immediate.bars} (${result.windows.immediate.role})`,
    '',
    '## Regime',
    `- Label: ${result.regime.label}`,
    `- Alternative: ${result.regime.alternative || 'none'}`,
    `- Direction: ${result.regime.direction}`,
    `- Confidence: ${result.regime.confidence}`,
    `- Evidence: ${result.regime.evidence.join(', ') || '—'}`,
    `- Playbook: ${result.playbook.guidance}`,
    `- Refs: ${result.playbook.refs.join(', ')}`,
    '',
    '## Fact table',
    'Every number in a report must cite one of these ids.',
    '',
    toMarkdownTable(result.facts, [
      { label: 'Id', value: (r) => r.id },
      { label: 'Key', value: (r) => r.key },
      { label: 'Window', value: (r) => r.window },
      { label: 'Value', value: (r) => printable(r.value) },
      { label: 'Description', value: (r) => r.desc },
    ]),
  ];
  return `${lines.join('\n')}\n`;
}
