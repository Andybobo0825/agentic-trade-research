import { getTaiwanCompany, getTaiwanInstitutional, getTaiwanPrice } from './taiwan-market.js';
import { getShioajiSnapshots } from './shioaji-market.js';

function rows(payload) {
  return Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : [];
}

function n(value) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(String(value).replace(/,/g, ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function r(value) {
  return Number.isFinite(value) ? Math.round(value * 10000) / 10000 : 0;
}

function codeOf(row) {
  return String(row.stock_id ?? row.Code ?? row.公司代號 ?? row.SecuritiesCompanyCode ?? row.code ?? '').trim();
}

function nameOf(row) {
  return row.stock_name ?? row.Name ?? row.CompanyName ?? row.公司簡稱 ?? row.公司名稱 ?? '';
}

function industryOf(row) {
  return String(row.industry_category ?? row.IndustryCategory ?? row.產業別 ?? row.industry ?? '未分類').trim() || '未分類';
}

function parseTickers(value) {
  if (Array.isArray(value)) return value.map(String).map((s) => s.trim()).filter(Boolean);
  return String(value || '').split(',').map((s) => s.trim()).filter(Boolean);
}

function companyMap(companyRows) {
  const map = new Map();
  for (const row of companyRows) {
    const code = codeOf(row);
    if (!code) continue;
    map.set(code, { code, name: nameOf(row), industry: industryOf(row) });
  }
  return map;
}

function ensureSector(map, industry) {
  if (!map.has(industry)) {
    map.set(industry, {
      industry,
      stocks: 0,
      turnover: 0,
      volume: 0,
      advancingCount: 0,
      decliningCount: 0,
      limitUpCount: 0,
      limitDownCount: 0,
      institutionalNetValue: 0,
      foreignNetValue: 0,
      investmentTrustNetValue: 0,
      dealerNetValue: 0,
      topTickers: [],
    });
  }
  return map.get(industry);
}

function cleanSector(row) {
  const topTickers = row.topTickers.sort((a, b) => b.turnover - a.turnover).slice(0, 5);
  return {
    ...row,
    turnover: r(row.turnover),
    volume: r(row.volume),
    institutionalNetValue: r(row.institutionalNetValue),
    foreignNetValue: r(row.foreignNetValue),
    investmentTrustNetValue: r(row.investmentTrustNetValue),
    dealerNetValue: r(row.dealerNetValue),
    topTickers,
  };
}

function rankSectors(map, rankBy = 'turnover') {
  return [...map.values()].map(cleanSector).sort((a, b) => Math.abs(b[rankBy] ?? 0) - Math.abs(a[rankBy] ?? 0));
}

function isForeign(group) {
  return /foreign|外資/i.test(String(group || ''));
}

function isTrust(group) {
  return /trust|投信/i.test(String(group || ''));
}

function isDealer(group) {
  return /dealer|自營/i.test(String(group || ''));
}

function groupOf(row) {
  return row.name ?? row.Name ?? row.institutional_investor ?? row.InvestorType ?? row.法人 ?? row.type ?? '';
}

function netShares(row) {
  const explicit = n(row.net ?? row.Net ?? row.buy_sell ?? row.BuySell ?? row.買賣超股數 ?? row.買賣超);
  if (explicit !== null) return explicit;
  const buy = n(row.buy ?? row.Buy ?? row.buy_volume ?? row.buyVolume ?? row.買進股數 ?? row.買進金額);
  const sell = n(row.sell ?? row.Sell ?? row.sell_volume ?? row.sellVolume ?? row.賣出股數 ?? row.賣出金額);
  return buy !== null && sell !== null ? buy - sell : 0;
}

function closePrice(row) {
  return n(row.close ?? row.Close ?? row.ClosingPrice ?? row.收盤價) ?? 0;
}

function volumeOf(row) {
  return n(row.Trading_Volume ?? row.trading_volume ?? row.TradeVolume ?? row.TradingShares ?? row.volume) ?? 0;
}

export async function buildSectorFlow(args = {}) {
  const mode = String(args.mode || 'realtime').toLowerCase();
  if (mode === 'close') return buildCloseFlow(args);
  if (mode === 'realtime') return buildRealtimeHeat(args);
  throw new Error('sector-flow mode must be realtime or close');
}

async function loadCompanyMap(args) {
  const company = await getTaiwanCompany({ ticker: undefined, provider: args.companyProvider || 'finmind' });
  return companyMap(rows(company));
}

async function buildRealtimeHeat(args) {
  const exchange = String(args.exchange || 'TSE').toUpperCase();
  const limit = args.limit ? Number(args.limit) : 1000;
  const companies = await loadCompanyMap(args);
  const tickers = parseTickers(args.tickers).length ? parseTickers(args.tickers) : [...companies.keys()].slice(0, limit);
  const chunkSize = Math.max(1, Number(args.chunkSize || 100));
  const sectorMap = new Map();
  const errors = [];

  for (let i = 0; i < tickers.length; i += chunkSize) {
    const slice = tickers.slice(i, i + chunkSize);
    try {
      const result = await getShioajiSnapshots({ tickers: slice, exchange, securityType: args.securityType || 'STK' });
      for (const quote of rows(result)) {
        const meta = companies.get(String(quote.code));
        const industry = meta?.industry || '未分類';
        const sector = ensureSector(sectorMap, industry);
        const price = n(quote.lastPrice) ?? 0;
        const volume = n(quote.totalVolume) ?? 0;
        const turnover = n(quote.totalAmount) ?? price * volume * 1000;
        const changeRate = n(quote.changeRate) ?? 0;
        sector.stocks += 1;
        sector.volume += volume;
        sector.turnover += turnover;
        if (changeRate > 0) sector.advancingCount += 1;
        if (changeRate < 0) sector.decliningCount += 1;
        if (quote.limitStatus?.isLimitUp) sector.limitUpCount += 1;
        if (quote.limitStatus?.isLimitDown) sector.limitDownCount += 1;
        sector.topTickers.push({ code: quote.code, name: meta?.name || '', lastPrice: price, changeRate, turnover: r(turnover), limit: quote.limitStatus?.isLimitUp ? '漲停' : quote.limitStatus?.isLimitDown ? '跌停' : '' });
      }
    } catch (error) {
      errors.push({ tickers: slice, message: error?.message || String(error) });
    }
  }

  return {
    mode: 'realtime',
    source: 'shioaji+finmind',
    readOnly: true,
    exchange,
    tickers: tickers.length,
    sectors: rankSectors(sectorMap, 'turnover'),
    errors,
    note: 'Realtime heat is a turnover/limit-up proxy from broker snapshots, not official money-flow attribution.',
  };
}

async function buildCloseFlow(args) {
  const date = args.date || args.startDate || new Date().toISOString().slice(0, 10);
  const companies = await loadCompanyMap(args);
  const errors = [];
  let priceSource = args.provider || 'finmind';
  let priceResult;
  try {
    priceResult = await getTaiwanPrice({ ticker: undefined, provider: priceSource, startDate: date, endDate: args.endDate || date });
  } catch (error) {
    errors.push({ source: priceSource, message: error?.message || String(error) });
    priceSource = 'twse';
    priceResult = await getTaiwanPrice({ ticker: undefined, provider: 'twse' });
  }
  const priceRows = rows(priceResult).filter((row) => {
    const rowDate = String(row.date ?? row.Date ?? '').slice(0, 10);
    if (priceSource !== 'finmind') return true;
    return !date || !rowDate || rowDate === String(date);
  });
  const closeByCode = new Map();
  const sectorMap = new Map();

  for (const row of priceRows) {
    const code = codeOf(row);
    if (!code) continue;
    const meta = companies.get(code);
    const sector = ensureSector(sectorMap, meta?.industry || '未分類');
    const close = closePrice(row);
    const volume = volumeOf(row);
    const turnover = close * volume;
    closeByCode.set(code, close);
    sector.stocks += 1;
    sector.volume += volume;
    sector.turnover += turnover;
    sector.topTickers.push({ code, name: meta?.name || nameOf(row), close, volume, turnover: r(turnover) });
  }

  let institutionalRows = [];
  let institutionalError;
  try {
    const institutional = await getTaiwanInstitutional({ ticker: undefined, provider: args.institutionalProvider || 'finmind', startDate: date, endDate: args.endDate || date });
    institutionalRows = rows(institutional).filter((row) => !date || String(row.date ?? row.Date ?? '').slice(0, 10) === String(date));
  } catch (error) {
    institutionalError = error?.message || String(error);
  }

  for (const row of institutionalRows) {
    const code = codeOf(row);
    const close = closeByCode.get(code);
    if (!code || !Number.isFinite(close)) continue;
    const meta = companies.get(code);
    const sector = ensureSector(sectorMap, meta?.industry || '未分類');
    const value = netShares(row) * close;
    const group = groupOf(row);
    sector.institutionalNetValue += value;
    if (isForeign(group)) sector.foreignNetValue += value;
    else if (isTrust(group)) sector.investmentTrustNetValue += value;
    else if (isDealer(group)) sector.dealerNetValue += value;
  }

  return {
    mode: 'close',
    source: priceSource === 'finmind' ? 'finmind' : 'twse-openapi+finmind-institutional-if-available',
    date,
    sectors: rankSectors(sectorMap, args.rankBy || 'turnover'),
    errors: institutionalError ? [...errors, { source: 'institutional', message: institutionalError }] : errors,
    note: 'Close flow aggregates turnover and institutional net buy value by industry; it is a proxy, not exchange-certified fund destination.',
  };
}
