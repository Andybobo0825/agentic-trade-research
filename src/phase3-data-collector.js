import {
  getTaiwanInstitutional,
  getTaiwanPrice,
  taiwanProviderEnvelope,
} from './taiwan-market.js';
import { normalizeEvidenceRecord, writeEvidenceRecord } from './point-in-time-store.js';

function dateOnly(row) {
  const value = row.date ?? row.Date ?? row.日期;
  return value ? String(value).slice(0, 10) : null;
}

function tickerOf(row, fallback) {
  return String(row.stock_id ?? row.ticker ?? row.code ?? row.Code ?? fallback ?? '');
}

function explicitPublication(row) {
  return row.published_at
    ?? row.publishedAt
    ?? row.publish_time
    ?? row.publishTime
    ?? row.發布時間
    ?? null;
}

function evidenceRows(rows, options, normalizer) {
  return (Array.isArray(rows) ? rows : []).flatMap((row) => {
    const input = normalizer(row, options);
    return input ? [normalizeEvidenceRecord(input)] : [];
  });
}

export function normalizeDailyMarketEvidence(rows = [], options = {}) {
  return evidenceRows(rows, options, (row) => {
    const date = dateOnly(row);
    if (!date) return null;
    const availableAt = `${date}T13:30:00+08:00`;
    return {
      ticker: tickerOf(row, options.ticker),
      source: options.source || 'finmind_market',
      sourceUrl: options.sourceUrl,
      eventTime: availableAt,
      publishedAt: availableAt,
      availableAt,
      fetchedAt: options.fetchedAt,
      dataQuality: 'accepted',
      payload: row,
    };
  });
}

export function normalizeInstitutionalEvidence(rows = [], options = {}) {
  return evidenceRows(rows, options, (row) => {
    const date = dateOnly(row);
    if (!date) return null;
    const publication = explicitPublication(row);
    const availableAt = publication || `${date}T18:00:00+08:00`;
    return {
      ticker: tickerOf(row, options.ticker),
      source: options.source || 'finmind_institutional',
      sourceUrl: options.sourceUrl,
      eventTime: `${date}T13:30:00+08:00`,
      publishedAt: availableAt,
      availableAt,
      fetchedAt: options.fetchedAt,
      dataQuality: publication ? 'accepted' : 'inferred_schedule',
      payload: row,
    };
  });
}

export async function collectPhase3PointInTimeData(args = {}, dependencies = {}) {
  const tickers = [...new Set((args.tickers || []).map(String).filter(Boolean))].sort();
  if (!tickers.length) throw new TypeError('tickers are required');
  if (!args.evidenceRoot) throw new TypeError('evidenceRoot is required');
  const fetchedAt = args.fetchedAt || new Date().toISOString();
  const adapters = [
    {
      key: 'market',
      get: dependencies.getPrice || getTaiwanPrice,
      normalize: normalizeDailyMarketEvidence,
      source: 'finmind_market',
    },
    {
      key: 'institutional',
      get: dependencies.getInstitutional || getTaiwanInstitutional,
      normalize: normalizeInstitutionalEvidence,
      source: 'finmind_institutional',
    },
  ];
  const acceptedBySource = Object.fromEntries(adapters.map(({ key }) => [key, new Set()]));
  const excluded = [];
  let recordsWritten = 0;

  for (const ticker of tickers) {
    for (const adapter of adapters) {
      let result;
      try {
        result = await adapter.get({
          ticker,
          startDate: args.startDate,
          endDate: args.endDate,
        });
      } catch (error) {
        excluded.push({
          ticker,
          source: adapter.key,
          reason: 'provider_error',
          message: error?.message || String(error),
        });
        continue;
      }
      const envelope = taiwanProviderEnvelope(result, fetchedAt);
      const rows = envelope.rows;
      let records;
      try {
        records = adapter.normalize(rows, {
          ticker,
          source: envelope.source === 'unknown'
            ? adapter.source
            : `${envelope.source}:${adapter.key}`,
          sourceUrl: envelope.sourceUrl,
          fetchedAt: envelope.fetchedAt,
        });
      } catch (error) {
        excluded.push({
          ticker,
          source: adapter.key,
          reason: 'normalization_error',
          message: error?.message || String(error),
        });
        continue;
      }
      if (adapter.requiresExplicitTimestamp && records.length < rows.length) {
        for (let index = records.length; index < rows.length; index += 1) {
          excluded.push({ ticker, source: adapter.key, reason: 'missing_timestamp' });
        }
      }
      if (records.length) acceptedBySource[adapter.key].add(ticker);
      for (const record of records) {
        const write = await writeEvidenceRecord(args.evidenceRoot, record);
        if (write.created) recordsWritten += 1;
      }
    }
  }

  return {
    schemaVersion: 1,
    executionMode: 'read_only',
    recordsWritten,
    excluded,
    coverage: Object.fromEntries(adapters.map(({ key }) => [
      key,
      acceptedBySource[key].size / tickers.length,
    ])),
    orderApiSafe: true,
  };
}
