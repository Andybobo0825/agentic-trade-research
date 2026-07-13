import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';

function callMcp(message) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ['src/mcp-server.js'], { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    const timeout = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new Error(`MCP call timed out. stderr=${stderr}`));
    }, 3000);
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
      const line = stdout.split('\n').find(Boolean);
      if (!line) return;
      clearTimeout(timeout);
      child.kill('SIGTERM');
      try { resolve(JSON.parse(line)); } catch (error) { reject(error); }
    });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.stdin.write(`${JSON.stringify(message)}\n`);
  });
}

test('MCP tools/list exposes low-token output controls', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 1, method: 'tools/list' });
  const endpoints = response.result.tools.find((tool) => tool.name === 'endpoints');
  assert.ok(endpoints);
  assert.ok(endpoints.inputSchema.properties.format);
  assert.ok(endpoints.inputSchema.properties.outputFields);
  assert.ok(endpoints.inputSchema.properties.maxRows);
});

test('MCP tools/call defaults to compact JSON text', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 2, method: 'tools/call', params: { name: 'endpoints', arguments: {} } });
  const text = response.result.content[0].text;
  assert.equal(text.includes('\n  '), false);
  assert.match(text, /^\{"endpoints":/);
});

test('MCP tools/list exposes hma-signal input schema', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 3, method: 'tools/list' });
  const tool = response.result.tools.find((entry) => entry.name === 'hma-signal');
  assert.ok(tool);
  assert.equal(tool.inputSchema.required.includes('ticker'), true);
  assert.ok(tool.inputSchema.properties.period);
  assert.ok(tool.inputSchema.properties.source);
  assert.ok(tool.inputSchema.properties.startDate);
});

test('MCP tools/list exposes signal-study input schema', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 4, method: 'tools/list' });
  const tool = response.result.tools.find((entry) => entry.name === 'signal-study');
  assert.ok(tool);
  assert.equal(tool.inputSchema.required.includes('ticker'), true);
  assert.ok(tool.inputSchema.properties.volumeWindow);
  assert.ok(tool.inputSchema.properties.institutionalDays);
  assert.ok(tool.inputSchema.properties.forwardDays);
  assert.ok(tool.inputSchema.properties.falseBreakoutDays);
});

test('MCP tools/list exposes daily-decision-study input schema', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 5, method: 'tools/list' });
  const tool = response.result.tools.find((entry) => entry.name === 'daily-decision-study');
  assert.ok(tool);
  assert.equal(tool.inputSchema.required.includes('ticker'), true);
  assert.ok(tool.inputSchema.properties.decisionDays);
  assert.ok(tool.inputSchema.properties.lookbackBars);
  assert.ok(tool.inputSchema.properties.minAverageTurnover);
  assert.ok(tool.inputSchema.properties.maxPositionPctOfAvgVolume);
});

test('MCP tools/list exposes chip-study input schema', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 6, method: 'tools/list' });
  const tool = response.result.tools.find((entry) => entry.name === 'chip-study');
  assert.ok(tool);
  assert.equal(tool.inputSchema.required.includes('ticker'), true);
  assert.ok(tool.inputSchema.properties.foreignDays);
  assert.ok(tool.inputSchema.properties.holderWeeks);
  assert.ok(tool.inputSchema.properties.minHolderLots);
  assert.ok(tool.inputSchema.properties.forwardDays);
});

test('MCP tools/list exposes Shioaji read-only tool schema', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 7, method: 'tools/list' });
  const quote = response.result.tools.find((entry) => entry.name === 'shioaji-quote');
  const orderbook = response.result.tools.find((entry) => entry.name === 'shioaji-orderbook');
  const ticks = response.result.tools.find((entry) => entry.name === 'shioaji-ticks');
  assert.ok(quote);
  assert.ok(orderbook);
  assert.ok(ticks);
  assert.equal(quote.inputSchema.required.includes('ticker'), true);
  assert.ok(orderbook.inputSchema.properties.timeoutMs);
  assert.ok(ticks.inputSchema.properties.last);
});


test('MCP tools/list exposes sector-flow input schema', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 8, method: 'tools/list' });
  const tool = response.result.tools.find((entry) => entry.name === 'sector-flow');
  assert.ok(tool);
  assert.ok(tool.inputSchema.properties.mode);
  assert.ok(tool.inputSchema.properties.tickers);
  assert.ok(tool.inputSchema.properties.rankBy);
});

test('MCP tools/list exposes xiaoyu-etf input schema', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 9, method: 'tools/list' });
  const tool = response.result.tools.find((entry) => entry.name === 'xiaoyu-etf');
  assert.ok(tool);
  assert.ok(tool.inputSchema.properties.mode);
  assert.ok(tool.inputSchema.properties.ticker);
  assert.ok(tool.inputSchema.properties.etf);
  assert.ok(tool.inputSchema.properties.scope);
  assert.ok(tool.inputSchema.properties.direction);
});


test('MCP tools/list exposes taiwan-agent-team input schema', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 10, method: 'tools/list' });
  const tool = response.result.tools.find((entry) => entry.name === 'taiwan-agent-team');
  assert.ok(tool);
  assert.ok(tool.inputSchema.properties.query);
  assert.ok(tool.inputSchema.properties.tickers);
  assert.ok(tool.inputSchema.properties.offline);
  assert.ok(tool.inputSchema.properties.capital);
});

test('MCP exposes closed read-only Phase 3 schemas without promotion', async () => {
  const response = await callMcp({ jsonrpc: '2.0', id: 11, method: 'tools/list' });
  const dataset = response.result.tools.find((entry) => entry.name === 'phase3-dataset');
  const screen = response.result.tools.find((entry) => entry.name === 'phase3-screen');
  assert.ok(dataset);
  assert.ok(screen);
  assert.equal(dataset.inputSchema.additionalProperties, false);
  assert.equal(screen.inputSchema.additionalProperties, false);
  assert.deepEqual(screen.inputSchema.required, []);
  assert.ok(screen.inputSchema.properties.evidenceRoot);
  assert.ok(screen.inputSchema.properties.candidateArtifact);
  assert.ok(screen.inputSchema.properties.top);
  assert.ok(screen.inputSchema.properties.includeRejected);
  for (const key of ['live', 'account', 'credential', 'certificate', 'placeOrder']) {
    assert.equal(screen.inputSchema.properties[key], undefined);
  }
  assert.equal(response.result.tools.some((entry) => entry.name === 'phase3-demo-promotion'), false);
});

test('MCP rejects unsafe Phase 3 screen arguments before reading evidence', async () => {
  const response = await callMcp({
    jsonrpc: '2.0',
    id: 12,
    method: 'tools/call',
    params: { name: 'phase3-screen', arguments: { live: true } },
  });
  assert.match(response.error.message, /forbids live|unsupported.*live/i);
});
