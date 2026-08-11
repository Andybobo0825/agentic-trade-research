import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';

import { ensurePhase3CandidateArtifact } from './phase3-candidates.js';
import { PHASE3_FILTER_CONFIG, evaluatePhase3Filter } from './phase3-filter.js';

export const PHASE3_SCREEN_INPUTS = Object.freeze([
  'evidenceRoot',
  'candidateArtifact',
  'startDate',
  'endDate',
  'asOfTime',
  'top',
  'includeRejected',
  'rebuild',
  'reportJson',
  'reportMarkdown',
]);

const FUNNEL_STAGES = Object.freeze([
  { stage: 'required_features_complete', matches: (reason) => reason.startsWith('missing_') },
  { stage: 'average_turnover', reasons: ['average_turnover_below_minimum'] },
  { stage: 'hma20_regime', reasons: ['hma20_regime_not_bullish'] },
  { stage: 'hma9_rising', reasons: ['hma9_not_rising'] },
  { stage: 'close_above_hma9', reasons: ['close_below_hma9'] },
  { stage: 'hma_distance', reasons: ['close_too_far_above_hma9'] },
  { stage: 'momentum5', reasons: ['momentum_5d_above_maximum'] },
  { stage: 'close_position', reasons: ['close_position_above_maximum'] },
]);

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

function exactDate(value, name) {
  if (value === undefined) return undefined;
  const text = String(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) throw new TypeError(`${name} must be YYYY-MM-DD`);
  const [year, month, day] = text.split('-').map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (parsed.toISOString().slice(0, 10) !== text) throw new TypeError(`${name} must be YYYY-MM-DD`);
  return text;
}

function exactTime(value, name) {
  if (value === undefined) return undefined;
  const text = String(value);
  if (!Number.isFinite(Date.parse(text))) throw new TypeError(`${name} must be a valid timestamp`);
  return text;
}

function positiveInteger(value, name, fallback) {
  if (value === undefined) return fallback;
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1) throw new TypeError(`${name} must be positive integer`);
  return number;
}

export function assertPhase3ScreenArgs(args = {}) {
  const allowed = new Set(PHASE3_SCREEN_INPUTS);
  for (const key of Object.keys(args)) {
    if (!allowed.has(key)) throw new Error(`phase3-screen forbids ${key}`);
  }
  const startDate = exactDate(args.startDate, 'startDate');
  const endDate = exactDate(args.endDate, 'endDate');
  exactTime(args.asOfTime, 'asOfTime');
  if (startDate && endDate && startDate > endDate) {
    throw new TypeError('startDate must not be after endDate');
  }
  positiveInteger(args.top, 'top', 20);
  return args;
}

async function writeAtomic(file, content) {
  await mkdir(dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, content, { flag: 'wx' });
  await rename(temporary, file);
}

function publicCandidate(candidate, evaluation, asOfTime) {
  return {
    ticker: candidate.ticker,
    decisionDate: candidate.decisionDate,
    decisionTime: candidate.decisionTime,
    asOfTime,
    decisionPrice: candidate.decisionPrice,
    technicalEligible: evaluation.technicalEligible,
    executionEligible: evaluation.executionEligible,
    reasons: evaluation.reasons,
    warnings: evaluation.warnings,
    hardGateDiagnostics: evaluation.hardGateDiagnostics,
    phase3RankScore: evaluation.phase3RankScore,
    softAdjustments: evaluation.softAdjustments,
    softFeatureCoverage: evaluation.softFeatureCoverage,
    volumeConfirmed: evaluation.volumeConfirmed,
    volumeConfirmationLevel: evaluation.volumeConfirmationLevel,
    marketContext: candidate.marketContext || null,
    foreignContext: candidate.foreignContext || null,
    evidenceAvailableAt: candidate.evidenceAvailableAt,
    technicalEvidenceHashes: candidate.technicalEvidenceHashes,
  };
}

function compareEligible(left, right) {
  return right.phase3RankScore - left.phase3RankScore
    || right.softFeatureCoverage.coveragePct - left.softFeatureCoverage.coveragePct
    || String(right.decisionDate).localeCompare(String(left.decisionDate))
    || String(left.ticker).localeCompare(String(right.ticker));
}

function compareRejected(left, right) {
  return String(right.decisionDate).localeCompare(String(left.decisionDate))
    || String(left.ticker).localeCompare(String(right.ticker));
}

function summarizeRejections(rows, exclusive = false) {
  const counts = new Map();
  for (const row of rows) {
    if (exclusive && row.reasons.length !== 1) continue;
    for (const reason of row.reasons) counts.set(reason, (counts.get(reason) || 0) + 1);
  }
  const order = FUNNEL_STAGES.flatMap((stage) => stage.reasons || []);
  const reasons = [...counts.keys()].sort((left, right) => {
    const leftIndex = order.indexOf(left);
    const rightIndex = order.indexOf(right);
    if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
    if (leftIndex === -1) return -1;
    if (rightIndex === -1) return 1;
    return leftIndex - rightIndex;
  });
  return Object.fromEntries(reasons.map((reason) => [reason, counts.get(reason)]));
}

function sequentialFunnel(rows) {
  let remaining = [...rows];
  return FUNNEL_STAGES.map((definition) => {
    const inputCount = remaining.length;
    const rejected = remaining.filter((row) => row.reasons.some((reason) =>
      definition.matches?.(reason) || definition.reasons?.includes(reason)));
    const rejectedKeys = new Set(rejected.map((row) => `${row.ticker}|${row.decisionDate}`));
    remaining = remaining.filter((row) => !rejectedKeys.has(`${row.ticker}|${row.decisionDate}`));
    return {
      stage: definition.stage,
      inputCount,
      rejectedCount: rejected.length,
      remainingCount: remaining.length,
    };
  });
}

function latestDecisionTime(rows) {
  return rows.filter((row) => Number.isFinite(Date.parse(row.decisionTime)))
    .sort((left, right) => Date.parse(left.decisionTime) - Date.parse(right.decisionTime))
    .at(-1)?.decisionTime || null;
}

export async function runPhase3Screen(args = {}, dependencies = {}) {
  assertPhase3ScreenArgs(args);
  const evidenceRoot = args.evidenceRoot || join('.omx', 'evidence', 'phase3');
  const candidateArtifact = args.candidateArtifact || join(evidenceRoot, 'candidates.json');
  const ensureCandidateArtifact = dependencies.ensureCandidateArtifact || ensurePhase3CandidateArtifact;
  const readCandidates = dependencies.readCandidates
    || (async (file) => JSON.parse(await readFile(file, 'utf8')));
  const artifact = await ensureCandidateArtifact({
    evidenceRoot,
    candidateArtifact,
    rebuild: Boolean(args.rebuild),
  });
  const candidates = await readCandidates(artifact.candidateArtifact || candidateArtifact);
  if (!Array.isArray(candidates)) throw new TypeError('Phase 3 candidate artifact must be an array');
  if (candidates.length === 0) {
    throw new Error('No Phase 3 candidates are available; run phase3-dataset with valid point-in-time evidence first');
  }

  const startDate = exactDate(args.startDate, 'startDate');
  const endDate = exactDate(args.endDate, 'endDate');
  const asOfTime = exactTime(args.asOfTime, 'asOfTime') || latestDecisionTime(candidates);
  if (!asOfTime) throw new Error('No Phase 3 candidates contain a valid decisionTime');
  const asOfTimestamp = Date.parse(asOfTime);
  const pointInTimeCandidates = candidates.filter((row) =>
    Number.isFinite(Date.parse(row.decisionTime)) && Date.parse(row.decisionTime) <= asOfTimestamp);
  const availableDates = pointInTimeCandidates.map((row) => String(row.decisionDate || ''))
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value)).sort();
  const latestDate = availableDates.at(-1) || null;
  const observations = pointInTimeCandidates.filter((row) => {
    const date = String(row.decisionDate || '');
    if (!startDate && !endDate) return date === latestDate;
    return (!startDate || date >= startDate) && (!endDate || date <= endDate);
  }).sort((left, right) => String(left.decisionTime).localeCompare(String(right.decisionTime))
    || String(left.ticker).localeCompare(String(right.ticker)));
  if (observations.length === 0) {
    throw new Error('No Phase 3 observations are available in the requested window');
  }

  const evaluated = observations.map((row) =>
    publicCandidate(row, evaluatePhase3Filter(row), asOfTime));
  const eligible = evaluated.filter((row) => row.technicalEligible).sort(compareEligible);
  const rankedEligible = eligible.map((row, index) => ({
    ...row,
    rank: index + 1,
    eligibleCount: eligible.length,
    rankPercentile: (eligible.length - index) / eligible.length,
  }));
  const rejected = evaluated.filter((row) => !row.technicalEligible).sort(compareRejected);
  const top = positiveInteger(args.top, 'top', 20);
  const core = {
    strategy: 'phase3_stability',
    command: 'phase3-screen',
    executionMode: 'read_only',
    asOfDate: observations.map((row) => row.decisionDate).sort().at(-1) || null,
    asOfTime,
    dataFreshnessPassed: observations.every((row) => Date.parse(row.decisionTime) <= asOfTimestamp),
    requestedWindow: { startDate: startDate || null, endDate: endDate || null },
    configuration: PHASE3_FILTER_CONFIG,
    evidenceManifestHash: artifact.evidenceManifestHash || null,
    candidateHash: artifact.candidateHash || null,
    sourceCandidateCount: artifact.candidateCount ?? candidates.length,
    observationCount: observations.length,
    eligibleCount: rankedEligible.length,
    rejectedCount: rejected.length,
    rejectionSummary: summarizeRejections(rejected),
    exclusiveRejectionSummary: summarizeRejections(rejected, true),
    sequentialFunnel: sequentialFunnel(evaluated),
    candidates: rankedEligible.slice(0, top),
    rejected: args.includeRejected ? rejected : [],
  };
  const result = { ...core, resultHash: sha256(core) };
  if (args.reportJson) await writeAtomic(args.reportJson, `${JSON.stringify(result, null, 2)}\n`);
  if (args.reportMarkdown) await writeAtomic(args.reportMarkdown, renderPhase3ScreenMarkdown(result));
  return result;
}

function unavailableDom(warning, details = {}) {
  return {
    available: false,
    observedAt: details.observedAt || null,
    sampleAgeSeconds: Number.isFinite(details.sampleAgeSeconds) ? details.sampleAgeSeconds : null,
    bestBid: null,
    bestAsk: null,
    spreadPct: null,
    bidDepth: null,
    askDepth: null,
    imbalance: null,
    suggestedPassiveBid: null,
    suggestedAggressiveBid: null,
    doNotChaseAbove: null,
    cancelOrWaitBelow: null,
    confidence: 'none',
    warnings: [warning],
  };
}

function withUnavailableDom(candidate, warning, details) {
  return { ...candidate, executionEligible: false, dom: unavailableDom(warning, details) };
}

function finitePositive(value) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
}

function depthTotal(levels) {
  const values = levels.map((level) => Number(level?.volume)).filter(Number.isFinite);
  return values.length ? values.reduce((sum, value) => sum + value, 0) : 0;
}

export function applyPhase3DomGuidance(candidate, domResult, options = {}) {
  if (!candidate?.technicalEligible) return withUnavailableDom(candidate, 'technical_ineligible');
  if (candidate.executionEligible === false) {
    return withUnavailableDom(candidate, 'preexisting_execution_ineligible');
  }
  if (!domResult || !Array.isArray(domResult.samples) || domResult.validSampleCount < 1) {
    return withUnavailableDom(candidate, 'dom_unavailable');
  }
  if (String(domResult.ticker) !== String(candidate.ticker)) {
    return withUnavailableDom(candidate, 'dom_ticker_mismatch');
  }
  const asOfTimestamp = Date.parse(options.asOfTime);
  const maxAgeSeconds = Number(options.maxAgeSeconds);
  if (!Number.isFinite(asOfTimestamp) || !Number.isFinite(maxAgeSeconds) || maxAgeSeconds < 0) {
    return withUnavailableDom(candidate, 'invalid_dom_freshness_config');
  }
  const sample = domResult.samples.filter((row) => row?.valid !== false)
    .sort((left, right) => Date.parse(left.capturedAt) - Date.parse(right.capturedAt)).at(-1);
  if (!sample) return withUnavailableDom(candidate, 'dom_unavailable');
  const observedAt = sample.capturedAt || null;
  const observedTimestamp = Date.parse(observedAt);
  if (!Number.isFinite(observedTimestamp)) return withUnavailableDom(candidate, 'invalid_dom_timestamp');
  const sampleAgeSeconds = (asOfTimestamp - observedTimestamp) / 1000;
  if (sampleAgeSeconds < 0) {
    return withUnavailableDom(candidate, 'future_dom_sample', { observedAt, sampleAgeSeconds });
  }
  if (sampleAgeSeconds > maxAgeSeconds) {
    return withUnavailableDom(candidate, 'stale_dom', { observedAt, sampleAgeSeconds });
  }
  const referenceObservedAt = domResult.referencePriceSources?.snapshotCapturedAt;
  if (referenceObservedAt !== undefined
    && Date.parse(referenceObservedAt) !== observedTimestamp) {
    return withUnavailableDom(candidate, 'dom_timestamp_mismatch', {
      observedAt,
      sampleAgeSeconds,
    });
  }

  const bestBid = finitePositive(sample.bids?.[0]?.price);
  const bestAsk = finitePositive(sample.asks?.[0]?.price);
  if (bestBid === null || bestAsk === null || bestBid >= bestAsk) {
    return withUnavailableDom(candidate, 'invalid_dom_spread', { observedAt, sampleAgeSeconds });
  }
  const bidDepth = depthTotal(sample.bids || []);
  const askDepth = depthTotal(sample.asks || []);
  const depth = bidDepth + askDepth;
  const measuredImbalance = typeof sample.depthImbalance === 'number'
    && Number.isFinite(sample.depthImbalance)
    ? sample.depthImbalance
    : depth > 0 ? (bidDepth - askDepth) / depth : null;
  const suggestedPassiveBid = finitePositive(domResult.referencePrices?.patientEntryPrice);
  const suggestedAggressiveBid = finitePositive(domResult.referencePrices?.activeEntryLimit);
  const doNotChaseAbove = finitePositive(domResult.referencePrices?.takeProfitPrice);
  const cancelOrWaitBelow = finitePositive(domResult.referencePrices?.stopLossPrice);
  const spreadPct = (bestAsk - bestBid) / bestBid * 100;
  if (!Number.isFinite(spreadPct)) {
    return withUnavailableDom(candidate, 'invalid_dom_spread', { observedAt, sampleAgeSeconds });
  }
  if (
    suggestedPassiveBid === null
    || suggestedAggressiveBid === null
    || doNotChaseAbove === null
    || cancelOrWaitBelow === null
    || suggestedPassiveBid > suggestedAggressiveBid
    || suggestedPassiveBid > doNotChaseAbove
    || suggestedAggressiveBid > doNotChaseAbove
    || cancelOrWaitBelow >= doNotChaseAbove
  ) return withUnavailableDom(candidate, 'invalid_dom_prices', { observedAt, sampleAgeSeconds });

  const confidence = ['low', 'medium', 'high'].includes(domResult.reliability)
    ? domResult.reliability
    : 'low';
  return {
    ...candidate,
    executionEligible: true,
    dom: {
      available: true,
      source: domResult.source || 'shioaji',
      ticker: String(domResult.ticker),
      observedAt,
      sampleAgeSeconds,
      bestBid,
      bestAsk,
      spreadPct,
      bidDepth,
      askDepth,
      bidLevels: sample.bids,
      askLevels: sample.asks,
      imbalance: measuredImbalance,
      suggestedPassiveBid,
      suggestedAggressiveBid,
      doNotChaseAbove,
      cancelOrWaitBelow,
      confidence,
      warnings: [],
    },
  };
}

function rowKey(row) {
  return `${row.ticker}|${row.decisionDate}`;
}

function reportRows(result) {
  return [...(result?.candidates || []), ...(result?.rejected || [])];
}

function rowEligibility(row, candidateKeys) {
  if (typeof row.technicalEligible === 'boolean') return row.technicalEligible;
  if (typeof row.eligible === 'boolean') return row.eligible;
  return candidateKeys.has(rowKey(row));
}

function rowScore(row) {
  const value = row.phase3RankScore ?? row.softScore;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function comparePhase3ScreenResults(before = {}, after = {}) {
  const beforeCandidates = new Map((before.candidates || []).map((row) => [rowKey(row), row]));
  const afterCandidates = new Map((after.candidates || []).map((row) => [rowKey(row), row]));
  const beforeRows = new Map(reportRows(before).map((row) => [rowKey(row), row]));
  const afterRows = new Map(reportRows(after).map((row) => [rowKey(row), row]));
  const allKeys = [...new Set([...beforeRows.keys(), ...afterRows.keys()])].sort();
  const changes = {
    addedCandidates: [...afterCandidates.entries()]
      .filter(([key]) => !beforeCandidates.has(key))
      .map(([, row]) => ({ ...row, reason: 'newly_technical_eligible' })),
    removedCandidates: [...beforeCandidates.entries()]
      .filter(([key]) => !afterCandidates.has(key))
      .map(([, row]) => ({ ...row, reason: 'no_longer_technical_eligible' })),
    eligibilityChanged: [],
    scoreChanged: [],
    marketContextChanged: [],
    foreignContextChanged: [],
  };
  for (const key of allKeys) {
    const beforeRow = beforeRows.get(key);
    const afterRow = afterRows.get(key);
    if (!beforeRow || !afterRow) continue;
    const [ticker, decisionDate] = key.split('|');
    const beforeEligible = rowEligibility(beforeRow, new Set(beforeCandidates.keys()));
    const afterEligible = rowEligibility(afterRow, new Set(afterCandidates.keys()));
    if (beforeEligible !== afterEligible) {
      changes.eligibilityChanged.push({
        ticker,
        decisionDate,
        before: beforeEligible,
        after: afterEligible,
        reason: 'technical_eligibility_changed',
      });
    }
    const beforeScore = rowScore(beforeRow);
    const afterScore = rowScore(afterRow);
    if (beforeScore !== null && afterScore !== null && beforeScore !== afterScore) {
      changes.scoreChanged.push({
        ticker,
        decisionDate,
        before: beforeScore,
        after: afterScore,
        reason: 'phase3_rank_score_changed',
      });
    }
    if (beforeScore !== null && afterScore !== null
      && stableJson(beforeRow.marketContext || null) !== stableJson(afterRow.marketContext || null)) {
      changes.marketContextChanged.push({
        ticker,
        decisionDate,
        before: beforeRow.marketContext || null,
        after: afterRow.marketContext || null,
        reason: 'daily_market_snapshot_changed',
      });
    }
    if (beforeScore !== null && afterScore !== null
      && stableJson(beforeRow.foreignContext || null) !== stableJson(afterRow.foreignContext || null)) {
      changes.foreignContextChanged.push({
        ticker,
        decisionDate,
        before: beforeRow.foreignContext || null,
        after: afterRow.foreignContext || null,
        reason: 'foreign_missingness_or_coverage_changed',
      });
    }
  }
  for (const key of Object.keys(changes)) {
    changes[key].sort((left, right) => rowKey(left).localeCompare(rowKey(right)));
  }
  return changes;
}

function markdownTable(rows, columns) {
  if (!rows.length) return '_None_';
  const header = `| ${columns.map(([label]) => label).join(' | ')} |`;
  const divider = `| ${columns.map(() => '---').join(' | ')} |`;
  const body = rows.map((row) => `| ${columns.map(([, field]) => {
    const value = typeof field === 'function' ? field(row) : row[field];
    return String(value ?? '').replaceAll('|', '\\|');
  }).join(' | ')} |`);
  return [header, divider, ...body].join('\n');
}

export function renderPhase3ScreenMarkdown(result) {
  const lines = [
    '# Phase 3 Screen',
    '',
    `- Strategy: ${result.strategy}`,
    `- Execution mode: ${result.executionMode}`,
    `- As-of date: ${result.asOfDate || 'none'}`,
    `- As-of time: ${result.asOfTime || 'none'}`,
    `- Data freshness passed: ${result.dataFreshnessPassed}`,
    `- Observations: ${result.observationCount}`,
    `- Eligible: ${result.eligibleCount}`,
    `- Rejected: ${result.rejectedCount}`,
    `- Result hash: ${result.resultHash}`,
    '',
    '**Phase 3 Rank Score is only for same-day eligible ranking and is not a probability or prediction confidence.**',
    '',
    '## Eligible candidates',
    '',
    markdownTable(result.candidates || [], [
      ['Rank', 'rank'],
      ['Ticker', 'ticker'],
      ['Decision date', 'decisionDate'],
      ['Price', 'decisionPrice'],
      ['Phase 3 Rank Score', 'phase3RankScore'],
      ['Soft coverage', (row) => `${row.softFeatureCoverage?.coveragePct ?? 0}%`],
    ]),
  ];
  if (result.rejected?.length) {
    lines.push(
      '',
      '## Rejected observations',
      '',
      markdownTable(result.rejected, [
        ['Ticker', 'ticker'],
        ['Decision date', 'decisionDate'],
        ['Reasons', (row) => row.reasons.join(', ')],
      ]),
    );
  }
  return `${lines.join('\n')}\n`;
}
