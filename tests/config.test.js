import test from 'node:test';
import assert from 'node:assert/strict';
import { getFinancialDatasetsConfig } from '../src/config.js';
import { ConfigError } from '../src/errors.js';

test('missing API key fails with clear config error', () => {
  assert.throws(() => getFinancialDatasetsConfig({}), ConfigError);
});

test('config reads API key and optional base URL', () => {
  assert.deepEqual(getFinancialDatasetsConfig({ FINANCIAL_DATASETS_API_KEY: 'k', FINANCIAL_DATASETS_BASE_URL: 'https://example.test' }), {
    apiKey: 'k',
    baseUrl: 'https://example.test',
  });
});
