import { getStatement, getMetrics, getPrice, getNews, getFilings, listEndpoints } from './financial-datasets.js';
import {
  getTaiwanAnnouncements,
  getTaiwanCompany,
  getTaiwanFinancials,
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
import { compactJson, compactNumber, shapeForTokenBudget, toMarkdownTable } from './format.js';

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
  'research-pack': {
    description: 'Fetch a complete investment-research bundle in one call while preserving source coverage; use format=markdown or compact-json to minimize Codex tokens.',
    async run(args) {
      return buildResearchPack(args || {});
    },
    toMarkdown(result) {
      return renderResearchPackMarkdown(result);
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
