import test from 'node:test';
import assert from 'node:assert/strict';
import { financialDatasetsGet } from '../src/financial-datasets.js';

test('financialDatasetsGet sends API key header and query params', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url, init) => {
      assert.equal(String(url), 'https://api.example.test/prices/snapshot/?ticker=AAPL');
      assert.equal(init.headers['x-api-key'], 'secret');
      return new Response(JSON.stringify({ prices: [{ ticker: 'AAPL' }] }), { status: 200, headers: { 'content-type': 'application/json' } });
    };
    const result = await financialDatasetsGet('price', { ticker: 'AAPL' }, { env: { FINANCIAL_DATASETS_API_KEY: 'secret', FINANCIAL_DATASETS_BASE_URL: 'https://api.example.test' } });
    assert.equal(result.endpoint, '/prices/snapshot/');
    assert.deepEqual(result.data, { prices: [{ ticker: 'AAPL' }] });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
