import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  evidenceAsOf,
  evidenceId,
  normalizeEvidenceRecord,
  readEvidenceManifest,
  writeEvidenceRecord,
} from '../src/point-in-time-store.js';

function evidence(overrides = {}) {
  return normalizeEvidenceRecord({
    ticker: '2330',
    peerGroups: ['D002', 'D001', 'D001'],
    source: 'finmind',
    sourceUrl: 'https://example.test/2330',
    eventTime: '2026-01-02T13:30:00+08:00',
    publishedAt: '2026-01-02T14:00:00+08:00',
    availableAt: '2026-01-02T14:05:00+08:00',
    fetchedAt: '2026-01-02T15:00:00+08:00',
    payload: { close: 100 },
    ...overrides,
  });
}

test('evidence requires a defensible availability timestamp', () => {
  assert.throws(() => normalizeEvidenceRecord({
    source: 'finmind',
    eventTime: '2026-01-02T00:00:00+08:00',
    payload: { value: 1 },
  }), /availableAt/);
});

test('evidence never invents publication time from availability time', () => {
  assert.throws(() => normalizeEvidenceRecord({
    source: 'finmind',
    eventTime: '2026-01-02T00:00:00+08:00',
    availableAt: '2026-01-02T18:00:00+08:00',
    fetchedAt: '2026-01-03T00:00:00+08:00',
    payload: { value: 1 },
  }), /publishedAt is required/);
});

test('evidence rejects availability before publication', () => {
  assert.throws(() => normalizeEvidenceRecord({
    source: 'mops',
    eventTime: '2026-01-02T10:00:00+08:00',
    publishedAt: '2026-01-02T11:00:00+08:00',
    availableAt: '2026-01-02T10:30:00+08:00',
    fetchedAt: '2026-01-02T12:00:00+08:00',
    payload: {},
  }), /availableAt.*publishedAt/);
});

test('normalization freezes sorted groups and hashes payload deterministically', () => {
  const first = evidence();
  const second = evidence({ peerGroups: ['D001', 'D002'], payload: { close: 100 } });
  assert.deepEqual(first.peerGroups, ['D001', 'D002']);
  assert.equal(first.sourceHash, second.sourceHash);
  assert.equal(Object.isFrozen(first), true);
  assert.equal(Object.isFrozen(first.peerGroups), true);
  assert.throws(() => first.peerGroups.push('D003'), TypeError);
});

test('append-only writes are idempotent and conflicting payloads get distinct files', async () => {
  const root = await mkdtemp(join(tmpdir(), 'pit-store-'));
  const first = evidence();
  const conflict = evidence({ payload: { close: 101 } });

  const firstWrite = await writeEvidenceRecord(root, first);
  const duplicateWrite = await writeEvidenceRecord(root, first);
  const conflictWrite = await writeEvidenceRecord(root, conflict);

  assert.equal(firstWrite.created, true);
  assert.equal(duplicateWrite.created, false);
  assert.notEqual(firstWrite.file, conflictWrite.file);
  assert.equal(JSON.parse(await readFile(firstWrite.file, 'utf8')).sourceHash, first.sourceHash);
});

test('as-of queries exclude future evidence and sort deterministically', () => {
  const earlier = evidence({
    eventTime: '2026-01-01T13:30:00+08:00',
    publishedAt: '2026-01-01T14:00:00+08:00',
    availableAt: '2026-01-01T14:05:00+08:00',
  });
  const later = evidence({
    eventTime: '2026-01-03T13:30:00+08:00',
    publishedAt: '2026-01-03T14:00:00+08:00',
    availableAt: '2026-01-03T14:05:00+08:00',
    fetchedAt: '2026-01-04T09:00:00+08:00',
  });
  assert.deepEqual(
    evidenceAsOf([later, earlier], '2026-01-02T09:00:00+08:00').map(evidenceId),
    [evidenceId(earlier)],
  );
});

test('manifest is deterministic regardless of write order', async () => {
  const root = await mkdtemp(join(tmpdir(), 'pit-manifest-'));
  const later = evidence({
    payload: { close: 102 },
    availableAt: '2026-01-03T14:05:00+08:00',
    fetchedAt: '2026-01-04T09:00:00+08:00',
  });
  const earlier = evidence({
    payload: { close: 99 },
    eventTime: '2026-01-01T13:30:00+08:00',
    publishedAt: '2026-01-01T14:00:00+08:00',
    availableAt: '2026-01-01T14:05:00+08:00',
  });
  await writeEvidenceRecord(root, later);
  await writeEvidenceRecord(root, earlier);
  const manifest = await readEvidenceManifest(root);
  assert.deepEqual(manifest.map((row) => row.id), [...manifest.map((row) => row.id)].sort());
});

test('manifest reader requires bounded positive batch size', async () => {
  const root = await mkdtemp(join(tmpdir(), 'pit-manifest-batch-'));
  await assert.rejects(
    readEvidenceManifest(root, { batchSize: 0 }),
    /batchSize must be a positive integer/,
  );
});
