import test from 'node:test';
import assert from 'node:assert/strict';
import { access, readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const REMOVED_MODULES = Object.freeze([
  'logistic-regression.js',
  'phase3-walk-forward.js',
  'phase3-demo-promotion.js',
  'phase3-direction-labels.js',
  'phase3-direction-research.js',
  'phase3-main-audit.js',
  'phase3-breadth-context.js',
  'phase3-breadth-role-comparison.js',
  'phase3-hybrid-features.js',
  'phase3-news-features.js',
]);

test('prediction and promotion modules are absent from the source tree', async () => {
  for (const file of REMOVED_MODULES) {
    await assert.rejects(access(join(ROOT, 'src', file)), { code: 'ENOENT' }, file);
  }
});

test('remaining source has no imports or references to the removed model stack', async () => {
  const forbidden = /logistic-regression|phase3-walk-forward|phase3-demo-promotion|phase3-direction|phase3-main-audit|phase3-breadth-role-comparison|phase3-hybrid-features|phase3-news-features/;
  const files = (await readdir(join(ROOT, 'src'))).filter((file) => file.endsWith('.js'));
  const hits = [];
  for (const file of files) {
    const source = await readFile(join(ROOT, 'src', file), 'utf8');
    if (forbidden.test(source)) hits.push(file);
  }
  assert.deepEqual(hits, []);
});

test('the retained Phase 3 entry graph contains no order API vocabulary', async () => {
  const files = [
    'phase3-data-collector.js',
    'phase3-dataset.js',
    'phase3-candidates.js',
    'phase3-filter.js',
    'phase3-screen.js',
  ];
  const forbidden = /placeOrder|updateOrder|cancelOrder|broker-orders|order api/i;
  const hits = [];
  for (const file of files) {
    const source = await readFile(join(ROOT, 'src', file), 'utf8');
    if (forbidden.test(source)) hits.push(file);
  }
  assert.deepEqual(hits, []);
});
