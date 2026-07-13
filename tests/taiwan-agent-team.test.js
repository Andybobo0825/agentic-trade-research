import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import {
  buildTaiwanAgentTeam,
  parseTaiwanAgentTeamCliArgs,
  renderTaiwanAgentTeamMarkdown,
  resolveTaiwanAgentTeamMode,
} from '../src/taiwan-agent-team.js';

function makeRepoFixture() {
  const root = mkdtempSync(join(tmpdir(), 'tw-agent-team-'));
  mkdirSync(join(root, '.omx/backtests'), { recursive: true });
  mkdirSync(join(root, '.omx/research'), { recursive: true });
  mkdirSync(join(root, '.omx/line-bridge/responses'), { recursive: true });
  mkdirSync(join(root, 'docs'), { recursive: true });
  mkdirSync(join(root, 'workflows'), { recursive: true });
  writeFileSync(join(root, '.omx/backtests/MVP.md'), '# MVP\n- Total return: 12.3%\n- Win rate: 61%\n- Max drawdown: -4.2%\n- SJ_API_KEY=fake-fixture-key\n');
  writeFileSync(join(root, '.omx/research/strategy.json'), JSON.stringify({ note: 'research-only', return: '8%' }));
  writeFileSync(join(root, 'docs/standard-workflow-v1.md'), '# Standard Workflow 1.4\n');
  return root;
}

function dom(ticker, overrides = {}) {
  return {
    ticker,
    executionMode: 'read_only',
    readOnly: true,
    validSampleCount: 3,
    requestedSampleCount: 3,
    domConfidenceScore: 68,
    meanPressure: 0.24,
    pressureLabel: 'buy_pressure',
    reliability: 'high',
    interpretation: 'patient_entry_preferred',
    risks: ['visible_depth_can_change_before_manual_entry'],
    referencePrices: {
      activeEntryLimit: 101,
      patientEntryPrice: 100.5,
      takeProfitPrice: 103,
      stopLossPrice: 99,
      stopReliability: 'normal',
    },
    ...overrides,
  };
}

function commonResult(name, args) {
  if (name === 'shioaji-snapshots' && args.securityType === 'IND') return { data: [{ code: '001', changeRate: -2.1 }] };
  if (name === 'shioaji-snapshots') return { data: String(args.tickers).split(',').map((code) => ({ code, changeRate: -0.8 })) };
  if (name === 'sector-flow') return { industries: [{ industry: '電子零組件', turnover: '100B', changePct: -5.2 }] };
  if (name === 'xiaoyu-etf') return { dataDate: '2026/07/06', mode: args.mode };
  if (name === 'preopen-brief') return { status: 'partial' };
  if (name === 'research-pack') return { ticker: args.ticker, sources: ['tw-news'] };
  if (name === 'ic-tpex-chain') return { ticker: args.ticker, peers: ['2303'] };
  if (name === 'phase3-dom-confidence') return dom(args.ticker);
  return {};
}

test('resolves screen/analyze intent with explicit overrides and legacy detail aliases', () => {
  assert.deepEqual(resolveTaiwanAgentTeamMode({ query: '請幫我篩選股票' }), { workflowMode: 'screen', modeSource: 'inferred' });
  assert.deepEqual(resolveTaiwanAgentTeamMode({ query: 'find stocks for Q3' }), { workflowMode: 'screen', modeSource: 'inferred' });
  assert.deepEqual(resolveTaiwanAgentTeamMode({ query: '分析 2330' }), { workflowMode: 'analyze', modeSource: 'default' });
  assert.deepEqual(resolveTaiwanAgentTeamMode({ mode: 'analyze', query: '請篩選股票' }), { workflowMode: 'analyze', modeSource: 'explicit' });
  assert.deepEqual(resolveTaiwanAgentTeamMode({ mode: 'screen', query: '分析 2330' }), { workflowMode: 'screen', modeSource: 'explicit' });
  assert.deepEqual(resolveTaiwanAgentTeamMode({ mode: 'brief', query: '請找股票' }), { workflowMode: 'screen', modeSource: 'inferred' });
});

test('parses workflow mode, detail, and evidence root from CLI arguments', () => {
  assert.deepEqual(parseTaiwanAgentTeamCliArgs({
    mode: 'screen',
    detail: 'brief',
    'evidence-root': '.omx/evidence/custom',
    'max-tickers': '4',
  }), {
    query: undefined,
    prompt: undefined,
    tickers: undefined,
    ticker: undefined,
    watchlist: undefined,
    date: undefined,
    startDate: undefined,
    endDate: undefined,
    capital: undefined,
    mode: 'screen',
    detail: 'brief',
    evidenceRoot: '.omx/evidence/custom',
    offline: false,
    maxTickers: 4,
  });
});

test('analyze mode skips Phase 3, runs research before DOM, and returns all four prices', async () => {
  const rootDir = makeRepoFixture();
  const calls = [];
  const result = await buildTaiwanAgentTeam({
    query: '分析 2330 token=super-secret-token',
    tickers: '2330',
    mode: 'analyze',
    date: '2026-07-07',
    startDate: '2026-06-01',
    endDate: '2026-07-07',
    capital: 500000,
  }, {
    rootDir,
    runTool: async (name, args) => {
      calls.push({ name, args });
      if (name === 'research-pack') {
        return { url: 'https://example.test/data?token=raw-secret-token', diagnostic: '{\\"token_tail\\":\\"...ABC123SECRET\\"}' };
      }
      return commonResult(name, args);
    },
  });

  assert.equal(result.workflowVersion, '1.4');
  assert.equal(result.workflowMode, 'analyze');
  assert.equal(result.agent.lanes.length, 7);
  assert.deepEqual(result.targets, ['2330']);
  assert.equal(result.tickerAnalysis[0].phase3Eligibility, 'not_evaluated');
  assert.equal(calls.some((call) => call.name === 'phase3-dataset' || call.name === 'phase3-screen'), false);
  assert.ok(calls.findIndex((call) => call.name === 'research-pack') < calls.findIndex((call) => call.name === 'phase3-dom-confidence'));
  assert.deepEqual(result.tickerAnalysis[0].prices, {
    activeEntryLimit: 101,
    patientEntryPrice: 100.5,
    takeProfitPrice: 103,
    stopLossPrice: 99,
  });
  assert.equal(result.tickerAnalysis[0].dom.executionMode, 'read_only');
  assert.ok(result.audit.every((entry, index) => entry.order === index + 1));
  assert.ok(existsSync(join(rootDir, result.scratchpad.path)));
  assert.ok(existsSync(join(rootDir, result.reportPath)));

  const scratch = readFileSync(join(rootDir, result.scratchpad.path), 'utf8');
  assert.match(scratch, /token=\[REDACTED\]/);
  assert.doesNotMatch(scratch, /raw-secret-token|super-secret-token|ABC123SECRET/);
  assert.doesNotMatch(JSON.stringify(result), /raw-secret-token|super-secret-token|fake-fixture-key|ABC123SECRET/);

  const markdown = renderTaiwanAgentTeamMarkdown(result);
  assert.match(markdown, /Standard Workflow 1\.4/);
  assert.match(markdown, /not_evaluated/);
  assert.match(markdown, /Active entry limit.*101/i);
  assert.match(markdown, /Take-profit.*103/i);
});

test('screen mode runs Phase 3 first and researches only eligible candidates', async () => {
  const rootDir = makeRepoFixture();
  const calls = [];
  const result = await buildTaiwanAgentTeam({
    query: '請篩選股票',
    mode: 'screen',
    maxTickers: 5,
    evidenceRoot: '.omx/evidence/test',
  }, {
    rootDir,
    runTool: async (name, args) => {
      calls.push({ name, args });
      if (name === 'phase3-dataset') return { candidateCount: 3, evidenceRoot: args.evidenceRoot };
      if (name === 'phase3-screen') return {
        strategy: 'phase3_stability',
        eligibleCount: 2,
        rejectedCount: 1,
        candidates: [{ ticker: '2330', softScore: 72 }, { ticker: '2303', softScore: 68 }],
        rejected: [{ ticker: '1504', reasons: ['hma_not_bullish'] }],
      };
      return commonResult(name, args);
    },
  });

  assert.equal(result.workflowMode, 'screen');
  assert.deepEqual(result.targets, ['2330', '2303']);
  assert.deepEqual(result.tickerAnalysis.map((row) => row.phase3Eligibility), ['eligible', 'eligible']);
  assert.equal(calls.filter((call) => call.name === 'research-pack').length, 2);
  assert.equal(calls.some((call) => call.args?.ticker === '1504'), false);
  assert.ok(calls.findIndex((call) => call.name === 'phase3-dataset') < calls.findIndex((call) => call.name === 'phase3-screen'));
  for (const ticker of result.targets) {
    const research = calls.findIndex((call) => call.name === 'research-pack' && call.args.ticker === ticker);
    const industry = calls.findIndex((call) => call.name === 'ic-tpex-chain' && call.args.ticker === ticker);
    const etf = calls.findIndex((call) => call.name === 'xiaoyu-etf' && call.args.mode === 'stock' && call.args.ticker === ticker);
    const domCall = calls.findIndex((call) => call.name === 'phase3-dom-confidence' && call.args.ticker === ticker);
    assert.ok(research < industry && industry < etf && etf < domCall);
  }
  assert.equal(result.phase3.screen.eligibleCount, 2);
});

test('screen mode with zero eligible candidates stops all target-specific calls', async () => {
  const rootDir = makeRepoFixture();
  const calls = [];
  const result = await buildTaiwanAgentTeam({ query: '找股票', mode: 'screen' }, {
    rootDir,
    runTool: async (name, args) => {
      calls.push({ name, args });
      if (name === 'phase3-dataset') return { candidateCount: 1 };
      if (name === 'phase3-screen') return { eligibleCount: 0, rejectedCount: 1, candidates: [], rejected: [{ ticker: '1504' }] };
      return commonResult(name, args);
    },
  });

  assert.deepEqual(result.targets, []);
  assert.deepEqual(result.tickerAnalysis, []);
  assert.equal(calls.some((call) => ['research-pack', 'ic-tpex-chain', 'phase3-dom-confidence', 'preopen-brief'].includes(call.name)), false);
  assert.equal(calls.some((call) => call.name === 'shioaji-snapshots' && !call.args.securityType), false);
  assert.equal(calls.some((call) => call.name === 'xiaoyu-etf' && call.args.mode === 'stock'), false);
  assert.ok(result.synthesis.dataGaps.some((gap) => /zero eligible/i.test(gap)));
});

test('external research failure does not suppress DOM, while DOM failure returns null prices', async () => {
  const rootDir = makeRepoFixture();
  const calls = [];
  const result = await buildTaiwanAgentTeam({ query: '分析 2330,2303', tickers: '2330,2303', mode: 'analyze' }, {
    rootDir,
    runTool: async (name, args) => {
      calls.push({ name, args });
      if (name === 'research-pack' && args.ticker === '2330') throw new Error('news unavailable');
      if (name === 'phase3-dom-confidence' && args.ticker === '2303') throw new Error('DOM unavailable');
      return commonResult(name, args);
    },
  });

  assert.equal(calls.some((call) => call.name === 'phase3-dom-confidence' && call.args.ticker === '2330'), true);
  const failedDom = result.tickerAnalysis.find((row) => row.ticker === '2303');
  assert.deepEqual(failedDom.prices, {
    activeEntryLimit: null,
    patientEntryPrice: null,
    takeProfitPrice: null,
    stopLossPrice: null,
  });
  assert.equal(failedDom.dom.reliability, 'unavailable');
  assert.ok(result.synthesis.dataGaps.some((gap) => /news unavailable|DOM unavailable/.test(gap)));
});

test('dataset failure prevents screening and all target research', async () => {
  const rootDir = makeRepoFixture();
  const calls = [];
  const result = await buildTaiwanAgentTeam({ query: '選股', mode: 'screen' }, {
    rootDir,
    runTool: async (name, args) => {
      calls.push({ name, args });
      if (name === 'phase3-dataset') throw new Error('point-in-time data unavailable');
      return commonResult(name, args);
    },
  });
  assert.equal(calls.some((call) => call.name === 'phase3-screen'), false);
  assert.equal(calls.some((call) => call.name === 'research-pack' || call.name === 'phase3-dom-confidence'), false);
  assert.deepEqual(result.targets, []);
  assert.match(result.errors.phase3_dataset, /point-in-time data unavailable/);
});

test('offline mode uses artifacts only and does not run any tool', async () => {
  const rootDir = makeRepoFixture();
  let callCount = 0;
  const result = await buildTaiwanAgentTeam({ query: '離線整合', offline: true }, {
    rootDir,
    runTool: async () => { callCount += 1; },
  });
  assert.equal(callCount, 0);
  assert.equal(result.request.offline, true);
  assert.equal(result.synthesis.marketRegime.label, 'artifact-only');
  assert.ok(result.synthesis.dataGaps.some((gap) => gap.includes('offline mode')));
});
