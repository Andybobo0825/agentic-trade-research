import { getStatement, getMetrics, getPrice, getNews, getFilings, listEndpoints } from './financial-datasets.js';
import {
  getTaiwanAnnouncements,
  getTaiwanCompany,
  getTaiwanFinancials,
  getTaiwanHoldingShares,
  getTaiwanInstitutional,
  getTaiwanNews,
  getTaiwanPrice,
  getTaiwanRaw,
  getTaiwanRevenue,
  getTaiwanValuation,
  getFugleCandles,
  getFugleHistoricalStats,
  getFugleQuote,
  getFugleRaw,
  getFugleSnapshot,
  getFugleTechnical,
  getFugleTicker,
  getFugleTrades,
  getFugleVolumes,
  listTaiwanEndpoints,
} from './taiwan-market.js';
import { getShioajiContract, getShioajiContracts, getShioajiDailyQuotes, getShioajiKbars, getShioajiOrderBook, getShioajiSnapshot, getShioajiSnapshots, getShioajiTicks } from './shioaji-market.js';
import { cacheShioajiDailyQuotes, cacheShioajiKbars } from './shioaji-pipeline.js';
import { getIcTpexCategory, getIcTpexCompanyChain } from './ic-tpex.js';
import { buildSectorFlow } from './sector-flow.js';
import { buildPreopenBrief, renderPreopenBriefMarkdown } from './preopen-brief.js';
import { loadMemoryEntryFile, renderMemorySyncMarkdown, syncDynamicMemory } from './dynamic-memory.js';
import { buildXiaoyuEtfLens, renderXiaoyuEtfMarkdown } from './xiaoyu-etf.js';
import { buildTaiwanAgentTeam, renderTaiwanAgentTeamMarkdown } from './taiwan-agent-team.js';
import { renderPhase3DatasetMarkdown, runPhase3Dataset } from './phase3-dataset.js';
import { renderPhase3ScreenMarkdown, runPhase3Screen } from './phase3-screen.js';
import { compactJson, compactNumber, shapeForTokenBudget, toMarkdownTable } from './format.js';
import { detectHmaSignals, evaluateHmaTrendSignal, normalizeCandleRows } from './indicators.js';

function unwrapArray(payload) {
  const data = payload.data || {};
  for (const value of Object.values(data)) {
    if (Array.isArray(value)) return value;
  }
  return Array.isArray(data) ? data : [];
}

function taiwanRows(result) {
  return Array.isArray(result.data) ? result.data : unwrapArray(result);
}

function pick(row, names) {
  for (const name of names) {
    if (row?.[name] !== undefined && row?.[name] !== '') return row[name];
  }
  return undefined;
}

function fugleArray(result) {
  if (Array.isArray(result.data)) return result.data;
  if (Array.isArray(result.data?.data)) return result.data.data;
  return [];
}

function shioajiTicks(result) {
  return Array.isArray(result.data?.ticks) ? result.data.ticks : [];
}

function shioajiKbars(result) {
  return Array.isArray(result.data?.rows) ? result.data.rows : [];
}

export const tools = {
  endpoints: {
    description: 'List supported US/Financial Datasets endpoint aliases.',
    async run() {
      return { endpoints: listEndpoints() };
    },
  },
  statement: {
    description: 'Fetch US income, balance, cash-flow, or combined financial statements for a ticker.',
    async run(args) {
      return getStatement(args);
    },
    toMarkdown(result) {
      const rows = unwrapArray(result).slice(0, 10);
      return toMarkdownTable(rows, [
        { label: 'Period', value: (r) => r.report_period || r.period || r.calendar_date },
        { label: 'Revenue', value: (r) => compactNumber(r.revenue) },
        { label: 'Net Inc', value: (r) => compactNumber(r.net_income) },
        { label: 'FCF', value: (r) => compactNumber(r.free_cash_flow) },
      ]);
    },
  },
  metrics: {
    description: 'Fetch latest US financial metrics snapshot for a ticker.',
    async run(args) {
      return getMetrics(args);
    },
  },
  price: {
    description: 'Fetch latest US stock price snapshot for a ticker.',
    async run(args) {
      return getPrice(args);
    },
  },
  news: {
    description: 'Fetch recent company or market news.',
    async run(args) {
      return getNews(args);
    },
  },
  filings: {
    description: 'Fetch SEC filings metadata for a ticker.',
    async run(args) {
      return getFilings(args);
    },
    toMarkdown(result) {
      const rows = unwrapArray(result).slice(0, 10);
      return toMarkdownTable(rows, [
        { label: 'Date', value: (r) => r.filing_date || r.report_date },
        { label: 'Type', value: (r) => r.filing_type },
        { label: 'URL', value: (r) => r.filing_url || r.url || r.accession_number },
      ]);
    },
  },
  'tw-endpoints': {
    description: 'List free Taiwan data interfaces: FinMind datasets, TWSE OpenAPI, TPEx OpenAPI, and MOPS-backed endpoints.',
    async run() {
      return { endpoints: listTaiwanEndpoints() };
    },
  },
  'tw-price': {
    description: 'Fetch Taiwan stock OHLCV from FinMind history or latest TWSE/TPEx official OpenAPI snapshots.',
    async run(args) {
      return getTaiwanPrice(args);
    },
    toMarkdown(result) {
      return toMarkdownTable(taiwanRows(result).slice(0, 20), [
        { label: 'Date', value: (r) => pick(r, ['date', 'Date']) },
        { label: 'Code', value: (r) => pick(r, ['stock_id', 'Code', 'SecuritiesCompanyCode']) },
        { label: 'Name', value: (r) => pick(r, ['Name', 'CompanyName']) },
        { label: 'Open', value: (r) => pick(r, ['open', 'OpeningPrice', 'Open']) },
        { label: 'High', value: (r) => pick(r, ['max', 'HighestPrice', 'High']) },
        { label: 'Low', value: (r) => pick(r, ['min', 'LowestPrice', 'Low']) },
        { label: 'Close', value: (r) => pick(r, ['close', 'ClosingPrice', 'Close']) },
        { label: 'Volume', value: (r) => compactNumber(pick(r, ['Trading_Volume', 'trading_volume', 'TradeVolume', 'TradingShares'])) },
      ]);
    },
  },
  'tw-company': {
    description: 'Fetch Taiwan listed/OTC company profile from TWSE/TPEx OpenAPI or FinMind.',
    async run(args) {
      return getTaiwanCompany(args);
    },
  },
  'tw-revenue': {
    description: 'Fetch Taiwan monthly revenue from FinMind free API.',
    async run(args) {
      return getTaiwanRevenue(args);
    },
    toMarkdown(result) {
      return toMarkdownTable(taiwanRows(result).slice(0, 24), [
        { label: 'Date', value: (r) => pick(r, ['date']) },
        { label: 'Code', value: (r) => pick(r, ['stock_id']) },
        { label: 'Revenue', value: (r) => compactNumber(pick(r, ['revenue', 'Revenue'])) },
        { label: 'YoY %', value: (r) => pick(r, ['revenue_year_growth_rate']) },
        { label: 'MoM %', value: (r) => pick(r, ['revenue_month_growth_rate']) },
      ]);
    },
  },
  'tw-financials': {
    description: 'Fetch Taiwan financial statements from FinMind or official TWSE/TPEx MOPS-backed snapshots.',
    async run(args) {
      return getTaiwanFinancials(args);
    },
    toMarkdown(result) {
      const rows = taiwanRows(result).slice(0, 30);
      return toMarkdownTable(rows, [
        { label: 'Date', value: (r) => pick(r, ['date', '出表日期', '年度']) },
        { label: 'Code', value: (r) => pick(r, ['stock_id', '公司代號', 'Code', 'SecuritiesCompanyCode']) },
        { label: 'Type', value: (r) => pick(r, ['type', 'statement']) },
        { label: 'Item', value: (r) => pick(r, ['origin_name', 'label', '會計項目']) },
        { label: 'Value', value: (r) => compactNumber(pick(r, ['value', 'amount', '本期金額', '金額'])) },
      ]);
    },
  },
  'tw-institutional': {
    description: 'Fetch Taiwan institutional investor buy/sell data from FinMind or TPEx official OpenAPI.',
    async run(args) {
      return getTaiwanInstitutional(args);
    },
  },
  'tw-valuation': {
    description: 'Fetch Taiwan PER/PBR/dividend-yield data from TWSE/TPEx official OpenAPI or FinMind history.',
    async run(args) {
      return getTaiwanValuation(args);
    },
    toMarkdown(result) {
      return toMarkdownTable(taiwanRows(result).slice(0, 20), [
        { label: 'Date', value: (r) => pick(r, ['date', 'Date']) },
        { label: 'Code', value: (r) => pick(r, ['stock_id', 'Code', 'SecuritiesCompanyCode']) },
        { label: 'Name', value: (r) => pick(r, ['Name', 'CompanyName']) },
        { label: 'PER', value: (r) => pick(r, ['PER', 'PEratio', 'P/E ratio', '本益比']) },
        { label: 'PBR', value: (r) => pick(r, ['PBR', 'PBratio', 'P/B ratio', '股價淨值比']) },
        { label: 'Yield', value: (r) => pick(r, ['dividend_yield', 'DividendYield', '殖利率(%)']) },
      ]);
    },
  },
  'tw-announcements': {
    description: 'Fetch Taiwan material announcements from MOPS-backed TWSE/TPEx OpenAPI datasets.',
    async run(args) {
      return getTaiwanAnnouncements(args);
    },
  },
  'tw-news': {
    description: 'Fetch Taiwan stock news from FinMind.',
    async run(args) {
      return getTaiwanNews(args);
    },
  },
  'tw-raw': {
    description: 'Call a raw free Taiwan provider endpoint: provider=finmind dataset=... or provider=twse/tpex endpoint=/...',
    async run(args) {
      return getTaiwanRaw(args);
    },
  },
  'ic-tpex-category': {
    description: 'Fetch official TPEx/TWSE industry value-chain category membership from ic.tpex.org.tw for research classification.',
    async run(args) {
      return getIcTpexCategory(args || {});
    },
    toMarkdown(result) {
      const rows = (result.companies || []).slice(0, 100);
      return [`# ${result.title || result.ic}`, '', `Source: ${result.url}`, '', toMarkdownTable(rows, [
        { label: 'Code', value: (r) => r.code },
        { label: 'Name', value: (r) => r.name },
      ]), '', `Note: ${result.disclaimer}`].join('\n');
    },
  },
  'ic-tpex-chain': {
    description: 'Fetch official TPEx/TWSE industry value-chain page for one Taiwan stock code from ic.tpex.org.tw.',
    async run(args) {
      return getIcTpexCompanyChain(args || {});
    },
    toMarkdown(result) {
      return [`# ic.tpex chain: ${result.ticker}`, '', `Category: ${result.ic || '—'} ${result.title || ''}`.trim(), `Source: ${result.url}`, '', result.text || '', '', `Note: ${result.disclaimer}`].join('\n');
    },
  },
  'fugle-quote': {
    description: 'Fetch Fugle realtime intraday quote for a Taiwan symbol. Requires FUGLE_API_KEY.',
    async run(args) {
      return getFugleQuote(args);
    },
    toMarkdown(result) {
      const r = result.data || {};
      return toMarkdownTable([r], [
        { label: 'Date', value: (row) => row.date },
        { label: 'Code', value: (row) => row.symbol },
        { label: 'Name', value: (row) => row.name },
        { label: 'Last', value: (row) => row.lastPrice ?? row.closePrice },
        { label: 'Change', value: (row) => row.change },
        { label: 'Change %', value: (row) => row.changePercent },
        { label: 'Open', value: (row) => row.openPrice },
        { label: 'High', value: (row) => row.highPrice },
        { label: 'Low', value: (row) => row.lowPrice },
        { label: 'Volume', value: (row) => compactNumber(row.total?.tradeVolume) },
      ]);
    },
  },
  'fugle-ticker': {
    description: 'Fetch Fugle symbol metadata. Requires FUGLE_API_KEY.',
    async run(args) {
      return getFugleTicker(args);
    },
  },
  'fugle-candles': {
    description: 'Fetch Fugle intraday or historical candles. Requires FUGLE_API_KEY.',
    async run(args) {
      return getFugleCandles(args);
    },
    toMarkdown(result) {
      return toMarkdownTable(fugleArray(result).slice(0, 50), [
        { label: 'Date', value: (r) => r.date },
        { label: 'Open', value: (r) => r.open },
        { label: 'High', value: (r) => r.high },
        { label: 'Low', value: (r) => r.low },
        { label: 'Close', value: (r) => r.close },
        { label: 'Volume', value: (r) => compactNumber(r.volume) },
      ]);
    },
  },
  'fugle-trades': {
    description: 'Fetch Fugle intraday trades. Requires FUGLE_API_KEY.',
    async run(args) {
      return getFugleTrades(args);
    },
  },
  'fugle-volumes': {
    description: 'Fetch Fugle intraday price-volume table. Requires FUGLE_API_KEY.',
    async run(args) {
      return getFugleVolumes(args);
    },
  },
  'fugle-snapshot': {
    description: 'Fetch Fugle market snapshot quotes/movers/actives. Requires paid Developer/Advanced plan for snapshot endpoints.',
    async run(args) {
      return getFugleSnapshot(args);
    },
    toMarkdown(result) {
      return toMarkdownTable(fugleArray(result).slice(0, 50), [
        { label: 'Code', value: (r) => r.symbol },
        { label: 'Name', value: (r) => r.name },
        { label: 'Close', value: (r) => r.closePrice },
        { label: 'Change', value: (r) => r.change },
        { label: 'Change %', value: (r) => r.changePercent },
        { label: 'Volume', value: (r) => compactNumber(r.tradeVolume) },
        { label: 'Value', value: (r) => compactNumber(r.tradeValue) },
      ]);
    },
  },
  'fugle-stats': {
    description: 'Fetch Fugle 52-week historical stats. Requires FUGLE_API_KEY.',
    async run(args) {
      return getFugleHistoricalStats(args);
    },
  },
  'fugle-technical': {
    description: 'Fetch Fugle technical indicator data: sma, rsi, kdj, macd, or bb. Requires eligible Fugle plan.',
    async run(args) {
      return getFugleTechnical(args);
    },
  },
  'fugle-raw': {
    description: 'Call a raw Fugle stock REST endpoint path. Requires FUGLE_API_KEY.',
    async run(args) {
      return getFugleRaw(args);
    },
  },
  'shioaji-quote': {
    description: 'Fetch Shioaji/Sinotrade read-only realtime snapshot for a Taiwan stock via local Shioaji server. Requires shioaji server start.',
    async run(args) {
      return getShioajiSnapshot(args);
    },
    toMarkdown(result) {
      const r = result.data || {};
      return toMarkdownTable([r], [
        { label: 'Code', value: (row) => row.code },
        { label: 'Last', value: (row) => row.lastPrice },
        { label: 'Bid', value: (row) => row.bidPrice },
        { label: 'Ask', value: (row) => row.askPrice },
        { label: 'Volume', value: (row) => compactNumber(row.totalVolume) },
        { label: 'Limit', value: (row) => row.limitStatus?.isLimitUp ? '漲停' : row.limitStatus?.isLimitDown ? '跌停' : row.changeType || '—' },
      ]);
    },
  },
  'shioaji-contract': {
    description: 'Fetch one Shioaji/Sinotrade stock contract from the local Shioaji server.',
    async run(args) {
      return getShioajiContract(args);
    },
    toMarkdown(result) {
      const r = result.data || {};
      return toMarkdownTable([r], [
        { label: 'Code', value: (row) => row.code },
        { label: 'Name', value: (row) => row.name },
        { label: 'Exchange', value: (row) => row.exchange },
        { label: 'Symbol', value: (row) => row.symbol },
        { label: 'Unit', value: (row) => row.unit },
        { label: 'Updated', value: (row) => row.updateDate },
      ]);
    },
  },
  'shioaji-contracts': {
    description: 'Query Shioaji/Sinotrade contracts with pagination through the local Shioaji server.',
    async run(args) {
      return getShioajiContracts(args);
    },
    toMarkdown(result) {
      return toMarkdownTable((result.data || []).slice(0, 100), [
        { label: 'Code', value: (row) => row.code },
        { label: 'Name', value: (row) => row.name },
        { label: 'Exchange', value: (row) => row.exchange },
        { label: 'Symbol', value: (row) => row.symbol },
        { label: 'Unit', value: (row) => row.unit },
      ]);
    },
  },
  'shioaji-snapshots': {
    description: 'Fetch Shioaji/Sinotrade read-only realtime snapshots in batches of up to 500 contracts.',
    async run(args) {
      return getShioajiSnapshots(args);
    },
    toMarkdown(result) {
      return toMarkdownTable((result.data || []).slice(0, 100), [
        { label: 'Code', value: (row) => row.code },
        { label: 'Last', value: (row) => row.lastPrice },
        { label: 'Change %', value: (row) => row.changeRate },
        { label: 'Volume', value: (row) => compactNumber(row.totalVolume) },
        { label: 'Amount', value: (row) => compactNumber(row.totalAmount) },
        { label: 'Limit', value: (row) => row.limitStatus?.isLimitUp ? '漲停' : row.limitStatus?.isLimitDown ? '跌停' : row.changeType || '—' },
      ]);
    },
  },
  'shioaji-kbars': {
    description: 'Fetch Shioaji historical K-bars/OHLCV rows through the local Shioaji server.',
    async run(args) {
      return getShioajiKbars(args);
    },
    toMarkdown(result) {
      return toMarkdownTable(shioajiKbars(result).slice(0, 100), [
        { label: 'Date', value: (r) => r.date },
        { label: 'Open', value: (r) => r.open },
        { label: 'High', value: (r) => r.high },
        { label: 'Low', value: (r) => r.low },
        { label: 'Close', value: (r) => r.close },
        { label: 'Volume', value: (r) => compactNumber(r.volume) },
        { label: 'Amount', value: (r) => compactNumber(r.amount) },
      ]);
    },
  },
  'shioaji-daily-quotes': {
    description: 'Fetch Shioaji full-market daily OHLCV rows for one date.',
    async run(args) {
      return getShioajiDailyQuotes(args);
    },
    toMarkdown(result) {
      return toMarkdownTable((result.data?.rows || []).slice(0, 100), [
        { label: 'Date', value: (r) => r.date },
        { label: 'Code', value: (r) => r.code },
        { label: 'Open', value: (r) => r.open },
        { label: 'High', value: (r) => r.high },
        { label: 'Low', value: (r) => r.low },
        { label: 'Close', value: (r) => r.close },
        { label: 'Volume', value: (r) => compactNumber(r.volume) },
        { label: 'Amount', value: (r) => compactNumber(r.amount) },
      ]);
    },
  },
  'shioaji-cache-kbars': {
    description: 'Fetch Shioaji K-bars for tickers and write local JSON cache files for backtests.',
    async run(args) {
      return cacheShioajiKbars(args);
    },
    toMarkdown(result) {
      const rows = [
        ...(result.ok || []).map((row) => ({ ...row, status: 'fetched' })),
        ...(result.cached || []).map((row) => ({ ...row, status: 'cached', rows: '—' })),
        ...(result.failed || []).map((row) => ({ ...row, status: 'failed', rows: '—' })),
      ];
      const table = toMarkdownTable(rows, [
        { label: 'Code', value: (r) => r.code },
        { label: 'Status', value: (r) => r.status },
        { label: 'Rows', value: (r) => r.rows },
        { label: 'Path/Error', value: (r) => r.path || r.error },
      ]);
      return [`# Shioaji kbar cache`, ``, `Range: ${result.start} ~ ${result.end}`, `Cache: ${result.cacheDir}`, ``, table].join('\n');
    },
  },
  'shioaji-cache-daily-quotes': {
    description: 'Fetch Shioaji full-market daily OHLCV rows by date range and write local cache files for backtests.',
    async run(args) {
      return cacheShioajiDailyQuotes(args);
    },
    toMarkdown(result) {
      const rows = [
        ...(result.ok || []).map((row) => ({ ...row, status: 'fetched' })),
        ...(result.cached || []).map((row) => ({ ...row, status: 'cached', rows: '—' })),
        ...(result.failed || []).map((row) => ({ ...row, status: 'failed', rows: '—' })),
      ];
      const table = toMarkdownTable(rows, [
        { label: 'Date', value: (r) => r.date },
        { label: 'Status', value: (r) => r.status },
        { label: 'Rows', value: (r) => r.rows },
        { label: 'Path/Error', value: (r) => r.path || r.error },
      ]);
      return [`# Shioaji daily quote cache`, ``, `Cache: ${result.cacheDir}`, ``, table].join('\n');
    },
  },
  'shioaji-orderbook': {
    description: 'Fetch one Shioaji read-only realtime five-level bid/ask event via local Shioaji SSE stream. Requires shioaji server start.',
    async run(args) {
      return getShioajiOrderBook(args);
    },
    toMarkdown(result) {
      const rows = [];
      const bids = result.data?.bids || [];
      const asks = result.data?.asks || [];
      const len = Math.max(bids.length, asks.length);
      for (let index = 0; index < len; index += 1) {
        rows.push({ level: index + 1, bid: bids[index]?.price, bidVolume: bids[index]?.volume, ask: asks[index]?.price, askVolume: asks[index]?.volume });
      }
      return toMarkdownTable(rows, [
        { label: 'Level', value: (r) => r.level },
        { label: 'Bid', value: (r) => r.bid },
        { label: 'Bid Vol', value: (r) => r.bidVolume },
        { label: 'Ask', value: (r) => r.ask },
        { label: 'Ask Vol', value: (r) => r.askVolume },
      ]);
    },
  },
  'shioaji-ticks': {
    description: 'Fetch Shioaji read-only stock tick rows via local Shioaji server. Defaults to latest 10 ticks for the given date.',
    async run(args) {
      return getShioajiTicks(args);
    },
    toMarkdown(result) {
      return toMarkdownTable(shioajiTicks(result).slice(0, 50), [
        { label: 'Time', value: (r) => r.datetime },
        { label: 'Close', value: (r) => r.close },
        { label: 'Volume', value: (r) => r.volume },
        { label: 'Bid', value: (r) => r.bidPrice },
        { label: 'Bid Vol', value: (r) => r.bidVolume },
        { label: 'Ask', value: (r) => r.askPrice },
        { label: 'Ask Vol', value: (r) => r.askVolume },
      ]);
    },
  },
  'sector-flow': {
    description: 'Analyze Taiwan sector heat: realtime Shioaji turnover/limit-up heat or close FinMind/TWSE institutional money-flow proxy.',
    async run(args) {
      return buildSectorFlow(args || {});
    },
    toMarkdown(result) {
      return renderSectorFlowMarkdown(result);
    },
  },
  'preopen-brief': {
    description: 'Run the article-bounded Taiwan pre-open 30-minute workflow: FX, TX futures basis, US-vs-Taiwan relative strength, broker branch flow, auction checks, and no-chase constraints.',
    async run(args) {
      return buildPreopenBrief(args || {});
    },
    toMarkdown(result) {
      return renderPreopenBriefMarkdown(result);
    },
  },
  'hma-signal': {
    description: 'Fetch OHLCV candles and evaluate the Pine-compatible Hull MA trend signal with buy/sell watch suggestions.',
    async run(args) {
      return buildHmaSignal(args || {});
    },
    toMarkdown(result) {
      return renderHmaSignalMarkdown(result);
    },
  },
  'signal-study': {
    description: 'Study recent HMA trend signals with volume confirmation, Taiwan institutional flow, forward 3/5/10-day returns, false breakouts, confidence, and chase/wait/avoid advice.',
    async run(args) {
      return buildSignalStudy(args || {});
    },
    toMarkdown(result) {
      return renderSignalStudyMarkdown(result);
    },
  },
  'daily-decision-study': {
    description: 'Build point-in-time daily K-bar decision frames for Codex/advisor review, including HMA, volume, liquidity gates, and next-day/forward outcome checks.',
    async run(args) {
      return buildDailyDecisionStudy(args || {});
    },
    toMarkdown(result) {
      return renderDailyDecisionStudyMarkdown(result);
    },
  },
  'chip-study': {
    description: 'Backtest a Taiwan chip-flow screen: foreign investors buy N consecutive days, 1000-lot holder percentage rises N consecutive weeks, then confirm with price/volume/industry context.',
    async run(args) {
      return buildChipStudy(args || {});
    },
    toMarkdown(result) {
      return renderChipStudyMarkdown(result);
    },
  },
  'phase3-dataset': {
    description: 'Build and audit immutable Phase 3 point-in-time market and institutional evidence. Read-only; no order mode.',
    async run(args) {
      return runPhase3Dataset(args || {});
    },
    toMarkdown(result) {
      return renderPhase3DatasetMarkdown(result);
    },
  },
  'phase3-screen': {
    description: 'Run the deterministic Phase 3 technical screen over read-only point-in-time evidence; this tool has no live order mode.',
    async run(args) {
      return runPhase3Screen(args || {});
    },
    toMarkdown(result) {
      return renderPhase3ScreenMarkdown(result);
    },
  },
  'research-pack': {
    description: 'Fetch a complete investment-research bundle in one call while preserving source coverage; use format=markdown or compact-json to minimize Codex tokens.',
    async run(args) {
      return buildResearchPack(args || {});
    },
    toMarkdown(result) {
      return renderResearchPackMarkdown(result);
    },
  },
  'xiaoyu-etf': {
    description: 'Fetch Xiaoyu ETF public ETF-holding lens: active ETF flows, ETF holdings, stock-to-ETF reverse lookup, and inferred ETF buy/sell ranks. Auxiliary only; Shioaji remains primary for price/volume.',
    async run(args) {
      return buildXiaoyuEtfLens(args || {});
    },
    toMarkdown(result) {
      return renderXiaoyuEtfMarkdown(result);
    },
  },
  'taiwan-agent-team': {
    description: 'Run a Dexter-inspired Taiwan investment research agent team: planner, data integration, scratchpad audit, backtest evidence, Shioaji/ETF/sector tools, scenario synthesis, and verification. Adds a harness without replacing existing Taiwan workflows.',
    async run(args) {
      return buildTaiwanAgentTeam(args || {}, { runTool });
    },
    toMarkdown(result) {
      return renderTaiwanAgentTeamMarkdown(result);
    },
  },
  'memory-sync': {
    description: 'Synchronize repo-local dynamic memory layers under .omx/memory from selective JSON entries.',
    async run(args) {
      const entries = [
        ...(args.entryFile ? loadMemoryEntryFile(args.entryFile) : []),
        ...(args.entry ? [{ date: args.date, category: args.category, text: args.entry, source: args.source, reason: args.reason, obsolete: args.obsolete }] : []),
      ];
      return syncDynamicMemory({
        memoryDir: args.memoryDir,
        now: args.now,
        maxHotEntries: args.maxHotEntries,
        entries,
      });
    },
    toMarkdown(result) {
      return renderMemorySyncMarkdown(result);
    },
  },
};

export async function runTool(name, args) {
  const tool = tools[name];
  if (!tool) throw new Error(`Unknown tool '${name}'. Available: ${Object.keys(tools).join(', ')}`);
  return tool.run(args || {});
}

export function renderToolResult(name, result, format = 'json', options = {}) {
  const shaped = shapeForTokenBudget(result, options);
  if (format === 'markdown' && tools[name]?.toMarkdown) return `${tools[name].toMarkdown(shaped)}\n`;
  if (format === 'compact-json' || format === 'compact') return `${compactJson(shaped)}\n`;
  return `${JSON.stringify(shaped, null, 2)}\n`;
}

async function buildResearchPack(args) {
  const market = String(args.market || inferMarket(args.ticker)).toLowerCase();
  const include = normalizeInclude(args.include, market === 'tw' || market === 'taiwan' ? [
    'tw-company',
    'tw-price',
    'xiaoyu-etf',
    'chip-study',
    'signal-study',
    'tw-revenue',
    'tw-financials',
    'tw-valuation',
    'tw-announcements',
    'tw-news',
  ] : [
    'price',
    'metrics',
    'statement',
    'news',
    'filings',
  ]);
  const common = {
    ticker: args.ticker,
    limit: args.limit,
    startDate: args.startDate,
    endDate: args.endDate,
    provider: args.provider,
  };
  const results = {};
  const errors = {};
  for (const toolName of include) {
    if (toolName === 'research-pack') continue;
    if (!tools[toolName]) {
      errors[toolName] = `Unknown research-pack include '${toolName}'`;
      continue;
    }
    try {
      results[toolName] = await runTool(toolName, argsForResearchTool(toolName, args, common));
    } catch (error) {
      errors[toolName] = error?.message || String(error);
    }
  }
  return {
    ticker: args.ticker,
    market,
    coverage: include,
    tokenPolicy: {
      searchVolumePreserved: true,
      note: 'research-pack keeps the requested source coverage and fetch limits; token savings come from one tool call plus compact/markdown rendering, not from dropping data sources.',
    },
    results,
    errors,
  };
}

function inferMarket(ticker) {
  return /^\d{4,6}$/.test(String(ticker || '').trim()) ? 'tw' : 'us';
}

function normalizeInclude(include, fallback) {
  if (!include) return fallback;
  if (Array.isArray(include)) return include.map(String).map((s) => s.trim()).filter(Boolean);
  return String(include).split(',').map((s) => s.trim()).filter(Boolean);
}

function argsForResearchTool(toolName, args, common) {
  if (toolName === 'signal-study') {
    return {
      ticker: args.ticker,
      market: args.market,
      provider: args.provider,
      period: args.hmaPeriod || 20,
      startDate: args.startDate,
      endDate: args.endDate,
      limit: args.hmaLimit || args.limit,
      volumeWindow: args.volumeWindow,
      volumeMultiplier: args.volumeMultiplier,
      institutionalDays: args.institutionalDays,
      institutionalProvider: args.institutionalProvider,
      institutionalLimit: args.institutionalLimit,
      liquidityWindow: args.liquidityWindow,
      minAverageVolume: args.minAverageVolume,
      minAverageTurnover: args.minAverageTurnover,
      maxPositionPctOfAvgVolume: args.maxPositionPctOfAvgVolume,
      forwardDays: args.forwardDays,
      falseBreakoutDays: args.falseBreakoutDays,
      falseBreakoutThreshold: args.falseBreakoutThreshold,
    };
  }
  if (toolName === 'hma-signal') {
    return {
      ticker: args.ticker,
      market: args.market,
      source: args.hmaSource || args.source,
      provider: args.provider,
      period: args.hmaPeriod || 20,
      startDate: args.startDate,
      endDate: args.endDate,
      limit: args.hmaLimit || args.limit,
    };
  }
  if (toolName === 'daily-decision-study') {
    return {
      ticker: args.ticker,
      market: args.market,
      provider: args.provider,
      period: args.hmaPeriod || args.period || 20,
      startDate: args.startDate,
      endDate: args.endDate,
      limit: args.hmaLimit || args.limit,
      decisionDays: args.decisionDays,
      lookbackBars: args.lookbackBars,
      volumeWindow: args.volumeWindow,
      volumeMultiplier: args.volumeMultiplier,
      liquidityWindow: args.liquidityWindow,
      minAverageVolume: args.minAverageVolume,
      minAverageTurnover: args.minAverageTurnover,
      maxPositionPctOfAvgVolume: args.maxPositionPctOfAvgVolume,
      forwardDays: args.forwardDays,
    };
  }
  if (toolName === 'chip-study') {
    return {
      ticker: args.ticker,
      market: args.market,
      provider: args.provider,
      period: args.hmaPeriod || args.period || 20,
      startDate: args.startDate,
      endDate: args.endDate,
      limit: args.hmaLimit || args.limit,
      foreignDays: args.foreignDays,
      holderWeeks: args.holderWeeks,
      minHolderLots: args.minHolderLots,
      volumeWindow: args.volumeWindow,
      volumeMultiplier: args.volumeMultiplier,
      liquidityWindow: args.liquidityWindow,
      minAverageVolume: args.minAverageVolume,
      minAverageTurnover: args.minAverageTurnover,
      maxPositionPctOfAvgVolume: args.maxPositionPctOfAvgVolume,
      forwardDays: args.forwardDays,
      institutionalProvider: args.institutionalProvider,
      institutionalLimit: args.institutionalLimit,
      holdingLimit: args.holdingLimit,
    };
  }
  if (toolName === 'xiaoyu-etf') {
    return {
      mode: 'stock',
      ticker: args.ticker,
      limit: args.xiaoyuLimit || args.limit || 10,
      baseUrl: args.xiaoyuBaseUrl,
    };
  }
  if (toolName === 'statement') {
    return {
      ticker: args.ticker,
      statement: args.statement || 'income',
      period: args.period || 'annual',
      limit: args.statementLimit || args.limit || 5,
    };
  }
  if (toolName === 'filings') {
    return { ticker: args.ticker, filingType: args.filingType || args['filing-type'], limit: args.filingLimit || args.limit || 5 };
  }
  if (toolName === 'news' || toolName === 'tw-news') return { ...common, limit: args.newsLimit || args.limit || 10 };
  if (toolName === 'tw-announcements') return { ...common, limit: args.announcementLimit || args.limit || 10 };
  if (toolName === 'tw-financials') return { ...common, statement: args.statement || 'income', limit: args.statementLimit || args.limit };
  return common;
}

async function buildHmaSignal(args) {
  const ticker = String(args.ticker || '').trim();
  if (!ticker) throw new Error('hma-signal requires ticker');
  const market = String(args.market || inferMarket(ticker)).toLowerCase();
  if (!['tw', 'taiwan'].includes(market)) {
    throw new Error('hma-signal currently supports Taiwan tickers via tw-price/FinMind or Fugle candles. Pass market=tw for numeric Taiwan symbols.');
  }
  const period = Number(args.period || 20);
  const source = String(args.source || 'finmind').toLowerCase();
  const limit = args.limit ? Number(args.limit) : undefined;
  let raw;
  let rows;
  let dataSource;

  if (source === 'fugle') {
    raw = await getFugleCandles({
      ticker,
      scope: args.scope || 'historical',
      timeframe: args.timeframe || 'D',
      from: args.from || args.startDate,
      to: args.to || args.endDate,
      adjusted: args.adjusted,
      limit,
    });
    rows = fugleArray(raw);
    dataSource = { tool: 'fugle-candles', source: 'fugle', scope: args.scope || 'historical', timeframe: args.timeframe || 'D' };
  } else if (source === 'finmind' || source === 'tw-price') {
    raw = await getTaiwanPrice({
      ticker,
      provider: args.provider || 'finmind',
      startDate: args.startDate,
      endDate: args.endDate,
      limit,
    });
    rows = taiwanRows(raw);
    dataSource = { tool: 'tw-price', source: 'finmind', provider: args.provider || 'finmind' };
  } else {
    throw new Error('hma-signal source must be finmind, tw-price, or fugle');
  }

  const signal = evaluateHmaTrendSignal(rows, { period });
  return {
    ticker,
    market: 'tw',
    dataSource,
    params: {
      period: signal.period,
      source,
      startDate: args.startDate || args.from,
      endDate: args.endDate || args.to,
      limit,
    },
    signal: {
      ...signal,
      candles: signal.candles.slice(-10).map(({ date, open, high, low, close, volume, hma }) => ({ date, open, high, low, close, volume, hma })),
    },
    inputRows: normalizeCandleRows(rows).length,
  };
}

async function buildSignalStudy(args) {
  const ticker = String(args.ticker || '').trim();
  if (!ticker) throw new Error('signal-study requires ticker');
  const market = String(args.market || inferMarket(ticker)).toLowerCase();
  if (!['tw', 'taiwan'].includes(market)) throw new Error('signal-study currently supports Taiwan tickers. Pass market=tw for numeric Taiwan symbols.');

  const period = Number(args.period || 20);
  const volumeWindow = Number(args.volumeWindow || args['volume-window'] || 20);
  const institutionalDays = Number(args.institutionalDays || args['institutional-days'] || 5);
  const liquidityWindow = Number(args.liquidityWindow || args['liquidity-window'] || 20);
  const minAverageVolume = Number(args.minAverageVolume || args['min-average-volume'] || 1_000_000);
  const minAverageTurnover = Number(args.minAverageTurnover || args['min-average-turnover'] || 20_000_000);
  const maxPositionPctOfAvgVolume = Number(args.maxPositionPctOfAvgVolume || args['max-position-pct-of-avg-volume'] || 0.02);
  const forwardDays = normalizeForwardDays(args.forwardDays || args['forward-days'] || [3, 5, 10]);
  const falseBreakoutDays = Number(args.falseBreakoutDays || args['false-breakout-days'] || 5);
  const falseBreakoutThreshold = Number(args.falseBreakoutThreshold || args['false-breakout-threshold'] || 0.03);
  const volumeMultiplier = Number(args.volumeMultiplier || args['volume-multiplier'] || 1.2);
  const limit = args.limit ? Number(args.limit) : undefined;

  const priceResult = await getTaiwanPrice({
    ticker,
    provider: args.provider || 'finmind',
    startDate: args.startDate,
    endDate: args.endDate,
    limit,
  });
  const priceRows = taiwanRows(priceResult);
  const candles = normalizeCandleRows(priceRows);
  const hmaCurrent = evaluateHmaTrendSignal(candles, { period });
  const { series, signals } = detectHmaSignals(candles, { period });
  const buySignals = signals.filter((signal) => signal.type === 'buy');

  let institutionalRows = [];
  let institutionalError;
  try {
    const institutionalResult = await getTaiwanInstitutional({
      ticker,
      provider: args.institutionalProvider || 'finmind',
      startDate: args.startDate,
      endDate: args.endDate,
      limit: args.institutionalLimit ? Number(args.institutionalLimit) : undefined,
    });
    institutionalRows = taiwanRows(institutionalResult);
  } catch (error) {
    institutionalError = error?.message || String(error);
  }

  const forwardPerformance = summarizeForwardPerformance(series, buySignals, forwardDays);
  const falseBreakouts = summarizeFalseBreakouts(series, buySignals, { falseBreakoutDays, falseBreakoutThreshold });
  const volume = summarizeVolume(series, { volumeWindow, volumeMultiplier });
  const liquidity = summarizeLiquidity(series, { liquidityWindow, minAverageVolume, minAverageTurnover, maxPositionPctOfAvgVolume });
  const institutional = summarizeInstitutional(institutionalRows, { institutionalDays, error: institutionalError });
  const latestSignal = summarizeLatestSignal(signals, series, { hmaCurrent, volume, liquidity, institutional, forwardPerformance, falseBreakouts });
  const advice = buildSignalAdvice({ hmaCurrent, volume, liquidity, institutional, latestSignal });

  return {
    ticker,
    market: 'tw',
    params: {
      period,
      startDate: args.startDate,
      endDate: args.endDate,
      provider: args.provider || 'finmind',
      volumeWindow,
      volumeMultiplier,
      institutionalDays,
      liquidityWindow,
      minAverageVolume,
      minAverageTurnover,
      maxPositionPctOfAvgVolume,
      forwardDays,
      falseBreakoutDays,
      falseBreakoutThreshold,
      limit,
    },
    hma: {
      current: {
        trend: hmaCurrent.trend,
        action: hmaCurrent.action,
        suggestion: hmaCurrent.suggestion,
        reason: hmaCurrent.reason,
        latest: hmaCurrent.latest,
        stats: hmaCurrent.stats,
      },
      signals: signals.slice(-20),
      buySignalCount: buySignals.length,
      sellSignalCount: signals.filter((signal) => signal.type === 'sell').length,
    },
    volume,
    liquidity,
    institutional,
    forwardPerformance,
    falseBreakouts,
    latestSignal,
    advice,
    recentCandles: series.slice(-10).map(({ date, close, volume: candleVolume, hma }) => ({ date, close, volume: candleVolume, hma })),
    disclaimer: 'Signal study is a technical/flow screen, not personalized investment advice. AI-theme regimes can change quickly; confirm with news, liquidity, and risk controls.',
  };
}

async function buildDailyDecisionStudy(args) {
  const ticker = String(args.ticker || '').trim();
  if (!ticker) throw new Error('daily-decision-study requires ticker');
  const market = String(args.market || inferMarket(ticker)).toLowerCase();
  if (!['tw', 'taiwan'].includes(market)) throw new Error('daily-decision-study currently supports Taiwan tickers. Pass market=tw for numeric Taiwan symbols.');

  const period = Number(args.period || 20);
  const decisionDays = Number(args.decisionDays || args['decision-days'] || 20);
  const lookbackBars = Number(args.lookbackBars || args['lookback-bars'] || 60);
  const volumeWindow = Number(args.volumeWindow || args['volume-window'] || 20);
  const volumeMultiplier = Number(args.volumeMultiplier || args['volume-multiplier'] || 1.2);
  const liquidityWindow = Number(args.liquidityWindow || args['liquidity-window'] || 20);
  const minAverageVolume = Number(args.minAverageVolume || args['min-average-volume'] || 1_000_000);
  const minAverageTurnover = Number(args.minAverageTurnover || args['min-average-turnover'] || 20_000_000);
  const maxPositionPctOfAvgVolume = Number(args.maxPositionPctOfAvgVolume || args['max-position-pct-of-avg-volume'] || 0.02);
  const forwardDays = normalizeForwardDays(args.forwardDays || args['forward-days'] || [3, 5, 10]);
  const limit = args.limit ? Number(args.limit) : undefined;

  const priceResult = await getTaiwanPrice({
    ticker,
    provider: args.provider || 'finmind',
    startDate: args.startDate,
    endDate: args.endDate,
    limit,
  });
  const candles = normalizeCandleRows(taiwanRows(priceResult));
  const full = detectHmaSignals(candles, { period }).series;
  const eligibleIndexes = full
    .map((row, index) => ({ row, index }))
    .filter(({ index, row }) => index > 0 && row.hma !== null && row.close !== null)
    .slice(-decisionDays);

  const decisions = eligibleIndexes.map(({ index }) => {
    const history = candles.slice(0, index + 1);
    const historyWindow = history.slice(-lookbackBars);
    const hmaCurrent = evaluateHmaTrendSignal(history, { period });
    const { series, signals } = detectHmaSignals(history, { period });
    const volume = summarizeVolume(series, { volumeWindow, volumeMultiplier });
    const liquidity = summarizeLiquidity(series, { liquidityWindow, minAverageVolume, minAverageTurnover, maxPositionPctOfAvgVolume });
    const latestSignal = signals.at(-1) || null;
    const decision = buildPointInTimeDecision({ hmaCurrent, volume, liquidity, latestSignal });
    const current = full[index];
    return {
      date: current.date,
      pointInTime: true,
      decision,
      hma: {
        trend: hmaCurrent.trend,
        action: hmaCurrent.action,
        close: hmaCurrent.latest?.close ?? null,
        hma: hmaCurrent.latest?.hma ?? null,
        hmaSlope: hmaCurrent.stats?.hmaSlope ?? null,
      },
      volume,
      liquidity,
      latestSignal,
      forwardOutcome: summarizeDecisionForwardOutcome(full, index, forwardDays),
      advisorFrame: {
        ticker,
        market: 'tw',
        date: current.date,
        rules: [
          'point_in_time_only',
          'do_not_use_future_candles',
          'respect_liquidity_gate',
          'prefer_hma_volume_confirmation',
        ],
        candles: detectHmaSignals(historyWindow, { period }).series.map(({ date, open, high, low, close, volume: candleVolume, hma }) => ({
          date,
          open,
          high,
          low,
          close,
          volume: candleVolume,
          hma,
        })),
        features: {
          hmaTrend: hmaCurrent.trend,
          volumeConfirmed: volume.confirmed,
          liquidityEligible: liquidity.eligible,
          averageTurnover: liquidity.averageTurnover,
          averageVolume: liquidity.averageVolume,
          suggestedMaxLots: liquidity.suggestedMaxLots,
        },
      },
      advisorPrompt: buildAdvisorPrompt({ ticker, date: current.date, hmaCurrent, volume, liquidity }),
    };
  });

  return {
    ticker,
    market: 'tw',
    params: {
      period,
      decisionDays,
      lookbackBars,
      volumeWindow,
      volumeMultiplier,
      liquidityWindow,
      minAverageVolume,
      minAverageTurnover,
      maxPositionPctOfAvgVolume,
      forwardDays,
      provider: args.provider || 'finmind',
      startDate: args.startDate,
      endDate: args.endDate,
      limit,
    },
    inputRows: candles.length,
    decisions,
    disclaimer: 'Daily decision study creates point-in-time advisor frames. It does not call an LLM or place orders; use it as a structured input and audit trail for Codex/human review.',
  };
}

async function buildChipStudy(args) {
  const ticker = String(args.ticker || '').trim();
  if (!ticker) throw new Error('chip-study requires ticker');
  const market = String(args.market || inferMarket(ticker)).toLowerCase();
  if (!['tw', 'taiwan'].includes(market)) throw new Error('chip-study currently supports Taiwan tickers. Pass market=tw for numeric Taiwan symbols.');

  const period = Number(args.period || 20);
  const foreignDays = Number(args.foreignDays || args['foreign-days'] || 3);
  const holderWeeks = Number(args.holderWeeks || args['holder-weeks'] || 3);
  const minHolderLots = Number(args.minHolderLots || args['min-holder-lots'] || 1000);
  const volumeWindow = Number(args.volumeWindow || args['volume-window'] || 20);
  const volumeMultiplier = Number(args.volumeMultiplier || args['volume-multiplier'] || 1.2);
  const liquidityWindow = Number(args.liquidityWindow || args['liquidity-window'] || 20);
  const minAverageVolume = Number(args.minAverageVolume || args['min-average-volume'] || 1_000_000);
  const minAverageTurnover = Number(args.minAverageTurnover || args['min-average-turnover'] || 20_000_000);
  const maxPositionPctOfAvgVolume = Number(args.maxPositionPctOfAvgVolume || args['max-position-pct-of-avg-volume'] || 0.02);
  const forwardDays = normalizeForwardDays(args.forwardDays || args['forward-days'] || [3, 5, 10]);
  const limit = args.limit ? Number(args.limit) : undefined;

  const priceResult = await getTaiwanPrice({
    ticker,
    provider: args.provider || 'finmind',
    startDate: args.startDate,
    endDate: args.endDate,
    limit,
  });
  const candles = normalizeCandleRows(taiwanRows(priceResult));
  const { series } = detectHmaSignals(candles, { period });
  const hmaCurrent = evaluateHmaTrendSignal(candles, { period });
  const volume = summarizeVolume(series, { volumeWindow, volumeMultiplier });
  const liquidity = summarizeLiquidity(series, { liquidityWindow, minAverageVolume, minAverageTurnover, maxPositionPctOfAvgVolume });

  let institutionalRows = [];
  let institutionalError;
  try {
    const institutionalResult = await getTaiwanInstitutional({
      ticker,
      provider: args.institutionalProvider || 'finmind',
      startDate: args.startDate,
      endDate: args.endDate,
      limit: args.institutionalLimit ? Number(args.institutionalLimit) : undefined,
    });
    institutionalRows = taiwanRows(institutionalResult);
  } catch (error) {
    institutionalError = error?.message || String(error);
  }

  let holdingRows = [];
  let holdingError;
  try {
    const holdingResult = await getTaiwanHoldingShares({
      ticker,
      startDate: args.startDate,
      endDate: args.endDate,
      limit: args.holdingLimit ? Number(args.holdingLimit) : undefined,
    });
    holdingRows = taiwanRows(holdingResult);
  } catch (error) {
    holdingError = error?.message || String(error);
  }

  let companyRows = [];
  try {
    companyRows = taiwanRows(await getTaiwanCompany({ ticker, provider: 'finmind' }));
  } catch {
    companyRows = [];
  }

  const foreign = summarizeForeignBuying(institutionalRows, { foreignDays, error: institutionalError });
  const holders = summarizeThousandLotHolders(holdingRows, { holderWeeks, minHolderLots, error: holdingError });
  const events = buildChipEvents(series, institutionalRows, holdingRows, { foreignDays, holderWeeks, minHolderLots, forwardDays });
  const forwardPerformance = summarizeChipEventPerformance(events, forwardDays);
  const chipGate = {
    passed: foreign.confirmed && holders.confirmed,
    required: {
      foreignConsecutiveBuyDays: foreignDays,
      holderIncreaseWeeks: holderWeeks,
      minHolderLots,
    },
    reason: foreign.confirmed && holders.confirmed
      ? 'Foreign buying streak and thousand-lot holder concentration both pass.'
      : 'Chip criteria are not fully confirmed; use as watchlist evidence, not an entry trigger.',
  };
  const industry = summarizeIndustry(companyRows);
  const advice = buildChipAdvice({ chipGate, hmaCurrent, volume, liquidity, forwardPerformance });

  return {
    ticker,
    market: 'tw',
    params: {
      period,
      startDate: args.startDate,
      endDate: args.endDate,
      provider: args.provider || 'finmind',
      foreignDays,
      holderWeeks,
      minHolderLots,
      volumeWindow,
      volumeMultiplier,
      liquidityWindow,
      minAverageVolume,
      minAverageTurnover,
      maxPositionPctOfAvgVolume,
      forwardDays,
      limit,
    },
    chipGate,
    foreign,
    holders,
    priceVolume: {
      hmaTrend: hmaCurrent.trend,
      hmaSuggestion: hmaCurrent.suggestion,
      latestClose: hmaCurrent.latest?.close ?? null,
      latestHma: hmaCurrent.latest?.hma ?? null,
      volume,
      liquidity,
    },
    industry,
    events: events.slice(-20),
    forwardPerformance,
    advice,
    recentCandles: series.slice(-10).map(({ date, close, volume: candleVolume, hma }) => ({ date, close, volume: candleVolume, hma })),
    disclaimer: 'Chip study is a screening and point-in-time backtest aid, not personalized investment advice. Confirm industry rank, news, and risk controls before trading.',
  };
}

function normalizeForwardDays(value) {
  const raw = Array.isArray(value) ? value : String(value).split(',');
  const days = raw.map((entry) => Number.parseInt(String(entry).trim(), 10)).filter((entry) => Number.isFinite(entry) && entry > 0);
  return [...new Set(days)].sort((a, b) => a - b);
}

function summarizeForwardPerformance(series, buySignals, days) {
  const byDay = {};
  for (const day of days) {
    const returns = [];
    for (const signal of buySignals) {
      const future = series[signal.index + day];
      if (!future) continue;
      returns.push((future.close - signal.close) / signal.close);
    }
    byDay[String(day)] = summarizeReturns(returns);
  }
  return { days, byDay };
}

function summarizeReturns(returns) {
  if (!returns.length) return { sampleSize: 0, averageReturnPct: null, winRatePct: null, bestReturnPct: null, worstReturnPct: null };
  const wins = returns.filter((value) => value > 0).length;
  return {
    sampleSize: returns.length,
    averageReturnPct: roundPct(returns.reduce((sum, value) => sum + value, 0) / returns.length),
    winRatePct: roundPct(wins / returns.length),
    bestReturnPct: roundPct(Math.max(...returns)),
    worstReturnPct: roundPct(Math.min(...returns)),
  };
}

function summarizeFalseBreakouts(series, buySignals, options) {
  const events = [];
  for (const signal of buySignals) {
    const window = series.slice(signal.index + 1, signal.index + 1 + options.falseBreakoutDays);
    if (!window.length) continue;
    const minReturn = Math.min(...window.map((row) => (row.close - signal.close) / signal.close));
    const closedBelowHma = window.some((row) => row.hma !== null && row.close < row.hma);
    if (closedBelowHma || minReturn <= -options.falseBreakoutThreshold) {
      events.push({
        date: signal.date,
        close: signal.close,
        minReturnPct: roundPct(minReturn),
        closedBelowHma,
      });
    }
  }
  return {
    count: events.length,
    checkedSignals: buySignals.filter((signal) => series[signal.index + 1]).length,
    ratePct: buySignals.length ? roundPct(events.length / buySignals.length) : null,
    days: options.falseBreakoutDays,
    thresholdPct: roundPct(options.falseBreakoutThreshold),
    events: events.slice(-10),
  };
}

function summarizeVolume(series, options) {
  const rows = series.filter((row) => Number.isFinite(row.volume));
  const latest = rows.at(-1);
  if (!latest) return { status: 'unavailable', confirmed: false, reason: 'No volume data available.' };
  const previous = rows.slice(Math.max(0, rows.length - 1 - options.volumeWindow), -1);
  if (!previous.length) return { status: 'insufficient_data', confirmed: false, latestVolume: latest.volume, reason: 'Not enough prior volume rows.' };
  const average = previous.reduce((sum, row) => sum + row.volume, 0) / previous.length;
  const ratio = average ? latest.volume / average : null;
  const confirmed = ratio !== null && ratio >= options.volumeMultiplier;
  return {
    status: confirmed ? 'confirmed' : 'not_confirmed',
    confirmed,
    latestDate: latest.date,
    latestVolume: latest.volume,
    averageVolume: roundNumber(average),
    ratio: roundNumber(ratio),
    threshold: options.volumeMultiplier,
    reason: confirmed ? 'Latest volume is above the confirmation threshold.' : 'Latest volume is not meaningfully above recent average.',
  };
}

function summarizeLiquidity(series, options = {}) {
  const window = Number(options.liquidityWindow || 20);
  const minAverageVolume = Number(options.minAverageVolume ?? 1_000_000);
  const minAverageTurnover = Number(options.minAverageTurnover ?? 20_000_000);
  const maxPositionPctOfAvgVolume = Number(options.maxPositionPctOfAvgVolume ?? 0.02);
  const rows = series.filter((row) => Number.isFinite(row.volume) && Number.isFinite(row.close));
  const recent = rows.slice(-window);
  if (!recent.length) {
    return {
      status: 'unavailable',
      eligible: false,
      reason: 'No usable volume/price rows for liquidity check.',
      window,
      minAverageVolume,
      minAverageTurnover,
    };
  }
  const averageVolume = recent.reduce((sum, row) => sum + row.volume, 0) / recent.length;
  const averageTurnover = recent.reduce((sum, row) => sum + row.volume * row.close, 0) / recent.length;
  const volumeRatio = minAverageVolume > 0 ? averageVolume / minAverageVolume : Infinity;
  const turnoverRatio = minAverageTurnover > 0 ? averageTurnover / minAverageTurnover : Infinity;
  const eligible = volumeRatio >= 1 && turnoverRatio >= 1;
  const suggestedMaxShares = Math.max(0, Math.floor(averageVolume * maxPositionPctOfAvgVolume));
  const suggestedMaxLots = Math.floor(suggestedMaxShares / 1000);
  const ratioScore = Math.min(volumeRatio, turnoverRatio);
  const score = Math.max(0, Math.min(100, Math.round(ratioScore * 100)));
  return {
    status: eligible ? 'liquid' : 'thin',
    eligible,
    window: recent.length,
    averageVolume: roundNumber(averageVolume),
    averageVolumeLots: roundNumber(averageVolume / 1000),
    averageTurnover: roundNumber(averageTurnover),
    minAverageVolume,
    minAverageTurnover,
    volumeRatio: roundNumber(volumeRatio),
    turnoverRatio: roundNumber(turnoverRatio),
    score,
    maxPositionPctOfAvgVolume,
    suggestedMaxShares,
    suggestedMaxLots,
    reason: eligible
      ? 'Average volume and turnover pass the liquidity gate.'
      : 'Average volume or turnover is below the liquidity gate; avoid or reduce order size to prevent slippage.',
  };
}

function summarizeInstitutional(rows, options) {
  if (options.error) return { status: 'unavailable', confirmed: false, reason: options.error, rows: [] };
  const normalized = rows.map(normalizeInstitutionalRow).filter((row) => row.net !== null);
  if (!normalized.length) return { status: 'unavailable', confirmed: false, reason: 'No usable institutional buy/sell rows.', rows: [] };
  const latestDates = [...new Set(normalized.map((row) => row.date).filter(Boolean))].sort().slice(-options.institutionalDays);
  const recent = normalized.filter((row) => latestDates.includes(row.date));
  const netByGroup = {};
  for (const row of recent) netByGroup[row.group] = (netByGroup[row.group] || 0) + row.net;
  const totalNet = recent.reduce((sum, row) => sum + row.net, 0);
  const confirmed = totalNet > 0;
  return {
    status: confirmed ? 'net_buy' : totalNet < 0 ? 'net_sell' : 'flat',
    confirmed,
    days: latestDates.length,
    totalNet: roundNumber(totalNet),
    netByGroup: Object.fromEntries(Object.entries(netByGroup).map(([key, value]) => [key, roundNumber(value)])),
    reason: confirmed ? 'Recent institutional flow is net buying.' : totalNet < 0 ? 'Recent institutional flow is net selling.' : 'Recent institutional flow is roughly flat.',
    rows: recent.slice(-20),
  };
}

function summarizeForeignBuying(rows, options) {
  if (options.error) return { status: 'unavailable', confirmed: false, reason: options.error, rows: [] };
  const foreignRows = rows
    .map(normalizeInstitutionalRow)
    .filter((row) => row.net !== null && isForeignInvestorGroup(row.group));
  if (!foreignRows.length) return { status: 'unavailable', confirmed: false, reason: 'No usable foreign investor buy/sell rows.', rows: [] };
  const byDate = sumRowsByDate(foreignRows);
  const recent = byDate.slice(-options.foreignDays);
  const confirmed = recent.length >= options.foreignDays && recent.every((row) => row.net > 0);
  const totalNet = recent.reduce((sum, row) => sum + row.net, 0);
  return {
    status: confirmed ? 'consecutive_buy' : totalNet > 0 ? 'net_buy_not_streak' : totalNet < 0 ? 'net_sell' : 'flat',
    confirmed,
    requiredDays: options.foreignDays,
    streakDays: countTrailingPositiveNetDays(byDate),
    totalNet: roundNumber(totalNet),
    latestDate: recent.at(-1)?.date || null,
    reason: confirmed
      ? `Foreign investors bought net for the latest ${options.foreignDays} trading days.`
      : `Foreign investor net buying did not meet the latest ${options.foreignDays}-day streak requirement.`,
    rows: recent,
  };
}

function isForeignInvestorGroup(group) {
  return /foreign|外資/i.test(String(group || ''));
}

function sumRowsByDate(rows) {
  const byDate = new Map();
  for (const row of rows) {
    if (!row.date) continue;
    const current = byDate.get(row.date) || { date: row.date, net: 0 };
    current.net += row.net;
    byDate.set(row.date, current);
  }
  return [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date))).map((row) => ({ ...row, net: roundNumber(row.net) }));
}

function countTrailingPositiveNetDays(rows) {
  let count = 0;
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    if (!(rows[index].net > 0)) break;
    count += 1;
  }
  return count;
}

function summarizeThousandLotHolders(rows, options) {
  if (options.error) return { status: 'unavailable', confirmed: false, reason: options.error, recent: [] };
  const byDate = aggregateHolderRows(rows, options);
  if (!byDate.length) return { status: 'unavailable', confirmed: false, reason: 'No usable holder distribution rows for the configured lot threshold.', recent: [] };
  const recent = byDate.slice(-options.holderWeeks);
  const confirmed = recent.length >= options.holderWeeks && isStrictlyIncreasing(recent.map((row) => row.percent));
  const changePct = recent.length >= 2 ? roundNumber(recent.at(-1).percent - recent[0].percent) : null;
  return {
    status: confirmed ? 'increasing' : changePct > 0 ? 'higher_not_streak' : changePct < 0 ? 'decreasing' : 'flat',
    confirmed,
    requiredWeeks: options.holderWeeks,
    minHolderLots: options.minHolderLots,
    latestDate: recent.at(-1)?.date || null,
    changePct,
    reason: confirmed
      ? `${options.minHolderLots}+ lot holder percentage increased for the latest ${options.holderWeeks} observations.`
      : `${options.minHolderLots}+ lot holder percentage did not meet the latest ${options.holderWeeks}-observation increase requirement.`,
    recent,
  };
}

function aggregateHolderRows(rows, options) {
  const byDate = new Map();
  for (const row of rows) {
    const date = row.date ?? row.Date ?? row.日期;
    const level = row.HoldingSharesLevel ?? row.holdingSharesLevel ?? row.level ?? row.持股分級;
    if (!date || lowerBoundLots(level) < options.minHolderLots) continue;
    const current = byDate.get(date) || { date, percent: 0, people: 0, unit: 0 };
    current.percent += numberFromKeys(row, ['percent', 'Percent', '比例']) ?? 0;
    current.people += numberFromKeys(row, ['people', 'People', '人數']) ?? 0;
    current.unit += numberFromKeys(row, ['unit', 'Unit', '股數']) ?? 0;
    byDate.set(date, current);
  }
  return [...byDate.values()]
    .sort((a, b) => String(a.date).localeCompare(String(b.date)))
    .map((row) => ({ ...row, percent: roundNumber(row.percent), people: roundNumber(row.people), unit: roundNumber(row.unit) }));
}

function lowerBoundLots(level) {
  const normalized = String(level || '').replace(/,/g, '');
  const match = normalized.match(/\d+/);
  return match ? Number(match[0]) : 0;
}

function isStrictlyIncreasing(values) {
  if (values.length < 2) return false;
  for (let index = 1; index < values.length; index += 1) {
    if (!(values[index] > values[index - 1])) return false;
  }
  return true;
}

function buildChipEvents(series, institutionalRows, holdingRows, options) {
  const events = [];
  for (let index = 0; index < series.length; index += 1) {
    const row = series[index];
    if (!row.date || row.hma === null || row.close === null) continue;
    const institutionalWindow = institutionalRows.filter((entry) => String(entry.date ?? entry.Date ?? entry.日期 ?? '') <= String(row.date));
    const holdingWindow = holdingRows.filter((entry) => String(entry.date ?? entry.Date ?? entry.日期 ?? '') <= String(row.date));
    const foreign = summarizeForeignBuying(institutionalWindow, { foreignDays: options.foreignDays });
    const holders = summarizeThousandLotHolders(holdingWindow, { holderWeeks: options.holderWeeks, minHolderLots: options.minHolderLots });
    if (!foreign.confirmed || !holders.confirmed) continue;
    events.push({
      date: row.date,
      close: row.close,
      hma: row.hma,
      foreignTotalNet: foreign.totalNet,
      holderPercent: holders.recent.at(-1)?.percent ?? null,
      holderChangePct: holders.changePct,
      forwardOutcome: summarizeDecisionForwardOutcome(series, index, options.forwardDays),
    });
  }
  return events;
}

function summarizeChipEventPerformance(events, days) {
  const byDay = {};
  for (const day of days) {
    const returns = events
      .map((event) => event.forwardOutcome?.byDay?.[String(day)]?.returnPct)
      .filter((value) => Number.isFinite(value))
      .map((value) => value / 100);
    byDay[String(day)] = summarizeReturns(returns);
  }
  return { days, eventCount: events.length, byDay };
}

function summarizeIndustry(rows) {
  const row = rows[0] || {};
  return {
    name: row.industry_category ?? row.IndustryCategory ?? row.產業別 ?? row.type ?? null,
    stockName: row.stock_name ?? row.Name ?? row.公司名稱 ?? null,
    note: 'Industry rank is exposed as context for downstream peer comparison; chip-study does not infer peer leadership without a peer universe.',
  };
}

function buildChipAdvice({ chipGate, hmaCurrent, volume, liquidity, forwardPerformance }) {
  if (liquidity.eligible === false) {
    return { action: '避開 / 降低部位', reason: '籌碼條件即使成立，流動性未通過會放大滑價與隔日風險。' };
  }
  if (!chipGate.passed) {
    return { action: '觀察名單 / 不進場', reason: '外資連買與千張大戶集中尚未同時成立，先不要把它當買點。' };
  }
  if (['bearish', 'bearish_reversal'].includes(hmaCurrent.trend)) {
    return { action: '等站回趨勢 / 不追高', reason: '籌碼面通過，但價格仍在偏空趨勢，等待量價修復。' };
  }
  const forward3 = forwardPerformance.byDay?.['3'];
  if (['bullish', 'bullish_reversal', 'weak_bullish'].includes(hmaCurrent.trend) && volume.confirmed) {
    return { action: '可列入分批觀察', reason: `籌碼門檻通過且量價偏多；事件樣本 +3D 平均=${forward3?.averageReturnPct ?? '—'}%，仍需等回測或突破確認。` };
  }
  return { action: '等回測 / 小部位觀察', reason: '籌碼門檻通過，但量能或趨勢確認不完整，適合放入 watchlist 而非直接追價。' };
}

function normalizeInstitutionalRow(row) {
  const buy = numberFromKeys(row, ['buy', 'Buy', 'buy_volume', 'buyVolume', '買進股數', '買進金額']);
  const sell = numberFromKeys(row, ['sell', 'Sell', 'sell_volume', 'sellVolume', '賣出股數', '賣出金額']);
  const explicitNet = numberFromKeys(row, ['net', 'Net', 'buy_sell', 'BuySell', '買賣超股數', '買賣超']);
  return {
    date: row.date ?? row.Date ?? row.日期 ?? null,
    group: String(row.name ?? row.Name ?? row.institutional_investor ?? row.InvestorType ?? row.法人 ?? row.type ?? 'institutional'),
    buy,
    sell,
    net: explicitNet ?? (buy !== null && sell !== null ? buy - sell : null),
  };
}

function numberFromKeys(row, keys) {
  for (const key of keys) {
    if (row?.[key] === undefined || row?.[key] === '') continue;
    const value = Number(String(row[key]).replace(/,/g, ''));
    if (Number.isFinite(value)) return value;
  }
  return null;
}

function summarizeLatestSignal(signals, series, context) {
  const latest = signals.at(-1) || null;
  const confidence = scoreSignalConfidence(context);
  return {
    signal: latest,
    barsAgo: latest ? series.length - 1 - latest.index : null,
    confidence,
    supportingEvidence: {
      hmaTrend: context.hmaCurrent.trend,
      volumeConfirmed: context.volume.confirmed,
      liquidityEligible: context.liquidity?.eligible ?? null,
      institutionalConfirmed: context.institutional.confirmed,
      falseBreakoutRatePct: context.falseBreakouts.ratePct,
      forward3DayAveragePct: context.forwardPerformance.byDay?.['3']?.averageReturnPct ?? null,
    },
  };
}

function scoreSignalConfidence(context) {
  let score = 0;
  if (['bullish', 'bullish_reversal'].includes(context.hmaCurrent.trend)) score += 35;
  else if (['weak_bullish'].includes(context.hmaCurrent.trend)) score += 20;
  else if (['bearish', 'bearish_reversal'].includes(context.hmaCurrent.trend)) score -= 20;
  if (context.volume.confirmed) score += 25;
  if (context.liquidity?.eligible) score += 15;
  else if (context.liquidity && context.liquidity.eligible === false) score -= 30;
  if (context.institutional.confirmed) score += 25;
  const forward3 = context.forwardPerformance.byDay?.['3'];
  if (forward3?.averageReturnPct > 0) score += 10;
  if (context.falseBreakouts.ratePct !== null && context.falseBreakouts.ratePct <= 30) score += 5;
  score = Math.max(0, Math.min(100, score));
  const label = score >= 70 ? 'high' : score >= 45 ? 'medium' : 'low';
  return { score, label };
}

function buildSignalAdvice({ hmaCurrent, volume, liquidity, institutional, latestSignal }) {
  const confidence = latestSignal.confidence?.label;
  if (liquidity && liquidity.eligible === false) {
    return { action: '避開 / 降低部位', reason: '流動性未通過門檻，短線容易滑價或被隔日流動性反噬。' };
  }
  if (['bearish', 'bearish_reversal'].includes(hmaCurrent.trend)) {
    return { action: '避開 / 減碼', reason: 'HMA 趨勢偏空，先不要用 AI 題材追價。' };
  }
  if (['bullish', 'bullish_reversal'].includes(hmaCurrent.trend) && volume.confirmed && institutional.confirmed && confidence === 'high') {
    return { action: '可追但分批 / 續抱', reason: 'HMA、成交量與法人資料同向偏多；仍應設定跌破 HMA 或回撤停損。' };
  }
  if (['bullish', 'bullish_reversal', 'weak_bullish'].includes(hmaCurrent.trend)) {
    return { action: '等回測 HMA / 不追高', reason: 'HMA 偏多但確認條件未全部滿足，等量縮回測不破或法人續買。' };
  }
  return { action: '觀察 / 避開', reason: '訊號尚未一致，等待 HMA、量、法人其中至少兩項同向。' };
}

function buildPointInTimeDecision({ hmaCurrent, volume, liquidity, latestSignal }) {
  if (liquidity.eligible === false) {
    return {
      action: 'avoid_liquidity',
      confidence: 'low',
      reason: '流動性不足，先不把技術訊號當進場依據。',
      riskControls: ['不追價', '若必須交易，部位需低於建議最大張數', '避免市價單'],
    };
  }
  const trend = hmaCurrent.trend;
  const recentBuy = latestSignal?.type === 'buy';
  if (['bullish', 'bullish_reversal'].includes(trend) && volume.confirmed) {
    return {
      action: recentBuy ? 'buy_watch' : 'hold_or_scale',
      confidence: 'high',
      reason: 'HMA 偏多且量能確認，流動性通過門檻。',
      riskControls: ['分批', '跌破 HMA 或前低停損', `單筆不超過平均量 ${Math.round((liquidity.maxPositionPctOfAvgVolume || 0) * 10000) / 100}%`],
    };
  }
  if (['bullish', 'bullish_reversal', 'weak_bullish'].includes(trend)) {
    return {
      action: 'wait_pullback',
      confidence: 'medium',
      reason: 'HMA 偏多但量能尚未完全確認，等待回測不破或補量。',
      riskControls: ['只掛限價', '不追當日急拉', '回測失守 HMA 不進'],
    };
  }
  if (['bearish', 'bearish_reversal'].includes(trend)) {
    return {
      action: 'avoid_trend',
      confidence: 'low',
      reason: 'HMA 趨勢偏空，等待重新站回趨勢線。',
      riskControls: ['不攤平', '只觀察量縮止跌'],
    };
  }
  return {
    action: 'watch',
    confidence: 'low',
    reason: '訊號混合，等待 HMA、量能、流動性同向。',
    riskControls: ['保留現金', '等待確認'],
  };
}

function summarizeDecisionForwardOutcome(series, index, days) {
  const current = series[index];
  const outcome = {};
  for (const day of days) {
    const future = series[index + day];
    outcome[String(day)] = future ? {
      futureDate: future.date,
      returnPct: roundPct((future.close - current.close) / current.close),
    } : {
      futureDate: null,
      returnPct: null,
    };
  }
  const next = series[index + 1];
  return {
    nextDate: next?.date || null,
    nextOpenReturnPct: next && Number.isFinite(next.open) ? roundPct((next.open - current.close) / current.close) : null,
    byDay: outcome,
  };
}

function buildAdvisorPrompt({ ticker, date, hmaCurrent, volume, liquidity }) {
  return [
    `只可使用以下截至 ${date} 的 K 棒與特徵，替 ${ticker} 產生短線交易提案。`,
    '不得使用未來資料；若流動性未通過，必須建議避開或降低部位。',
    `HMA=${hmaCurrent.trend}; volumeConfirmed=${volume.confirmed}; liquidityEligible=${liquidity.eligible}; avgTurnover=${liquidity.averageTurnover ?? 'NA'}; suggestedMaxLots=${liquidity.suggestedMaxLots ?? 0}.`,
    '輸出 action、entryZone、stopLoss、takeProfit、confidence、reasons、risks。',
  ].join('\n');
}

function roundPct(value) {
  return Number.isFinite(value) ? Math.round(value * 10000) / 100 : null;
}

function roundNumber(value) {
  return Number.isFinite(value) ? Math.round(value * 10000) / 10000 : null;
}

function renderHmaSignalMarkdown(result) {
  const signal = result.signal || {};
  const latest = signal.latest || {};
  const stats = signal.stats || {};
  const lines = [
    `# HMA trend signal: ${result.ticker}`,
    '',
    `- Market/source: ${result.market || 'auto'} / ${result.dataSource?.tool || 'unknown'}`,
    `- Period: ${signal.period || result.params?.period || 20}`,
    `- Trend: ${signal.trend || 'unknown'}`,
    `- Action: ${signal.action || 'watch'}`,
    `- Suggestion: ${signal.suggestion || '觀察'}`,
    `- Reason: ${signal.reason || 'No reason available.'}`,
    `- Latest: ${latest.date || '—'} close=${latest.close ?? '—'} HMA=${latest.hma ?? '—'}`,
    `- HMA slope: ${stats.hmaSlope ?? '—'}; close-HMA: ${stats.closeMinusHma ?? '—'}`,
    '',
    signal.disclaimer || 'Technical signal only; not personalized investment advice.',
  ];
  const rows = signal.candles || [];
  if (rows.length) {
    lines.push('', '## Recent HMA values', toMarkdownTable(rows, [
      { label: 'Date', value: (r) => r.date },
      { label: 'Close', value: (r) => r.close },
      { label: 'HMA', value: (r) => r.hma },
      { label: 'Volume', value: (r) => compactNumber(r.volume) },
    ]));
  }
  return `${lines.join('\n')}\n`;
}

function renderSectorFlowMarkdown(result) {
  const title = result.mode === 'close' ? `# Sector close flow: ${result.date || ''}` : '# Sector realtime heat';
  const lines = [
    title.trim(),
    '',
    `- Source: ${result.source || 'unknown'}`,
    `- Note: ${result.note || '—'}`,
    '',
    toMarkdownTable((result.sectors || []).slice(0, 20), [
      { label: 'Industry', value: (r) => r.industry },
      { label: 'Stocks', value: (r) => r.stocks },
      { label: 'Turnover', value: (r) => compactNumber(r.turnover) },
      { label: 'Inst Net', value: (r) => compactNumber(r.institutionalNetValue) },
      { label: 'Foreign', value: (r) => compactNumber(r.foreignNetValue) },
      { label: 'Trust', value: (r) => compactNumber(r.investmentTrustNetValue) },
      { label: 'LimitUp', value: (r) => r.limitUpCount },
      { label: 'Adv/Dec', value: (r) => `${r.advancingCount}/${r.decliningCount}` },
      { label: 'Top', value: (r) => (r.topTickers || []).slice(0, 3).map((t) => `${t.code}${t.name ? ` ${t.name}` : ''}`).join(', ') },
    ]),
  ];
  if (result.errors?.length) lines.push('', `Errors: ${result.errors.length}`);
  return lines.join('\n');
}

function renderSignalStudyMarkdown(result) {
  const fp = result.forwardPerformance?.byDay || {};
  const lines = [
    `# Signal study: ${result.ticker}`,
    '',
    '## HMA 訊號',
    `- Current: ${result.hma?.current?.trend || 'unknown'} / ${result.hma?.current?.suggestion || '觀察'}`,
    `- Latest close/HMA: ${result.hma?.current?.latest?.close ?? '—'} / ${result.hma?.current?.latest?.hma ?? '—'}`,
    `- Buy signals: ${result.hma?.buySignalCount ?? 0}; Sell signals: ${result.hma?.sellSignalCount ?? 0}`,
    '',
    '## 成交量確認',
    `- Status: ${result.volume?.status || 'unknown'}; ratio=${result.volume?.ratio ?? '—'}x; confirmed=${result.volume?.confirmed ? 'yes' : 'no'}`,
    `- Reason: ${result.volume?.reason || '—'}`,
    '',
    '## 流動性確認',
    `- Status: ${result.liquidity?.status || 'unknown'}; eligible=${result.liquidity?.eligible ? 'yes' : 'no'}; avgTurnover=${compactNumber(result.liquidity?.averageTurnover)}; avgVolume=${compactNumber(result.liquidity?.averageVolume)}`,
    `- Suggested max: ${result.liquidity?.suggestedMaxLots ?? '—'} lots; reason=${result.liquidity?.reason || '—'}`,
    '',
    '## 法人確認',
    `- Status: ${result.institutional?.status || 'unknown'}; totalNet=${compactNumber(result.institutional?.totalNet)}; confirmed=${result.institutional?.confirmed ? 'yes' : 'no'}`,
    `- Reason: ${result.institutional?.reason || '—'}`,
    '',
    '## 買訊後 3/5/10 日表現',
  ];
  for (const day of result.forwardPerformance?.days || []) {
    const row = fp[String(day)] || {};
    lines.push(`- +${day}D: samples=${row.sampleSize || 0}, avg=${row.averageReturnPct ?? '—'}%, winRate=${row.winRatePct ?? '—'}%, worst=${row.worstReturnPct ?? '—'}%`);
  }
  lines.push(
    '',
    '## 假突破次數',
    `- ${result.falseBreakouts?.count ?? 0}/${result.falseBreakouts?.checkedSignals ?? 0}; rate=${result.falseBreakouts?.ratePct ?? '—'}%`,
    '',
    '## 最近一次訊號可信度',
    `- Confidence: ${result.latestSignal?.confidence?.label || 'unknown'} (${result.latestSignal?.confidence?.score ?? 0}/100)`,
    `- Latest signal: ${result.latestSignal?.signal ? `${result.latestSignal.signal.type} @ ${result.latestSignal.signal.date}` : '—'}`,
    '',
    '## 現在是否適合追 / 等回測 / 避開',
    `- Action: ${result.advice?.action || '觀察'}`,
    `- Reason: ${result.advice?.reason || '—'}`,
    '',
    result.disclaimer || 'Signal study is not personalized investment advice.',
  );
  if (result.recentCandles?.length) {
    lines.push('', '## Recent candles', toMarkdownTable(result.recentCandles, [
      { label: 'Date', value: (r) => r.date },
      { label: 'Close', value: (r) => r.close },
      { label: 'HMA', value: (r) => r.hma },
      { label: 'Volume', value: (r) => compactNumber(r.volume) },
    ]));
  }
  return `${lines.join('\n')}\n`;
}

function renderDailyDecisionStudyMarkdown(result) {
  const lines = [
    `# Daily decision study: ${result.ticker}`,
    '',
    `Point-in-time Codex frames: ${result.decisions?.length || 0}`,
    `Params: HMA=${result.params?.period || 20}, lookbackBars=${result.params?.lookbackBars || 60}, liquidityWindow=${result.params?.liquidityWindow || 20}`,
    '',
    '## Recent decisions',
  ];
  if (result.decisions?.length) {
    lines.push(toMarkdownTable(result.decisions.slice(-10), [
      { label: 'Date', value: (r) => r.date },
      { label: 'Action', value: (r) => r.decision?.action },
      { label: 'Conf', value: (r) => r.decision?.confidence },
      { label: 'HMA', value: (r) => r.hma?.trend },
      { label: 'Vol', value: (r) => (r.volume?.confirmed ? 'yes' : 'no') },
      { label: 'Liq', value: (r) => (r.liquidity?.eligible ? 'yes' : 'no') },
      { label: 'AvgTurnover', value: (r) => compactNumber(r.liquidity?.averageTurnover) },
      { label: 'MaxLots', value: (r) => r.liquidity?.suggestedMaxLots ?? '—' },
      { label: '+3D', value: (r) => `${r.forwardOutcome?.byDay?.['3']?.returnPct ?? '—'}%` },
    ]));
  } else {
    lines.push('No point-in-time decisions could be built from the provided data.');
  }
  lines.push('', result.disclaimer || 'Point-in-time study only; not personalized investment advice.');
  return `${lines.join('\n')}\n`;
}

function renderChipStudyMarkdown(result) {
  const fp = result.forwardPerformance?.byDay || {};
  const lines = [
    `# Chip study: ${result.ticker}`,
    '',
    '## 籌碼門檻',
    `- Gate: ${result.chipGate?.passed ? 'pass' : 'watch'}; reason=${result.chipGate?.reason || '—'}`,
    `- 外資連買: ${result.foreign?.status || 'unknown'}; streak=${result.foreign?.streakDays ?? 0}/${result.foreign?.requiredDays ?? result.params?.foreignDays}; totalNet=${compactNumber(result.foreign?.totalNet)}`,
    `- 1000 張以上持股: ${result.holders?.status || 'unknown'}; latest=${result.holders?.latestDate || '—'}; change=${result.holders?.changePct ?? '—'} pct-pt`,
    '',
    '## 量價與流動性',
    `- HMA: ${result.priceVolume?.hmaTrend || 'unknown'} / ${result.priceVolume?.hmaSuggestion || '觀察'}`,
    `- Volume: ${result.priceVolume?.volume?.status || 'unknown'}; ratio=${result.priceVolume?.volume?.ratio ?? '—'}x`,
    `- Liquidity: ${result.priceVolume?.liquidity?.status || 'unknown'}; maxLots=${result.priceVolume?.liquidity?.suggestedMaxLots ?? '—'}`,
    '',
    '## 產業位階入口',
    `- Industry: ${result.industry?.name || '—'}; stockName=${result.industry?.stockName || '—'}`,
    `- Note: ${result.industry?.note || '—'}`,
    '',
    '## 事件後 3/5/10 日表現',
    `- Events: ${result.forwardPerformance?.eventCount ?? 0}`,
  ];
  for (const day of result.forwardPerformance?.days || []) {
    const row = fp[String(day)] || {};
    lines.push(`- +${day}D: samples=${row.sampleSize || 0}, avg=${row.averageReturnPct ?? '—'}%, winRate=${row.winRatePct ?? '—'}%, worst=${row.worstReturnPct ?? '—'}%`);
  }
  lines.push(
    '',
    '## 現在是否適合列入研究',
    `- Action: ${result.advice?.action || '觀察'}`,
    `- Reason: ${result.advice?.reason || '—'}`,
    '',
    result.disclaimer || 'Chip study is not personalized investment advice.',
  );
  if (result.holders?.recent?.length) {
    lines.push('', '## Recent 1000+ holder observations', toMarkdownTable(result.holders.recent, [
      { label: 'Date', value: (r) => r.date },
      { label: 'Percent', value: (r) => r.percent },
      { label: 'People', value: (r) => compactNumber(r.people) },
      { label: 'Unit', value: (r) => compactNumber(r.unit) },
    ]));
  }
  if (result.events?.length) {
    lines.push('', '## Recent chip events', toMarkdownTable(result.events.slice(-10), [
      { label: 'Date', value: (r) => r.date },
      { label: 'Close', value: (r) => r.close },
      { label: 'HMA', value: (r) => r.hma },
      { label: 'ForeignNet', value: (r) => compactNumber(r.foreignTotalNet) },
      { label: 'Holder%', value: (r) => r.holderPercent ?? '—' },
      { label: '+3D', value: (r) => `${r.forwardOutcome?.byDay?.['3']?.returnPct ?? '—'}%` },
    ]));
  }
  return `${lines.join('\n')}\n`;
}

function renderResearchPackMarkdown(pack) {
  const sections = [
    `# Research pack: ${pack.ticker || 'market'} (${pack.market || 'auto'})`,
    '',
    `Coverage: ${(pack.coverage || []).join(', ')}`,
    '',
    `Token policy: ${pack.tokenPolicy?.note || 'compact evidence bundle.'}`,
  ];
  for (const [toolName, result] of Object.entries(pack.results || {})) {
    sections.push('', `## ${toolName}`);
    if (tools[toolName]?.toMarkdown) sections.push(tools[toolName].toMarkdown(result));
    else sections.push('```json', compactJson(shapeForTokenBudget(result, { maxRows: 5 })), '```');
  }
  const errors = Object.entries(pack.errors || {});
  if (errors.length) {
    sections.push('', '## Fetch errors');
    for (const [toolName, message] of errors) sections.push(`- ${toolName}: ${message}`);
  }
  return sections.join('\n');
}
