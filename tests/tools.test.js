import test from 'node:test';
import assert from 'node:assert/strict';
import { renderToolResult } from '../src/tools.js';

test('statement markdown renderer gives Codex-friendly table', () => {
  const result = { data: { income_statements: [{ report_period: '2025', revenue: 1234567890, net_income: 1000000 }] } };
  const out = renderToolResult('statement', result, 'markdown');
  assert.match(out, /\| Period \| Revenue \| Net Inc \| FCF \|/);
  assert.match(out, /\| 2025 \| 1.23B \| 1.00M \| — \|/);
});

test('filings markdown renderer includes filing URL field', () => {
  const result = { data: { filings: [{ filing_date: '2026-01-01', filing_type: '10-K', filing_url: 'https://sec.example/filing' }] } };
  const out = renderToolResult('filings', result, 'markdown');
  assert.match(out, /\| Date \| Type \| URL \|/);
  assert.match(out, /https:\/\/sec.example\/filing/);
});


test('compact-json renderer removes pretty-print whitespace', () => {
  const out = renderToolResult('endpoints', { endpoints: { price: '/prices/snapshot/' } }, 'compact-json');
  assert.equal(out, '{"endpoints":{"price":"/prices/snapshot/"}}\n');
});

test('renderer can project output fields without changing fetched payload shape', () => {
  const result = { data: [{ date: '2026-01-01', close: 100, unused: 'large' }] };
  const out = renderToolResult('tw-price', result, 'compact-json', { fields: 'date,close', maxRows: 1 });
  assert.equal(out, '{"data":[{"date":"2026-01-01","close":100}]}\n');
});
