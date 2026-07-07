import test from 'node:test';
import assert from 'node:assert/strict';
import { main } from '../src/cli.js';
import { renderToolResult, runTool } from '../src/tools.js';

const fixture = {
  meta: {
    latest: '20260706',
    latest_slash: '2026/07/06',
    active_updated: 1,
    active_total: 1,
    etf_total: 2,
    active_count: 1,
    cover_latest: 2,
    cover_full: 2,
    incomplete: false,
  },
  etfs: [
    {
      code: '00981A',
      name: '主動統一台股增長',
      type: 'active',
      date: '20260706',
      updated: true,
      price: 15.5,
      chg: 1.2,
      scale: 100,
      scale_chg: 2,
      net: 1.5,
      buy_amt: 2,
      sell_amt: -0.5,
      add_n: 1,
      cut_n: 1,
      holdings: [
        { code: '2330', name: '台積電', weight: 10, lots: 100, value: 12, d1: 10, money: 1.2, chg: 1.1 },
        { code: '2454', name: '聯發科', weight: 5, lots: 50, value: 6, d1: -5, money: -0.6, chg: -0.5 },
      ],
    },
    {
      code: '0050',
      name: '元大台灣50',
      type: 'etf',
      holdings: [
        { code: '2330', name: '台積電', weight: 50, lots: 1000, value: 120, d1: 0, money: 0, chg: 1.1 },
      ],
    },
  ],
  stocks: {
    2330: {
      name: '台積電',
      price: 1200,
      chg: 1.1,
      holders: [
        { etf: '00981A', etfname: '主動統一台股增長', lots: 100, weight: 10, d1: 10, streak: 1 },
        { etf: '0050', etfname: '元大台灣50', lots: 1000, weight: 50, d1: 0, streak: 0 },
      ],
      tot_lots: 1100,
      tot_value: 132,
      net_amt: 1.2,
      etf_count: 2,
      streak: 1,
    },
  },
  rank: {
    active: {
      d1: {
        buy: [{ code: '2330', name: '台積電', price: 1200, lots: 10, money: 1.2, chg: 1.1, etf_count: 1, etfs: [{ etf: '00981A', d1: 10 }] }],
        sell: [{ code: '2454', name: '聯發科', price: 1300, lots: -5, money: -0.6, chg: -0.5, etf_count: 1, etfs: [{ etf: '00981A', d1: -5 }] }],
      },
    },
    market: { d1: { buy: [], sell: [] } },
  },
};

function mockFetch() {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    assert.match(String(url), /data\.js/);
    return new Response(`window.DATA = ${JSON.stringify(fixture)};`, { status: 200 });
  };
  return () => { globalThis.fetch = originalFetch; };
}

test('xiaoyu-etf stock mode reverse-lookups ETF holders and active flows', async () => {
  const restore = mockFetch();
  try {
    const result = await runTool('xiaoyu-etf', { mode: 'stock', ticker: '2330', limit: 5 });
    assert.equal(result.source, 'xiaoyu-etf');
    assert.equal(result.stock.activeEtfCount, 1);
    assert.equal(result.stock.activeNetLots, 10);
    assert.equal(result.stock.activeEstimatedNetValueYi, 0.12);
    assert.equal(result.topHolders[0].etf, '00981A');
    const out = renderToolResult('xiaoyu-etf', result, 'markdown');
    assert.match(out, /Xiaoyu ETF lens: stock/);
    assert.match(out, /2330 台積電/);
    assert.match(out, /00981A 主動統一台股增長/);
  } finally {
    restore();
  }
});

test('xiaoyu-etf rank mode renders inferred active ETF buy rank', async () => {
  const restore = mockFetch();
  try {
    const out = await main(['xiaoyu-etf', '--mode', 'rank', '--scope', 'active', '--window', 'd1', '--direction', 'buy', '--format', 'markdown']);
    assert.match(out, /ETF inferred buy rank/);
    assert.match(out, /2330 台積電/);
    assert.match(out, /主動式 ETF 持股推估買賣超/);
  } finally {
    restore();
  }
});
