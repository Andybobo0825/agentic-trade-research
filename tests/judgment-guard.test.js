import test from 'node:test';
import assert from 'node:assert/strict';
import {
  validateJudgment,
  validateReportNumbers,
  scanForbiddenContent,
  buildRetryFeedback,
} from '../src/judgment-guard.js';

const factTable = {
  ticker: 'TAIEX',
  asOf: '2026-08-11',
  facts: [
    { id: 'F1', key: 'close', window: 'immediate', value: 45120.72, desc: '收盤' },
    { id: 'F2', key: 'ma20', window: 'structure', value: 43615.12, desc: '20 日均價' },
    { id: 'F3', key: 'swingHigh60', window: 'background', value: 47395.30, desc: '高點' },
    { id: 'F4', key: 'swingLow60', window: 'background', value: 39384.85, desc: '低點' },
    { id: 'F5', key: 'turnoverRatio', window: 'immediate', value: 0.83, desc: '量比' },
  ],
};

function baseJudgment(overrides = {}) {
  return {
    stage: 'decision-included',
    diagnosis: {
      regime: 'normal_channel',
      alternative_regime: null,
      direction: 'bullish',
      confidence: 65,
      gate_result: 'proceed',
      gate_trace: [
        { node: 'D1', question: '資料是否足夠?', branch: 'yes', facts: ['F1'] },
        { node: 'D2', question: 'regime?', branch: 'normal_channel', facts: ['F2'] },
        { node: 'D3', question: '方向?', branch: 'bullish', facts: ['F1', 'F2'] },
        { node: 'D4', question: '是否進入決策?', branch: 'proceed', facts: ['F5'] },
      ],
      cited_facts: { F1: 45120.72, F2: 43615.12 },
    },
    decision: {
      stance: 'enter',
      prices: {
        activeEntryLimit: 45120.72,
        patientEntryPrice: 43615.12,
        takeProfitPrice: 47395.30,
        stopLossPrice: 43615.12 * 0.99,
      },
      conditions: ['量能回升'],
      risks: ['背景仍低於前高'],
    },
    ...overrides,
  };
}

test('a judgment that cites the fact table and prices a real level passes', () => {
  const result = validateJudgment(baseJudgment(), factTable);
  assert.equal(result.ok, true, JSON.stringify(result.errors));
  assert.deepEqual(result.errors, []);
});

test('enum and type violations are rejected', () => {
  const bad = baseJudgment();
  bad.diagnosis.regime = 'super_bull';
  bad.diagnosis.confidence = 'high';
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'BAD_ENUM'));
  assert.ok(result.errors.some((e) => e.code === 'BAD_TYPE'));
});

test('proceeding without walking every mandatory node is rejected', () => {
  const bad = baseJudgment();
  bad.diagnosis.gate_trace = bad.diagnosis.gate_trace.filter((n) => n.node !== 'D3');
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'MISSING_NODE' && e.message.includes('D3')));
});

test('a conclusion that contradicts its own decision path is rejected', () => {
  const bad = baseJudgment();
  bad.diagnosis.gate_trace.find((n) => n.node === 'D2').branch = 'trading_range';
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'TRACE_CONFLICT'));
});

test('an alternative regime is an acceptable branch for the regime node', () => {
  const judgment = baseJudgment();
  judgment.diagnosis.alternative_regime = 'trading_range';
  judgment.diagnosis.gate_trace.find((n) => n.node === 'D2').branch = 'trading_range';
  const result = validateJudgment(judgment, factTable);
  assert.equal(result.ok, true, JSON.stringify(result.errors));
});

test('citing a fact id that does not exist is rejected', () => {
  const bad = baseJudgment();
  bad.diagnosis.gate_trace.find((n) => n.node === 'D2').facts = ['F99'];
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'UNKNOWN_FACT'));
});

test('a trace step with no evidence at all is rejected', () => {
  const bad = baseJudgment();
  bad.diagnosis.gate_trace.find((n) => n.node === 'D4').facts = [];
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'NO_EVIDENCE'));
});

test('restating a fact with the wrong value is rejected', () => {
  const bad = baseJudgment();
  bad.diagnosis.cited_facts.F1 = 45999;
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'FACT_VALUE_MISMATCH'));
});

test('a label fact such as above/below can be cited without a false mismatch', () => {
  const labelled = { ...factTable, facts: [...factTable.facts, { id: 'F6', key: 'closeVsMa20', window: 'structure', value: 'above', desc: '相對均線' }] };
  const judgment = baseJudgment();
  judgment.diagnosis.cited_facts.F6 = 'above';
  assert.equal(validateJudgment(judgment, labelled).ok, true, JSON.stringify(validateJudgment(judgment, labelled).errors));

  const wrong = baseJudgment();
  wrong.diagnosis.cited_facts.F6 = 'below';
  const result = validateJudgment(wrong, labelled);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'FACT_VALUE_MISMATCH'));
});

test('a waiting gate may not carry entry prices', () => {
  const bad = baseJudgment();
  bad.diagnosis.gate_result = 'wait';
  bad.diagnosis.gate_trace.find((n) => n.node === 'D4').branch = 'wait';
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'GATE_VIOLATION'));
});

test('a waiting gate with four null prices is accepted', () => {
  const judgment = baseJudgment();
  judgment.diagnosis.gate_result = 'wait';
  judgment.diagnosis.gate_trace.find((n) => n.node === 'D4').branch = 'wait';
  judgment.decision = {
    stance: 'wait',
    prices: { activeEntryLimit: null, patientEntryPrice: null, takeProfitPrice: null, stopLossPrice: null },
    conditions: ['等量能'],
    risks: [],
  };
  const result = validateJudgment(judgment, factTable);
  assert.equal(result.ok, true, JSON.stringify(result.errors));
});

test('the program recomputes reward-to-risk instead of trusting the claim', () => {
  const bad = baseJudgment();
  bad.decision.prices.takeProfitPrice = 45200;
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'RR_TOO_LOW'));
});

test('a long plan with the stop above the entry is rejected', () => {
  const bad = baseJudgment();
  bad.decision.prices.stopLossPrice = 46000;
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'PRICE_ORDER'));
});

test('a price invented far from every fact is rejected', () => {
  const bad = baseJudgment();
  bad.decision.prices.patientEntryPrice = 24000;
  const result = validateJudgment(bad, factTable);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some((e) => e.code === 'UNANCHORED_PRICE'));
});

test('report numbers that trace back to the fact table pass', () => {
  const report = '# 大盤\n\n8/11 收 45,120.72,仍高於 20 日均 43,615.12,距高點 47,395.30 尚有距離。';
  const errors = validateReportNumbers(report, factTable, baseJudgment());
  assert.deepEqual(errors, []);
});

test('a number that appears nowhere in the evidence is caught', () => {
  const report = '大盤在 24,633 見高後回落,收 45,120.72。';
  const errors = validateReportNumbers(report, factTable, baseJudgment());
  assert.equal(errors.length, 1);
  assert.equal(errors[0].code, 'UNTRACEABLE_NUMBER');
  assert.match(errors[0].message, /24633|24,633/);
});

test('a number followed by a comma and a short number is not glued into a phantom value', () => {
  const report = '收 45120.72,20 日均 43615.12,量比 0.83。';
  assert.deepEqual(validateReportNumbers(report, factTable, baseJudgment()), []);
});

test('a ticker code is exempt only when it is the subject of the fact table', () => {
  const named = '2330 收 45,120.72,守住 43,615.12。';
  assert.deepEqual(validateReportNumbers(named, { ...factTable, ticker: '2330' }, baseJudgment()), []);

  const unlisted = validateReportNumbers('2454 收 45,120.72。', { ...factTable, ticker: '2330' }, baseJudgment());
  assert.equal(unlisted.length, 1);
  assert.equal(unlisted[0].code, 'UNTRACEABLE_NUMBER');

  const allowed = validateReportNumbers('2454 收 45,120.72。', { ...factTable, ticker: '2330' }, baseJudgment(), { tickers: ['2454'] });
  assert.deepEqual(allowed, []);
});

test('a formatted price is never mistaken for a ticker exemption', () => {
  const errors = validateReportNumbers('目標 2,330 元。', { ...factTable, ticker: '2330' }, baseJudgment());
  assert.equal(errors.length, 1);
  assert.equal(errors[0].code, 'UNTRACEABLE_NUMBER');
});

test('small numbers such as percentages are not treated as price claims', () => {
  const report = '量比 0.83,漲幅 3.5%,共 12 檔候選,收 45,120.72。';
  assert.deepEqual(validateReportNumbers(report, factTable, baseJudgment()), []);
});

test('position-management and guarantee language is banned outright', () => {
  const banned = [
    '建議投入 70% 倉位',
    '可以先買 3 口再加碼',
    '把停損移到成本價',
    '這檔保證會漲',
    '穩賺不賠',
  ];
  for (const text of banned) {
    const errors = scanForbiddenContent(text);
    assert.ok(errors.length > 0, `expected a ban for: ${text}`);
    assert.equal(errors[0].code, 'FORBIDDEN_CONTENT');
  }
  assert.deepEqual(scanForbiddenContent('等回測 43,615 止穩再分批觀察,失守則本次假設失效。'), []);
});

test('retry feedback classifies the failures and forbids gaming the validator', () => {
  const bad = baseJudgment();
  bad.diagnosis.regime = 'super_bull';
  bad.diagnosis.cited_facts.F1 = 45999;
  bad.diagnosis.gate_trace = bad.diagnosis.gate_trace.filter((n) => n.node !== 'D3');
  const { errors } = validateJudgment(bad, factTable);
  const feedback = buildRetryFeedback(errors);

  assert.ok(feedback.categories.includes('schema'));
  assert.ok(feedback.categories.includes('missing'));
  assert.ok(feedback.categories.includes('untraceable'));
  assert.match(feedback.message, /D3/);
  assert.equal(feedback.forbiddenFixes.length, 2);
  assert.match(feedback.forbiddenFixes.join(' '), /regime/);
  assert.match(feedback.forbiddenFixes.join(' '), /cited_facts/);
});
