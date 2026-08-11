const REGIMES = ['spike', 'tight_channel', 'normal_channel', 'trading_range', 'insufficient_data'];
const DIRECTIONS = ['bullish', 'bearish', 'neutral'];
const GATE_RESULTS = ['proceed', 'wait'];
const STANCES = ['enter', 'wait', 'avoid'];
const MANDATORY_NODES = ['D1', 'D2', 'D3', 'D4'];
const PRICE_KEYS = ['activeEntryLimit', 'patientEntryPrice', 'takeProfitPrice', 'stopLossPrice'];

const FACT_TOLERANCE = 0.005;
const PRICE_ANCHOR_TOLERANCE = 0.03;
const MIN_TRACEABLE_NUMBER = 1000;

const FORBIDDEN_PATTERNS = [
  { label: '倉位比例', re: /\d+\s*%[^。\n]{0,6}(倉|部位|資金)/ },
  { label: '倉位比例', re: /(倉位|部位)[^。\n]{0,6}\d+\s*%/ },
  // Volume is reported in 張 too, so a lot count only counts as position sizing
  // when it sits next to an act of buying, selling or holding.
  { label: '手數', re: /(買|賣|進場|建倉|投入|下單|做多|做空|部位|倉位)[^。\n]{0,8}\d+\s*(口|張|手)/ },
  { label: '手數', re: /\d+\s*(口|張|手)[^。\n]{0,6}(部位|倉位|進場|建倉|試單)/ },
  { label: '倉位比例', re: /(部位|倉位)[^。\n]{0,8}\d+\s*\/\s*\d+/ },
  { label: '加碼', re: /加碼|攤平|補倉/ },
  { label: '減碼', re: /減碼|分批出場|分批減/ },
  { label: '移動停損', re: /移(動|到|至)?[^。\n]{0,3}(停損|止損)|(停損|止損)[^。\n]{0,4}(移|上移|拉高|下移)|保本停損|盈虧平衡/ },
  // A disclaimer that something is NOT guaranteed is the opposite of a promise.
  { label: '保證語言', re: /(?<!非|不|未|無法|沒有|不能|難以)保證|穩賺|必漲|必跌|一定(會)?(漲|跌)|包賺/ },
  { label: '全押', re: /all[- ]?in|梭哈|重壓/i },
];

export function validateJudgment(judgment, factTable) {
  const errors = [];
  const facts = Array.isArray(factTable?.facts) ? factTable.facts : [];
  const factById = new Map(facts.map((fact) => [fact.id, fact]));
  const diagnosis = judgment?.diagnosis;

  if (!diagnosis || typeof diagnosis !== 'object') {
    return { ok: false, errors: [{ code: 'BAD_SHAPE', path: 'diagnosis', message: 'judgment.diagnosis is required' }] };
  }

  checkEnum(errors, 'diagnosis.regime', diagnosis.regime, REGIMES);
  checkEnum(errors, 'diagnosis.direction', diagnosis.direction, DIRECTIONS);
  checkEnum(errors, 'diagnosis.gate_result', diagnosis.gate_result, GATE_RESULTS);
  if (diagnosis.alternative_regime !== null && diagnosis.alternative_regime !== undefined) {
    checkEnum(errors, 'diagnosis.alternative_regime', diagnosis.alternative_regime, REGIMES);
  }
  if (!Number.isInteger(diagnosis.confidence)) {
    errors.push({ code: 'BAD_TYPE', path: 'diagnosis.confidence', message: 'confidence must be an integer 0-100' });
  }

  const trace = Array.isArray(diagnosis.gate_trace) ? diagnosis.gate_trace : [];
  if (!trace.length) {
    errors.push({ code: 'BAD_SHAPE', path: 'diagnosis.gate_trace', message: 'gate_trace must list the nodes that were walked' });
  }
  const nodes = new Set(trace.map((item) => item?.node));
  if (diagnosis.gate_result === 'proceed') {
    for (const node of MANDATORY_NODES) {
      if (!nodes.has(node)) {
        errors.push({ code: 'MISSING_NODE', path: 'diagnosis.gate_trace', message: `gate_result=proceed requires node ${node}` });
      }
    }
  }

  for (const [index, item] of trace.entries()) {
    const path = `diagnosis.gate_trace[${index}]`;
    const cited = Array.isArray(item?.facts) ? item.facts : [];
    if (!cited.length) {
      errors.push({ code: 'NO_EVIDENCE', path, message: `node ${item?.node ?? '?'} cites no fact id` });
    }
    for (const id of cited) {
      if (!factById.has(id)) {
        errors.push({ code: 'UNKNOWN_FACT', path, message: `node ${item?.node ?? '?'} cites unknown fact ${id}` });
      }
    }
  }

  const regimeNode = trace.find((item) => item?.node === 'D2');
  if (regimeNode && regimeNode.branch !== diagnosis.regime && regimeNode.branch !== diagnosis.alternative_regime) {
    errors.push({
      code: 'TRACE_CONFLICT',
      path: 'diagnosis.gate_trace[D2]',
      message: `node D2 branch ${regimeNode.branch} conflicts with regime ${diagnosis.regime}`,
    });
  }
  const directionNode = trace.find((item) => item?.node === 'D3');
  if (directionNode && directionNode.branch !== diagnosis.direction) {
    errors.push({
      code: 'TRACE_CONFLICT',
      path: 'diagnosis.gate_trace[D3]',
      message: `node D3 branch ${directionNode.branch} conflicts with direction ${diagnosis.direction}`,
    });
  }

  for (const [id, value] of Object.entries(diagnosis.cited_facts || {})) {
    const fact = factById.get(id);
    if (!fact) {
      errors.push({ code: 'UNKNOWN_FACT', path: `diagnosis.cited_facts.${id}`, message: `cited fact ${id} is not in the fact table` });
      continue;
    }
    if (!withinTolerance(value, fact.value, FACT_TOLERANCE)) {
      errors.push({
        code: 'FACT_VALUE_MISMATCH',
        path: `diagnosis.cited_facts.${id}`,
        message: `${id} was restated as ${value} but the fact table says ${fact.value}`,
      });
    }
  }

  const decision = judgment?.decision;
  if (decision) {
    checkEnum(errors, 'decision.stance', decision.stance, STANCES);
    const prices = decision.prices || {};
    const priced = PRICE_KEYS.filter((key) => Number.isFinite(Number(prices[key])) && prices[key] !== null);

    if (diagnosis.gate_result === 'wait' && priced.length) {
      errors.push({
        code: 'GATE_VIOLATION',
        path: 'decision.prices',
        message: 'gate_result=wait requires all four reference prices to be null',
      });
    }
    if (priced.length && diagnosis.gate_result !== 'proceed') {
      errors.push({ code: 'GATE_VIOLATION', path: 'decision.prices', message: 'reference prices require gate_result=proceed' });
    }
    if (diagnosis.gate_result === 'wait' && decision.stance === 'enter') {
      errors.push({ code: 'GATE_VIOLATION', path: 'decision.stance', message: 'gate_result=wait cannot carry stance=enter' });
    }

    for (const key of priced) {
      const value = Number(prices[key]);
      const anchored = facts.some((fact) => Number.isFinite(Number(fact.value)) && withinTolerance(value, Number(fact.value), PRICE_ANCHOR_TOLERANCE));
      if (!anchored) {
        errors.push({
          code: 'UNANCHORED_PRICE',
          path: `decision.prices.${key}`,
          message: `${key}=${value} is not anchored within ${PRICE_ANCHOR_TOLERANCE * 100}% of any fact`,
        });
      }
    }

    if (decision.stance === 'enter' && priced.length >= 3) {
      errors.push(...checkTradePlan(prices, diagnosis.direction));
    }
  }

  return { ok: errors.length === 0, errors };
}

function checkTradePlan(prices, direction) {
  const errors = [];
  const entry = Number(prices.activeEntryLimit);
  const stop = Number(prices.stopLossPrice);
  const target = Number(prices.takeProfitPrice);
  if (![entry, stop, target].every(Number.isFinite)) return errors;

  const long = direction !== 'bearish';
  const ordered = long ? stop < entry && entry < target : target < entry && entry < stop;
  if (!ordered) {
    errors.push({
      code: 'PRICE_ORDER',
      path: 'decision.prices',
      message: long
        ? `long plan needs stopLoss < activeEntry < takeProfit, got ${stop} / ${entry} / ${target}`
        : `short plan needs takeProfit < activeEntry < stopLoss, got ${target} / ${entry} / ${stop}`,
    });
    return errors;
  }

  const reward = Math.abs(target - entry);
  const risk = Math.abs(entry - stop);
  const rr = risk > 0 ? reward / risk : 0;
  if (rr < 1) {
    errors.push({
      code: 'RR_TOO_LOW',
      path: 'decision.prices',
      message: `recomputed reward-to-risk is ${rr.toFixed(2)}; the plan needs at least 1.0`,
    });
  }
  return errors;
}

// Years and calendar dates are excluded: a bare 2026 is a date, not a level.
// Ticker codes must be exempted explicitly rather than by range, because a
// Taiwan code like 2330 is indistinguishable from an invented index level.
export function validateReportNumbers(markdownText, factTable, judgment, options = {}) {
  const text = String(markdownText || '');
  const known = [
    ...(factTable?.facts || []).map((fact) => Number(fact.value)),
    ...PRICE_KEYS.map((key) => Number(judgment?.decision?.prices?.[key])),
  ].filter(Number.isFinite);
  const tickerCodes = new Set(
    [factTable?.ticker, ...(options.tickers || [])]
      .map((value) => Number(String(value ?? '').trim()))
      .filter((value) => Number.isInteger(value) && value > 0),
  );

  const errors = [];
  const seen = new Set();
  const withoutDates = text.replace(/\d{4}[-/]\d{1,2}[-/]\d{1,2}/g, ' ');
  // Thousands groups must be exactly three digits, otherwise "1135,20 日均" would
  // glue two separate numbers into one and report a phantom mismatch.
  for (const match of withoutDates.matchAll(/\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?/g)) {
    const raw = match[0];
    const value = Number(raw.replace(/,/g, ''));
    if (!Number.isFinite(value) || value < MIN_TRACEABLE_NUMBER) continue;
    if (Number.isInteger(value) && value >= 1900 && value <= 2100) continue;
    if (tickerCodes.has(value) && !raw.includes(',') && !raw.includes('.')) continue;
    if (seen.has(value)) continue;
    seen.add(value);
    if (!known.some((candidate) => withinTolerance(value, candidate, FACT_TOLERANCE))) {
      errors.push({
        code: 'UNTRACEABLE_NUMBER',
        path: 'report',
        message: `report states ${raw} but no fact or reference price matches it`,
      });
    }
  }
  return errors;
}

export function scanForbiddenContent(markdownText) {
  const text = String(markdownText || '');
  const errors = [];
  for (const { label, re } of FORBIDDEN_PATTERNS) {
    const match = text.match(re);
    if (match) {
      errors.push({ code: 'FORBIDDEN_CONTENT', path: 'report', message: `${label}:「${match[0]}」不得出現在輸出中` });
    }
  }
  return errors;
}

const CATEGORY_BY_CODE = {
  BAD_ENUM: 'schema',
  BAD_TYPE: 'schema',
  BAD_SHAPE: 'schema',
  MISSING_NODE: 'missing',
  NO_EVIDENCE: 'missing',
  TRACE_CONFLICT: 'inconsistency',
  GATE_VIOLATION: 'inconsistency',
  RR_TOO_LOW: 'inconsistency',
  PRICE_ORDER: 'inconsistency',
  FORBIDDEN_CONTENT: 'inconsistency',
  UNKNOWN_FACT: 'untraceable',
  FACT_VALUE_MISMATCH: 'untraceable',
  UNANCHORED_PRICE: 'untraceable',
  UNTRACEABLE_NUMBER: 'untraceable',
};

const CATEGORY_LABEL = {
  schema: '欄位型別或枚舉不合法',
  missing: '缺少必經節點或證據',
  inconsistency: '結論與推理路徑/規則不一致',
  untraceable: '數字無法追溯回事實表',
};

export function buildRetryFeedback(errors = []) {
  const categories = [...new Set(errors.map((error) => CATEGORY_BY_CODE[error.code] || 'schema'))];
  const lines = ['判讀未通過驗證,請依下列逐條修正後重新輸出完整 JSON:'];
  for (const category of categories) {
    lines.push('', `【${CATEGORY_LABEL[category]}】`);
    for (const error of errors.filter((e) => (CATEGORY_BY_CODE[e.code] || 'schema') === category)) {
      lines.push(`- ${error.path}: ${error.message}`);
    }
  }
  const forbiddenFixes = [
    '不得為了通過驗證而更改 regime、direction、gate_result 或 stance;結論只能因為重新對照事實表而改變。',
    '不得刪除或縮減 cited_facts 來規避比對;必須修正引用的數值或改引用正確的 fact id。',
  ];
  lines.push('', '修正時的禁止事項:', ...forbiddenFixes.map((item) => `- ${item}`));
  return { categories, message: lines.join('\n'), forbiddenFixes };
}

export function runJudgmentGuard({ judgment, facts, report, tickers } = {}) {
  const judgmentErrors = validateJudgment(judgment, facts);
  const reportErrors = report ? validateReportNumbers(report, facts, judgment, { tickers: normalizeTickers(tickers) }) : [];
  const forbiddenErrors = report ? scanForbiddenContent(report) : [];
  const errors = [...judgmentErrors.errors, ...reportErrors, ...forbiddenErrors];
  return {
    ok: errors.length === 0,
    checked: { judgment: true, reportNumbers: Boolean(report), forbiddenContent: Boolean(report) },
    errors,
    retryFeedback: errors.length ? buildRetryFeedback(errors) : null,
  };
}

export function renderJudgmentGuardMarkdown(result) {
  const lines = [
    '# Judgment guard',
    '',
    `- Result: ${result.ok ? 'PASS' : 'FAIL'}`,
    `- Checks: judgment${result.checked.reportNumbers ? ', report numbers' : ''}${result.checked.forbiddenContent ? ', forbidden content' : ''}`,
    `- Errors: ${result.errors.length}`,
  ];
  if (result.errors.length) {
    lines.push('', '## Errors');
    for (const error of result.errors) lines.push(`- \`${error.code}\` ${error.path}: ${error.message}`);
    lines.push('', '## Retry feedback', '', '```text', result.retryFeedback.message, '```');
  }
  return `${lines.join('\n')}\n`;
}

function normalizeTickers(value) {
  if (!value) return [];
  return Array.isArray(value) ? value : String(value).split(',').map((item) => item.trim()).filter(Boolean);
}

function checkEnum(errors, path, value, allowed) {
  if (!allowed.includes(value)) {
    errors.push({ code: 'BAD_ENUM', path, message: `${path}=${JSON.stringify(value)} must be one of ${allowed.join(', ')}` });
  }
}

function withinTolerance(value, target, tolerance) {
  const a = Number(value);
  const b = Number(target);
  // Facts such as closeVsMa20 are labels, not levels: compare those as text,
  // since Number('above') is NaN and NaN never equals itself.
  if (!Number.isFinite(a) || !Number.isFinite(b)) return String(value) === String(target);
  if (b === 0) return Math.abs(a) < 1e-9;
  return Math.abs(a - b) / Math.abs(b) <= tolerance;
}
