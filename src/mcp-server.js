#!/usr/bin/env node
import { loadDotEnv } from './dotenv.js';
loadDotEnv();
import readline from 'node:readline';
import { renderToolResult, runTool, tools } from './tools.js';
import { TAIWAN_AGENT_TEAM_INPUT_SCHEMA } from './taiwan-agent-team.js';

const serverInfo = { name: 'codex-finance-tools', version: '0.1.0' };

function toolSchema(name, tool) {
  const base = {
    name,
    description: tool.description,
    inputSchema: { type: 'object', properties: {}, additionalProperties: true },
  };
  if (name === 'statement') {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      statement: { type: 'string', enum: ['income', 'balance', 'cash-flow', 'financials'] },
      period: { type: 'string', enum: ['annual', 'quarterly'] },
      limit: { type: 'number' },
    };
    base.inputSchema.required = ['ticker'];
  } else if (['metrics', 'price', 'filings'].includes(name)) {
    base.inputSchema.properties = { ticker: { type: 'string' }, limit: { type: 'number' }, filingType: { type: 'string' } };
    base.inputSchema.required = ['ticker'];
  } else if (name === 'news') {
    base.inputSchema.properties = { ticker: { type: 'string' }, limit: { type: 'number' } };
  } else if (name === 'hma-signal') {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      market: { type: 'string', enum: ['tw', 'taiwan'] },
      source: { type: 'string', enum: ['finmind', 'tw-price', 'fugle'] },
      provider: { type: 'string' },
      period: { type: 'number', description: 'Hull MA period. Defaults to 20, matching the provided Pine input.' },
      startDate: { type: 'string' },
      endDate: { type: 'string' },
      limit: { type: 'number' },
      scope: { type: 'string', enum: ['intraday', 'historical'] },
      timeframe: { type: 'string' },
      from: { type: 'string' },
      to: { type: 'string' },
      adjusted: { type: 'string' },
    };
    base.inputSchema.required = ['ticker'];
  } else if (name === 'signal-study') {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      market: { type: 'string', enum: ['tw', 'taiwan'] },
      provider: { type: 'string' },
      period: { type: 'number', description: 'Hull MA period. Defaults to 20.' },
      startDate: { type: 'string' },
      endDate: { type: 'string' },
      limit: { type: 'number' },
      volumeWindow: { type: 'number' },
      volumeMultiplier: { type: 'number' },
      institutionalDays: { type: 'number' },
      institutionalProvider: { type: 'string' },
      institutionalLimit: { type: 'number' },
      liquidityWindow: { type: 'number' },
      minAverageVolume: { type: 'number' },
      minAverageTurnover: { type: 'number' },
      maxPositionPctOfAvgVolume: { type: 'number' },
      forwardDays: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'number' } }] },
      falseBreakoutDays: { type: 'number' },
      falseBreakoutThreshold: { type: 'number' },
    };
    base.inputSchema.required = ['ticker'];
  } else if (name === 'daily-decision-study') {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      market: { type: 'string', enum: ['tw', 'taiwan'] },
      provider: { type: 'string' },
      period: { type: 'number', description: 'Hull MA period. Defaults to 20.' },
      startDate: { type: 'string' },
      endDate: { type: 'string' },
      limit: { type: 'number' },
      decisionDays: { type: 'number' },
      lookbackBars: { type: 'number' },
      volumeWindow: { type: 'number' },
      volumeMultiplier: { type: 'number' },
      liquidityWindow: { type: 'number' },
      minAverageVolume: { type: 'number' },
      minAverageTurnover: { type: 'number' },
      maxPositionPctOfAvgVolume: { type: 'number' },
      forwardDays: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'number' } }] },
    };
    base.inputSchema.required = ['ticker'];
  } else if (name === 'chip-study') {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      market: { type: 'string', enum: ['tw', 'taiwan'] },
      provider: { type: 'string' },
      period: { type: 'number', description: 'Hull MA period used for price/volume confirmation. Defaults to 20.' },
      startDate: { type: 'string' },
      endDate: { type: 'string' },
      limit: { type: 'number' },
      foreignDays: { type: 'number', description: 'Required consecutive net-buy days by foreign investors. Defaults to 3.' },
      holderWeeks: { type: 'number', description: 'Required consecutive increases in holder distribution observations. Defaults to 3.' },
      minHolderLots: { type: 'number', description: 'Minimum holding-share level lower bound in lots. Defaults to 1000.' },
      holdingLimit: { type: 'number' },
      volumeWindow: { type: 'number' },
      volumeMultiplier: { type: 'number' },
      institutionalProvider: { type: 'string' },
      institutionalLimit: { type: 'number' },
      liquidityWindow: { type: 'number' },
      minAverageVolume: { type: 'number' },
      minAverageTurnover: { type: 'number' },
      maxPositionPctOfAvgVolume: { type: 'number' },
      forwardDays: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'number' } }] },
    };
    base.inputSchema.required = ['ticker'];
  } else if (name === 'phase3-dataset') {
    base.inputSchema.additionalProperties = false;
    base.inputSchema.properties = {
      universeFile: { type: 'string' },
      startDate: { type: 'string' },
      endDate: { type: 'string' },
      evidenceRoot: { type: 'string' },
      reportJson: { type: 'string' },
      reportMarkdown: { type: 'string' },
      refreshUniverse: { type: 'boolean' },
    };
    base.inputSchema.required = [];
  } else if (name === 'phase3-screen') {
    base.inputSchema.additionalProperties = false;
    base.inputSchema.properties = {
      startDate: { type: 'string' },
      endDate: { type: 'string' },
      evidenceRoot: { type: 'string' },
      candidateArtifact: { type: 'string' },
      top: { type: 'number' },
      includeRejected: { type: 'boolean' },
      rebuild: { type: 'boolean' },
      reportJson: { type: 'string' },
      reportMarkdown: { type: 'string' },
    };
    base.inputSchema.required = [];
  } else if (name === 'sector-flow') {
    base.inputSchema.properties = {
      mode: { type: 'string', enum: ['realtime', 'close'] },
      date: { type: 'string' },
      tickers: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }] },
      exchange: { type: 'string', enum: ['TSE', 'OTC'] },
      securityType: { type: 'string', enum: ['STK'] },
      provider: { type: 'string' },
      companyProvider: { type: 'string' },
      institutionalProvider: { type: 'string' },
      rankBy: { type: 'string', enum: ['turnover', 'institutionalNetValue', 'foreignNetValue', 'investmentTrustNetValue'] },
      chunkSize: { type: 'number' },
      limit: { type: 'number' },
    };
  } else if (name === 'preopen-brief') {
    base.inputSchema.properties = {
      date: { type: 'string' },
      updateTime: { type: 'string' },
      month: { type: 'number' },
      watchlist: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }] },
      fxPreviousClose: { type: 'number' },
      fxCurrent: { type: 'number' },
      futureClose: { type: 'number' },
      futureChange: { type: 'number' },
      futureVolume: { type: 'number' },
      previousSpotClose: { type: 'number' },
      usMoves: { oneOf: [{ type: 'string' }, { type: 'object' }] },
      branchData: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'object' } }] },
      branchFile: { type: 'string' },
      auctionData: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'object' } }] },
      auctionFile: { type: 'string' },
      auctionThresholdPct: { type: 'number' },
      noFetch: { type: 'boolean' },
      spotFrom: { type: 'string' },
    };
  } else if (name === 'market-diagnosis') {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      provider: { type: 'string' },
      startDate: { type: 'string' },
      endDate: { type: 'string' },
    };
  } else if (name === 'judgment-validate') {
    base.inputSchema.properties = {
      judgment: { type: 'object' },
      facts: { type: 'object' },
      report: { type: 'string' },
      judgmentFile: { type: 'string' },
      factsFile: { type: 'string' },
      reportFile: { type: 'string' },
      tickers: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }] },
    };
  } else if (name === 'experience-log') {
    base.inputSchema.properties = {
      regime: { type: 'string', enum: ['spike', 'tight_channel', 'normal_channel', 'trading_range', 'insufficient_data'] },
      date: { type: 'string' },
      ticker: { type: 'string' },
      judgment: { type: 'object' },
      note: { type: 'string' },
    };
  } else if (name === 'experience-recall') {
    base.inputSchema.properties = {
      regime: { type: 'string', enum: ['spike', 'tight_channel', 'normal_channel', 'trading_range', 'insufficient_data'] },
      limit: { type: 'number' },
    };
  } else if (name === 'xiaoyu-etf') {
    base.inputSchema.properties = {
      mode: { type: 'string', enum: ['stock', 'etf', 'rank', 'overview'] },
      ticker: { type: 'string' },
      etf: { type: 'string' },
      scope: { type: 'string', enum: ['active', 'market'] },
      window: { type: 'string', enum: ['d1', 'd5', 'd10', 'd20', 'd60'] },
      direction: { type: 'string', enum: ['buy', 'sell'] },
      limit: { type: 'number' },
      includeDetail: { type: 'boolean' },
      baseUrl: { type: 'string' },
    };
  } else if (name === 'taiwan-agent-team') {
    base.inputSchema.properties = TAIWAN_AGENT_TEAM_INPUT_SCHEMA;
  } else if (name.startsWith('tw-')) {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      provider: { type: 'string' },
      startDate: { type: 'string' },
      endDate: { type: 'string' },
      limit: { type: 'number' },
      statement: { type: 'string' },
      dataset: { type: 'string' },
      endpoint: { type: 'string' },
    };
    if (!['tw-endpoints', 'tw-raw'].includes(name)) base.inputSchema.required = ['ticker'];
  } else if (name.startsWith('fugle-')) {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      type: { type: 'string' },
      timeframe: { type: 'string' },
      sort: { type: 'string' },
      from: { type: 'string' },
      to: { type: 'string' },
      adjusted: { type: 'string' },
      fields: { type: 'string' },
      limit: { type: 'number' },
      scope: { type: 'string', enum: ['intraday', 'historical'] },
      market: { type: 'string' },
      kind: { type: 'string', enum: ['quotes', 'movers', 'actives'] },
      indicator: { type: 'string', enum: ['sma', 'rsi', 'kdj', 'macd', 'bb'] },
      period: { type: 'string' },
      fastPeriod: { type: 'string' },
      slowPeriod: { type: 'string' },
      signalPeriod: { type: 'string' },
      endpoint: { type: 'string' },
    };
    if (!['fugle-snapshot', 'fugle-raw'].includes(name)) base.inputSchema.required = ['ticker'];
    if (name === 'fugle-raw') base.inputSchema.required = ['endpoint'];
  } else if (name.startsWith('shioaji-')) {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      tickers: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }] },
      exchange: { type: 'string', enum: ['TSE', 'OTC', 'OES', 'TAIFEX'] },
      securityType: { type: 'string', enum: ['STK', 'FUT', 'OPT', 'IND'] },
      page: { type: 'number' },
      pageSize: { type: 'number' },
      start: { type: 'string' },
      end: { type: 'string' },
      startDate: { type: 'string' },
      endDate: { type: 'string' },
      chunkSize: { type: 'number' },
      cacheDir: { type: 'string' },
      refresh: { type: 'boolean' },
      timeoutMs: { type: 'number', description: 'Only for shioaji-orderbook SSE wait. Defaults to 3000 ms.' },
      intradayOdd: { type: 'boolean' },
      date: { type: 'string' },
      last: { type: 'number' },
      all: { type: 'boolean' },
      timeStart: { type: 'string' },
      timeEnd: { type: 'string' },
    };
    if (['shioaji-snapshots', 'shioaji-cache-kbars'].includes(name)) base.inputSchema.required = ['tickers'];
    else if (['shioaji-contracts'].includes(name)) base.inputSchema.required = [];
    else if (['shioaji-daily-quotes'].includes(name)) base.inputSchema.required = ['date'];
    else if (['shioaji-cache-daily-quotes'].includes(name)) base.inputSchema.required = [];
    else base.inputSchema.required = ['ticker'];
    if (['shioaji-kbars', 'shioaji-cache-kbars', 'shioaji-cache-daily-quotes'].includes(name)) {
      base.inputSchema.required = [...base.inputSchema.required, 'start', 'end'];
    }
  } else if (name === 'research-pack') {
    base.inputSchema.properties = {
      ticker: { type: 'string' },
      market: { type: 'string', enum: ['us', 'tw', 'taiwan'] },
      include: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }] },
      limit: { type: 'number' },
      newsLimit: { type: 'number' },
      filingLimit: { type: 'number' },
      statementLimit: { type: 'number' },
      announcementLimit: { type: 'number' },
      hmaLimit: { type: 'number' },
      hmaPeriod: { type: 'number' },
      hmaSource: { type: 'string', enum: ['finmind', 'tw-price', 'fugle'] },
      volumeWindow: { type: 'number' },
      volumeMultiplier: { type: 'number' },
      institutionalDays: { type: 'number' },
      institutionalProvider: { type: 'string' },
      institutionalLimit: { type: 'number' },
      holdingLimit: { type: 'number' },
      foreignDays: { type: 'number' },
      holderWeeks: { type: 'number' },
      minHolderLots: { type: 'number' },
      decisionDays: { type: 'number' },
      lookbackBars: { type: 'number' },
      forwardDays: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'number' } }] },
      falseBreakoutDays: { type: 'number' },
      falseBreakoutThreshold: { type: 'number' },
      statement: { type: 'string' },
      period: { type: 'string' },
      provider: { type: 'string' },
      startDate: { type: 'string' },
      endDate: { type: 'string' },
      liquidityWindow: { type: 'number' },
      minAverageVolume: { type: 'number' },
      minAverageTurnover: { type: 'number' },
      maxPositionPctOfAvgVolume: { type: 'number' },
    };
    base.inputSchema.required = ['ticker'];
  }
  base.inputSchema.properties = { ...outputControlProperties(), ...base.inputSchema.properties };
  return base;
}

function outputControlProperties() {
  return {
    format: { type: 'string', enum: ['compact-json', 'json', 'markdown'], description: 'Output rendering only. compact-json is the MCP default to reduce Codex token use.' },
    outputFields: { oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }], description: 'Optional output-only field projection for row objects. Does not reduce upstream fetch coverage.' },
    maxRows: { type: 'number', description: 'Optional output-only row cap for rendered arrays. Use API limit separately when you intentionally want to fetch less data.' },
  };
}

async function handle(message) {
  const { id, method, params = {} } = message;
  if (method === 'initialize') return { jsonrpc: '2.0', id, result: { protocolVersion: '2024-11-05', capabilities: { tools: {} }, serverInfo } };
  if (method === 'tools/list') return { jsonrpc: '2.0', id, result: { tools: Object.entries(tools).map(([name, tool]) => toolSchema(name, tool)) } };
  if (method === 'tools/call') {
    const args = params.arguments || {};
    const { format = 'compact-json', outputFields, maxRows, ...toolArgs } = args;
    const result = await runTool(params.name, toolArgs);
    return { jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: renderToolResult(params.name, result, format, { fields: outputFields, maxRows }).trimEnd() }] } };
  }
  if (id === undefined) return null;
  return { jsonrpc: '2.0', id, error: { code: -32601, message: `Unknown method: ${method}` } };
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on('line', async (line) => {
  if (!line.trim()) return;
  try {
    const response = await handle(JSON.parse(line));
    if (response) process.stdout.write(`${JSON.stringify(response)}\n`);
  } catch (error) {
    const id = safeId(line);
    process.stdout.write(`${JSON.stringify({ jsonrpc: '2.0', id, error: { code: -32000, message: error.message || String(error) } })}\n`);
  }
});

function safeId(line) {
  try { return JSON.parse(line).id ?? null; } catch { return null; }
}
