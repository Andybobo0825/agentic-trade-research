import fs from 'node:fs/promises';
import path from 'node:path';
import { getShioajiDailyQuotes, getShioajiKbars } from './shioaji-market.js';

export const DEFAULT_SHIOAJI_CACHE_DIR = '.omx/cache/shioaji';

function normalizeTickerList(tickers) {
  if (Array.isArray(tickers)) return tickers.map(String).map((s) => s.trim()).filter(Boolean);
  return String(tickers || '').split(',').map((s) => s.trim()).filter(Boolean);
}

function safePart(value) {
  return String(value || '').replace(/[^0-9A-Za-z_.-]/g, '_');
}

export function shioajiKbarCachePath({ cacheDir = DEFAULT_SHIOAJI_CACHE_DIR, ticker, start, end }) {
  return path.join(cacheDir, 'kbars', `${safePart(ticker)}_${safePart(start)}_${safePart(end)}.json`);
}

export function shioajiDailyQuoteCachePath({ cacheDir = DEFAULT_SHIOAJI_CACHE_DIR, date }) {
  return path.join(cacheDir, 'daily-quotes', `${safePart(date)}.json`);
}

async function exists(file) {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

export async function cacheShioajiKbars(args = {}, options = {}) {
  const tickers = normalizeTickerList(args.tickers || args.ticker);
  if (!tickers.length) throw new Error('cacheShioajiKbars requires tickers');
  const start = args.start || args.startDate;
  const end = args.end || args.endDate;
  if (!start || !end) throw new Error('cacheShioajiKbars requires start and end');

  const cacheDir = args.cacheDir || DEFAULT_SHIOAJI_CACHE_DIR;
  await fs.mkdir(path.join(cacheDir, 'kbars'), { recursive: true });

  const ok = [];
  const cached = [];
  const failed = [];
  for (const ticker of tickers) {
    const file = shioajiKbarCachePath({ cacheDir, ticker, start, end });
    if (!args.refresh && await exists(file)) {
      cached.push({ code: ticker, path: file });
      continue;
    }
    try {
      const result = await getShioajiKbars({
        ticker,
        exchange: args.exchange || 'TSE',
        securityType: args.securityType || 'STK',
        start,
        end,
      }, options);
      const payload = {
        source: 'shioaji',
        code: result.data.code,
        exchange: result.data.exchange,
        start,
        end,
        fetchedAt: new Date().toISOString(),
        rows: result.data.rows,
      };
      await fs.writeFile(file, `${JSON.stringify(payload, null, 2)}\n`);
      ok.push({ code: ticker, path: file, rows: payload.rows.length });
    } catch (error) {
      failed.push({ code: ticker, error: String(error?.message || error) });
    }
  }

  return {
    source: 'shioaji',
    cacheDir,
    start,
    end,
    ok,
    cached,
    failed,
  };
}

function normalizeDates(args = {}) {
  if (Array.isArray(args.dates)) return args.dates.map(String).filter(Boolean);
  if (args.dates) return String(args.dates).split(',').map((s) => s.trim()).filter(Boolean);
  const start = args.start || args.startDate;
  const end = args.end || args.endDate;
  if (!start || !end) throw new Error('dates or start/end are required');
  const dates = [];
  const cursor = new Date(`${start}T00:00:00Z`);
  const stop = new Date(`${end}T00:00:00Z`);
  while (cursor <= stop) {
    dates.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return dates;
}

export async function cacheShioajiDailyQuotes(args = {}, options = {}) {
  const dates = normalizeDates(args);
  const cacheDir = args.cacheDir || DEFAULT_SHIOAJI_CACHE_DIR;
  await fs.mkdir(path.join(cacheDir, 'daily-quotes'), { recursive: true });

  const ok = [];
  const cached = [];
  const failed = [];
  for (const date of dates) {
    const file = shioajiDailyQuoteCachePath({ cacheDir, date });
    if (!args.refresh && await exists(file)) {
      cached.push({ date, path: file });
      continue;
    }
    try {
      const result = await getShioajiDailyQuotes({ date, exclude: args.exclude }, options);
      const payload = {
        source: 'shioaji',
        date,
        fetchedAt: new Date().toISOString(),
        rows: result.data.rows,
      };
      await fs.writeFile(file, `${JSON.stringify(payload, null, 2)}\n`);
      ok.push({ date, path: file, rows: payload.rows.length });
    } catch (error) {
      failed.push({ date, error: String(error?.message || error) });
    }
  }

  return {
    source: 'shioaji',
    cacheDir,
    ok,
    cached,
    failed,
  };
}
