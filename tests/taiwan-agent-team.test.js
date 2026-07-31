import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { buildTaiwanAgentTeam, renderTaiwanAgentTeamMarkdown } from '../src/taiwan-agent-team.js';

function makeRepoFixture() {
  const root = mkdtempSync(join(tmpdir(), 'tw-agent-team-'));
  mkdirSync(join(root, '.omx/backtests'), { recursive: true });
  mkdirSync(join(root, '.omx/research'), { recursive: true });
  mkdirSync(join(root, '.omx/line-bridge/responses'), { recursive: true });
  mkdirSync(join(root, 'docs'), { recursive: true });
  mkdirSync(join(root, 'workflows'), { recursive: true });
  writeFileSync(join(root, '.omx/backtests/MVP.md'), '# MVP\n- Total return: 12.3%\n- Win rate: 61%\n- Max drawdown: -4.2%\n- SJ_API_KEY=fake-fixture-key\n');
  writeFileSync(join(root, '.omx/research/strategy.json'), JSON.stringify({ note: 'research-only', return: '8%' }));
  writeFileSync(join(root, 'docs/standard-workflow-v1.md'), '# Standard Workflow 1.01\n');
  return root;
}

test('taiwan agent team creates Dexter-style scratchpad and report without replacing workflows', async () => {
  const rootDir = makeRepoFixture();
  const calls = [];
  const result = await buildTaiwanAgentTeam({
    query: '測試台股 agent team token=super-secret-token',
    tickers: '2330,00981A',
    date: '2026-07-07',
    startDate: '2026-06-01',
    endDate: '2026-07-07',
    capital: 500000,
  }, {
    rootDir,
    runTool: async (name, args) => {
      calls.push({ name, args });
      if (name === 'shioaji-snapshots' && args.tickers.includes('001')) return { data: [{ code: '001', changeRate: -2.1 }] };
      if (name === 'shioaji-snapshots') return { data: [{ code: '2330', changeRate: -0.8 }, { code: '00981A', changeRate: -4.3 }] };
      if (name === 'sector-flow') return { industries: [{ industry: '電子零組件', turnover: '100B', changePct: -5.2 }] };
      if (name === 'xiaoyu-etf') return { dataDate: '2026/07/06' };
      if (name === 'preopen-brief') return { status: 'partial' };
      if (name === 'research-pack') {
        return {
          results: {
            'signal-study': {
              ticker: args.ticker,
              url: 'https://example.test/data?token=raw-secret-token',
              diagnostic: '{\\"token_tail\\":\\"...ABC123SECRET\\"}',
            },
          },
        };
      }
      return {};
    },
  });

  assert.equal(result.agent.name, 'taiwan-agent-team');
  assert.equal(result.synthesis.marketRegime.label, 'risk-off');
  assert.ok(result.scratchpad.path.endsWith('.jsonl'));
  assert.ok(existsSync(join(rootDir, result.scratchpad.path)));
  assert.ok(existsSync(join(rootDir, result.reportPath)));
  assert.ok(calls.some((call) => call.name === 'research-pack'));
  assert.ok(calls.some((call) => call.name === 'shioaji-snapshots' && call.args.securityType === 'IND'));

  const scratch = readFileSync(join(rootDir, result.scratchpad.path), 'utf8');
  assert.match(scratch, /"type":"init"/);
  assert.match(scratch, /"toolName":"shioaji-snapshots"/);
  assert.match(scratch, /token=\[REDACTED\]/);
  assert.doesNotMatch(scratch, /raw-secret-token/);
  assert.doesNotMatch(scratch, /super-secret-token/);
  assert.doesNotMatch(scratch, /ABC123SECRET/);
  assert.match(JSON.stringify(result.toolResults), /token=\[REDACTED\]/);
  assert.doesNotMatch(JSON.stringify(result.toolResults), /raw-secret-token/);
  assert.doesNotMatch(JSON.stringify(result), /super-secret-token|fake-fixture-key|ABC123SECRET/);

  const markdown = renderTaiwanAgentTeamMarkdown(result);
  assert.match(markdown, /Taiwan Agent Team Research Report/);
  assert.match(markdown, /Dexter-style architecture/);
  assert.match(markdown, /Evidence boundaries/);
  assert.match(markdown, /Auxiliary flow lens/);
  assert.match(markdown, /risk-off/);
  assert.match(markdown, /MVP.md: Total return: 12.3%/);
  assert.doesNotMatch(markdown, /super-secret-token|fake-fixture-key|ABC123SECRET/);
  const persistedReport = readFileSync(join(rootDir, result.reportPath), 'utf8');
  assert.match(persistedReport, new RegExp(`Report artifact: ${result.reportPath.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`));
  assert.doesNotMatch(persistedReport, /super-secret-token|fake-fixture-key|ABC123SECRET/);
});

test('taiwan agent team supports offline artifact-only synthesis', async () => {
  const rootDir = makeRepoFixture();
  const result = await buildTaiwanAgentTeam({ query: '離線整合', offline: true }, { rootDir });
  assert.equal(result.request.offline, true);
  assert.equal(result.synthesis.marketRegime.label, 'artifact-only');
  assert.ok(result.synthesis.dataGaps.some((gap) => gap.includes('offline mode')));
});
