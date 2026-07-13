import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runPhase3Dataset } from '../src/phase3-dataset.js';
import { writeEvidenceRecord } from '../src/point-in-time-store.js';

test('dataset freezes a read-only normal-equity universe and reports incomplete quality', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'phase3-dataset-'));
  const universeFile = join(dir, 'evidence', 'universe.json');
  const reportJson = join(dir, 'reports', 'quality.json');
  let contractCalls = 0;
  const result = await runPhase3Dataset({
    universeFile,
    evidenceRoot: join(dir, 'evidence'),
    reportJson,
    reportMarkdown: join(dir, 'reports', 'quality.md'),
    startDate: '2024-01-01',
    endDate: '2026-06-30',
  }, {
    getContracts: async () => {
      contractCalls += 1;
      return {
        readOnly: true,
        maxPage: 1,
        data: [
          { securityType: 'STK', exchange: 'TSE', code: '2330', name: '台積電', unit: 1000 },
          { securityType: 'STK', exchange: 'OTC', code: '6274', name: '台燿', unit: 1000 },
          { securityType: 'STK', exchange: 'TSE', code: '0050', name: '元大台灣50 ETF', unit: 1000 },
        ],
      };
    },
    collect: async ({ tickers }) => ({
      executionMode: 'demo_replay',
      orderApiSafe: true,
      tickers,
      recordsWritten: 0,
      excluded: [],
    }),
  });

  assert.equal(contractCalls, 1);
  assert.equal(result.executionMode, 'read_only');
  assert.equal(result.orderApiSafe, true);
  assert.equal(result.quality.usable, false);
  assert.match(result.inputHash, /^[a-f0-9]{64}$/);
  assert.match(result.resultHash, /^[a-f0-9]{64}$/);
  assert.deepEqual(result.collection.tickers, ['2330', '6274']);
  const universe = JSON.parse(await readFile(universeFile, 'utf8'));
  assert.deepEqual(universe.tickers, ['2330', '6274']);
  assert.match(universe.contractSnapshotHash, /^[a-f0-9]{64}$/);
  assert.deepEqual(JSON.parse(await readFile(reportJson, 'utf8')), result);
});

test('dataset reuses the frozen universe unless refresh is explicit', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'phase3-dataset-reuse-'));
  const args = {
    universeFile: join(dir, 'universe.json'),
    evidenceRoot: join(dir, 'evidence'),
    reportJson: join(dir, 'report.json'),
    reportMarkdown: join(dir, 'report.md'),
  };
  const dependencies = {
    getContracts: async () => ({
      readOnly: true,
      maxPage: 1,
      data: [{ securityType: 'STK', exchange: 'TSE', code: '2330', name: '台積電', unit: 1000 }],
    }),
    collect: async () => ({ executionMode: 'demo_replay', recordsWritten: 0, excluded: [] }),
  };
  await runPhase3Dataset(args, dependencies);
  dependencies.getContracts = async () => { throw new Error('must reuse frozen universe'); };
  const second = await runPhase3Dataset(args, dependencies);
  assert.equal(second.universe.tickerCount, 1);
});

test('dataset reproduction reuses frozen evidence without provider collection', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'phase3-dataset-frozen-evidence-'));
  const evidenceRoot = join(dir, 'evidence');
  await writeEvidenceRecord(evidenceRoot, {
    ticker: '2330',
    source: 'finmind:market',
    eventTime: '2026-01-02T13:30:00+08:00',
    publishedAt: '2026-01-02T14:00:00+08:00',
    availableAt: '2026-01-02T14:05:00+08:00',
    fetchedAt: '2026-01-03T00:00:00+08:00',
    payload: { close: 100 },
  });
  await writeFile(join(evidenceRoot, 'candidates.json'), JSON.stringify([{
    decisionDate: '2026-01-02',
    decisionTime: '2026-01-02T18:00:00+08:00',
    evidenceAvailableAt: ['2026-01-02T14:05:00+08:00'],
    features: [1, 2],
  }]));
  const result = await runPhase3Dataset({
    universeFile: join(dir, 'universe.json'),
    evidenceRoot,
    reportJson: join(dir, 'report.json'),
    reportMarkdown: join(dir, 'report.md'),
  }, {
    getContracts: async () => ({
      readOnly: true, maxPage: 1,
      data: [{ securityType: 'STK', exchange: 'TSE', code: '2330', name: '台積電', unit: 1000 }],
    }),
    collect: async () => { throw new Error('frozen reproduction must not call providers'); },
    ensureCandidates: async ({ candidateArtifact, evidenceManifestHash }) => ({
      candidateArtifact,
      candidateCount: 1,
      evidenceManifestHash,
      created: false,
    }),
  });

  assert.deepEqual(result.collection, {
    mode: 'frozen_evidence_reuse',
    providerCalls: 0,
    evidenceRecordCount: 1,
  });
});

test('dataset saves a deterministic publication-time audit sample for every source', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'phase3-dataset-audit-'));
  const evidenceRoot = join(dir, 'evidence');
  const result = await runPhase3Dataset({
    universeFile: join(dir, 'universe.json'),
    evidenceRoot,
    reportJson: join(dir, 'report.json'),
    reportMarkdown: join(dir, 'report.md'),
  }, {
    getContracts: async () => ({
      readOnly: true,
      maxPage: 1,
      data: [{ securityType: 'STK', exchange: 'TSE', code: '2330', name: '台積電', unit: 1000 }],
    }),
    collect: async () => {
      for (const source of ['finmind_daily', 'twse_institutional']) {
        await writeEvidenceRecord(evidenceRoot, {
          ticker: '2330',
          source,
          eventTime: '2026-01-02T13:30:00+08:00',
          publishedAt: '2026-01-02T14:00:00+08:00',
          availableAt: '2026-01-02T14:05:00+08:00',
          fetchedAt: '2026-01-03T00:00:00+08:00',
          payload: { source },
        });
      }
      return { executionMode: 'demo_replay', recordsWritten: 2, excluded: [] };
    },
  });

  assert.equal(result.sourceTimingAudit.seed, 3005);
  assert.equal(result.sourceTimingAudit.passed, true);
  assert.deepEqual(
    result.sourceTimingAudit.samples.map((row) => row.source),
    ['finmind_daily', 'twse_institutional'],
  );
  assert.ok(result.sourceTimingAudit.samples.every((row) =>
    Date.parse(row.publishedAt) <= Date.parse(row.availableAt)));
});

test('dataset quality metrics describe decision-time observations without model labels or folds', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'phase3-dataset-candidates-'));
  const evidenceRoot = join(dir, 'evidence');
  await mkdir(evidenceRoot, { recursive: true });
  const candidates = Array.from({ length: 8 }, (_, index) => ({
    decisionDate: new Date(Date.UTC(2024, index, 1)).toISOString().slice(0, 10),
    decisionTime: new Date(Date.UTC(2024, index, 1)).toISOString(),
    evidenceAvailableAt: [new Date(Date.UTC(2024, index, 1)).toISOString()],
    features: index === 0 ? [1, null] : [1, 2],
  }));
  await writeFile(join(evidenceRoot, 'candidates.json'), JSON.stringify(candidates));
  const result = await runPhase3Dataset({
    universeFile: join(dir, 'universe.json'),
    evidenceRoot,
    reportJson: join(dir, 'report.json'),
    reportMarkdown: join(dir, 'report.md'),
  }, {
    getContracts: async () => ({
      readOnly: true, maxPage: 1,
      data: [{ securityType: 'STK', exchange: 'TSE', code: '2330', name: '台積電', unit: 1000 }],
    }),
    collect: async () => ({ executionMode: 'demo_replay', recordsWritten: 0, excluded: [] }),
    ensureCandidates: async ({ candidateArtifact, evidenceManifestHash }) => ({
      candidateArtifact,
      candidateCount: candidates.length,
      evidenceManifestHash,
      created: false,
    }),
  });
  assert.deepEqual(result.datasetMetrics, {
    candidateCount: 8,
    coreCoveragePct: 87.5,
    candidateArtifact: join(evidenceRoot, 'candidates.json'),
    featureTimingAudit: { candidateCount: 8, passed: true, violationCount: 0 },
  });
  assert.equal(Object.hasOwn(result, 'readiness'), false);
});

test('dataset generates the technical candidate artifact before evaluating quality', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'phase3-dataset-generate-'));
  const evidenceRoot = join(dir, 'evidence');
  let generationCalls = 0;
  const result = await runPhase3Dataset({
    universeFile: join(dir, 'universe.json'),
    evidenceRoot,
    reportJson: join(dir, 'report.json'),
    reportMarkdown: join(dir, 'report.md'),
  }, {
    getContracts: async () => ({
      readOnly: true,
      maxPage: 1,
      data: [{ securityType: 'STK', exchange: 'TSE', code: '2330', name: '台積電', unit: 1000 }],
    }),
    collect: async () => ({ executionMode: 'demo_replay', recordsWritten: 0, excluded: [] }),
    ensureCandidates: async ({ candidateArtifact }) => {
      generationCalls += 1;
      await mkdir(evidenceRoot, { recursive: true });
      await writeFile(candidateArtifact, JSON.stringify([{
        decisionDate: '2024-01-01',
        decisionTime: '2024-01-01T18:00:00+08:00',
        evidenceAvailableAt: ['2024-01-01T18:00:00+08:00'],
        features: [1, 2],
      }]));
      return { candidateArtifact, candidateCount: 1, created: true };
    },
  });

  assert.equal(generationCalls, 1);
  assert.equal(result.datasetMetrics.candidateCount, 1);
  assert.equal(result.candidateArtifact.created, true);
});
