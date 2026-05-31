import { getFinancialDatasetsConfig } from './config.js';

const ENDPOINTS = {
  income: '/financials/income-statements/',
  balance: '/financials/balance-sheets/',
  cashflow: '/financials/cash-flow-statements/',
  financials: '/financials/',
  metrics: '/financial-metrics/snapshot/',
  ratios: '/financial-metrics/',
  price: '/prices/snapshot/',
  prices: '/prices/',
  news: '/news',
  filings: '/filings/',
  filingItems: '/filings/items/',
};

export function listEndpoints() {
  return { ...ENDPOINTS };
}

export async function financialDatasetsGet(endpointKey, params = {}, options = {}) {
  const endpoint = ENDPOINTS[endpointKey] || endpointKey;
  if (!endpoint.startsWith('/')) throw new Error(`Unknown endpoint: ${endpointKey}`);
  const cfg = options.config || getFinancialDatasetsConfig(options.env);
  const url = new URL(endpoint, cfg.baseUrl);
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, String(v)));
    else url.searchParams.append(key, String(value));
  }
  const res = await fetch(url, { headers: { 'x-api-key': cfg.apiKey, accept: 'application/json' } });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Financial Datasets request failed (${res.status} ${res.statusText}) for ${url.pathname}: ${text.slice(0, 500)}`);
  }
  const data = text ? JSON.parse(text) : {};
  return { endpoint, url: url.toString(), data };
}

export async function getStatement({ ticker, statement = 'income', period = 'annual', limit = 5 }) {
  const key = statement === 'cash-flow' ? 'cashflow' : statement;
  return financialDatasetsGet(key, { ticker, period, limit });
}

export async function getMetrics({ ticker }) {
  return financialDatasetsGet('metrics', { ticker });
}

export async function getPrice({ ticker }) {
  return financialDatasetsGet('price', { ticker });
}

export async function getNews({ ticker, limit = 10 }) {
  return financialDatasetsGet('news', { ticker, limit });
}

export async function getFilings({ ticker, filingType, limit = 5 }) {
  return financialDatasetsGet('filings', { ticker, filing_type: filingType, limit });
}
