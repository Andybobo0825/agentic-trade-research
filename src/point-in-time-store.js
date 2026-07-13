import { createHash, randomUUID } from 'node:crypto';
import { access, link, mkdir, readFile, readdir, unlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw new TypeError('evidence values must be JSON serializable');
  return encoded;
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function requiredInstant(value, name) {
  if (value === null || value === undefined || value === '') {
    throw new TypeError(`${name} is required`);
  }
  const instant = String(value);
  if (!Number.isFinite(Date.parse(instant))) throw new TypeError(`${name} must be a valid timestamp`);
  return instant;
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

export function normalizeEvidenceRecord(input = {}) {
  const availableAt = requiredInstant(input.availableAt, 'availableAt');
  const publishedAt = requiredInstant(input.publishedAt, 'publishedAt');
  const fetchedAt = requiredInstant(input.fetchedAt ?? new Date().toISOString(), 'fetchedAt');
  if (Date.parse(availableAt) < Date.parse(publishedAt)) {
    throw new Error('availableAt must not precede publishedAt');
  }
  if (Date.parse(fetchedAt) < Date.parse(availableAt)) {
    throw new Error('fetchedAt must not precede availableAt');
  }
  if (!String(input.source || '').trim()) throw new TypeError('source is required');
  stableJson(input.payload);

  return deepFreeze({
    schemaVersion: 1,
    ticker: input.ticker === null || input.ticker === undefined ? null : String(input.ticker),
    peerGroups: [...new Set((input.peerGroups || []).map(String).filter(Boolean))].sort(),
    source: String(input.source).trim(),
    sourceUrl: input.sourceUrl ? String(input.sourceUrl) : null,
    eventTime: requiredInstant(input.eventTime, 'eventTime'),
    publishedAt,
    availableAt,
    fetchedAt,
    dataQuality: input.dataQuality || 'accepted',
    payload: input.payload,
    sourceHash: sha256(stableJson(input.payload)),
  });
}

export function evidenceId(record) {
  return sha256(stableJson(normalizeEvidenceRecord(record)));
}

export function evidenceAsOf(records = [], decisionTime) {
  const cutoff = Date.parse(requiredInstant(decisionTime, 'decisionTime'));
  return records
    .map(normalizeEvidenceRecord)
    .filter((record) => Date.parse(record.availableAt) <= cutoff)
    .sort((left, right) =>
      left.availableAt.localeCompare(right.availableAt)
      || evidenceId(left).localeCompare(evidenceId(right)));
}

export async function writeEvidenceRecord(root, input) {
  const record = normalizeEvidenceRecord(input);
  const id = evidenceId(record);
  const directory = join(root, 'records');
  const file = join(directory, `${id}.json`);
  const temporary = join(directory, `.${id}.${process.pid}.${randomUUID()}.tmp`);
  await mkdir(directory, { recursive: true });
  try {
    await access(file);
    return { id, file, created: false };
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  await writeFile(temporary, `${JSON.stringify(record, null, 2)}\n`, { flag: 'wx' });
  try {
    await link(temporary, file);
    return { id, file, created: true };
  } catch (error) {
    if (error?.code !== 'EEXIST') throw error;
    return { id, file, created: false };
  } finally {
    await unlink(temporary).catch(() => {});
  }
}

export async function readEvidenceManifest(root, { batchSize = 64 } = {}) {
  if (!Number.isInteger(batchSize) || batchSize < 1) {
    throw new TypeError('batchSize must be a positive integer');
  }
  const directory = join(root, 'records');
  let files;
  try {
    files = await readdir(directory);
  } catch (error) {
    if (error?.code === 'ENOENT') return [];
    throw error;
  }
  const evidenceFiles = files.filter((file) => /^[a-f0-9]{64}\.json$/.test(file));
  const rows = [];
  for (let offset = 0; offset < evidenceFiles.length; offset += batchSize) {
    const batch = await Promise.all(evidenceFiles.slice(offset, offset + batchSize).map(async (file) => {
      const record = normalizeEvidenceRecord(JSON.parse(await readFile(join(directory, file), 'utf8')));
      const id = evidenceId(record);
      if (`${id}.json` !== file) throw new Error(`evidence filename hash mismatch: ${file}`);
      return {
        id,
        file: join(directory, file),
        source: record.source,
        ticker: record.ticker,
        availableAt: record.availableAt,
        sourceHash: record.sourceHash,
      };
    }));
    rows.push(...batch);
  }
  return rows.sort((left, right) => left.id.localeCompare(right.id));
}
