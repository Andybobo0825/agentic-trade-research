import { ConfigError } from './errors.js';

export const FINMIND_BASE_URL = 'https://api.finmindtrade.com';
export const TWSE_OPENAPI_BASE_URL = 'https://openapi.twse.com.tw/v1';
export const TPEX_OPENAPI_BASE_URL = 'https://www.tpex.org.tw/openapi/v1';
export const FUGLE_MARKETDATA_BASE_URL = 'https://api.fugle.tw/marketdata/v1.0/stock';

const FINMIND_DATASETS = {
  price: 'TaiwanStockPrice',
  revenue: 'TaiwanStockMonthRevenue',
  financials: 'TaiwanStockFinancialStatements',
  balance: 'TaiwanStockBalanceSheet',
  cashflow: 'TaiwanStockCashFlowsStatement',
  institutional: 'TaiwanStockInstitutionalInvestorsBuySell',
  holdingShares: 'TaiwanStockHoldingSharesPer',
  valuation: 'TaiwanStockPER',
  dividend: 'TaiwanStockDividend',
  company: 'TaiwanStockInfo',
  news: 'TaiwanStockNews',
};

const TWSE_ENDPOINTS = {
  price: '/exchangeReport/STOCK_DAY_ALL',
  valuation: '/exchangeReport/BWIBBU_ALL',
  company: '/opendata/t187ap03_L',
  announcements: '/opendata/t187ap04_L',
  incomeGeneral: '/opendata/t187ap06_L_ci',
  balanceGeneral: '/opendata/t187ap07_L_ci',
};

const TPEX_ENDPOINTS = {
  price: '/tpex_mainboard_daily_close_quotes',
  valuation: '/tpex_mainboard_peratio_analysis',
  company: '/mopsfin_t187ap03_O',
  announcements: '/mopsfin_t187ap04_O',
  institutional: '/tpex_3insti_daily_trading',
  incomeGeneral: '/mopsfin_t187ap06_O_ci',
  balanceGeneral: '/mopsfin_t187ap07_O_ci',
};

const FUGLE_ENDPOINTS = {
  ticker: '/intraday/ticker/{symbol}',
  quote: '/intraday/quote/{symbol}',
  candles: '/intraday/candles/{symbol}',
  trades: '/intraday/trades/{symbol}',
  volumes: '/intraday/volumes/{symbol}',
  snapshotQuotes: '/snapshot/quotes/{market}',
  snapshotMovers: '/snapshot/movers/{market}',
  snapshotActives: '/snapshot/actives/{market}',
  historicalCandles: '/historical/candles/{symbol}',
  historicalStats: '/historical/stats/{symbol}',
  technicalSma: '/technical/sma/{symbol}',
  technicalRsi: '/technical/rsi/{symbol}',
  technicalKdj: '/technical/kdj/{symbol}',
  technicalMacd: '/technical/macd/{symbol}',
  technicalBb: '/technical/bb/{symbol}',
};

export function listTaiwanEndpoints() {
  return {
    finmind: { baseUrl: FINMIND_BASE_URL, datasets: { ...FINMIND_DATASETS } },
    twse: { baseUrl: TWSE_OPENAPI_BASE_URL, endpoints: { ...TWSE_ENDPOINTS } },
    tpex: { baseUrl: TPEX_OPENAPI_BASE_URL, endpoints: { ...TPEX_ENDPOINTS } },
    fugle: {
      baseUrl: FUGLE_MARKETDATA_BASE_URL,
      auth: 'X-API-KEY header from FUGLE_API_KEY',
      endpoints: { ...FUGLE_ENDPOINTS },
      note: 'Fugle provides realtime/intraday REST and WebSocket market data; this toolkit wires REST endpoints only.',
    },
    mops: {
      note: 'MOPS company announcements and statement snapshots are exposed through TWSE/TPEx OpenAPI endpoints in this toolkit.',
      twse: { announcements: TWSE_ENDPOINTS.announcements, incomeGeneral: TWSE_ENDPOINTS.incomeGeneral, balanceGeneral: TWSE_ENDPOINTS.balanceGeneral },
      tpex: { announcements: TPEX_ENDPOINTS.announcements, incomeGeneral: TPEX_ENDPOINTS.incomeGeneral, balanceGeneral: TPEX_ENDPOINTS.balanceGeneral },
    },
  };
}

export function getFugleConfig(env = process.env, options = {}) {
  const apiKey = options.apiKey ?? env.FUGLE_API_KEY;
  if (!apiKey) {
    throw new ConfigError('FUGLE_API_KEY is required for Fugle realtime market data. Create a Fugle Developer key and set FUGLE_API_KEY in .env or your shell.');
  }
  return {
    apiKey,
    baseUrl: options.baseUrl || env.FUGLE_MARKETDATA_BASE_URL || FUGLE_MARKETDATA_BASE_URL,
  };
}

export async function finmindData(dataset, params = {}, options = {}) {
  const url = new URL('/api/v4/data', options.baseUrl || process.env.FINMIND_BASE_URL || FINMIND_BASE_URL);
  url.searchParams.set('dataset', dataset);
  for (const [key, value] of Object.entries(params)) addParam(url, key, value);
  const token = options.token ?? process.env.FINMIND_API_TOKEN;
  if (token) url.searchParams.set('token', token);
  return fetchJson(url, { source: 'finmind', dataset });
}

export async function twseOpenApi(endpoint, options = {}) {
  return fetchOpenApi(options.baseUrl || process.env.TWSE_OPENAPI_BASE_URL || TWSE_OPENAPI_BASE_URL, endpoint, 'twse');
}

export async function tpexOpenApi(endpoint, options = {}) {
  return fetchOpenApi(options.baseUrl || process.env.TPEX_OPENAPI_BASE_URL || TPEX_OPENAPI_BASE_URL, endpoint, 'tpex');
}

export async function fugleMarketData(path, params = {}, options = {}) {
  const cfg = options.config || getFugleConfig(options.env, options);
  if (!path || !path.startsWith('/')) throw new Error('Fugle path must start with /');
  const url = new URL(`${String(cfg.baseUrl).replace(/\/$/, '')}${path}`);
  for (const [key, value] of Object.entries(params)) addParam(url, key, value);
  return fetchJson(url, { source: 'fugle', endpoint: path }, { 'X-API-KEY': cfg.apiKey });
}

export async function getFugleTicker({ ticker, type }) {
  return fugleMarketData(symbolPath(FUGLE_ENDPOINTS.ticker, ticker), compactParams({ type }));
}

export async function getFugleQuote({ ticker, type }) {
  return fugleMarketData(symbolPath(FUGLE_ENDPOINTS.quote, ticker), compactParams({ type }));
}

export async function getFugleCandles({ ticker, scope = 'intraday', type, timeframe, sort, from, to, adjusted, fields, limit }) {
  const endpoint = scope === 'historical' ? FUGLE_ENDPOINTS.historicalCandles : FUGLE_ENDPOINTS.candles;
  return limitNestedData(await fugleMarketData(symbolPath(endpoint, ticker), compactParams({ type, timeframe, sort, from, to, adjusted, fields })), limit);
}

export async function getFugleTrades({ ticker, type, limit }) {
  return limitNestedData(await fugleMarketData(symbolPath(FUGLE_ENDPOINTS.trades, ticker), compactParams({ type })), limit);
}

export async function getFugleVolumes({ ticker, type, limit }) {
  return limitNestedData(await fugleMarketData(symbolPath(FUGLE_ENDPOINTS.volumes, ticker), compactParams({ type })), limit);
}

export async function getFugleSnapshot({ market = 'TSE', kind = 'quotes', type, limit }) {
  const endpoint = kind === 'movers' ? FUGLE_ENDPOINTS.snapshotMovers : kind === 'actives' ? FUGLE_ENDPOINTS.snapshotActives : FUGLE_ENDPOINTS.snapshotQuotes;
  return limitNestedData(await fugleMarketData(endpoint.replace('{market}', encodeURIComponent(market)), compactParams({ type })), limit);
}

export async function getFugleHistoricalStats({ ticker }) {
  return fugleMarketData(symbolPath(FUGLE_ENDPOINTS.historicalStats, ticker));
}

export async function getFugleTechnical({ ticker, indicator = 'sma', timeframe, period, fastPeriod, slowPeriod, signalPeriod, from, to, sort, limit }) {
  const endpoints = {
    sma: FUGLE_ENDPOINTS.technicalSma,
    rsi: FUGLE_ENDPOINTS.technicalRsi,
    kdj: FUGLE_ENDPOINTS.technicalKdj,
    macd: FUGLE_ENDPOINTS.technicalMacd,
    bb: FUGLE_ENDPOINTS.technicalBb,
  };
  const endpoint = endpoints[indicator];
  if (!endpoint) throw new Error('Fugle technical indicator must be one of: sma, rsi, kdj, macd, bb');
  return limitNestedData(await fugleMarketData(symbolPath(endpoint, ticker), compactParams({ timeframe, period, fastPeriod, slowPeriod, signalPeriod, from, to, sort })), limit);
}

export async function getFugleRaw({ endpoint, ticker, market, type, timeframe, sort, from, to, adjusted, fields, limit }) {
  if (!endpoint) throw new Error('fugle-raw requires --endpoint');
  const path = endpoint.replace('{symbol}', encodeURIComponent(ticker || '')).replace('{market}', encodeURIComponent(market || ''));
  return limitNestedData(await fugleMarketData(path, compactParams({ type, timeframe, sort, from, to, adjusted, fields })), limit);
}

export async function getTaiwanPrice({ ticker, provider = 'auto', startDate, endDate, limit }) {
  if (provider === 'finmind' || provider === 'auto-history' || startDate || endDate) {
    const result = await finmindData(FINMIND_DATASETS.price, withDateRange({ data_id: ticker }, startDate, endDate));
    return limitRows(result, limit);
  }
  if (provider === 'twse') return filterRows(await twseOpenApi(TWSE_ENDPOINTS.price), ticker, ['Code']);
  if (provider === 'tpex') return filterRows(await tpexOpenApi(TPEX_ENDPOINTS.price), ticker, ['SecuritiesCompanyCode']);
  return firstNonEmpty([
    () => filterRows(twseOpenApi(TWSE_ENDPOINTS.price), ticker, ['Code']),
    () => filterRows(tpexOpenApi(TPEX_ENDPOINTS.price), ticker, ['SecuritiesCompanyCode']),
  ]);
}

export async function getTaiwanCompany({ ticker, provider = 'auto' }) {
  if (provider === 'finmind') return filterRows(await finmindData(FINMIND_DATASETS.company, {}), ticker, ['stock_id']);
  if (provider === 'twse') return filterRows(await twseOpenApi(TWSE_ENDPOINTS.company), ticker, ['公司代號', 'Code']);
  if (provider === 'tpex') return filterRows(await tpexOpenApi(TPEX_ENDPOINTS.company), ticker, ['SecuritiesCompanyCode', '公司代號']);
  return firstNonEmpty([
    () => filterRows(twseOpenApi(TWSE_ENDPOINTS.company), ticker, ['公司代號', 'Code']),
    () => filterRows(tpexOpenApi(TPEX_ENDPOINTS.company), ticker, ['SecuritiesCompanyCode', '公司代號']),
    () => filterRows(finmindData(FINMIND_DATASETS.company, {}), ticker, ['stock_id']),
  ]);
}

export async function getTaiwanRevenue({ ticker, startDate, endDate, limit }) {
  return limitRows(await finmindData(FINMIND_DATASETS.revenue, withDateRange({ data_id: ticker }, startDate, endDate)), limit);
}

export async function getTaiwanFinancials({ ticker, statement = 'income', provider = 'finmind', startDate, endDate, limit }) {
  if (provider === 'twse') return getOfficialStatement('twse', statement, ticker);
  if (provider === 'tpex') return getOfficialStatement('tpex', statement, ticker);
  const dataset = statement === 'balance' ? FINMIND_DATASETS.balance : statement === 'cashflow' ? FINMIND_DATASETS.cashflow : FINMIND_DATASETS.financials;
  return limitRows(await finmindData(dataset, withDateRange({ data_id: ticker }, startDate, endDate)), limit);
}

export async function getTaiwanInstitutional({ ticker, provider = 'finmind', startDate, endDate, limit }) {
  if (provider === 'tpex') return filterRows(await tpexOpenApi(TPEX_ENDPOINTS.institutional), ticker, ['SecuritiesCompanyCode', 'Code']);
  return limitRows(await finmindData(FINMIND_DATASETS.institutional, withDateRange({ data_id: ticker }, startDate, endDate)), limit);
}

export async function getTaiwanHoldingShares({ ticker, startDate, endDate, limit }) {
  return limitRows(await finmindData(FINMIND_DATASETS.holdingShares, withDateRange({ data_id: ticker }, startDate, endDate)), limit);
}

export async function getTaiwanValuation({ ticker, provider = 'auto', startDate, endDate, limit }) {
  if (provider === 'finmind') return limitRows(await finmindData(FINMIND_DATASETS.valuation, withDateRange({ data_id: ticker }, startDate, endDate)), limit);
  if (provider === 'twse') return filterRows(await twseOpenApi(TWSE_ENDPOINTS.valuation), ticker, ['Code']);
  if (provider === 'tpex') return filterRows(await tpexOpenApi(TPEX_ENDPOINTS.valuation), ticker, ['SecuritiesCompanyCode']);
  return firstNonEmpty([
    () => filterRows(twseOpenApi(TWSE_ENDPOINTS.valuation), ticker, ['Code']),
    () => filterRows(tpexOpenApi(TPEX_ENDPOINTS.valuation), ticker, ['SecuritiesCompanyCode']),
    () => limitRows(finmindData(FINMIND_DATASETS.valuation, withDateRange({ data_id: ticker }, startDate, endDate)), limit),
  ]);
}

export async function getTaiwanAnnouncements({ ticker, provider = 'auto', limit }) {
  if (provider === 'twse') return limitRows(filterRows(await twseOpenApi(TWSE_ENDPOINTS.announcements), ticker, ['公司代號', 'Code']), limit);
  if (provider === 'tpex') return limitRows(filterRows(await tpexOpenApi(TPEX_ENDPOINTS.announcements), ticker, ['SecuritiesCompanyCode', '公司代號']), limit);
  return firstNonEmpty([
    () => limitRows(filterRows(twseOpenApi(TWSE_ENDPOINTS.announcements), ticker, ['公司代號', 'Code']), limit),
    () => limitRows(filterRows(tpexOpenApi(TPEX_ENDPOINTS.announcements), ticker, ['SecuritiesCompanyCode', '公司代號']), limit),
  ]);
}

export async function getTaiwanNews({ ticker, startDate, endDate, limit }) {
  // FinMind restricts TaiwanStockNews to one day per request and rejects
  // end_date. Prefer the requested window's latest point-in-time day.
  const newsDate = endDate || startDate;
  return limitRows(await finmindData(FINMIND_DATASETS.news, withDateRange({ data_id: ticker }, newsDate)), limit);
}

export async function getTaiwanRaw({ provider, endpoint, dataset, ticker, startDate, endDate, limit }) {
  if (provider === 'finmind') {
    if (!dataset) throw new Error('tw-raw --provider finmind requires --dataset');
    return limitRows(await finmindData(dataset, withDateRange({ data_id: ticker }, startDate, endDate)), limit);
  }
  if (provider === 'twse') return limitRows(ticker ? filterRows(await twseOpenApi(endpoint), ticker, ['Code', '公司代號']) : await twseOpenApi(endpoint), limit);
  if (provider === 'tpex') return limitRows(ticker ? filterRows(await tpexOpenApi(endpoint), ticker, ['SecuritiesCompanyCode', 'Code', '公司代號']) : await tpexOpenApi(endpoint), limit);
  throw new Error('tw-raw --provider must be finmind, twse, or tpex');
}

async function getOfficialStatement(provider, statement, ticker) {
  if (statement === 'cashflow') throw new Error('Official TWSE/TPEx OpenAPI cash-flow snapshot is not wired; use provider=finmind for cash flow.');
  const endpoints = provider === 'twse' ? TWSE_ENDPOINTS : TPEX_ENDPOINTS;
  const rows = await (provider === 'twse' ? twseOpenApi : tpexOpenApi)(statement === 'balance' ? endpoints.balanceGeneral : endpoints.incomeGeneral);
  return filterRows(rows, ticker, ['公司代號', 'Code', 'SecuritiesCompanyCode']);
}

async function fetchOpenApi(baseUrl, endpoint, source) {
  if (!endpoint || !endpoint.startsWith('/')) throw new Error(`${source} endpoint must start with /`);
  const url = `${String(baseUrl).replace(/\/$/, '')}${endpoint}`;
  return fetchJson(new URL(url), { source, endpoint });
}

async function fetchJson(url, meta, headers = {}) {
  let res;
  try {
    res = await fetch(url, { headers: { accept: 'application/json', ...headers } });
  } catch (error) {
    throw new Error(`${meta.source} request failed before response for ${safeUrlForError(url)}: ${error?.message || error}`);
  }
  const text = await res.text();
  if (!res.ok) throw new Error(`${meta.source} request failed (${res.status} ${res.statusText}) for ${url.pathname}: ${text.slice(0, 500)}`);
  const payload = text ? JSON.parse(text) : null;
  return { ...meta, url: url.toString(), data: payload?.data ?? payload };
}

function safeUrlForError(url) {
  const value = url instanceof URL ? url : new URL(String(url));
  return `${value.origin}${value.pathname}`;
}

function symbolPath(template, ticker) {
  if (!ticker) throw new Error('Fugle symbol/ticker is required');
  return template.replace('{symbol}', encodeURIComponent(String(ticker).trim()));
}

function compactParams(params) {
  return Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== ''));
}

function addParam(url, key, value) {
  if (value === undefined || value === null || value === '') return;
  url.searchParams.set(key, String(value));
}

function withDateRange(params, startDate, endDate) {
  const next = { ...params };
  addPlainParam(next, 'start_date', startDate);
  addPlainParam(next, 'end_date', endDate);
  return next;
}

function addPlainParam(obj, key, value) {
  if (value !== undefined && value !== null && value !== '') obj[key] = value;
}

async function firstNonEmpty(loaders) {
  let last = null;
  for (const load of loaders) {
    const result = await load();
    last = result;
    if (rowsOf(result).length > 0) return result;
  }
  return last || { data: [] };
}

async function filterRows(payloadOrPromise, ticker, keys) {
  const payload = await payloadOrPromise;
  if (!ticker) return payload;
  const wanted = String(ticker).trim();
  return { ...payload, data: rowsOf(payload).filter((row) => keys.some((key) => String(row?.[key] ?? '').trim() === wanted)) };
}

async function limitRows(payloadOrPromise, limit) {
  const payload = await payloadOrPromise;
  if (!limit) return payload;
  return { ...payload, data: rowsOf(payload).slice(0, limit) };
}

async function limitNestedData(payloadOrPromise, limit) {
  const payload = await payloadOrPromise;
  if (!limit || !Array.isArray(payload?.data?.data)) return payload;
  return { ...payload, data: { ...payload.data, data: payload.data.data.slice(0, limit) } };
}

function rowsOf(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.data)) return payload.data;
  return [];
}

export function taiwanProviderEnvelope(result, fetchedAt) {
  return {
    rows: rowsOf(result),
    source: result?.source || 'unknown',
    sourceUrl: result?.url,
    fetchedAt,
  };
}
