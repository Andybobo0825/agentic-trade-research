import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { readEvidenceManifest } from './point-in-time-store.js';
import { calculateHullMovingAverage } from './indicators.js';

export const PHASE3_CANDIDATE_SCHEMA_VERSION = 5;
export const PHASE3_MARKET_CONTEXT_MINIMUM_COVERAGE_PCT = 80;

export const PHASE3_CANDIDATE_FEATURE_NAMES = Object.freeze([
  'hma9SlopePct',
  'hma9AccelerationPct',
  'hma20SlopePct',
  'closeToHma9Pct',
  'volumeRatio',
  'volumeThreeDayAcceleration',
  'averageTurnover',
  'averageTurnoverLog10',
  'momentum1Pct',
  'momentum3Pct',
  'momentum5Pct',
  'marketBreadth1d',
  'marketMedianMomentum3Pct',
  'relativeMomentum3Pct',
  'intradayRangePct',
  'closePosition',
  'foreignBuyStreak',
  'foreignThreeDayIntensity',
  'foreignTwentyDayPercentile',
]);

const REQUIRED_CANDIDATE_FEATURES = Object.freeze([
  'hma9SlopePct',
  'hma20SlopePct',
  'closeToHma9Pct',
  'averageTurnover',
  'momentum5Pct',
  'closePosition',
]);

export function finiteOrNull(value) {
  if (
    value === null
    || value === undefined
    || (typeof value === 'string' && value.trim() === '')
  ) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function finiteOr(value, fallback = 0) {
  const number = finiteOrNull(value);
  return number === null ? fallback : number;
}

function round(value, digits = 8) {
  if (!Number.isFinite(value)) return null;
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function sha256(value) {
  return createHash('sha256').update(stableJson(value)).digest('hex');
}

function marketDate(record) {
  return String(record?.payload?.date || record?.eventTime || '').slice(0, 10);
}

function isValidMarketDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return false;
  const [year, month, day] = String(value).split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function latestByDate(records) {
  const byDate = new Map();
  for (const record of records) {
    const date = marketDate(record);
    if (!isValidMarketDate(date)) {
      throw new TypeError('market record date must be exact valid YYYY-MM-DD');
    }
    const current = byDate.get(date);
    if (
      !current
      || String(record.availableAt).localeCompare(String(current.availableAt)) > 0
      || (
        record.availableAt === current.availableAt
        && String(record.sourceHash).localeCompare(String(current.sourceHash)) > 0
      )
    ) byDate.set(date, record);
  }
  return [...byDate.values()].sort((left, right) =>
    marketDate(left).localeCompare(marketDate(right)));
}

function aggregateForeignByDate(records) {
  const byDate = new Map();
  for (const record of records) {
    if (record?.payload?.name !== 'Foreign_Investor') continue;
    const date = marketDate(record);
    if (!isValidMarketDate(date)) {
      throw new TypeError('institutional record date must be exact valid YYYY-MM-DD');
    }
    const buy = finiteOrNull(record.payload.buy);
    const sell = finiteOrNull(record.payload.sell);
    const current = byDate.get(date) || {
      date,
      netBuy: 0,
      valid: true,
      availableAt: record.availableAt,
      sourceHashes: [],
    };
    if (buy === null || sell === null) current.valid = false;
    else current.netBuy += buy - sell;
    if (String(record.availableAt).localeCompare(String(current.availableAt)) > 0) {
      current.availableAt = record.availableAt;
    }
    if (record.sourceHash) current.sourceHashes.push(record.sourceHash);
    byDate.set(date, current);
  }
  for (const row of byDate.values()) {
    row.netBuy = row.valid ? row.netBuy : null;
    delete row.valid;
    row.sourceHashes.sort();
  }
  return byDate;
}

function pctChange(current, previous) {
  return Number.isFinite(current) && Number.isFinite(previous) && previous > 0
    ? ((current / previous) - 1) * 100
    : null;
}

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((left, right) => left - right);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

function latestAvailableAt(records) {
  const times = records.map((record) => record.availableAt)
    .filter((value) => Number.isFinite(Date.parse(value)))
    .sort();
  return times.at(-1) || null;
}

function marketObservation(ticker, market, closes, index) {
  const evidenceRecords = [market[index], market[index - 1], market[index - 3]].filter(Boolean);
  const availableAt = latestAvailableAt(evidenceRecords);
  const return1d = pctChange(closes[index], closes[index - 1]);
  const momentum3Pct = pctChange(closes[index], closes[index - 3]);
  if (!availableAt || !Number.isFinite(return1d) || !Number.isFinite(momentum3Pct)) return null;
  return {
    ticker,
    availableAt,
    sourceHashes: evidenceRecords.map((record) => record.sourceHash).filter(Boolean).sort(),
    return1d,
    momentum3Pct,
  };
}

function buildDailyMarketSnapshots(observationsByDate, universeStarts, minimumCoveragePct) {
  const snapshots = new Map();
  for (const [decisionDate, observations] of observationsByDate) {
    const dailyCutoff = Date.parse(`${decisionDate}T23:59:59.999+08:00`);
    const universeCount = universeStarts.filter((availableAt) =>
      Date.parse(availableAt) <= dailyCutoff).length;
    const availableRows = observations
      .filter((row) => Date.parse(row.availableAt) <= dailyCutoff)
      .sort((left, right) => left.ticker.localeCompare(right.ticker));
    const availableCount = availableRows.length;
    const coveragePct = universeCount > 0 ? availableCount / universeCount * 100 : 0;
    const cutoffTime = latestAvailableAt(availableRows);
    const available = availableCount > 0 && coveragePct >= minimumCoveragePct;
    const snapshotCore = {
      decisionDate,
      cutoffTime,
      universeCount,
      availableCount,
      coveragePct: round(coveragePct),
      observations: availableRows.map((row) => ({
        ticker: row.ticker,
        availableAt: row.availableAt,
        return1d: round(row.return1d),
        momentum3Pct: round(row.momentum3Pct),
        sourceHashes: row.sourceHashes,
      })),
    };
    snapshots.set(decisionDate, {
      context: {
        available,
        universeCount,
        availableCount,
        coveragePct: round(coveragePct),
        cutoffTime,
        snapshotHash: sha256(snapshotCore),
      },
      values: {
        breadth1d: available
          ? availableRows.filter((row) => row.return1d > 0).length / availableCount
          : null,
        medianMomentum3Pct: available
          ? median(availableRows.map((row) => row.momentum3Pct))
          : null,
      },
    });
  }
  return snapshots;
}

function foreignFeatures(foreignByDate, market, index) {
  const historyRows = market.slice(0, index + 1).map((record) =>
    foreignByDate.get(marketDate(record)) || null);
  const history = historyRows.map((row) => Number.isFinite(row?.netBuy) ? row.netBuy : null);
  const recent = history.slice(-3);
  const twenty = history.slice(-20);
  const coverage3d = recent.filter(Number.isFinite).length / 3;
  const coverage20d = twenty.filter(Number.isFinite).length / 20;
  const current = history.at(-1);

  let streak = null;
  if (Number.isFinite(current)) {
    streak = 0;
    for (
      let cursor = history.length - 1;
      cursor >= 0 && Number.isFinite(history[cursor]) && history[cursor] > 0 && streak < 20;
      cursor -= 1
    ) streak += 1;
  }

  const recentVolumes = market.slice(Math.max(0, index - 2), index + 1)
    .map((record) => finiteOrNull(record.payload?.Trading_Volume));
  const recentVolume = recentVolumes.length === 3 && recentVolumes.every(Number.isFinite)
    ? recentVolumes.reduce((sum, value) => sum + value, 0)
    : null;
  const intensity = coverage3d === 1 && recentVolume > 0
    ? recent.reduce((sum, value) => sum + value, 0) / recentVolume
    : null;
  const percentile = coverage20d === 1 && Number.isFinite(current)
    ? twenty.filter((value) => value <= current).length / twenty.length
    : null;

  return {
    context: {
      available: coverage3d === 1 && coverage20d === 1,
      coverage3d,
      coverage20d,
    },
    values: {
      foreignBuyStreak: streak,
      foreignThreeDayIntensity: intensity,
      foreignTwentyDayPercentile: percentile,
    },
    evidence: historyRows.slice(-20).filter(Boolean).flatMap((row) =>
      row.sourceHashes.map((sourceHash) => ({ availableAt: row.availableAt, sourceHash }))),
  };
}

function averageFinite(values) {
  return values.length > 0 && values.every(Number.isFinite)
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : null;
}

function candidateFor(market, foreignByDate, index, options) {
  const currentRecord = market[index];
  const current = currentRecord.payload || {};
  const close = finiteOrNull(current.close);
  const hma9 = options.hma9[index];
  const hma20 = options.hma20[index];
  if (!(close > 0) || !Number.isFinite(hma9) || !Number.isFinite(hma20)) return null;
  if (!Number.isFinite(options.hma9[index - 1]) || !Number.isFinite(options.hma20[index - 1])) {
    return null;
  }

  const hma9SlopePct = pctChange(hma9, options.hma9[index - 1]);
  const previousHma9SlopePct = pctChange(options.hma9[index - 1], options.hma9[index - 2]);
  const hma20SlopePct = pctChange(hma20, options.hma20[index - 1]);
  const closeToHma9Pct = pctChange(close, hma9);
  const turnoverWindow = market.slice(index - 19, index + 1);
  const turnoverValues = turnoverWindow.map((record) => {
    const payload = record.payload || {};
    const tradingMoney = finiteOrNull(payload.Trading_money);
    const fallbackTurnover = finiteOrNull(payload.close) !== null
      && finiteOrNull(payload.Trading_Volume) !== null
      ? finiteOr(payload.close) * finiteOr(payload.Trading_Volume)
      : null;
    return tradingMoney ?? fallbackTurnover;
  });
  const averageTurnover = averageFinite(turnoverValues);
  const volumeWindow = market.slice(index - 20, index)
    .map((record) => finiteOrNull(record.payload?.Trading_Volume));
  const averageVolume = averageFinite(volumeWindow);
  const currentVolume = finiteOrNull(current.Trading_Volume);
  const high = finiteOrNull(current.max ?? current.high);
  const low = finiteOrNull(current.min ?? current.low);
  if (!Number.isFinite(high) || !Number.isFinite(low) || !(high > low)) return null;
  const range = high - low;
  const foreign = foreignFeatures(foreignByDate, market, index);
  const momentum3Pct = pctChange(close, finiteOrNull(market[index - 3]?.payload?.close));
  const decisionDate = marketDate(currentRecord);
  const marketRegime = options.dailyMarketSnapshots.get(decisionDate);
  if (!marketRegime) return null;
  const priorThreeVolume = averageFinite(market.slice(index - 3, index)
    .map((record) => finiteOrNull(record.payload?.Trading_Volume)));

  const rawFeatures = {
    hma9SlopePct,
    hma9AccelerationPct: Number.isFinite(previousHma9SlopePct)
      ? hma9SlopePct - previousHma9SlopePct
      : null,
    hma20SlopePct,
    closeToHma9Pct,
    volumeRatio: averageVolume > 0 && Number.isFinite(currentVolume)
      ? currentVolume / averageVolume
      : null,
    volumeThreeDayAcceleration: priorThreeVolume > 0 && Number.isFinite(currentVolume)
      ? currentVolume / priorThreeVolume
      : null,
    averageTurnover,
    averageTurnoverLog10: averageTurnover > 0 ? Math.log10(averageTurnover) : null,
    momentum1Pct: pctChange(close, finiteOrNull(market[index - 1]?.payload?.close)),
    momentum3Pct,
    momentum5Pct: pctChange(close, finiteOrNull(market[index - 5]?.payload?.close)),
    marketBreadth1d: marketRegime.values.breadth1d,
    marketMedianMomentum3Pct: marketRegime.values.medianMomentum3Pct,
    relativeMomentum3Pct: Number.isFinite(momentum3Pct)
      && Number.isFinite(marketRegime.values.medianMomentum3Pct)
      ? momentum3Pct - marketRegime.values.medianMomentum3Pct
      : null,
    intradayRangePct: range / close * 100,
    closePosition: (close - low) / range,
    ...foreign.values,
  };
  if (REQUIRED_CANDIDATE_FEATURES.some((name) => !Number.isFinite(rawFeatures[name]))) return null;
  const featureValues = PHASE3_CANDIDATE_FEATURE_NAMES.map((name) => round(rawFeatures[name]));

  // HMA20 slope is the longest technical dependency: current and prior HMA values
  // require at most 24 daily market rows. Older rows must not bloat every candidate.
  const ownMarketEvidence = market.slice(Math.max(0, index - 23), index + 1);
  const snapshotEvidence = marketRegime.context.cutoffTime
    ? [{
      availableAt: marketRegime.context.cutoffTime,
      sourceHash: marketRegime.context.snapshotHash,
    }]
    : [];
  const featureEvidence = [...ownMarketEvidence, ...foreign.evidence, ...snapshotEvidence];
  const evidenceAvailableAt = [...new Set(featureEvidence
    .map((record) => record.availableAt)
    .filter((value) => Number.isFinite(Date.parse(value))))].sort();
  const decisionTime = evidenceAvailableAt.at(-1);
  if (!decisionTime || !isValidMarketDate(decisionDate)) return null;

  return {
    ticker: String(currentRecord.ticker),
    decisionDate,
    decisionTime,
    evidenceAvailableAt,
    technicalEvidenceHashes: [...new Set(featureEvidence
      .map((record) => record.sourceHash)
      .filter(Boolean))].sort(),
    featureNames: [...PHASE3_CANDIDATE_FEATURE_NAMES],
    features: featureValues,
    decisionPrice: round(close),
    marketContext: marketRegime.context,
    foreignContext: foreign.context,
  };
}

export function buildPhase3Candidates(records = [], settings = {}) {
  const byTicker = new Map();
  for (const record of records) {
    if (!['accepted', 'inferred_schedule'].includes(record?.dataQuality) || !record?.ticker) continue;
    if (!['finmind:market', 'finmind:institutional'].includes(record.source)) continue;
    const bucket = byTicker.get(String(record.ticker)) || [];
    bucket.push(record);
    byTicker.set(String(record.ticker), bucket);
  }

  const tickerData = new Map();
  const marketObservationsByDate = new Map();
  for (const [ticker, tickerRecords] of [...byTicker.entries()].sort()) {
    const market = latestByDate(tickerRecords.filter((record) => record.source === 'finmind:market'));
    if (market.length < 25) continue;
    const foreignByDate = aggregateForeignByDate(
      tickerRecords.filter((record) => record.source === 'finmind:institutional'),
    );
    const closes = market.map((record) => finiteOrNull(record.payload?.close));
    const hma9 = calculateHullMovingAverage(closes, 9);
    const hma20 = calculateHullMovingAverage(closes, 20);
    tickerData.set(ticker, { market, foreignByDate, hma9, hma20 });
    for (let index = 5; index < market.length; index += 1) {
      const date = marketDate(market[index]);
      const observations = marketObservationsByDate.get(date) || [];
      const observation = marketObservation(ticker, market, closes, index);
      if (observation) observations.push(observation);
      marketObservationsByDate.set(date, observations);
    }
  }

  const minimumCoveragePct = finiteOr(
    settings.marketContextMinimumCoveragePct,
    PHASE3_MARKET_CONTEXT_MINIMUM_COVERAGE_PCT,
  );
  const dailyMarketSnapshots = buildDailyMarketSnapshots(
    marketObservationsByDate,
    [...tickerData.values()].map((data) => data.market[0]?.availableAt).filter(Boolean),
    minimumCoveragePct,
  );
  const candidates = [];
  for (const [, data] of tickerData) {
    const { market, foreignByDate, hma9, hma20 } = data;
    for (let index = 21; index < market.length; index += 1) {
      const candidate = candidateFor(market, foreignByDate, index, {
        hma9,
        hma20,
        dailyMarketSnapshots,
      });
      if (candidate) candidates.push(candidate);
    }
  }
  return candidates.sort((left, right) =>
    left.decisionTime.localeCompare(right.decisionTime)
    || left.ticker.localeCompare(right.ticker));
}

async function readCertificationEvidence(evidenceRoot, batchSize = 256) {
  const recordsDirectory = join(evidenceRoot, 'records');
  let files;
  try {
    files = (await readdir(recordsDirectory)).filter((file) => /^[a-f0-9]{64}\.json$/.test(file));
  } catch (error) {
    if (error?.code === 'ENOENT') return [];
    throw error;
  }
  const accepted = [];
  for (let offset = 0; offset < files.length; offset += batchSize) {
    const rows = await Promise.all(files.slice(offset, offset + batchSize).map(async (file) =>
      JSON.parse(await readFile(join(recordsDirectory, file), 'utf8'))));
    for (const record of rows) {
      if (record.source === 'finmind:market') accepted.push(record);
      else if (record.source === 'finmind:institutional'
        && record.payload?.name === 'Foreign_Investor') accepted.push(record);
    }
  }
  return accepted;
}

async function writeAtomic(file, content) {
  await mkdir(dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, content, { flag: 'wx' });
  await rename(temporary, file);
}

function hashEvidenceManifest(manifest) {
  const hasher = createHash('sha256');
  for (const row of manifest) hasher.update(`${row.id}:${row.sourceHash}\n`);
  return hasher.digest('hex');
}

export async function ensurePhase3CandidateArtifact({
  evidenceRoot,
  candidateArtifact = join(evidenceRoot, 'candidates.json'),
  evidenceManifestHash = null,
  rebuild = false,
} = {}) {
  if (!evidenceRoot) throw new TypeError('evidenceRoot is required');
  const currentEvidenceManifestHash = evidenceManifestHash
    || hashEvidenceManifest(await readEvidenceManifest(evidenceRoot));
  const metadataArtifact = `${candidateArtifact}.meta.json`;
  if (!rebuild) {
    try {
      const existing = JSON.parse(await readFile(candidateArtifact, 'utf8'));
      if (!Array.isArray(existing)) throw new TypeError('candidates.json must contain an array');
      const candidateHash = createHash('sha256').update(stableJson(existing)).digest('hex');
      let metadata = null;
      try {
        metadata = JSON.parse(await readFile(metadataArtifact, 'utf8'));
      } catch (error) {
        if (error?.code !== 'ENOENT') throw error;
      }
      if (metadata?.schemaVersion === PHASE3_CANDIDATE_SCHEMA_VERSION
        && metadata?.evidenceManifestHash === currentEvidenceManifestHash
        && metadata?.candidateHash === candidateHash) {
        return {
          candidateArtifact,
          metadataArtifact,
          candidateCount: existing.length,
          candidateHash,
          evidenceManifestHash: currentEvidenceManifestHash,
          created: false,
        };
      }
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }
  const records = await readCertificationEvidence(evidenceRoot);
  const candidates = buildPhase3Candidates(records);
  const candidateHash = createHash('sha256').update(stableJson(candidates)).digest('hex');
  await writeAtomic(candidateArtifact, `${JSON.stringify(candidates)}\n`);
  await writeAtomic(metadataArtifact, `${JSON.stringify({
    schemaVersion: PHASE3_CANDIDATE_SCHEMA_VERSION,
    evidenceManifestHash: currentEvidenceManifestHash,
    candidateHash,
  }, null, 2)}\n`);
  return {
    candidateArtifact,
    metadataArtifact,
    candidateCount: candidates.length,
    candidateHash,
    evidenceManifestHash: currentEvidenceManifestHash,
    created: true,
  };
}
