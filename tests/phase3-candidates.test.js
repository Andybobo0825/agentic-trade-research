import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  PHASE3_CANDIDATE_SCHEMA_VERSION,
  PHASE3_CANDIDATE_FEATURE_NAMES,
  buildPhase3Candidates,
  ensurePhase3CandidateArtifact,
  finiteOr,
  finiteOrNull,
} from '../src/phase3-candidates.js';
import { writeEvidenceRecord } from '../src/point-in-time-store.js';

function technicalFixture() {
  const records = [];
  let close = 100;
  for (let index = 0; index < 42; index += 1) {
    const date = new Date(Date.UTC(2025, 0, index + 1)).toISOString().slice(0, 10);
    close *= index >= 30 && index <= 32 ? 1.02 : 1.002;
    records.push({
      ticker: '2330',
      source: 'finmind:market',
      sourceHash: `market-${index}`,
      eventTime: `${date}T13:30:00+08:00`,
      publishedAt: `${date}T13:30:00+08:00`,
      availableAt: `${date}T13:30:00+08:00`,
      dataQuality: 'accepted',
      payload: {
        date,
        open: close * 0.998,
        max: close * 1.01,
        min: close * 0.99,
        close,
        Trading_Volume: 1_000_000 + index * 10_000,
        Trading_money: close * (1_000_000 + index * 10_000),
      },
    });
    records.push({
      ticker: '2330',
      source: 'finmind:institutional',
      sourceHash: `foreign-${index}`,
      eventTime: `${date}T13:30:00+08:00`,
      publishedAt: `${date}T18:00:00+08:00`,
      availableAt: `${date}T18:00:00+08:00`,
      dataQuality: 'inferred_schedule',
      payload: {
        date,
        name: 'Foreign_Investor',
        buy: 100_000 + index * 1000,
        sell: 20_000,
      },
    });
  }
  return records;
}

function peerMarketFixture({ lateObservation = false } = {}) {
  const records = [];
  for (let index = 0; index < 42; index += 1) {
    const date = new Date(Date.UTC(2025, 0, index + 1)).toISOString().slice(0, 10);
    const close = index === 23 ? 50 : 100;
    records.push({
      ticker: '1101',
      source: 'finmind:market',
      sourceHash: `peer-market-${index}`,
      eventTime: `${date}T13:30:00+08:00`,
      publishedAt: `${date}T13:00:00+08:00`,
      availableAt: lateObservation && index === 23
        ? '2025-01-25T09:00:00+08:00'
        : `${date}T13:00:00+08:00`,
      dataQuality: 'accepted',
      payload: {
        date,
        open: close,
        max: close * 1.01,
        min: close * 0.99,
        close,
        Trading_Volume: 1_000_000,
        Trading_money: close * 1_000_000,
      },
    });
  }
  return records;
}

function featureValue(row, name) {
  return row.features[row.featureNames.indexOf(name)];
}

test('creates the latest decision-time observation without future sessions or outcome fields', () => {
  const records = technicalFixture();
  const latestMarket = records.filter((record) => record.source === 'finmind:market').at(-1);
  const latest = buildPhase3Candidates(records).at(-1);

  assert.equal(latest.decisionDate, latestMarket.payload.date);
  for (const field of [
    'label', 'outcomeTime', 'outcomePath', 'outcomeEvidenceHashes', 'entryDate',
    'entryPrice', 'exitPrice', 'exitReason', 'leadDays', 'falseSignal',
    'maximumThreeSessionReturnPct', 'riskLineBreachTradingDay',
  ]) assert.equal(Object.hasOwn(latest, field), false, field);
  assert.ok(latest.evidenceAvailableAt.every((time) =>
    Date.parse(time) <= Date.parse(latest.decisionTime)));
});

test('candidate generation is deterministic and contains only technical decision features', () => {
  const records = technicalFixture();
  const first = buildPhase3Candidates(records);
  const second = buildPhase3Candidates([...records].reverse());

  assert.deepEqual(first, second);
  assert.ok(first.length > 0);
  for (const name of [
    'hma9AccelerationPct', 'relativeMomentum3Pct', 'marketBreadth1d',
    'foreignBuyStreak', 'momentum5Pct', 'averageTurnover', 'closePosition',
  ]) assert.ok(PHASE3_CANDIDATE_FEATURE_NAMES.includes(name), name);
  for (const row of first) {
    assert.deepEqual(row.featureNames, [...PHASE3_CANDIDATE_FEATURE_NAMES]);
    assert.equal(row.features.length, PHASE3_CANDIDATE_FEATURE_NAMES.length);
    assert.equal(row.featureNames.some((name) =>
      /news|financial|podcast|earnings|outcome|future/i.test(name)), false);
    assert.ok(row.decisionPrice > 0);
    assert.ok(row.technicalEvidenceHashes.length > 0);
  }
});

test('distinguishes missing numeric values from real zero values', () => {
  assert.equal(finiteOrNull(null), null);
  assert.equal(finiteOrNull(undefined), null);
  assert.equal(finiteOrNull(''), null);
  assert.equal(finiteOrNull('   '), null);
  assert.equal(finiteOrNull('123.5'), 123.5);
  assert.equal(finiteOr(null, 7), 7);
  assert.equal(finiteOr(0, 7), 0);
});

test('uses close times volume fallback when Trading_money is null or blank', () => {
  for (const missing of [null, '']) {
    const records = technicalFixture().map((record) => record.source === 'finmind:market'
      ? { ...record, payload: { ...record.payload, Trading_money: missing } }
      : record);
    const latest = buildPhase3Candidates(records).at(-1);

    assert.ok(latest);
    assert.ok(featureValue(latest, 'averageTurnover') > 20_000_000);
  }
});

test('distinguishes missing foreign data from zero net buy', () => {
  const records = technicalFixture().filter((record) =>
    !(record.source === 'finmind:institutional' && record.payload.date >= '2025-02-09'));
  const latest = buildPhase3Candidates(records).at(-1);

  assert.equal(latest.foreignContext.available, false);
  assert.equal(latest.foreignContext.coverage3d, 0);
  assert.ok(latest.foreignContext.coverage20d < 1);
  assert.equal(featureValue(latest, 'foreignBuyStreak'), null);
  assert.equal(featureValue(latest, 'foreignThreeDayIntensity'), null);
});

test('foreign buy streak stops at a missing foreign row', () => {
  const records = technicalFixture();
  const latestDate = records.filter((record) => record.source === 'finmind:market').at(-1).payload.date;
  const changed = records.filter((record) =>
    !(record.source === 'finmind:institutional' && record.payload.date === latestDate));
  const latest = buildPhase3Candidates(changed).at(-1);

  assert.equal(featureValue(latest, 'foreignBuyStreak'), null);
  assert.equal(latest.foreignContext.coverage3d, 2 / 3);
});

test('same decision date shares one fixed market breadth snapshot across tickers', () => {
  const first = technicalFixture().map((record) => ({
    ...record,
    ticker: '2330',
    sourceHash: `first-${record.sourceHash}`,
    ...(record.source === 'finmind:institutional'
      ? { availableAt: record.availableAt.replace('18:00:00', '14:00:00') }
      : {}),
  }));
  const second = technicalFixture().map((record) => ({
    ...record,
    ticker: '2317',
    sourceHash: `second-${record.sourceHash}`,
  }));
  const latePeer = peerMarketFixture().map((record) => ({
    ...record,
    availableAt: record.availableAt.replace('13:00:00', '16:00:00'),
  }));
  const decisionDate = first.filter((record) => record.source === 'finmind:market').at(-1).payload.date;
  const rows = buildPhase3Candidates([...first, ...second, ...latePeer])
    .filter((row) => row.decisionDate === decisionDate && ['2330', '2317'].includes(row.ticker));

  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0].marketContext, rows[1].marketContext);
  for (const name of ['marketBreadth1d', 'marketMedianMomentum3Pct', 'relativeMomentum3Pct']) {
    assert.equal(featureValue(rows[0], name), featureValue(rows[1], name));
  }
});

test('reports unavailable market context when daily universe coverage is insufficient', () => {
  const primary = technicalFixture();
  const incompletePeer = peerMarketFixture().filter((record) => record.payload.date < '2025-02-11');
  const latest = buildPhase3Candidates([...primary, ...incompletePeer])
    .filter((row) => row.ticker === '2330').at(-1);

  assert.equal(latest.marketContext.universeCount, 2);
  assert.equal(latest.marketContext.availableCount, 1);
  assert.equal(latest.marketContext.coveragePct, 50);
  assert.equal(latest.marketContext.available, false);
  assert.equal(featureValue(latest, 'marketBreadth1d'), null);
  assert.equal(featureValue(latest, 'marketMedianMomentum3Pct'), null);
});

test('historical market universe excludes tickers that were not observable yet', () => {
  const primary = technicalFixture();
  const futurePeer = peerMarketFixture().map((record) => {
    const shiftedDate = new Date(`${record.payload.date}T00:00:00.000Z`);
    shiftedDate.setUTCDate(shiftedDate.getUTCDate() + 90);
    const date = shiftedDate.toISOString().slice(0, 10);
    return {
      ...record,
      eventTime: `${date}T13:30:00+08:00`,
      publishedAt: `${date}T13:00:00+08:00`,
      availableAt: `${date}T13:00:00+08:00`,
      payload: { ...record.payload, date },
    };
  });
  const decisionDate = '2025-01-24';
  const base = buildPhase3Candidates(primary).find((row) => row.decisionDate === decisionDate);
  const withFutureTicker = buildPhase3Candidates([...primary, ...futurePeer])
    .find((row) => row.ticker === '2330' && row.decisionDate === decisionDate);

  assert.deepEqual(withFutureTicker.marketContext, base.marketContext);
  assert.equal(withFutureTicker.marketContext.universeCount, 1);
});

test('does not fabricate close position when the daily range is unavailable', () => {
  const records = technicalFixture();
  const latestMarket = records.filter((record) => record.source === 'finmind:market').at(-1);
  delete latestMarket.payload.max;
  delete latestMarket.payload.min;

  const candidates = buildPhase3Candidates(records);
  assert.equal(candidates.some((row) => row.decisionDate === latestMarket.payload.date), false);
});

test('rejects a candidate when close is missing or the daily range is zero', () => {
  for (const mutate of [
    (payload) => ({ ...payload, close: null }),
    (payload) => ({ ...payload, min: payload.max }),
  ]) {
    const records = technicalFixture();
    const latestMarket = records.filter((record) => record.source === 'finmind:market').at(-1);
    latestMarket.payload = mutate(latestMarket.payload);

    assert.equal(
      buildPhase3Candidates(records).some((row) => row.decisionDate === latestMarket.payload.date),
      false,
    );
  }
});

test('future commentary cannot affect an earlier candidate', () => {
  const records = technicalFixture();
  const original = buildPhase3Candidates(records);
  const decision = original[0].decisionTime;
  const changed = buildPhase3Candidates([...records, {
    ticker: '2330',
    source: 'news',
    sourceHash: 'future-news',
    eventTime: '2026-01-01T09:00:00+08:00',
    publishedAt: '2026-01-01T09:00:00+08:00',
    availableAt: '2026-01-01T09:00:00+08:00',
    dataQuality: 'accepted',
    payload: { title: 'future commentary' },
  }]);
  assert.deepEqual(
    changed.find((row) => row.decisionTime === decision),
    original.find((row) => row.decisionTime === decision),
  );
});

test('market context excludes peer observations published after the fixed daily cutoff', () => {
  const records = technicalFixture();
  const decisionDate = '2025-01-24';
  const base = buildPhase3Candidates(records).find((row) => row.decisionDate === decisionDate);
  const latePeer = buildPhase3Candidates([
    ...records,
    ...peerMarketFixture({ lateObservation: true }),
  ]).find((row) => row.ticker === '2330' && row.decisionDate === decisionDate);
  const timelyPeer = buildPhase3Candidates([
    ...records,
    ...peerMarketFixture(),
  ]).find((row) => row.ticker === '2330' && row.decisionDate === decisionDate);

  assert.equal(base.marketContext.available, true);
  assert.equal(latePeer.marketContext.available, false);
  assert.equal(latePeer.marketContext.availableCount, 1);
  assert.equal(featureValue(latePeer, 'marketBreadth1d'), null);
  assert.equal(timelyPeer.marketContext.available, true);
  assert.notEqual(
    featureValue(timelyPeer, 'marketMedianMomentum3Pct'),
    featureValue(base, 'marketMedianMomentum3Pct'),
  );
  assert.equal(latePeer.technicalEvidenceHashes.includes('peer-market-23'), false);
  assert.equal(timelyPeer.marketContext.snapshotHash.length, 64);
  assert.equal(timelyPeer.technicalEvidenceHashes.includes(timelyPeer.marketContext.snapshotHash), true);
});

test('all own lookback history used by HMA and volume features remains auditable', () => {
  const records = technicalFixture();
  const base = buildPhase3Candidates(records)[0];
  const changed = buildPhase3Candidates(records.map((record) => {
    if (record.sourceHash !== 'market-1') return record;
    return {
      ...record,
      sourceHash: 'market-1-revised',
      payload: { ...record.payload, close: record.payload.close * 1.08 },
    };
  })).find((row) => row.decisionTime === base.decisionTime);

  assert.notDeepEqual(changed.features, base.features);
  assert.equal(changed.technicalEvidenceHashes.includes('market-1-revised'), true);
  assert.equal(changed.technicalEvidenceHashes.includes('market-1'), false);
  assert.ok(base.technicalEvidenceHashes.filter((hash) => hash.startsWith('foreign-')).length >= 20);
});

test('candidate audit hashes exclude own market rows outside the maximum technical lookback', () => {
  const records = technicalFixture();
  const base = buildPhase3Candidates(records).at(-1);
  const changed = buildPhase3Candidates(records.map((record) => record.sourceHash === 'market-1'
    ? { ...record, sourceHash: 'market-1-revised' }
    : record)).at(-1);

  assert.deepEqual(changed, base);
  assert.equal(base.technicalEvidenceHashes.includes('market-1'), false);
});

test('market changes after a frozen decision do not affect that earlier observation', () => {
  const records = technicalFixture();
  const base = buildPhase3Candidates(records)[0];
  const changedRecords = records.map((record) => {
    if (record.source !== 'finmind:market' || record.payload.date <= base.decisionDate) return record;
    return {
      ...record,
      payload: {
        ...record.payload,
        open: record.payload.open + 7,
        max: record.payload.max + 9,
        min: record.payload.min + 5,
        close: record.payload.close + 8,
      },
    };
  });
  const changed = buildPhase3Candidates(changedRecords)
    .find((row) => row.ticker === base.ticker && row.decisionTime === base.decisionTime);
  assert.deepEqual(changed, base);
});

test('candidate generation fails closed on malformed market or institutional dates', () => {
  for (const [sourceHash, expected] of [
    ['market-23', /market record date must be exact valid YYYY-MM-DD/],
    ['foreign-23', /institutional record date must be exact valid YYYY-MM-DD/],
  ]) {
    const changed = technicalFixture().map((record) => record.sourceHash === sourceHash
      ? { ...record, payload: { ...record.payload, date: '2025-02-30' } }
      : record);
    assert.throws(() => buildPhase3Candidates(changed), expected);
  }
});

test('rebuilds a candidate artifact when the evidence manifest changes', async () => {
  const evidenceRoot = await mkdtemp(join(tmpdir(), 'phase3-candidate-binding-'));
  const first = await ensurePhase3CandidateArtifact({ evidenceRoot });
  assert.equal(first.created, true);
  await writeEvidenceRecord(evidenceRoot, {
    ticker: '2330',
    source: 'news',
    eventTime: '2026-01-02T09:00:00+08:00',
    publishedAt: '2026-01-02T09:00:00+08:00',
    availableAt: '2026-01-02T09:00:00+08:00',
    fetchedAt: '2026-01-02T10:00:00+08:00',
    payload: { title: 'audit event' },
  });
  const second = await ensurePhase3CandidateArtifact({ evidenceRoot });
  assert.equal(second.created, true);
  assert.notEqual(second.evidenceManifestHash, first.evidenceManifestHash);
});

test('candidate metadata uses the outcome-free schema version', () => {
  assert.equal(PHASE3_CANDIDATE_SCHEMA_VERSION, 5);
});
