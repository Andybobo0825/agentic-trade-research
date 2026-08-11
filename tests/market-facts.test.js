import test from 'node:test';
import assert from 'node:assert/strict';
import { computeMarketFacts, renderMarketDiagnosisMarkdown } from '../src/market-facts.js';

function dateAt(index) {
  return new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10);
}

function bar(date, open, high, low, close, money = 1_000_000_000) {
  return { date, open, max: high, min: low, close, Trading_money: money };
}

function seriesFrom(startClose, steps, { offset = 0, bodyPct = 0.01, range = 1.6 } = {}) {
  const rows = [];
  let close = startClose;
  for (let i = 0; i < steps.length; i += 1) {
    const open = close;
    close = open * (1 + steps[i] * bodyPct);
    const high = Math.max(open, close) + Math.abs(close - open) * (range - 1) / 2;
    const low = Math.min(open, close) - Math.abs(close - open) * (range - 1) / 2;
    rows.push(bar(dateAt(offset + i), open, high, low, close));
  }
  return rows;
}

function flatSeries(count, price = 100, offset = 0) {
  const rows = [];
  for (let i = 0; i < count; i += 1) {
    const wobble = (i % 2 === 0 ? 1 : -1) * 0.004;
    rows.push(bar(dateAt(offset + i), price * (1 - wobble), price * 1.012, price * 0.988, price * (1 + wobble)));
  }
  return rows;
}

test('insufficient data is its own regime and never guesses a direction', () => {
  const result = computeMarketFacts(flatSeries(10), { ticker: 'TEST' });
  assert.equal(result.regime.label, 'insufficient_data');
  assert.equal(result.regime.direction, 'neutral');
  assert.equal(result.regime.confidence, 10);
  assert.ok(result.facts.some((f) => f.key === 'insufficient'));
});

test('fact ids are stable and every fact carries a window and description', () => {
  const rows = flatSeries(70);
  const a = computeMarketFacts(rows, { ticker: 'TEST' });
  const b = computeMarketFacts(rows, { ticker: 'TEST' });
  assert.deepEqual(a.facts.map((f) => f.id), b.facts.map((f) => f.id));
  assert.deepEqual(a.facts.map((f) => f.key), b.facts.map((f) => f.key));
  for (const fact of a.facts) {
    assert.match(fact.id, /^F\d+$/);
    assert.ok(['background', 'structure', 'immediate'].includes(fact.window), `bad window ${fact.window}`);
    assert.ok(fact.desc && fact.desc.length > 0);
  }
});

test('row order does not change the fact table', () => {
  const rows = flatSeries(70);
  const ascending = computeMarketFacts(rows, { ticker: 'TEST' });
  const descending = computeMarketFacts([...rows].reverse(), { ticker: 'TEST' });
  assert.equal(descending.asOf, ascending.asOf);
  assert.deepEqual(
    descending.facts.map((f) => [f.key, f.value]),
    ascending.facts.map((f) => [f.key, f.value]),
  );
});

test('moving averages and turnover ratios are computed from the raw rows', () => {
  const rows = flatSeries(70, 100).map((row, index) => ({ ...row, Trading_money: index === 69 ? 2_000_000_000 : 1_000_000_000 }));
  const result = computeMarketFacts(rows, { ticker: 'TEST' });
  const value = (key) => result.facts.find((f) => f.key === key)?.value;
  assert.equal(value('close'), rows[69].close);
  assert.ok(Math.abs(value('ma20') - 100) < 0.5);
  assert.equal(value('turnover'), 2_000_000_000);
  assert.ok(Math.abs(value('turnoverRatio') - 2_000_000_000 / value('avgTurnover20')) < 1e-9);
});

test('a run of wide same-direction bodies with little overlap is a spike', () => {
  const rows = [...flatSeries(60, 100), ...seriesFrom(100, [3, 3, 3, 3], { offset: 60, bodyPct: 0.02, range: 1.1 })];
  const result = computeMarketFacts(rows, { ticker: 'TEST' });
  assert.equal(result.regime.label, 'spike');
  assert.equal(result.regime.direction, 'bullish');
  assert.ok(result.regime.evidence.length > 0);
  for (const id of result.regime.evidence) {
    assert.ok(result.facts.some((f) => f.id === id), `evidence ${id} missing from facts`);
  }
});

test('a shallow pullback above a rising mean is a tight channel', () => {
  const rows = [];
  let price = 100;
  for (let i = 0; i < 60; i += 1) {
    const leg = i % 5 === 4 ? -0.5 : 1;
    const open = price;
    price = open * (1 + leg * 0.01);
    rows.push(bar(dateAt(i), open, Math.max(open, price) * 1.001, Math.min(open, price) * 0.999, price));
  }
  const result = computeMarketFacts(rows, { ticker: 'TEST' });
  assert.equal(result.regime.label, 'tight_channel');
  assert.equal(result.regime.direction, 'bullish');
  const depth = result.facts.find((f) => f.key === 'pullbackDepthPct');
  assert.ok(depth.value < 30, `expected shallow pullback, got ${depth.value}`);
});

test('a deeper but still trending pullback is a normal channel', () => {
  const rows = [];
  let price = 100;
  for (let i = 0; i < 60; i += 1) {
    const leg = i % 6 >= 4 ? -0.8 : 1;
    const open = price;
    price = open * (1 + leg * 0.01);
    rows.push(bar(dateAt(i), open, Math.max(open, price) * 1.001, Math.min(open, price) * 0.999, price));
  }
  const result = computeMarketFacts(rows, { ticker: 'TEST' });
  assert.equal(result.regime.label, 'normal_channel');
  const depth = result.facts.find((f) => f.key === 'pullbackDepthPct');
  assert.ok(depth.value >= 30 && depth.value <= 50, `expected mid pullback, got ${depth.value}`);
});

test('overlapping bars around a flat mean fall through to a trading range', () => {
  const result = computeMarketFacts(flatSeries(60), { ticker: 'TEST' });
  assert.equal(result.regime.label, 'trading_range');
});

test('confidence drops when the immediate window fights the structure window', () => {
  const trending = [];
  let price = 100;
  for (let i = 0; i < 60; i += 1) {
    const leg = i % 5 === 2 ? -0.5 : 1;
    const open = price;
    price = open * (1 + leg * 0.01);
    trending.push(bar(dateAt(i), open, Math.max(open, price) * 1.001, Math.min(open, price) * 0.999, price));
  }
  // Two indecisive down bars: enough to point the immediate window the other way,
  // not enough (long wicks, only two of them) to reclassify the regime as a spike.
  const hesitant = [];
  let last = trending[trending.length - 1].close;
  for (let i = 0; i < 2; i += 1) {
    const open = last;
    last = open * 0.997;
    hesitant.push(bar(dateAt(60 + i), open, open * 1.006, last * 0.994, last));
  }

  const aligned = computeMarketFacts(trending, { ticker: 'TEST' });
  const conflicted = computeMarketFacts([...trending, ...hesitant], { ticker: 'TEST' });

  assert.equal(aligned.regime.direction, 'bullish');
  assert.equal(conflicted.regime.label, aligned.regime.label);
  assert.equal(conflicted.regime.direction, 'bullish');
  assert.ok(
    conflicted.regime.confidence < aligned.regime.confidence,
    `expected a penalty, got ${conflicted.regime.confidence} vs ${aligned.regime.confidence}`,
  );
  assert.ok(conflicted.regime.confidence >= 10 && aligned.regime.confidence <= 95);
});

test('windows declare their roles so background can never overrule structure', () => {
  const result = computeMarketFacts(flatSeries(70), { ticker: 'TEST' });
  assert.equal(result.windows.background.role, 'risk-context');
  assert.equal(result.windows.structure.role, 'direction');
  assert.equal(result.windows.immediate.role, 'signal-quality');
  assert.equal(result.factTableVersion, 1);
});

test('every regime carries a playbook that points back at repo guidance', () => {
  const result = computeMarketFacts(flatSeries(60), { ticker: 'TEST' });
  assert.equal(result.playbook.regime, result.regime.label);
  assert.ok(result.playbook.guidance.length > 0);
  assert.ok(result.playbook.refs.includes('docs/standard-workflow-v1.md'));
});

test('markdown renders the fact table with ids so a report can cite them', () => {
  const result = computeMarketFacts(flatSeries(70), { ticker: 'TEST' });
  const markdown = renderMarketDiagnosisMarkdown(result);
  assert.match(markdown, /F1/);
  assert.match(markdown, /Regime/);
  assert.match(markdown, /trading_range|tight_channel|normal_channel|spike|insufficient_data/);
});

test('a counter-move larger than its leg is not a pullback and lands in a range', () => {
  // Legs of 40/8 up, 4 down, 4 up, then a 4-bar drop larger than the leg it retraces.
  // Wide wicks keep the tail from qualifying as a spike, so the depth decides the label.
  const legs = [[40, 1], [8, 1], [4, -1.5], [4, 1], [4, -1.2]];
  const rows = [];
  let price = 100;
  let index = 0;
  for (const [count, step] of legs) {
    for (let i = 0; i < count; i += 1) {
      const open = price;
      price = open * (1 + step * 0.01);
      const body = Math.abs(price - open);
      rows.push(bar(dateAt(index), open, Math.max(open, price) + body, Math.min(open, price) - body, price));
      index += 1;
    }
  }

  const result = computeMarketFacts(rows, { ticker: 'TEST' });
  const depth = result.facts.find((f) => f.key === 'pullbackDepthPct');
  assert.ok(Number.isFinite(depth.value));
  assert.ok(depth.value > 100, `expected an uncapped ratio above 100, got ${depth.value}`);
  assert.equal(result.regime.label, 'trading_range');
});
