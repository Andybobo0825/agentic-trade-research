import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { collectPhase3PointInTimeData } from './phase3-data-collector.js';
import { ensurePhase3CandidateArtifact } from './phase3-candidates.js';
import { readEvidenceManifest } from './point-in-time-store.js';
import { getShioajiContracts } from './shioaji-market.js';

export const PHASE3_DATASET_INPUTS = Object.freeze([
  'universeFile',
  'startDate',
  'endDate',
  'evidenceRoot',
  'reportJson',
  'reportMarkdown',
  'refreshUniverse',
]);

function exactDate(value, name) {
  if (value === undefined) return undefined;
  const text = String(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) throw new TypeError(`${name} must be YYYY-MM-DD`);
  const [year, month, day] = text.split('-').map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (parsed.toISOString().slice(0, 10) !== text) throw new TypeError(`${name} must be YYYY-MM-DD`);
  return text;
}

export function assertPhase3DatasetArgs(args = {}) {
  const allowed = new Set(PHASE3_DATASET_INPUTS);
  for (const key of Object.keys(args)) {
    if (!allowed.has(key)) throw new Error(`phase3-dataset forbids ${key}`);
  }
  const startDate = exactDate(args.startDate, 'startDate');
  const endDate = exactDate(args.endDate, 'endDate');
  if (startDate && endDate && startDate > endDate) {
    throw new TypeError('startDate must not be after endDate');
  }
  return args;
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function latestCompletedTaiwanEvidenceDate(now = new Date()) {
  const taipei = new Date(now.getTime() + 8 * 60 * 60 * 1000);
  if (taipei.getUTCHours() < 18) taipei.setUTCDate(taipei.getUTCDate() - 1);
  return taipei.toISOString().slice(0, 10);
}

async function writeAtomic(file, content) {
  await mkdir(dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, content, { flag: 'wx' });
  await rename(temporary, file);
}

function isNormalEquity(contract) {
  return ['TSE', 'OTC'].includes(contract.exchange)
    && /^[1-9]\d{3}$/.test(contract.code)
    && Number(contract.unit) === 1000
    && !/(ETF|ETN|指數|特別股)/i.test(contract.name);
}

async function buildFrozenUniverse(getContracts) {
  const contracts = [];
  let page = 1;
  let maxPage = 1;
  do {
    const result = await getContracts({ securityType: 'STK', page, pageSize: 1000 });
    if (result.readOnly !== true) throw new Error('contract source must be read-only');
    contracts.push(...(result.data || []));
    maxPage = Number(result.maxPage || 1);
    page += 1;
  } while (page <= maxPage);
  const accepted = contracts.filter(isNormalEquity).sort((a, b) => a.code.localeCompare(b.code));
  const contractSnapshotHash = createHash('sha256').update(stableJson(contracts)).digest('hex');
  return {
    schemaVersion: 1,
    source: 'shioaji:contracts',
    readOnly: true,
    contractSnapshotHash,
    tickers: accepted.map((row) => row.code),
    contracts: accepted,
  };
}

async function loadUniverse(file, refresh, getContracts) {
  if (!refresh) {
    try {
      return JSON.parse(await readFile(file, 'utf8'));
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }
  const universe = await buildFrozenUniverse(getContracts);
  await writeAtomic(file, `${JSON.stringify(universe, null, 2)}\n`);
  return universe;
}

async function readDatasetMetrics(evidenceRoot) {
  const candidateArtifact = join(evidenceRoot, 'candidates.json');
  let rows;
  try {
    rows = JSON.parse(await readFile(candidateArtifact, 'utf8'));
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
    rows = [];
  }
  if (!Array.isArray(rows)) throw new TypeError('candidates.json must contain an array');
  const timingValid = (row) =>
    Number.isFinite(Date.parse(row.decisionTime))
    && Array.isArray(row.evidenceAvailableAt)
    && row.evidenceAvailableAt.length > 0
    && row.evidenceAvailableAt.every((value) =>
      Number.isFinite(Date.parse(value))
      && Date.parse(value) <= Date.parse(row.decisionTime));
  const complete = rows.filter((row) =>
    Array.isArray(row.features)
    && row.features.length > 0
    && row.features.every((value) => value !== null && Number.isFinite(Number(value)))
    && timingValid(row));
  return {
    candidateCount: rows.length,
    coreCoveragePct: rows.length ? complete.length / rows.length * 100 : 0,
    candidateArtifact,
    featureTimingAudit: {
      candidateCount: rows.length,
      passed: rows.length > 0 && rows.every(timingValid),
      violationCount: rows.filter((row) => !timingValid(row)).length,
    },
  };
}

async function auditSourceTiming(evidenceRoot, manifest, seed = 3005) {
  const selected = new Map();
  for (const row of manifest) {
    const rank = createHash('sha256').update(`${seed}:${row.id}`).digest('hex');
    const current = selected.get(row.source);
    if (!current || rank < current.rank) selected.set(row.source, { ...row, rank });
  }
  const samples = [];
  for (const row of [...selected.values()].sort((left, right) =>
    left.source.localeCompare(right.source))) {
    const record = JSON.parse(await readFile(join(evidenceRoot, 'records', `${row.id}.json`), 'utf8'));
    const valid = Date.parse(record.publishedAt) <= Date.parse(record.availableAt);
    samples.push({
      source: record.source,
      evidenceId: row.id,
      publishedAt: record.publishedAt,
      availableAt: record.availableAt,
      valid,
    });
  }
  return {
    seed,
    method: 'sha256_min_per_source',
    scope: 'source publication ordering only; feature inclusion is audited separately',
    sampleCount: samples.length,
    passed: samples.every((row) => row.valid),
    violations: samples.filter((row) => !row.valid).map((row) => row.evidenceId),
    samples,
  };
}

export async function runPhase3Dataset(args = {}, dependencies = {}) {
  assertPhase3DatasetArgs(args);
  const config = {
    universeFile: args.universeFile || '.omx/evidence/phase3/universe.json',
    startDate: args.startDate || '2024-01-01',
    endDate: args.endDate || latestCompletedTaiwanEvidenceDate(
      dependencies.now ? dependencies.now() : new Date(),
    ),
    evidenceRoot: args.evidenceRoot || '.omx/evidence/phase3',
    reportJson: args.reportJson || '.omx/reports/phase3-dataset-quality.json',
    reportMarkdown: args.reportMarkdown || '.omx/reports/phase3-dataset-quality.md',
    refreshUniverse: args.refreshUniverse === true,
  };
  assertPhase3DatasetArgs({ startDate: config.startDate, endDate: config.endDate });
  const universe = await loadUniverse(
    config.universeFile,
    config.refreshUniverse,
    dependencies.getContracts || getShioajiContracts,
  );
  let manifest = await readEvidenceManifest(config.evidenceRoot);
  const collection = manifest.length
    ? {
      mode: 'frozen_evidence_reuse',
      providerCalls: 0,
      evidenceRecordCount: manifest.length,
    }
    : await (dependencies.collect || collectPhase3PointInTimeData)({
      tickers: universe.tickers,
      startDate: config.startDate,
      endDate: config.endDate,
      evidenceRoot: config.evidenceRoot,
    });
  if (!manifest.length) manifest = await readEvidenceManifest(config.evidenceRoot);
  const sourceCounts = {};
  for (const row of manifest) sourceCounts[row.source] = (sourceCounts[row.source] || 0) + 1;
  const sourceTimingAudit = await auditSourceTiming(config.evidenceRoot, manifest);
  const manifestHasher = createHash('sha256');
  for (const row of manifest) manifestHasher.update(`${row.id}:${row.sourceHash}\n`);
  const evidenceManifestHash = manifestHasher.digest('hex');
  const candidateArtifact = await (
    dependencies.ensureCandidates || ensurePhase3CandidateArtifact
  )({
    evidenceRoot: config.evidenceRoot,
    candidateArtifact: join(config.evidenceRoot, 'candidates.json'),
    evidenceManifestHash,
  });
  const datasetMetrics = await readDatasetMetrics(config.evidenceRoot);
  const qualityChecks = {
    evidenceManifestPresent: manifest.length > 0,
    sourceTimingPassed: sourceTimingAudit.passed,
    candidateEvidenceBound: candidateArtifact.evidenceManifestHash === evidenceManifestHash,
    featureTimingPassed: datasetMetrics.featureTimingAudit.passed,
  };
  const coreReport = {
    schemaVersion: 2,
    executionMode: 'read_only',
    orderApiSafe: true,
    range: { startDate: config.startDate, endDate: config.endDate },
    universe: {
      tickerCount: universe.tickers.length,
      contractSnapshotHash: universe.contractSnapshotHash,
      file: config.universeFile,
    },
    collection,
    candidateArtifact,
    evidenceRecordCount: manifest.length,
    evidenceManifestHash,
    sourceCounts,
    sourceTimingAudit,
    featureTimingAudit: datasetMetrics.featureTimingAudit,
    datasetMetrics,
    quality: {
      usable: Object.values(qualityChecks).every(Boolean),
      checks: qualityChecks,
      failures: Object.entries(qualityChecks).filter(([, passed]) => !passed)
        .map(([name]) => name),
    },
  };
  const report = {
    ...coreReport,
    inputHash: createHash('sha256').update(stableJson({
      range: coreReport.range,
      contractSnapshotHash: universe.contractSnapshotHash,
      evidenceManifestHash,
    })).digest('hex'),
    resultHash: createHash('sha256').update(stableJson(coreReport)).digest('hex'),
  };
  await writeAtomic(config.reportJson, `${JSON.stringify(report, null, 2)}\n`);
  await writeAtomic(config.reportMarkdown, `${renderPhase3DatasetMarkdown(report)}\n`);
  return report;
}

export function renderPhase3DatasetMarkdown(report) {
  return [
    '# Phase 3 point-in-time dataset',
    '',
    `Execution mode: ${report.executionMode}`,
    `Universe tickers: ${report.universe.tickerCount}`,
    `Evidence records: ${report.evidenceRecordCount}`,
    `Source timing audit: ${report.sourceTimingAudit.passed ? 'PASS' : 'BLOCKED'} (${report.sourceTimingAudit.sampleCount} samples, seed ${report.sourceTimingAudit.seed})`,
    `Dataset quality: ${report.quality.usable ? 'PASS' : 'INCOMPLETE'}`,
    `Quality gaps: ${report.quality.failures.join(', ') || 'none'}`,
    `Contract snapshot hash: ${report.universe.contractSnapshotHash}`,
    `Evidence manifest hash: ${report.evidenceManifestHash}`,
    `Input hash: ${report.inputHash}`,
    `Result hash: ${report.resultHash}`,
  ].join('\n');
}
