import test from 'node:test';
import assert from 'node:assert/strict';
import { main } from '../src/cli.js';

test('CLI exposes Phase 3 dataset and sole read-only screen commands', async () => {
  const help = await main(['help']);
  assert.match(help, /phase3-dataset/);
  assert.match(help, /phase3-screen/);
  assert.doesNotMatch(help, /phase3-demo-promotion/);

  for (const command of ['phase3-dataset', 'phase3-screen']) {
    await assert.rejects(
      () => main([command, '--live', 'true']),
      /forbids --live/,
    );
  }
});

test('CLI hma-signal passes ticker and period into the tool', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => {
      const data = Array.from({ length: 30 }, (_, index) => ({ date: `2026-01-${String(index + 1).padStart(2, '0')}`, stock_id: '2330', close: index + 1 }));
      return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
    };
    const out = await main(['hma-signal', '--ticker', '2330', '--market', 'tw', '--source', 'finmind', '--period', '9', '--start-date', '2026-01-01', '--format', 'markdown']);
    assert.match(out, /# HMA trend signal: 2330/);
    assert.match(out, /Period: 9/);
    assert.match(out, /偏多續抱/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('CLI signal-study passes study parameters into the tool', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      const text = String(url);
      if (text.includes('TaiwanStockPrice')) {
        const data = Array.from({ length: 30 }, (_, index) => ({
          date: `2026-02-${String(index + 1).padStart(2, '0')}`,
          stock_id: '2330',
          close: index + 10,
          Trading_Volume: index === 29 ? 8000 : 1000,
        }));
        return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
      }
      if (text.includes('TaiwanStockInstitutionalInvestorsBuySell')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [{ date: '2026-02-28', stock_id: '2330', buy: 2000, sell: 1000 }] }), { status: 200 });
      }
      throw new Error(`Unexpected URL ${text}`);
    };
    const out = await main(['signal-study', '--ticker', '2330', '--market', 'tw', '--period', '9', '--start-date', '2026-02-01', '--volume-window', '5', '--institutional-days', '3', '--forward-days', '3,5,10', '--format', 'markdown']);
    assert.match(out, /# Signal study: 2330/);
    assert.match(out, /HMA 訊號/);
    assert.match(out, /買訊後 3\/5\/10 日表現/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('CLI daily-decision-study renders point-in-time frames', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => {
      const data = Array.from({ length: 32 }, (_, index) => {
        const close = 20 + index * 0.4;
        return {
          date: `2026-03-${String(index + 1).padStart(2, '0')}`,
          stock_id: '2330',
          open: close - 0.1,
          max: close + 0.2,
          min: close - 0.2,
          close,
          Trading_Volume: 2_000_000,
        };
      });
      return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
    };
    const out = await main([
      'daily-decision-study',
      '--ticker', '2330',
      '--market', 'tw',
      '--period', '9',
      '--start-date', '2026-03-01',
      '--decision-days', '2',
      '--lookback-bars', '20',
      '--min-average-turnover', '10000000',
      '--format', 'markdown',
    ]);
    assert.match(out, /# Daily decision study: 2330/);
    assert.match(out, /Point-in-time Codex frames: 2/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('CLI chip-study renders chip strategy research flow', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      const text = String(url);
      if (text.includes('TaiwanStockPrice')) {
        const data = Array.from({ length: 32 }, (_, index) => {
          const close = 30 + index * 0.5;
          return {
            date: `2026-05-${String(index + 1).padStart(2, '0')}`,
            stock_id: '2330',
            open: close - 0.1,
            max: close + 0.2,
            min: close - 0.2,
            close,
            Trading_Volume: 3_000_000,
          };
        });
        return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
      }
      if (text.includes('TaiwanStockInstitutionalInvestorsBuySell')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [
          { date: '2026-05-28', stock_id: '2330', name: 'Foreign_Investor', buy: 2000, sell: 1000 },
          { date: '2026-05-29', stock_id: '2330', name: 'Foreign_Investor', buy: 2100, sell: 1000 },
          { date: '2026-05-30', stock_id: '2330', name: 'Foreign_Investor', buy: 2200, sell: 1000 },
        ] }), { status: 200 });
      }
      if (text.includes('TaiwanStockHoldingSharesPer')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [
          { date: '2026-05-15', stock_id: '2330', HoldingSharesLevel: '1000-5000', percent: 20, people: 10, unit: 1000 },
          { date: '2026-05-22', stock_id: '2330', HoldingSharesLevel: '1000-5000', percent: 21, people: 11, unit: 1100 },
          { date: '2026-05-29', stock_id: '2330', HoldingSharesLevel: '1000-5000', percent: 22, people: 12, unit: 1200 },
        ] }), { status: 200 });
      }
      if (text.includes('TaiwanStockInfo')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [{ stock_id: '2330', stock_name: '台積電', industry_category: '半導體業' }] }), { status: 200 });
      }
      throw new Error(`Unexpected URL ${text}`);
    };
    const out = await main([
      'chip-study',
      '--ticker', '2330',
      '--market', 'tw',
      '--period', '9',
      '--start-date', '2026-05-01',
      '--foreign-days', '3',
      '--holder-weeks', '3',
      '--format', 'markdown',
    ]);
    assert.match(out, /# Chip study: 2330/);
    assert.match(out, /籌碼門檻/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('CLI shioaji-quote renders read-only realtime snapshot', async () => {
  const originalFetch = globalThis.fetch;
  try {
    process.env.SHIOAJI_SERVER_BASE_URL = 'http://sj.test';
    globalThis.fetch = async (url, init) => {
      assert.equal(String(url), 'http://sj.test/api/v1/data/snapshots');
      assert.equal(JSON.parse(init.body).contracts[0].code, '2327');
      return new Response(JSON.stringify({ data: [{ code: '2327', close: 1080, buy_price: 0, sell_price: 0, total_volume: 79122, change_type: 'LimitUp' }] }), { status: 200 });
    };

    const out = await main(['shioaji-quote', '--ticker', '2327', '--format', 'markdown']);
    assert.match(out, /\| 2327 \| 1080 \| 0 \| 0 \| 79.12K \| 漲停 \|/);
  } finally {
    delete process.env.SHIOAJI_SERVER_BASE_URL;
    globalThis.fetch = originalFetch;
  }
});

test('CLI shioaji-kbars renders historical OHLCV rows', async () => {
  const originalFetch = globalThis.fetch;
  try {
    process.env.SHIOAJI_SERVER_BASE_URL = 'http://sj.test';
    globalThis.fetch = async (url, init) => {
      assert.equal(String(url), 'http://sj.test/api/v1/data/kbars');
      assert.deepEqual(JSON.parse(init.body), {
        contract: { security_type: 'STK', exchange: 'TSE', code: '2330' },
        start: '2026-04-01',
        end: '2026-04-02',
      });
      return new Response(JSON.stringify({
        datetime: ['2026-04-01T09:00:00'],
        Open: [100],
        High: [105],
        Low: [99],
        Close: [104],
        Volume: [1000],
        Amount: [104000],
      }), { status: 200 });
    };

    const out = await main(['shioaji-kbars', '--ticker', '2330', '--start', '2026-04-01', '--end', '2026-04-02', '--format', 'markdown']);
    assert.match(out, /\| Date \| Open \| High \| Low \| Close \| Volume \| Amount \|/);
    assert.match(out, /\| 2026-04-01 \| 100 \| 105 \| 99 \| 104 \| 1.00K \| 104.00K \|/);
  } finally {
    delete process.env.SHIOAJI_SERVER_BASE_URL;
    globalThis.fetch = originalFetch;
  }
});

test('CLI shioaji-daily-quotes renders full-market daily OHLCV rows', async () => {
  const originalFetch = globalThis.fetch;
  try {
    process.env.SHIOAJI_SERVER_BASE_URL = 'http://sj.test';
    globalThis.fetch = async (url, init) => {
      assert.equal(String(url), 'http://sj.test/api/v1/data/daily_quotes');
      assert.deepEqual(JSON.parse(init.body), { date: '2026-04-01' });
      return new Response(JSON.stringify({
        Date: ['2026-04-01'],
        Code: ['2330'],
        Open: [100],
        High: [105],
        Low: [99],
        Close: [104],
        Volume: [1000],
        Amount: [104000],
        Transaction: [100],
      }), { status: 200 });
    };

    const out = await main(['shioaji-daily-quotes', '--date', '2026-04-01', '--format', 'markdown']);
    assert.match(out, /\| Date \| Code \| Open \| High \| Low \| Close \| Volume \| Amount \|/);
    assert.match(out, /\| 2026-04-01 \| 2330 \| 100 \| 105 \| 99 \| 104 \| 1.00K \| 104.00K \|/);
  } finally {
    delete process.env.SHIOAJI_SERVER_BASE_URL;
    globalThis.fetch = originalFetch;
  }
});

test('CLI shioaji-cache-kbars reports cached kbar files', async () => {
  const originalFetch = globalThis.fetch;
  const { mkdtemp } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const cacheDir = await mkdtemp(join(tmpdir(), 'shioaji-cli-cache-'));
  try {
    process.env.SHIOAJI_SERVER_BASE_URL = 'http://sj.test';
    globalThis.fetch = async () => new Response(JSON.stringify({
      datetime: ['2026-04-01T09:00:00'],
      Open: [100],
      High: [105],
      Low: [99],
      Close: [104],
      Volume: [1000],
      Amount: [104000],
    }), { status: 200 });

    const out = await main(['shioaji-cache-kbars', '--tickers', '2330', '--start', '2026-04-01', '--end', '2026-04-01', '--cache-dir', cacheDir, '--format', 'markdown']);
    assert.match(out, /# Shioaji kbar cache/);
    assert.match(out, /\| 2330 \| fetched \| 1 \|/);
  } finally {
    delete process.env.SHIOAJI_SERVER_BASE_URL;
    globalThis.fetch = originalFetch;
  }
});

test('CLI shioaji-cache-daily-quotes reports cached full-market daily quote files', async () => {
  const originalFetch = globalThis.fetch;
  const { mkdtemp } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const cacheDir = await mkdtemp(join(tmpdir(), 'shioaji-cli-daily-cache-'));
  try {
    process.env.SHIOAJI_SERVER_BASE_URL = 'http://sj.test';
    globalThis.fetch = async (url, init) => {
      const body = JSON.parse(init.body);
      return new Response(JSON.stringify({
        Date: [body.date],
        Code: ['2330'],
        Open: [100],
        High: [105],
        Low: [99],
        Close: [104],
        Volume: [1000],
        Amount: [104000],
        Transaction: [100],
      }), { status: 200 });
    };

    const out = await main(['shioaji-cache-daily-quotes', '--start', '2026-04-01', '--end', '2026-04-01', '--cache-dir', cacheDir, '--format', 'markdown']);
    assert.match(out, /# Shioaji daily quote cache/);
    assert.match(out, /\| 2026-04-01 \| fetched \| 1 \|/);
  } finally {
    delete process.env.SHIOAJI_SERVER_BASE_URL;
    globalThis.fetch = originalFetch;
  }
});

test('CLI sector-flow close renders sector table', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      const text = String(url);
      if (text.includes('TaiwanStockInfo')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [{ stock_id: '2330', stock_name: '台積電', industry_category: '半導體業' }] }), { status: 200 });
      }
      if (text.includes('TaiwanStockPrice')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [{ date: '2026-06-18', stock_id: '2330', close: 1000, Trading_Volume: 1000 }] }), { status: 200 });
      }
      if (text.includes('TaiwanStockInstitutionalInvestorsBuySell')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [{ date: '2026-06-18', stock_id: '2330', name: 'Foreign_Investor', buy: 2000, sell: 1000 }] }), { status: 200 });
      }
      throw new Error(`Unexpected URL ${text}`);
    };
    const out = await main(['sector-flow', '--mode', 'close', '--date', '2026-06-18', '--format', 'markdown']);
    assert.match(out, /# Sector close flow: 2026-06-18/);
    assert.match(out, /半導體業/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
