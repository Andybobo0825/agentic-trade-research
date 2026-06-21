import { ConfigError } from './errors.js';

export const SHIOAJI_SERVER_BASE_URL = 'http://localhost:8080';

export function getShioajiConfig(env = process.env, options = {}) {
  return {
    baseUrl: String(options.baseUrl || env.SHIOAJI_SERVER_BASE_URL || SHIOAJI_SERVER_BASE_URL).replace(/\/$/, ''),
  };
}

function normalizeCode(value) {
  const code = String(value || '').trim();
  if (!code) throw new Error('ticker is required');
  return code;
}

function contractPayload({ ticker, exchange = 'TSE', securityType = 'STK' }) {
  return {
    security_type: String(securityType || 'STK').toUpperCase(),
    exchange: String(exchange || 'TSE').toUpperCase(),
    code: normalizeCode(ticker),
  };
}

function toNumber(value) {
  if (value === null || value === undefined || value === '') return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : value;
}

function normalizeChangeType(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/^ChangeType\./, '').trim();
}

export function normalizeShioajiSnapshot(row = {}) {
  const changeType = normalizeChangeType(row.change_type ?? row.changeType ?? row.chg_type);
  const chgType = Number(row.chg_type);
  const isLimitUp = changeType === 'LimitUp' || chgType === 1;
  const isLimitDown = changeType === 'LimitDown' || chgType === 5;
  const bid = toNumber(row.buy_price ?? row.bid_price ?? row.buyPrice);
  const ask = toNumber(row.sell_price ?? row.ask_price ?? row.sellPrice);
  return {
    datetime: row.datetime ?? row.ts ?? row.date,
    code: String(row.code ?? ''),
    exchange: String(row.exchange ?? ''),
    open: toNumber(row.open),
    high: toNumber(row.high),
    low: toNumber(row.low),
    lastPrice: toNumber(row.close ?? row.lastPrice),
    averagePrice: toNumber(row.average_price ?? row.avg_price ?? row.averagePrice),
    bidPrice: bid,
    bidVolume: toNumber(row.buy_volume ?? row.bid_volume ?? row.bidVolume),
    askPrice: ask,
    askVolume: toNumber(row.sell_volume ?? row.ask_volume ?? row.askVolume),
    volume: toNumber(row.volume),
    totalVolume: toNumber(row.total_volume ?? row.totalVolume),
    amount: toNumber(row.amount),
    totalAmount: toNumber(row.total_amount ?? row.totalAmount),
    changePrice: toNumber(row.change_price ?? row.price_chg ?? row.changePrice),
    changeRate: toNumber(row.change_rate ?? row.pct_chg ?? row.changeRate),
    changeType,
    limitStatus: {
      isLimitUp,
      isLimitDown,
      changeType,
    },
    orderLocked: Boolean((isLimitUp && Number(bid) === 0 && Number(ask) === 0) || (isLimitDown && Number(bid) === 0 && Number(ask) === 0)),
  };
}

function firstDataRow(payload) {
  const data = payload?.data ?? payload;
  if (Array.isArray(data)) return data[0] || {};
  if (Array.isArray(data?.data)) return data.data[0] || {};
  return data || {};
}

async function getJson(path, options = {}) {
  const cfg = getShioajiConfig(options.env, options);
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const res = await fetchImpl(`${cfg.baseUrl}${path}`);
  const text = await res.text();
  if (!res.ok) throw new Error(`shioaji request failed (${res.status}) for ${path}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : {};
}

async function fetchJson(path, payload, options = {}) {
  const cfg = getShioajiConfig(options.env, options);
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const res = await fetchImpl(`${cfg.baseUrl}${path}`, {
    method: 'POST',
    headers: { accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify(payload),
    signal: options.timeoutMs ? AbortSignal.timeout(options.timeoutMs) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`shioaji request failed (${res.status}) for ${path}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : {};
}

export async function getShioajiSnapshot(args = {}, options = {}) {
  const contract = contractPayload(args);
  const raw = await fetchJson('/api/v1/data/snapshots', { contracts: [contract] }, options);
  return {
    source: 'shioaji',
    mode: 'server-http',
    endpoint: '/api/v1/data/snapshots',
    readOnly: true,
    data: normalizeShioajiSnapshot(firstDataRow(raw)),
  };
}

function chunkArray(values, size) {
  const chunkSize = Math.max(1, Math.min(500, Number(size) || 500));
  const chunks = [];
  for (let i = 0; i < values.length; i += chunkSize) chunks.push(values.slice(i, i + chunkSize));
  return chunks;
}

export async function getShioajiSnapshots(args = {}, options = {}) {
  const tickers = Array.isArray(args.tickers)
    ? args.tickers
    : String(args.tickers || args.ticker || '').split(',');
  const contracts = tickers.map((ticker) => String(ticker).trim()).filter(Boolean).map((ticker) => contractPayload({ ...args, ticker }));
  if (!contracts.length) throw new Error('shioaji snapshots requires at least one ticker');
  const rows = [];
  for (const chunk of chunkArray(contracts, args.chunkSize)) {
    const raw = await fetchJson('/api/v1/data/snapshots', { contracts: chunk }, options);
    const data = raw?.data ?? raw;
    rows.push(...(Array.isArray(data) ? data : Array.isArray(data?.data) ? data.data : []));
  }
  return {
    source: 'shioaji',
    mode: 'server-http',
    endpoint: '/api/v1/data/snapshots',
    readOnly: true,
    data: rows.map(normalizeShioajiSnapshot),
  };
}

export function normalizeShioajiContract(row = {}) {
  return {
    securityType: String(row.security_type ?? row.securityType ?? ''),
    exchange: String(row.exchange ?? ''),
    code: String(row.code ?? ''),
    symbol: String(row.symbol ?? ''),
    name: String(row.name ?? ''),
    unit: toNumber(row.unit),
    updateDate: row.update_date ?? row.updateDate,
    raw: row,
  };
}

export async function getShioajiContract(args = {}, options = {}) {
  const securityType = String(args.securityType || 'STK').toUpperCase();
  const code = encodeURIComponent(normalizeCode(args.ticker || args.code));
  const raw = await getJson(`/api/v1/data/contracts/${code}?security_type=${encodeURIComponent(securityType)}`, options);
  return {
    source: 'shioaji',
    mode: 'server-http',
    endpoint: '/api/v1/data/contracts/{code}',
    readOnly: true,
    data: normalizeShioajiContract(raw?.data ?? raw),
  };
}

export async function getShioajiContracts(args = {}, options = {}) {
  const payload = {
    security_type: String(args.securityType || 'STK').toUpperCase(),
  };
  if (args.page !== undefined) payload.page = Number(args.page);
  if (args.pageSize !== undefined || args.page_size !== undefined) payload.page_size = Number(args.pageSize ?? args.page_size);
  const raw = await fetchJson('/api/v1/data/contracts', payload, options);
  return {
    source: 'shioaji',
    mode: 'server-http',
    endpoint: '/api/v1/data/contracts',
    readOnly: true,
    securityType: raw.security_type ?? payload.security_type,
    page: raw.page,
    pageSize: raw.page_size,
    maxPage: raw.max_page,
    total: raw.total,
    data: (raw.contracts || []).map(normalizeShioajiContract),
  };
}

export function normalizeShioajiDailyQuotes(payload = {}) {
  const data = payload?.data ?? payload;
  const dates = firstArray(data, ['Date', 'date']);
  const codes = firstArray(data, ['Code', 'code']);
  const opens = firstArray(data, ['Open', 'open']);
  const highs = firstArray(data, ['High', 'high']);
  const lows = firstArray(data, ['Low', 'low']);
  const closes = firstArray(data, ['Close', 'close']);
  const volumes = firstArray(data, ['Volume', 'volume']);
  const amounts = firstArray(data, ['Amount', 'amount']);
  const transactions = firstArray(data, ['Transaction', 'transaction']);
  return codes.map((code, index) => ({
    date: dates[index],
    code: String(code),
    open: toNumber(opens[index]),
    high: toNumber(highs[index]),
    low: toNumber(lows[index]),
    close: toNumber(closes[index]),
    volume: toNumber(volumes[index]),
    amount: toNumber(amounts[index]),
    transaction: toNumber(transactions[index]),
  }));
}

export async function getShioajiDailyQuotes(args = {}, options = {}) {
  if (!args.date) throw new Error('getShioajiDailyQuotes requires date');
  const payload = { date: String(args.date) };
  if (args.exclude !== undefined) payload.exclude = Boolean(args.exclude);
  const raw = await fetchJson('/api/v1/data/daily_quotes', payload, options);
  return {
    source: 'shioaji',
    mode: 'server-http',
    endpoint: '/api/v1/data/daily_quotes',
    readOnly: true,
    data: {
      date: payload.date,
      rows: normalizeShioajiDailyQuotes(raw),
    },
  };
}

export function parseSseJsonEvents(text) {
  const events = [];
  for (const block of String(text || '').split(/\r?\n\r?\n/)) {
    let event = '';
    const data = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice('event:'.length).trim();
      if (line.startsWith('data:')) data.push(line.slice('data:'.length).trim());
    }
    if (!data.length) continue;
    try {
      events.push({ event, data: JSON.parse(data.join('\n')) });
    } catch {
      // Ignore partial/non-JSON stream chunks.
    }
  }
  return events;
}

async function readSseEvent(path, { eventName, code, timeoutMs = 3000 } = {}, options = {}) {
  const cfg = getShioajiConfig(options.env, options);
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const res = await fetchImpl(`${cfg.baseUrl}${path}`, {
    headers: { accept: 'text/event-stream' },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`shioaji stream failed (${res.status}) for ${path}`);

  let buffer = '';
  const check = () => {
    for (const entry of parseSseJsonEvents(buffer)) {
      if (eventName && entry.event !== eventName) continue;
      if (code && String(entry.data?.code) !== String(code)) continue;
      return entry.data;
    }
    return null;
  };

  if (res.body) {
    for await (const chunk of res.body) {
      buffer += Buffer.from(chunk).toString('utf8');
      const found = check();
      if (found) return found;
    }
  } else {
    buffer = await res.text();
  }
  const found = check();
  if (found) return found;
  throw new Error(`Timed out waiting for Shioaji ${eventName || 'stream'} event for ${code || '(any code)'}`);
}

function levelRows(prices = [], volumes = [], diffs = []) {
  return prices.map((price, index) => ({
    price: toNumber(price),
    volume: toNumber(volumes[index]),
    diffVolume: toNumber(diffs[index] ?? 0),
  }));
}

function normalizeOrderBook(row = {}) {
  return {
    code: String(row.code ?? ''),
    date: row.date,
    time: row.time,
    bids: levelRows(row.bid_price || row.bidPrice || [], row.bid_volume || row.bidVolume || [], row.diff_bid_vol || row.diffBidVolume || []),
    asks: levelRows(row.ask_price || row.askPrice || [], row.ask_volume || row.askVolume || [], row.diff_ask_vol || row.diffAskVolume || []),
    suspend: Boolean(row.suspend),
    simtrade: Boolean(row.simtrade),
    intradayOdd: Boolean(row.intraday_odd ?? row.intradayOdd),
  };
}

export async function getShioajiOrderBook(args = {}, options = {}) {
  const contract = contractPayload(args);
  const payload = { ...contract, quote_type: 'BidAsk', intraday_odd: Boolean(args.intradayOdd) };
  await fetchJson('/api/v1/stream/subscribe', payload, options);
  try {
    const row = await readSseEvent('/api/v1/stream/data/bidask_stk', {
      eventName: 'bidask_stk',
      code: contract.code,
      timeoutMs: Number(args.timeoutMs || options.timeoutMs || 3000),
    }, options);
    return {
      source: 'shioaji',
      mode: 'server-sse',
      endpoint: '/api/v1/stream/data/bidask_stk',
      readOnly: true,
      data: normalizeOrderBook(row),
    };
  } finally {
    await fetchJson('/api/v1/stream/unsubscribe', payload, options).catch(() => undefined);
  }
}

function zipTicks(payload = {}) {
  const datetimes = payload.datetime || payload.ts || [];
  return datetimes.map((datetime, index) => ({
    datetime,
    close: toNumber(payload.close?.[index]),
    volume: toNumber(payload.volume?.[index]),
    bidPrice: toNumber(payload.bid_price?.[index]),
    bidVolume: toNumber(payload.bid_volume?.[index]),
    askPrice: toNumber(payload.ask_price?.[index]),
    askVolume: toNumber(payload.ask_volume?.[index]),
    tickType: toNumber(payload.tick_type?.[index]),
  }));
}

function firstArray(payload = {}, names = []) {
  for (const name of names) {
    if (Array.isArray(payload[name])) return payload[name];
  }
  return [];
}

export function normalizeShioajiKbars(payload = {}) {
  const data = payload?.data ?? payload;
  const datetimes = firstArray(data, ['datetime', 'ts', 'Time']);
  const opens = firstArray(data, ['Open', 'open']);
  const highs = firstArray(data, ['High', 'high']);
  const lows = firstArray(data, ['Low', 'low']);
  const closes = firstArray(data, ['Close', 'close']);
  const volumes = firstArray(data, ['Volume', 'volume']);
  const amounts = firstArray(data, ['Amount', 'amount']);
  return datetimes.map((datetime, index) => ({
    datetime,
    date: String(datetime).slice(0, 10),
    open: toNumber(opens[index]),
    high: toNumber(highs[index]),
    low: toNumber(lows[index]),
    close: toNumber(closes[index]),
    volume: toNumber(volumes[index]),
    amount: toNumber(amounts[index]),
  }));
}

export async function getShioajiKbars(args = {}, options = {}) {
  const contract = contractPayload(args);
  const payload = {
    contract,
    start: args.start || args.startDate,
    end: args.end || args.endDate,
  };
  const raw = await fetchJson('/api/v1/data/kbars', payload, options);
  return {
    source: 'shioaji',
    mode: 'server-http',
    endpoint: '/api/v1/data/kbars',
    readOnly: true,
    data: {
      code: contract.code,
      exchange: contract.exchange,
      start: payload.start,
      end: payload.end,
      rows: normalizeShioajiKbars(raw),
    },
  };
}

export async function getShioajiTicks(args = {}, options = {}) {
  const contract = contractPayload(args);
  const queryType = args.all ? 'AllDay' : (args.timeStart || args.timeEnd) ? 'RangeTime' : 'LastCount';
  const payload = {
    contract,
    date: args.date,
    query_type: queryType,
  };
  if (queryType === 'LastCount') payload.last_cnt = Number(args.last || args.limit || 10);
  if (args.timeStart) payload.time_start = args.timeStart;
  if (args.timeEnd) payload.time_end = args.timeEnd;
  const raw = await fetchJson('/api/v1/data/ticks', payload, options);
  return {
    source: 'shioaji',
    mode: 'server-http',
    endpoint: '/api/v1/data/ticks',
    readOnly: true,
    data: {
      code: contract.code,
      exchange: contract.exchange,
      date: args.date,
      queryType,
      ticks: zipTicks(raw?.data ?? raw),
    },
  };
}

export function assertShioajiReadOnly(result) {
  if (result?.readOnly !== true) throw new ConfigError('Shioaji market-data operation must be readOnly=true.');
  return result;
}
