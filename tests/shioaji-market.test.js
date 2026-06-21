import test from 'node:test';
import assert from 'node:assert/strict';
import { ConfigError } from '../src/errors.js';
import { assertOrderAllowed, isOrderEnabled } from '../src/order-guard.js';
import {
  getShioajiConfig,
  getShioajiContract,
  getShioajiContracts,
  getShioajiDailyQuotes,
  getShioajiKbars,
  getShioajiOrderBook,
  getShioajiSnapshot,
  getShioajiSnapshots,
  getShioajiTicks,
  normalizeShioajiKbars,
  normalizeShioajiSnapshot,
  normalizeShioajiDailyQuotes,
  parseSseJsonEvents,
} from '../src/shioaji-market.js';
import { renderToolResult, runTool } from '../src/tools.js';

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } });
}

function sseResponse(text) {
  return new Response(text, { status: 200, headers: { 'content-type': 'text/event-stream' } });
}

test('Shioaji config uses local server base URL without requiring order credentials', () => {
  assert.deepEqual(getShioajiConfig({ SHIOAJI_SERVER_BASE_URL: 'http://localhost:8080' }), {
    baseUrl: 'http://localhost:8080',
  });
  assert.deepEqual(getShioajiConfig({}), { baseUrl: 'http://localhost:8080' });
});

test('normalizeShioajiSnapshot exposes realtime price, volume, and limit-up status', () => {
  const normalized = normalizeShioajiSnapshot({
    datetime: '2026-06-18T12:10:00',
    code: '2327',
    exchange: 'TSE',
    close: 1080,
    buy_price: 0,
    sell_price: 0,
    open: 1015,
    high: 1080,
    low: 974,
    total_volume: 79122,
    volume: 2,
    change_price: 96,
    change_rate: 9.76,
    change_type: 'LimitUp',
  });

  assert.equal(normalized.code, '2327');
  assert.equal(normalized.lastPrice, 1080);
  assert.equal(normalized.totalVolume, 79122);
  assert.equal(normalized.limitStatus.isLimitUp, true);
  assert.equal(normalized.limitStatus.isLimitDown, false);
  assert.equal(normalized.orderLocked, true);
});

test('getShioajiSnapshot posts read-only snapshots request and normalizes first row', async () => {
  const seen = [];
  const fetchImpl = async (url, init) => {
    seen.push({ url: String(url), body: JSON.parse(init.body), method: init.method });
    return jsonResponse({ data: [{ code: '2330', exchange: 'TSE', close: 2390, total_volume: 16277, change_type: 'Up' }] });
  };

  const result = await getShioajiSnapshot({ ticker: '2330' }, { fetchImpl, env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' } });

  assert.deepEqual(seen, [{
    url: 'http://sj.test/api/v1/data/snapshots',
    method: 'POST',
    body: { contracts: [{ security_type: 'STK', exchange: 'TSE', code: '2330' }] },
  }]);
  assert.equal(result.readOnly, true);
  assert.equal(result.data.lastPrice, 2390);
  assert.equal(result.data.totalVolume, 16277);
});

test('getShioajiSnapshots chunks batch requests at 500 contracts for full-market scans', async () => {
  const calls = [];
  const tickers = Array.from({ length: 501 }, (_, index) => String(1101 + index));
  const fetchImpl = async (url, init) => {
    const body = JSON.parse(init.body);
    calls.push({ url: String(url), contracts: body.contracts });
    return jsonResponse({ data: body.contracts.map((contract) => ({
      code: contract.code,
      exchange: contract.exchange,
      close: Number(contract.code),
      total_volume: 1000,
    })) });
  };

  const result = await getShioajiSnapshots({ tickers, exchange: 'TSE', chunkSize: 500 }, {
    fetchImpl,
    env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' },
  });

  assert.equal(calls.length, 2);
  assert.equal(calls[0].contracts.length, 500);
  assert.equal(calls[1].contracts.length, 1);
  assert.equal(result.readOnly, true);
  assert.equal(result.data.length, 501);
  assert.equal(result.data[500].code, tickers[500]);
});

test('getShioajiContract fetches a stock contract from the local server', async () => {
  const fetchImpl = async (url, init) => {
    assert.equal(init, undefined);
    assert.equal(String(url), 'http://sj.test/api/v1/data/contracts/2330?security_type=STK');
    return jsonResponse({
      security_type: 'STK',
      exchange: 'TSE',
      code: '2330',
      symbol: 'TSE2330',
      name: '台積電',
      unit: 1000,
      update_date: '2026/06/18',
    });
  };

  const result = await getShioajiContract({ ticker: '2330' }, {
    fetchImpl,
    env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' },
  });

  assert.equal(result.readOnly, true);
  assert.deepEqual(result.data, {
    securityType: 'STK',
    exchange: 'TSE',
    code: '2330',
    symbol: 'TSE2330',
    name: '台積電',
    unit: 1000,
    updateDate: '2026/06/18',
    raw: {
      security_type: 'STK',
      exchange: 'TSE',
      code: '2330',
      symbol: 'TSE2330',
      name: '台積電',
      unit: 1000,
      update_date: '2026/06/18',
    },
  });
});

test('getShioajiContracts queries paginated stock contracts', async () => {
  const fetchImpl = async (url, init) => {
    assert.equal(String(url), 'http://sj.test/api/v1/data/contracts');
    assert.deepEqual(JSON.parse(init.body), { security_type: 'STK', page: 1, page_size: 2 });
    return jsonResponse({
      security_type: 'STK',
      page: 1,
      page_size: 2,
      max_page: 1,
      total: 2,
      contracts: [
        { security_type: 'STK', exchange: 'TSE', code: '2330', symbol: 'TSE2330', name: '台積電', unit: 1000, update_date: '2026/06/18' },
        { security_type: 'STK', exchange: 'OTC', code: '6274', symbol: 'OTC6274', name: '台燿', unit: 1000, update_date: '2026/06/18' },
      ],
    });
  };

  const result = await getShioajiContracts({ securityType: 'STK', page: 1, pageSize: 2 }, {
    fetchImpl,
    env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' },
  });

  assert.equal(result.readOnly, true);
  assert.equal(result.total, 2);
  assert.deepEqual(result.data.map((row) => [row.code, row.exchange, row.name]), [
    ['2330', 'TSE', '台積電'],
    ['6274', 'OTC', '台燿'],
  ]);
});

test('getShioajiDailyQuotes fetches full-market daily OHLCV rows for one date', async () => {
  const fetchImpl = async (url, init) => {
    assert.equal(String(url), 'http://sj.test/api/v1/data/daily_quotes');
    assert.deepEqual(JSON.parse(init.body), { date: '2026-04-01' });
    return jsonResponse({
      Date: ['2026-04-01', '2026-04-01'],
      Code: ['2330', '2317'],
      Open: [1840, 160],
      High: [1850, 162],
      Low: [1830, 158],
      Close: [1845, 161],
      Volume: [1000, 2000],
      Amount: [1845000, 322000],
      Transaction: [100, 200],
    });
  };

  const result = await getShioajiDailyQuotes({ date: '2026-04-01' }, {
    fetchImpl,
    env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' },
  });

  assert.equal(result.readOnly, true);
  assert.deepEqual(result.data.rows, [
    { date: '2026-04-01', code: '2330', open: 1840, high: 1850, low: 1830, close: 1845, volume: 1000, amount: 1845000, transaction: 100 },
    { date: '2026-04-01', code: '2317', open: 160, high: 162, low: 158, close: 161, volume: 2000, amount: 322000, transaction: 200 },
  ]);
});

test('normalizeShioajiDailyQuotes zips quote arrays into row objects', () => {
  assert.deepEqual(normalizeShioajiDailyQuotes({
    Date: ['2026-04-01'],
    Code: ['2330'],
    Open: [1],
    High: [2],
    Low: [0.5],
    Close: [1.5],
    Volume: [10],
    Amount: [15],
    Transaction: [2],
  }), [
    { date: '2026-04-01', code: '2330', open: 1, high: 2, low: 0.5, close: 1.5, volume: 10, amount: 15, transaction: 2 },
  ]);
});

test('getShioajiKbars posts date range and normalizes OHLCV rows', async () => {
  const fetchImpl = async (url, init) => {
    assert.equal(String(url), 'http://sj.test/api/v1/data/kbars');
    assert.deepEqual(JSON.parse(init.body), {
      contract: { security_type: 'STK', exchange: 'TSE', code: '2330' },
      start: '2026-04-01',
      end: '2026-04-02',
    });
    return jsonResponse({
      datetime: ['2026-04-01T09:00:00', '2026-04-02T09:00:00'],
      Open: [100, 104],
      High: [105, 108],
      Low: [99, 103],
      Close: [104, 107],
      Volume: [1000, 2000],
      Amount: [104000, 214000],
    });
  };

  const result = await getShioajiKbars({
    ticker: '2330',
    start: '2026-04-01',
    end: '2026-04-02',
  }, {
    fetchImpl,
    env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' },
  });

  assert.equal(result.readOnly, true);
  assert.deepEqual(result.data.rows, [
    { datetime: '2026-04-01T09:00:00', date: '2026-04-01', open: 100, high: 105, low: 99, close: 104, volume: 1000, amount: 104000 },
    { datetime: '2026-04-02T09:00:00', date: '2026-04-02', open: 104, high: 108, low: 103, close: 107, volume: 2000, amount: 214000 },
  ]);
});

test('normalizeShioajiKbars accepts lowercase and nested data payloads', () => {
  assert.deepEqual(normalizeShioajiKbars({ data: {
    ts: ['2026-04-01T09:00:00'],
    open: [10],
    high: [11],
    low: [9],
    close: [10.5],
    volume: [123],
    amount: [1291.5],
  } }), [
    { datetime: '2026-04-01T09:00:00', date: '2026-04-01', open: 10, high: 11, low: 9, close: 10.5, volume: 123, amount: 1291.5 },
  ]);
});

test('parseSseJsonEvents extracts JSON payloads from Shioaji SSE text', () => {
  const events = parseSseJsonEvents('event:bidask_stk\ndata:{"code":"2330","bid_price":["2385"],"ask_price":["2390"]}\n\n: heartbeat\n\nevent:tick_stk\ndata:{"code":"2330","close":"2390"}\n\n');

  assert.deepEqual(events, [
    { event: 'bidask_stk', data: { code: '2330', bid_price: ['2385'], ask_price: ['2390'] } },
    { event: 'tick_stk', data: { code: '2330', close: '2390' } },
  ]);
});

test('getShioajiOrderBook subscribes to bidask stream and always unsubscribes', async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined });
    if (String(url).endsWith('/api/v1/stream/data/bidask_stk')) {
      return sseResponse('event:bidask_stk\ndata:{"code":"2330","date":"2026-06-18","time":"12:10:00","bid_price":["2385","2380"],"bid_volume":[12,34],"diff_bid_vol":[1,0],"ask_price":["2390","2395"],"ask_volume":[5,6],"diff_ask_vol":[0,-1],"suspend":false}\n\n');
    }
    return jsonResponse({ ok: true });
  };

  const result = await getShioajiOrderBook({ ticker: '2330', timeoutMs: 1000 }, { fetchImpl, env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' } });

  assert.equal(result.data.code, '2330');
  assert.deepEqual(result.data.bids[0], { price: 2385, volume: 12, diffVolume: 1 });
  assert.deepEqual(result.data.asks[1], { price: 2395, volume: 6, diffVolume: -1 });
  assert.deepEqual(calls.map((call) => [call.method, call.url]), [
    ['POST', 'http://sj.test/api/v1/stream/subscribe'],
    ['GET', 'http://sj.test/api/v1/stream/data/bidask_stk'],
    ['POST', 'http://sj.test/api/v1/stream/unsubscribe'],
  ]);
  assert.equal(calls[0].body.quote_type, 'BidAsk');
  assert.equal(calls[2].body.quote_type, 'BidAsk');
});

test('getShioajiTicks posts LastCount query and zips tick arrays into rows', async () => {
  const fetchImpl = async (url, init) => {
    assert.equal(String(url), 'http://sj.test/api/v1/data/ticks');
    assert.deepEqual(JSON.parse(init.body), {
      contract: { security_type: 'STK', exchange: 'TSE', code: '2330' },
      date: '2026-06-18',
      query_type: 'LastCount',
      last_cnt: 2,
    });
    return jsonResponse({ datetime: ['2026-06-18T13:24:56', '2026-06-18T13:30:00'], close: [2385, 2390], volume: [1, 2], bid_price: [2380, 2385], bid_volume: [10, 11], ask_price: [2390, 2395], ask_volume: [5, 6], tick_type: [1, 2] });
  };

  const result = await getShioajiTicks({ ticker: '2330', date: '2026-06-18', last: 2 }, { fetchImpl, env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' } });

  assert.equal(result.data.queryType, 'LastCount');
  assert.deepEqual(result.data.ticks, [
    { datetime: '2026-06-18T13:24:56', close: 2385, volume: 1, bidPrice: 2380, bidVolume: 10, askPrice: 2390, askVolume: 5, tickType: 1 },
    { datetime: '2026-06-18T13:30:00', close: 2390, volume: 2, bidPrice: 2385, bidVolume: 11, askPrice: 2395, askVolume: 6, tickType: 2 },
  ]);
});

test('Shioaji tools render quote markdown and keep all operations read-only', async () => {
  const originalFetch = globalThis.fetch;
  try {
    process.env.SHIOAJI_SERVER_BASE_URL = 'http://sj.test';
    globalThis.fetch = async () => jsonResponse({ data: [{ code: '2327', exchange: 'TSE', close: 1080, buy_price: 0, sell_price: 0, total_volume: 79122, change_type: 'LimitUp' }] });

    const result = await runTool('shioaji-quote', { ticker: '2327' });
    assert.equal(result.readOnly, true);
    assert.equal(result.data.limitStatus.isLimitUp, true);
    const out = renderToolResult('shioaji-quote', result, 'markdown');
    assert.match(out, /\| Code \| Last \| Bid \| Ask \| Volume \| Limit \|/);
    assert.match(out, /\| 2327 \| 1080 \| 0 \| 0 \| 79.12K \| 漲停 \|/);
  } finally {
    delete process.env.SHIOAJI_SERVER_BASE_URL;
    globalThis.fetch = originalFetch;
  }
});

test('order guard rejects live orders unless two explicit env switches are present', () => {
  assert.equal(isOrderEnabled({}), false);
  assert.equal(isOrderEnabled({ TRADE_ORDER_ENABLED: '1', TRADE_ORDER_CONFIRM: 'I_UNDERSTAND_LIVE_ORDER_RISK' }), true);
  assert.throws(() => assertOrderAllowed({}, 'place-order'), ConfigError);
  assert.doesNotThrow(() => assertOrderAllowed({ TRADE_ORDER_ENABLED: '1', TRADE_ORDER_CONFIRM: 'I_UNDERSTAND_LIVE_ORDER_RISK' }, 'place-order'));
});
