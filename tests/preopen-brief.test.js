import test from 'node:test';
import assert from 'node:assert/strict';
import { main } from '../src/cli.js';
import { runTool, renderToolResult } from '../src/tools.js';
import { analyzePreopenWorkflow, tryFetchPreviousSpotClose } from '../src/preopen-brief.js';

test('preopen analyzer marks bullish only when ordered workflow signals agree', () => {
  const result = analyzePreopenWorkflow({
    date: '2026-07-02',
    updateTime: '08:59',
    fx: { previousClose: 29.6, current: 29.48 },
    futures: { nightClose: 47180, change: 180, volume: 120000, previousSpotClose: 47018.99 },
    usMarket: { dow: 0.4, sp500: 0.8, nasdaq: 1.1, sox: 1.6 },
    branches: [{ ticker: '2330', name: '台積電', branch: '凱基-台北', dailyNetLots: [120, 180, 260, 330, 410] }],
    auctions: [{ ticker: '2330', price858: 2500, price859: 2504, open: 2506 }],
  });

  assert.equal(result.completeness.status, 'complete');
  assert.equal(result.fx.judgement, 'bullish');
  assert.equal(result.futures.judgement, 'bullish');
  assert.equal(result.branches[0].action, 'observe');
  assert.equal(result.auctions[0].state, 'stable');
  assert.equal(result.summary.marketEnvironment, 'bullish');
  assert.equal(result.summary.allowOpenChase, false);
  assert.match(result.summary.researchAdvice, /環境偏多/);
});

test('preopen analyzer detects conflicts and blocks chasing when futures lag US strength', () => {
  const result = analyzePreopenWorkflow({
    date: '2026-07-02',
    month: 7,
    fx: { previousClose: 29.6, current: 29.72 },
    futures: { nightClose: 46850, change: -120, volume: 90000, previousSpotClose: 47018.99 },
    usMarket: { dow: 1.1, sp500: 1.4, nasdaq: 1.8, sox: 2.2 },
    branches: [{ ticker: '2454', name: '聯發科', branch: '兆豐-嘉義', dailyNetLots: [300, 250, 100, -80, -160] }],
    auctions: [{ ticker: '2454', price858: 4300, price859: 4360, open: 4340 }],
  });

  assert.equal(result.fx.judgement, 'bearish');
  assert.equal(result.futures.exDividendCaveat, true);
  assert.equal(result.relativeStrength.state, 'taiwan_weaker_than_us');
  assert.equal(result.branches[0].action, 'exclude');
  assert.equal(result.auctions[0].state, 'last_minute_pull_up');
  assert.equal(result.summary.marketEnvironment, 'conflict');
  assert.equal(result.summary.allowOpenChase, false);
  assert.match(result.summary.cancelConditions.join(' '), /正式開盤後無法延續/);
});

test('preopen analyzer only evaluates the latest five branch observations', () => {
  const result = analyzePreopenWorkflow({
    date: '2026-07-02',
    fx: { previousClose: 29.6, current: 29.48 },
    futures: { nightClose: 47180, change: 180, volume: 120000, previousSpotClose: 47018.99 },
    usMarket: { dow: 0.4, sp500: 0.8, nasdaq: 1.1, sox: 1.6 },
    branches: [{
      ticker: '2330',
      name: '台積電',
      branch: '凱基-台北',
      dailyNetLots: [999, -999, 120, 180, 260, 330, 410],
    }],
    auctions: [{ ticker: '2330', price858: 2500, price859: 2504, open: 2506 }],
  });

  assert.deepEqual(result.branches[0].dailyNetLots, [120, 180, 260, 330, 410]);
  assert.equal(result.branches[0].action, 'observe');
});

test('preopen tool renders the article-bounded markdown report and data gaps', async () => {
  const result = await runTool('preopen-brief', {
    date: '2026-07-02',
    noFetch: true,
    fxPreviousClose: 29.6,
    fxCurrent: 29.49,
    futureClose: 47160,
    futureChange: 140,
    futureVolume: 100000,
    previousSpotClose: 47018.99,
    usMoves: 'dow=0.3,sp500=0.5,nasdaq=0.9,sox=1.2',
    branchData: JSON.stringify([{ ticker: '2330', name: '台積電', branch: '凱基-台北', dailyNetLots: [10, 20, 35, 55, 80] }]),
    auctionData: JSON.stringify([{ ticker: '2330', price858: 2500, price859: 2502, open: 2503 }]),
  });
  const out = renderToolResult('preopen-brief', result, 'markdown');

  assert.match(out, /# 今日台股盤前報告/);
  assert.match(out, /## 一、新台幣匯率/);
  assert.match(out, /## 二、台指期夜盤/);
  assert.match(out, /## 四、個股分點觀察/);
  assert.match(out, /凱基-台北/);
  assert.match(out, /## 七、執行原則/);
  assert.doesNotMatch(out, /保證|必漲/);
});

test('CLI preopen-brief accepts manual data-agent inputs', async () => {
  const out = await main([
    'preopen-brief',
    '--date', '2026-07-02',
    '--no-fetch',
    '--fx-prev-close', '29.6',
    '--fx-current', '29.49',
    '--future-close', '47160',
    '--future-change', '140',
    '--future-volume', '100000',
    '--previous-spot-close', '47018.99',
    '--us-moves', 'dow=0.3,sp500=0.5,nasdaq=0.9,sox=1.2',
    '--branch-data', '[{"ticker":"2330","name":"台積電","branch":"凱基-台北","dailyNetLots":[10,20,35,55,80]}]',
    '--auction-data', '[{"ticker":"2330","price858":2500,"price859":2502,"open":2503}]',
    '--format', 'markdown',
  ]);

  assert.match(out, /# 今日台股盤前報告/);
  assert.match(out, /資料完整性：完整/);
  assert.match(out, /市場環境：偏多/);
});

test('CLI preopen-brief accepts data-agent US moves as JSON object', async () => {
  const out = await main([
    'preopen-brief',
    '--date', '2026-07-02',
    '--no-fetch',
    '--fx-prev-close', '29.6',
    '--fx-current', '29.49',
    '--future-close', '47160',
    '--future-change', '140',
    '--future-volume', '100000',
    '--previous-spot-close', '47018.99',
    '--us-moves', '{"dow":0.3,"sp500":0.5,"nasdaq":0.9,"sox":1.2}',
    '--branch-data', '[{"ticker":"2330","name":"台積電","branch":"凱基-台北","dailyNetLots":[10,20,35,55,80]}]',
    '--auction-data', '[{"ticker":"2330","price858":2500,"price859":2502,"open":2503}]',
    '--format', 'markdown',
  ]);

  assert.match(out, /美股主要指數表現：dow \+0.30%、sp500 \+0.50%、nasdaq \+0.90%、sox \+1.20%/);
  assert.match(out, /資料完整性：完整/);
});

test('preopen brief merges watchlist tickers into the observation list', async () => {
  const result = await runTool('preopen-brief', {
    date: '2026-07-02',
    noFetch: true,
    watchlist: '2330,2454',
    fxPreviousClose: 29.6,
    fxCurrent: 29.49,
    futureClose: 47160,
    futureChange: 140,
    futureVolume: 100000,
    previousSpotClose: 47018.99,
    usMoves: 'dow=0.3,sp500=0.5,nasdaq=0.9,sox=1.2',
    auctionData: JSON.stringify([]),
  });

  assert.deepEqual(result.summary.observeTickers, ['2330', '2454']);
  const out = renderToolResult('preopen-brief', result, 'markdown');
  assert.match(out, /今日觀察股票：2330, 2454/);
});

test('tryFetchPreviousSpotClose uses the effective report date instead of an undefined args.date', async () => {
  const calls = [];
  const fetchCandles = async (params) => {
    calls.push(params);
    return {
      data: [
        { date: '2026-07-06', close: 47018.99 },
        { date: '2026-07-03', close: 46888.88 },
      ],
    };
  };

  const value = await tryFetchPreviousSpotClose({ spotFrom: '2026-07-01' }, '2026-07-06', fetchCandles);

  assert.equal(value, 46888.88);
  assert.deepEqual(calls[0], {
    ticker: 'IX0001',
    scope: 'historical',
    timeframe: 'D',
    from: '2026-07-01',
    to: '2026-07-06',
    limit: 5,
  });
});
