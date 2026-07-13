import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { readEvidenceManifest } from './point-in-time-store.js';
import { calculateHullMovingAverage } from './indicators.js';

export const PHASE3_CANDIDATE_SCHEMA_VERSION = 4;

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

function finite(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
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
    const current = byDate.get(date) || {
      date,
      netBuy: 0,
      availableAt: record.availableAt,
      sourceHashes: [],
    };
    current.netBuy += finite(record.payload.buy) - finite(record.payload.sell);
    if (String(record.availableAt).localeCompare(String(current.availableAt)) > 0) {
      current.availableAt = record.availableAt;
    }
    if (record.sourceHash) current.sourceHashes.push(record.sourceHash);
    byDate.set(date, current);
  }
  return byDate;
}

function pctChange(current, previous) {
  return previous > 0 ? ((current / previous) - 1) * 100 : 0;
}

function median(values) {
  const sorted = values.filter(Number.isFinite).sort((left, right) => left - right);
  if (!sorted.length) return 0;
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

function marketObservation(market, closes, index) {
  const evidenceRecords = [
    market[index],
    market[index - 1],
    market[index - 3],
  ].filter(Boolean);
  const availableAt = latestAvailableAt(evidenceRecords);
  if (!availableAt) return null;
  return {
    availableAt,
    evidence: evidenceRecords.map((record) => ({
      availableAt: record.availableAt,
      sourceHash: record.sourceHash,
    })),
    return1d: pctChange(closes[index], closes[index - 1]),
    momentum3Pct: pctChange(closes[index], closes[index - 3]),
  };
}

function marketStatsFor(observations = [], decisionTime) {
  const availableObservations = observations.filter((observation) =>
    Date.parse(observation.availableAt) <= Date.parse(decisionTime));
  if (!availableObservations.length) {
    return {
      values: {
        breadth1d: 0.5,
        medianMomentum3Pct: 0,
      },
      evidence: [],
    };
  }
  return {
    values: {
      breadth1d: availableObservations.filter((row) => row.return1d > 0).length
        / availableObservations.length,
      medianMomentum3Pct: median(availableObservations.map((row) => row.momentum3Pct)),
    },
    evidence: availableObservations.flatMap((observation) => observation.evidence),
  };
}

function foreignFeatures(foreignByDate, market, index) {
  const historyRows = market.slice(0, index + 1).map((record) =>
    foreignByDate.get(marketDate(record)) || null);
  const history = historyRows.map((row) => row?.netBuy || 0);
  let streak = 0;
  for (
    let cursor = history.length - 1;
    cursor >= 0 && history[cursor] > 0 && streak < 20;
    cursor -= 1
  ) {
    streak += 1;
  }
  const recent = history.slice(-3);
  const recentVolume = market.slice(Math.max(0, index - 2), index + 1)
    .reduce((sum, record) => sum + finite(record.payload?.Trading_Volume), 0);
  const twenty = history.slice(-20);
  const current = history.at(-1) || 0;
  return {
    values: {
      foreignBuyStreak: streak,
      foreignThreeDayIntensity: recentVolume > 0
        ? recent.reduce((sum, value) => sum + value, 0) / recentVolume
        : 0,
      foreignTwentyDayPercentile: twenty.length
        ? twenty.filter((value) => value <= current).length / twenty.length
        : 0,
    },
    evidence: historyRows.slice(-20).filter(Boolean).flatMap((row) =>
      row.sourceHashes.map((sourceHash) => ({
        availableAt: row.availableAt,
        sourceHash,
      }))),
  };
}

function candidateFor(market, foreignByDate, index, options) {
  const currentRecord = market[index];
  const current = currentRecord.payload || {};
  const close = finite(current.close);
  const hma9 = options.hma9[index];
  const hma20 = options.hma20[index];
  if (!(close > 0) || !Number.isFinite(hma9) || !Number.isFinite(hma20)) return null;
  if (!Number.isFinite(options.hma9[index - 1]) || !Number.isFinite(options.hma20[index - 1])) {
    return null;
  }
  const hma9SlopePct = pctChange(hma9, options.hma9[index - 1]);
  const previousHma9SlopePct = pctChange(
    options.hma9[index - 1],
    options.hma9[index - 2],
  );
  const hma20SlopePct = pctChange(hma20, options.hma20[index - 1]);
  const closeToHma9Pct = pctChange(close, hma9);
  const turnoverWindow = market.slice(index - 19, index + 1);
  const averageTurnover = turnoverWindow.reduce((sum, record) => {
    const payload = record.payload || {};
    return sum + finite(
      payload.Trading_money,
      finite(payload.close) * finite(payload.Trading_Volume),
    );
  }, 0) / turnoverWindow.length;
  const volumeWindow = market.slice(index - 20, index);
  const averageVolume = volumeWindow.reduce(
    (sum, record) => sum + finite(record.payload?.Trading_Volume),
    0,
  ) / volumeWindow.length;
  const rawHigh = current.max ?? current.high;
  const rawLow = current.min ?? current.low;
  const high = typeof rawHigh === 'number' && Number.isFinite(rawHigh) ? rawHigh : null;
  const low = typeof rawLow === 'number' && Number.isFinite(rawLow) ? rawLow : null;
  if (!Number.isFinite(high) || !Number.isFinite(low) || !(high > low)) return null;
  const range = high - low;
  const foreign = foreignFeatures(foreignByDate, market, index);
  const momentum3Pct = pctChange(close, finite(market[index - 3]?.payload?.close));
  const ownMarketEvidence = market.slice(0, index + 1);
  const ownFeatureEvidence = [
    ...ownMarketEvidence,
    ...foreign.evidence,
  ];
  const provisionalEvidenceAvailableAt = [...new Set(ownFeatureEvidence
    .map((record) => record.availableAt)
    .filter((value) => Number.isFinite(Date.parse(value))))].sort();
  const provisionalDecisionTime = provisionalEvidenceAvailableAt.at(-1);
  if (!provisionalDecisionTime) return null;
  const marketRegime = marketStatsFor(
    options.marketObservationsByDate.get(marketDate(currentRecord)),
    provisionalDecisionTime,
  );
  const priorThreeVolume = market.slice(index - 3, index).reduce(
    (sum, record) => sum + finite(record.payload?.Trading_Volume),
    0,
  ) / 3;
  const rawFeatures = {
    hma9SlopePct,
    hma9AccelerationPct: hma9SlopePct - previousHma9SlopePct,
    hma20SlopePct,
    closeToHma9Pct,
    volumeRatio: averageVolume > 0 ? finite(current.Trading_Volume) / averageVolume : 0,
    volumeThreeDayAcceleration: priorThreeVolume > 0
      ? finite(current.Trading_Volume) / priorThreeVolume
      : 0,
    averageTurnover,
    averageTurnoverLog10: Math.log10(Math.max(1, averageTurnover)),
    momentum1Pct: pctChange(close, finite(market[index - 1]?.payload?.close)),
    momentum3Pct,
    momentum5Pct: pctChange(close, finite(market[index - 5]?.payload?.close)),
    marketBreadth1d: marketRegime.values.breadth1d,
    marketMedianMomentum3Pct: marketRegime.values.medianMomentum3Pct,
    relativeMomentum3Pct: momentum3Pct - marketRegime.values.medianMomentum3Pct,
    intradayRangePct: close > 0 ? range / close * 100 : 0,
    closePosition: (close - low) / range,
    ...foreign.values,
  };
  const featureValues = PHASE3_CANDIDATE_FEATURE_NAMES.map((name) => round(rawFeatures[name]));
  if (featureValues.some((value) => !Number.isFinite(value))) return null;

  const featureEvidence = [
    ...ownFeatureEvidence,
    ...marketRegime.evidence,
  ];
  const evidenceAvailableAt = [...new Set(featureEvidence
    .map((record) => record.availableAt)
    .filter((value) => Number.isFinite(Date.parse(value))))].sort();
  const decisionTime = evidenceAvailableAt.at(-1);
  const decisionDate = marketDate(currentRecord);
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
  };
}

export function buildPhase3Candidates(records = [], settings = {}) {
  void settings;
  const byTicker = new Map();
  for (const record of records) {
    if (!['accepted', 'inferred_schedule'].includes(record?.dataQuality) || !record?.ticker) {
      continue;
    }
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
    const closes = market.map((record) => finite(record.payload?.close, null));
    const hma9 = calculateHullMovingAverage(closes, 9);
    const hma20 = calculateHullMovingAverage(closes, 20);
    tickerData.set(ticker, { market, foreignByDate, hma9, hma20 });
    for (let index = 5; index < market.length; index += 1) {
      const date = marketDate(market[index]);
      const observations = marketObservationsByDate.get(date) || [];
      const observation = marketObservation(market, closes, index);
      if (observation) observations.push(observation);
      marketObservationsByDate.set(date, observations);
    }
  }

  const candidates = [];
  for (const [, data] of tickerData) {
    const {
      market,
      foreignByDate,
      hma9,
      hma20,
    } = data;
    for (let index = 21; index < market.length; index += 1) {
      const candidate = candidateFor(market, foreignByDate, index, {
        hma9,
        hma20,
        marketObservationsByDate,
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
    files = (await readdir(recordsDirectory))
      .filter((file) => /^[a-f0-9]{64}\.json$/.test(file));
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
      else if (
        record.source === 'finmind:institutional'
        && record.payload?.name === 'Foreign_Investor'
      ) accepted.push(record);
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
