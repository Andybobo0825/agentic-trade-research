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

test('hma-signal fetches Taiwan candles and renders a trend suggestion', async () => {
  const { runTool } = await import('../src/tools.js');
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      assert.match(String(url), /dataset=TaiwanStockPrice/);
      const data = Array.from({ length: 30 }, (_, index) => ({
        date: `2026-01-${String(index + 1).padStart(2, '0')}`,
        stock_id: '2330',
        close: index + 1,
        open: index + 0.5,
        max: index + 1.5,
        min: index + 0.25,
        Trading_Volume: 1000 + index,
      }));
      return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
    };
    const result = await runTool('hma-signal', { ticker: '2330', market: 'tw', source: 'finmind', period: 9, startDate: '2026-01-01' });
    assert.equal(result.signal.trend, 'bullish');
    assert.equal(result.signal.action, 'hold_long');
    assert.equal(result.dataSource.tool, 'tw-price');
    const out = renderToolResult('hma-signal', result, 'markdown');
    assert.match(out, /# HMA trend signal: 2330/);
    assert.match(out, /偏多續抱/);
    assert.match(out, /Technical signal only/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('signal-study combines HMA, volume, institutional flow, forward returns, and advice', async () => {
  const { runTool } = await import('../src/tools.js');
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      const text = String(url);
      if (text.includes('TaiwanStockPrice')) {
        const closes = [10, 10.2, 10.1, 10.3, 10.4, 10.5, 10.4, 10.3, 10.2, 10.1, 10.4, 10.8, 11.2, 11.6, 12, 12.4, 12.8, 13, 13.3, 13.6, 13.9, 14.2, 14.4, 14.7, 15, 15.2, 15.4, 15.7, 16, 16.3];
        const data = closes.map((close, index) => ({
          date: `2026-01-${String(index + 1).padStart(2, '0')}`,
          stock_id: '2330',
          open: close - 0.1,
          max: close + 0.2,
          min: close - 0.2,
          close,
          Trading_Volume: index === 29 ? 7_000_000 : 1_000_000 + index * 10_000,
        }));
        return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
      }
      if (text.includes('TaiwanStockInstitutionalInvestorsBuySell')) {
        const data = Array.from({ length: 5 }, (_, index) => ({
          date: `2026-01-${String(26 + index).padStart(2, '0')}`,
          stock_id: '2330',
          name: index % 2 === 0 ? 'Foreign_Investor' : 'Investment_Trust',
          buy: 2000 + index * 100,
          sell: 1000,
        }));
        return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
      }
      throw new Error(`Unexpected URL ${text}`);
    };

    const result = await runTool('signal-study', {
      ticker: '2330',
      market: 'tw',
      period: 9,
      startDate: '2026-01-01',
      volumeWindow: 5,
      institutionalDays: 5,
      forwardDays: '3,5,10',
    });

    assert.equal(result.ticker, '2330');
    assert.equal(result.hma.current.trend, 'bullish');
    assert.equal(result.volume.confirmed, true);
    assert.equal(result.liquidity.eligible, true);
    assert.equal(result.liquidity.status, 'liquid');
    assert.equal(result.institutional.confirmed, true);
    assert.deepEqual(result.forwardPerformance.days, [3, 5, 10]);
    assert.ok(result.forwardPerformance.byDay['3'].sampleSize >= 1);
    assert.equal(result.latestSignal.confidence.label, 'high');
    assert.match(result.advice.action, /追|續抱|pullback|回測/);

    const out = renderToolResult('signal-study', result, 'markdown');
    assert.match(out, /# Signal study: 2330/);
    assert.match(out, /HMA 訊號/);
    assert.match(out, /買訊後 3\/5\/10 日表現/);
    assert.match(out, /流動性確認/);
    assert.match(out, /最近一次訊號可信度/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('daily-decision-study builds point-in-time advisor frames with liquidity gating', async () => {
  const { runTool } = await import('../src/tools.js');
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      assert.match(String(url), /dataset=TaiwanStockPrice/);
      const closes = [
        10, 10.1, 10.2, 10.1, 10.3, 10.6, 10.8, 11.0, 10.9, 11.2,
        11.5, 11.8, 12.2, 12.6, 13.0, 13.4, 13.8, 14.2, 14.6, 15.0,
        15.4, 15.9, 16.4, 17.0, 17.6, 18.2, 18.8, 19.4, 20.0, 20.8,
      ];
      const data = closes.map((close, index) => ({
        date: `2026-02-${String(index + 1).padStart(2, '0')}`,
        stock_id: '2330',
        open: close - 0.1,
        max: close + 0.3,
        min: close - 0.3,
        close,
        Trading_Volume: 2_000_000 + index * 50_000,
      }));
      return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
    };

    const result = await runTool('daily-decision-study', {
      ticker: '2330',
      market: 'tw',
      period: 9,
      startDate: '2026-02-01',
      decisionDays: 3,
      lookbackBars: 20,
      volumeWindow: 5,
      minAverageTurnover: 20_000_000,
      maxPositionPctOfAvgVolume: 0.01,
    });

    assert.equal(result.ticker, '2330');
    assert.equal(result.decisions.length, 3);
    assert.equal(result.decisions[0].pointInTime, true);
    assert.ok(result.decisions[0].advisorFrame.candles.length <= 20);
    assert.equal(result.decisions.at(-1).liquidity.eligible, true);
    assert.ok(result.decisions.at(-1).liquidity.suggestedMaxLots >= 1);
    assert.match(result.decisions.at(-1).advisorPrompt, /只可使用以下截至/);

    const illiquid = await runTool('daily-decision-study', {
      ticker: '2330',
      market: 'tw',
      period: 9,
      startDate: '2026-02-01',
      decisionDays: 1,
      lookbackBars: 20,
      volumeWindow: 5,
      minAverageTurnover: 500_000_000,
    });
    assert.equal(illiquid.decisions[0].liquidity.eligible, false);
    assert.equal(illiquid.decisions[0].decision.action, 'avoid_liquidity');

    const out = renderToolResult('daily-decision-study', result, 'markdown');
    assert.match(out, /# Daily decision study: 2330/);
    assert.match(out, /Point-in-time Codex frames/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('chip-study combines foreign buying, thousand-lot holder concentration, price/volume checks, and forward outcomes', async () => {
  const { runTool } = await import('../src/tools.js');
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      const text = String(url);
      if (text.includes('TaiwanStockPrice')) {
        const closes = [
          10, 10.1, 10.2, 10.4, 10.6, 10.8, 11, 11.2, 11.4, 11.6,
          11.8, 12, 12.2, 12.4, 12.6, 12.8, 13, 13.2, 13.4, 13.6,
          13.8, 14, 14.2, 14.4, 14.6, 14.8, 15, 15.2, 15.4, 15.8,
          16.2, 16.6, 17,
        ];
        const data = closes.map((close, index) => ({
          date: `2026-04-${String(index + 1).padStart(2, '0')}`,
          stock_id: '2330',
          open: close - 0.1,
          max: close + 0.2,
          min: close - 0.2,
          close,
          Trading_Volume: index >= 29 ? 3_500_000 : 2_000_000,
        }));
        return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
      }
      if (text.includes('TaiwanStockInstitutionalInvestorsBuySell')) {
        const data = [
          { date: '2026-04-27', stock_id: '2330', name: 'Foreign_Investor', buy: 1000, sell: 1200 },
          { date: '2026-04-28', stock_id: '2330', name: 'Foreign_Investor', buy: 2000, sell: 1000 },
          { date: '2026-04-29', stock_id: '2330', name: 'Foreign_Investor', buy: 2200, sell: 1000 },
          { date: '2026-04-30', stock_id: '2330', name: 'Foreign_Investor', buy: 2500, sell: 1000 },
          { date: '2026-04-30', stock_id: '2330', name: 'Investment_Trust', buy: 400, sell: 300 },
        ];
        return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
      }
      if (text.includes('TaiwanStockHoldingSharesPer')) {
        const data = [
          { date: '2026-04-10', stock_id: '2330', HoldingSharesLevel: '1-999', people: 100, percent: 35, unit: 3500 },
          { date: '2026-04-10', stock_id: '2330', HoldingSharesLevel: '1000-5000', people: 10, percent: 20, unit: 2000 },
          { date: '2026-04-10', stock_id: '2330', HoldingSharesLevel: '5001-10000', people: 2, percent: 5, unit: 500 },
          { date: '2026-04-17', stock_id: '2330', HoldingSharesLevel: '1000-5000', people: 12, percent: 22, unit: 2200 },
          { date: '2026-04-17', stock_id: '2330', HoldingSharesLevel: '5001-10000', people: 3, percent: 6, unit: 600 },
          { date: '2026-04-24', stock_id: '2330', HoldingSharesLevel: '1000-5000', people: 15, percent: 24, unit: 2400 },
          { date: '2026-04-24', stock_id: '2330', HoldingSharesLevel: '5001-10000', people: 4, percent: 7, unit: 700 },
        ];
        return new Response(JSON.stringify({ status: 200, msg: 'success', data }), { status: 200 });
      }
      if (text.includes('TaiwanStockInfo')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [{ stock_id: '2330', stock_name: '台積電', industry_category: '半導體業' }] }), { status: 200 });
      }
      throw new Error(`Unexpected URL ${text}`);
    };

    const result = await runTool('chip-study', {
      ticker: '2330',
      market: 'tw',
      period: 9,
      startDate: '2026-04-01',
      endDate: '2026-04-30',
      foreignDays: 3,
      holderWeeks: 3,
      forwardDays: '3,5,10',
      volumeWindow: 5,
    });

    assert.equal(result.ticker, '2330');
    assert.equal(result.foreign.confirmed, true);
    assert.equal(result.foreign.streakDays, 3);
    assert.equal(result.holders.confirmed, true);
    assert.equal(result.holders.recent.length, 3);
    assert.equal(result.chipGate.passed, true);
    assert.equal(result.industry.name, '半導體業');
    assert.ok(result.events.length >= 1);
    assert.deepEqual(result.forwardPerformance.days, [3, 5, 10]);
    assert.match(result.advice.action, /觀察|分批|回測/);

    const out = renderToolResult('chip-study', result, 'markdown');
    assert.match(out, /# Chip study: 2330/);
    assert.match(out, /外資連買/);
    assert.match(out, /1000 張以上持股/);
    assert.match(out, /事件後 3\/5\/10 日表現/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('sector-flow realtime groups Shioaji snapshots by industry', async () => {
  const { runTool } = await import('../src/tools.js');
  const originalFetch = globalThis.fetch;
  try {
    process.env.SHIOAJI_SERVER_BASE_URL = 'http://sj.test';
    globalThis.fetch = async (url, init) => {
      const text = String(url);
      if (text.includes('TaiwanStockInfo')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [
          { stock_id: '2330', stock_name: '台積電', industry_category: '半導體業' },
          { stock_id: '2327', stock_name: '國巨', industry_category: '電子零組件業' },
          { stock_id: '3481', stock_name: '群創', industry_category: '光電業' },
        ] }), { status: 200 });
      }
      if (text === 'http://sj.test/api/v1/data/snapshots') {
        const body = JSON.parse(init.body);
        assert.deepEqual(body.contracts.map((contract) => contract.code), ['2330', '2327', '3481']);
        return new Response(JSON.stringify({ data: [
          { code: '2330', close: 1000, total_volume: 1000, change_rate: 1.2, change_type: 'Up' },
          { code: '2327', close: 100, total_volume: 3000, change_rate: 2.5, change_type: 'LimitUp' },
          { code: '3481', close: 20, total_volume: 10000, change_rate: -1.5, change_type: 'Down' },
        ] }), { status: 200 });
      }
      throw new Error(`Unexpected URL ${text}`);
    };

    const result = await runTool('sector-flow', { mode: 'realtime', tickers: '2330,2327,3481', limit: 3 });

    assert.equal(result.mode, 'realtime');
    assert.equal(result.readOnly, true);
    assert.equal(result.sectors[0].industry, '半導體業');
    assert.equal(result.sectors[0].turnover, 1_000_000_000);
    assert.equal(result.sectors.find((row) => row.industry === '電子零組件業').limitUpCount, 1);
    assert.equal(result.sectors.find((row) => row.industry === '光電業').decliningCount, 1);
  } finally {
    delete process.env.SHIOAJI_SERVER_BASE_URL;
    globalThis.fetch = originalFetch;
  }
});

test('sector-flow close groups daily turnover and institutional net value by industry', async () => {
  const { runTool } = await import('../src/tools.js');
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url) => {
      const text = String(url);
      if (text.includes('TaiwanStockInfo')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [
          { stock_id: '2330', stock_name: '台積電', industry_category: '半導體業' },
          { stock_id: '2454', stock_name: '聯發科', industry_category: '半導體業' },
          { stock_id: '2327', stock_name: '國巨', industry_category: '電子零組件業' },
        ] }), { status: 200 });
      }
      if (text.includes('TaiwanStockPrice')) {
        assert.match(text, /start_date=2026-06-18/);
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [
          { date: '2026-06-18', stock_id: '2330', close: 1000, Trading_Volume: 1000 },
          { date: '2026-06-18', stock_id: '2454', close: 1200, Trading_Volume: 2000 },
          { date: '2026-06-18', stock_id: '2327', close: 100, Trading_Volume: 3000 },
        ] }), { status: 200 });
      }
      if (text.includes('TaiwanStockInstitutionalInvestorsBuySell')) {
        return new Response(JSON.stringify({ status: 200, msg: 'success', data: [
          { date: '2026-06-18', stock_id: '2330', name: 'Foreign_Investor', buy: 2000, sell: 1000 },
          { date: '2026-06-18', stock_id: '2454', name: 'Investment_Trust', buy: 3000, sell: 1000 },
          { date: '2026-06-18', stock_id: '2327', name: 'Foreign_Investor', buy: 1000, sell: 4000 },
        ] }), { status: 200 });
      }
      throw new Error(`Unexpected URL ${text}`);
    };

    const result = await runTool('sector-flow', { mode: 'close', date: '2026-06-18' });

    assert.equal(result.mode, 'close');
    assert.equal(result.sectors[0].industry, '半導體業');
    assert.equal(result.sectors[0].turnover, 3_400_000);
    assert.equal(result.sectors[0].foreignNetValue, 1_000_000);
    assert.equal(result.sectors[0].investmentTrustNetValue, 2_400_000);
    assert.equal(result.sectors.find((row) => row.industry === '電子零組件業').foreignNetValue, -300_000);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('ic-tpex-category markdown renders official value-chain membership', async () => {
  const { runTool } = await import('../src/tools.js');
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(`<h3>人工智慧產業鏈簡介</h3><a href="company_basic.php?stk_code=6112">邁達特</a>`, { status: 200 });
    const result = await runTool('ic-tpex-category', { ic: '5300' });
    const out = renderToolResult('ic-tpex-category', result, 'markdown');
    assert.match(out, /人工智慧產業鏈簡介/);
    assert.match(out, /6112/);
    assert.match(out, /邁達特/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
