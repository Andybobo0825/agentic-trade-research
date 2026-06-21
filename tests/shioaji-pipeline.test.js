import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { cacheShioajiDailyQuotes, cacheShioajiKbars, shioajiDailyQuoteCachePath, shioajiKbarCachePath } from '../src/shioaji-pipeline.js';

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } });
}

test('cacheShioajiKbars writes one local cache file per ticker and reports failures', async () => {
  const cacheDir = await fs.mkdtemp(path.join(os.tmpdir(), 'shioaji-cache-'));
  const calls = [];
  const fetchImpl = async (url, init) => {
    const body = JSON.parse(init.body);
    calls.push(body.contract.code);
    if (body.contract.code === '9999') {
      return jsonResponse({ error: 'not found' }, 404);
    }
    return jsonResponse({
      datetime: ['2026-04-01T09:00:00'],
      Open: [100],
      High: [105],
      Low: [99],
      Close: [104],
      Volume: [1000],
      Amount: [104000],
    });
  };

  const result = await cacheShioajiKbars({
    tickers: ['2330', '9999'],
    start: '2026-04-01',
    end: '2026-04-01',
    cacheDir,
  }, {
    fetchImpl,
    env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' },
  });

  assert.deepEqual(calls, ['2330', '9999']);
  assert.equal(result.ok.length, 1);
  assert.equal(result.failed.length, 1);
  assert.equal(result.ok[0].code, '2330');
  assert.equal(result.ok[0].rows, 1);
  assert.equal(result.failed[0].code, '9999');

  const cached = JSON.parse(await fs.readFile(shioajiKbarCachePath({
    cacheDir,
    ticker: '2330',
    start: '2026-04-01',
    end: '2026-04-01',
  }), 'utf8'));
  assert.equal(cached.source, 'shioaji');
  assert.equal(cached.code, '2330');
  assert.equal(cached.rows[0].close, 104);
});

test('cacheShioajiKbars reuses existing cache unless refresh is requested', async () => {
  const cacheDir = await fs.mkdtemp(path.join(os.tmpdir(), 'shioaji-cache-'));
  await fs.mkdir(path.join(cacheDir, 'kbars'), { recursive: true });
  const file = shioajiKbarCachePath({ cacheDir, ticker: '2330', start: '2026-04-01', end: '2026-04-01' });
  await fs.writeFile(file, JSON.stringify({ source: 'shioaji', code: '2330', rows: [{ close: 100 }] }));

  let calls = 0;
  const result = await cacheShioajiKbars({
    tickers: ['2330'],
    start: '2026-04-01',
    end: '2026-04-01',
    cacheDir,
  }, {
    fetchImpl: async () => {
      calls += 1;
      return jsonResponse({});
    },
  });

  assert.equal(calls, 0);
  assert.equal(result.cached.length, 1);
  assert.equal(result.cached[0].code, '2330');
});

test('cacheShioajiDailyQuotes writes one full-market daily quote file per date', async () => {
  const cacheDir = await fs.mkdtemp(path.join(os.tmpdir(), 'shioaji-daily-cache-'));
  const calls = [];
  const fetchImpl = async (url, init) => {
    const body = JSON.parse(init.body);
    calls.push(body.date);
    return jsonResponse({
      Date: [body.date],
      Code: ['2330'],
      Open: [100],
      High: [105],
      Low: [99],
      Close: [104],
      Volume: [1000],
      Amount: [104000],
      Transaction: [100],
    });
  };

  const result = await cacheShioajiDailyQuotes({
    dates: ['2026-04-01', '2026-04-02'],
    cacheDir,
  }, {
    fetchImpl,
    env: { SHIOAJI_SERVER_BASE_URL: 'http://sj.test' },
  });

  assert.deepEqual(calls, ['2026-04-01', '2026-04-02']);
  assert.equal(result.ok.length, 2);
  const cached = JSON.parse(await fs.readFile(shioajiDailyQuoteCachePath({ cacheDir, date: '2026-04-01' }), 'utf8'));
  assert.equal(cached.source, 'shioaji');
  assert.equal(cached.date, '2026-04-01');
  assert.equal(cached.rows[0].code, '2330');
  assert.equal(cached.rows[0].close, 104);
});
