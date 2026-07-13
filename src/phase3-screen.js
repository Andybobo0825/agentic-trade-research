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
  'top',
  'includeRejected',
  'rebuild',
  'reportJson',
  'reportMarkdown',
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

function publicCandidate(candidate, evaluation) {
  return {
    ticker: candidate.ticker,
    decisionDate: candidate.decisionDate,
    decisionTime: candidate.decisionTime,
    decisionPrice: candidate.decisionPrice,
    eligible: evaluation.eligible,
    reasons: evaluation.reasons,
    diagnostics: evaluation.diagnostics,
    softScore: evaluation.softScore,
    softAdjustments: evaluation.softAdjustments,
    evidenceAvailableAt: candidate.evidenceAvailableAt,
    technicalEvidenceHashes: candidate.technicalEvidenceHashes,
  };
}

function compareEligible(left, right) {
  return right.softScore - left.softScore
    || String(right.decisionDate).localeCompare(String(left.decisionDate))
    || String(left.ticker).localeCompare(String(right.ticker));
}

function compareRejected(left, right) {
  return String(right.decisionDate).localeCompare(String(left.decisionDate))
    || String(left.ticker).localeCompare(String(right.ticker));
}

export async function runPhase3Screen(args = {}, dependencies = {}) {
  assertPhase3ScreenArgs(args);
  const evidenceRoot = args.evidenceRoot || join('.omx', 'evidence', 'phase3');
  const candidateArtifact = args.candidateArtifact || join(evidenceRoot, 'candidates.json');
  const ensureCandidateArtifact = dependencies.ensureCandidateArtifact
    || ensurePhase3CandidateArtifact;
  const readCandidates = dependencies.readCandidates
    || (async (file) => JSON.parse(await readFile(file, 'utf8')));
  const artifact = await ensureCandidateArtifact({
    evidenceRoot,
    candidateArtifact,
    rebuild: Boolean(args.rebuild),
  });
  const candidates = await readCandidates(artifact.candidateArtifact || candidateArtifact);
  if (!Array.isArray(candidates)) throw new TypeError('Phase 3 candidate artifact must be an array');

  const startDate = exactDate(args.startDate, 'startDate');
  const endDate = exactDate(args.endDate, 'endDate');
  const availableDates = candidates.map((row) => String(row.decisionDate || ''))
    .filter((value) => /^\d{4}-\d{2}-\d{2}$/.test(value)).sort();
  const latestDate = availableDates.at(-1) || null;
  const observations = candidates.filter((row) => {
    const date = String(row.decisionDate || '');
    if (!startDate && !endDate) return date === latestDate;
    return (!startDate || date >= startDate) && (!endDate || date <= endDate);
  });
  const evaluated = observations.map((row) => publicCandidate(row, evaluatePhase3Filter(row)));
  const eligible = evaluated.filter((row) => row.eligible).sort(compareEligible);
  const rejected = evaluated.filter((row) => !row.eligible).sort(compareRejected);
  const top = positiveInteger(args.top, 'top', 20);
  const core = {
    strategy: 'phase3_stability',
    command: 'phase3-screen',
    executionMode: 'read_only',
    asOfDate: observations.map((row) => row.decisionDate).sort().at(-1) || null,
    requestedWindow: { startDate: startDate || null, endDate: endDate || null },
    configuration: PHASE3_FILTER_CONFIG,
    evidenceManifestHash: artifact.evidenceManifestHash || null,
    candidateHash: artifact.candidateHash || null,
    sourceCandidateCount: artifact.candidateCount ?? candidates.length,
    observationCount: observations.length,
    eligibleCount: eligible.length,
    rejectedCount: rejected.length,
    candidates: eligible.slice(0, top),
    rejected: args.includeRejected ? rejected : [],
  };
  const result = { ...core, resultHash: sha256(core) };
  if (args.reportJson) await writeAtomic(args.reportJson, `${JSON.stringify(result, null, 2)}\n`);
  if (args.reportMarkdown) {
    await writeAtomic(args.reportMarkdown, renderPhase3ScreenMarkdown(result));
  }
  return result;
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
    `- Observations: ${result.observationCount}`,
    `- Eligible: ${result.eligibleCount}`,
    `- Rejected: ${result.rejectedCount}`,
    `- Result hash: ${result.resultHash}`,
    '',
    '## Eligible candidates',
    '',
    markdownTable(result.candidates || [], [
      ['Ticker', 'ticker'],
      ['Decision date', 'decisionDate'],
      ['Price', 'decisionPrice'],
      ['Soft score', 'softScore'],
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
