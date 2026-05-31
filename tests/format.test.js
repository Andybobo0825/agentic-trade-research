import test from 'node:test';
import assert from 'node:assert/strict';
import { compactNumber, toMarkdownTable } from '../src/format.js';

test('compactNumber formats finance scale', () => {
  assert.equal(compactNumber(1234567890), '1.23B');
  assert.equal(compactNumber(null), '—');
});

test('toMarkdownTable renders compact table', () => {
  const md = toMarkdownTable([{ ticker: 'AAPL', revenue: 1000 }], [
    { label: 'Ticker', value: (r) => r.ticker },
    { label: 'Revenue', value: (r) => compactNumber(r.revenue) },
  ]);
  assert.match(md, /\| Ticker \| Revenue \|/);
  assert.match(md, /\| AAPL \| 1.00K \|/);
});
