import test from 'node:test';
import assert from 'node:assert/strict';
import { ConfigError } from '../src/errors.js';
import { finmindData, fugleMarketData, getFugleCandles, getFugleConfig, getFugleQuote, getFugleSnapshot, getTaiwanNews, getTaiwanPrice, listTaiwanEndpoints, taiwanProviderEnvelope, tpexOpenApi, twseOpenApi } from '../src/taiwan-market.js';
import { renderToolResult } from '../src/tools.js';

test('listTaiwanEndpoints exposes free provider groups', () => {
  const endpoints = listTaiwanEndpoints();
  assert.equal(endpoints.finmind.datasets.price, 'TaiwanStockPrice');
  assert.equal(endpoints.twse.endpoints.price, '/exchangeReport/STOCK_DAY_ALL');
  assert.equal(endpoints.tpex.endpoints.price, '/tpex_mainboard_daily_close_quotes');
  assert.equal(endpoints.fugle.endpoints.quote, '/intraday/quote/{symbol}');
  assert.ok(endpoints.mops.twse.announcements);
});

test('taiwanProviderEnvelope preserves source metadata and rows for evidence collection', () => {
  assert.deepEqual(taiwanProviderEnvelope({
    source: 'finmind',
    url: 'https://api.test/data',
    data: [{ stock_id: '2330' }],
  }, '2026-01-03T00:00:00+08:00'), {
    source: 'finmind',
    sourceUrl: 'https://api.test/data',
    fetchedAt: '2026-01-03T00:00:00+08:00',
    rows: [{ stock_id: '2330' }],
  });
});

test('finmindData builds v4 data URL and optional token', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      assert.equal(String(url), 'https://api.test/api/v4/data?dataset=TaiwanStockPrice&data_id=2330&start_date=2024-01-01&token=t');
      return new Response(JSON.stringify({ status: 200, msg: 'success', data: [{ stock_id: '2330' }] }), { status: 200 });
    };
    const result = await finmindData('TaiwanStockPrice', { data_id: '2330', start_date: '2024-01-01' }, { baseUrl: 'https://api.test', token: 't' });
    assert.deepEqual(result.data, [{ stock_id: '2330' }]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('twseOpenApi and tpexOpenApi call official endpoint paths', async () => {
  const originalFetch = globalThis.fetch;
  const seen = [];
  try {
    globalThis.fetch = async (url) => {
      seen.push(String(url));
      return new Response(JSON.stringify([{ Code: '2330' }]), { status: 200 });
    };
    assert.deepEqual((await twseOpenApi('/exchangeReport/STOCK_DAY_ALL', { baseUrl: 'https://twse.test/v1' })).data, [{ Code: '2330' }]);
    assert.deepEqual((await tpexOpenApi('/tpex_mainboard_daily_close_quotes', { baseUrl: 'https://tpex.test/v1' })).data, [{ Code: '2330' }]);
    assert.deepEqual(seen, ['https://twse.test/v1/exchangeReport/STOCK_DAY_ALL', 'https://tpex.test/v1/tpex_mainboard_daily_close_quotes']);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('getTaiwanPrice auto falls through TWSE to TPEx when ticker is OTC', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      if (String(url).includes('twse')) return new Response(JSON.stringify([{ Code: '2330' }]), { status: 200 });
      return new Response(JSON.stringify([{ SecuritiesCompanyCode: '6488', Close: '100' }]), { status: 200 });
    };
    const result = await getTaiwanPrice({ ticker: '6488', provider: 'auto' });
    assert.deepEqual(result.data, [{ SecuritiesCompanyCode: '6488', Close: '100' }]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('getTaiwanNews queries one point-in-time day without unsupported end_date', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      const parsed = new URL(String(url));
      assert.equal(parsed.searchParams.get('dataset'), 'TaiwanStockNews');
      assert.equal(parsed.searchParams.get('data_id'), '2330');
      assert.equal(parsed.searchParams.get('start_date'), '2026-07-14');
      assert.equal(parsed.searchParams.has('end_date'), false);
      return new Response(JSON.stringify({ status: 200, msg: 'success', data: [] }), { status: 200 });
    };
    await getTaiwanNews({ ticker: '2330', startDate: '2026-04-01', endDate: '2026-07-14', limit: 10 });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('tw-price markdown renders Taiwan rows', () => {
  const out = renderToolResult('tw-price', { data: [{ date: '2024-01-02', stock_id: '2330', open: 590, max: 593, min: 589, close: 593, Trading_Volume: 27997826 }] }, 'markdown');
  assert.match(out, /\| Date \| Code \| Name \| Open \| High \| Low \| Close \| Volume \|/);
  assert.match(out, /\| 2024-01-02 \| 2330 \| — \| 590 \| 593 \| 589 \| 593 \| 28.00M \|/);
});

test('Fugle config requires API key and reads env', () => {
  assert.throws(() => getFugleConfig({}), ConfigError);
  assert.deepEqual(getFugleConfig({ FUGLE_API_KEY: 'key', FUGLE_MARKETDATA_BASE_URL: 'https://fugle.test/stock' }), {
    apiKey: 'key',
    baseUrl: 'https://fugle.test/stock',
  });
});

test('fugleMarketData sends X-API-KEY header and query params', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url, init) => {
      assert.equal(String(url), 'https://fugle.test/stock/intraday/quote/2330?type=oddlot');
      assert.equal(init.headers['X-API-KEY'], 'secret');
      return new Response(JSON.stringify({ symbol: '2330', lastPrice: 600 }), { status: 200 });
    };
    const result = await fugleMarketData('/intraday/quote/2330', { type: 'oddlot' }, { baseUrl: 'https://fugle.test/stock', apiKey: 'secret' });
    assert.equal(result.source, 'fugle');
    assert.equal(result.data.lastPrice, 600);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Fugle quote, candles, and snapshot build documented endpoint paths', async () => {
  const originalFetch = globalThis.fetch;
  const seen = [];
  try {
    process.env.FUGLE_API_KEY = 'secret';
    process.env.FUGLE_MARKETDATA_BASE_URL = 'https://fugle.test/stock';
    globalThis.fetch = async (url) => {
      seen.push(String(url));
      return new Response(JSON.stringify({ data: [{ date: '2024-01-01', close: 100 }] }), { status: 200 });
    };
    await getFugleQuote({ ticker: '2330' });
    await getFugleCandles({ ticker: '2330', scope: 'historical', timeframe: 'D', from: '2024-01-01', to: '2024-01-31', limit: 1 });
    await getFugleSnapshot({ market: 'TSE', kind: 'quotes', type: 'COMMONSTOCK', limit: 1 });
    assert.deepEqual(seen, [
      'https://fugle.test/stock/intraday/quote/2330',
      'https://fugle.test/stock/historical/candles/2330?timeframe=D&from=2024-01-01&to=2024-01-31',
      'https://fugle.test/stock/snapshot/quotes/TSE?type=COMMONSTOCK',
    ]);
  } finally {
    delete process.env.FUGLE_API_KEY;
    delete process.env.FUGLE_MARKETDATA_BASE_URL;
    globalThis.fetch = originalFetch;
  }
});



test('fetch failures include provider and URL context without leaking secrets', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => {
      throw new TypeError('fetch failed');
    };
    await assert.rejects(
      () => fugleMarketData('/intraday/quote/2330', {}, { baseUrl: 'https://fugle.test/stock', apiKey: 'secret' }),
      (error) => {
        assert.match(error.message, /fugle request failed before response/);
        assert.match(error.message, /\/intraday\/quote\/2330/);
        assert.doesNotMatch(error.message, /secret/);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('fugle-quote markdown renders realtime quote fields', () => {
  const out = renderToolResult('fugle-quote', { data: { date: '2026-05-26', symbol: '2330', name: '台積電', lastPrice: 2310, change: 55, changePercent: 2.44, openPrice: 2275, highPrice: 2310, lowPrice: 2275, total: { tradeVolume: 28250 } } }, 'markdown');
  assert.match(out, /\| Date \| Code \| Name \| Last \| Change \| Change % \|/);
  assert.match(out, /\| 2026-05-26 \| 2330 \| 台積電 \| 2310 \| 55 \| 2.44 \|/);
});
