import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

export const MEMORY_FILES = {
  hot: 'hot.md',
  warm: 'warm.md',
  archive: 'archive.md',
  obsolete: 'obsolete.md',
};

export const ALLOWED_MEMORY_CATEGORIES = new Set([
  'decision',
  'verified-fix',
  'failure-case',
  'milestone',
]);

const LAYER_TITLES = {
  hot: 'Dynamic Memory — Hot',
  warm: 'Dynamic Memory — Warm',
  archive: 'Dynamic Memory — Archive',
  obsolete: 'Dynamic Memory — Obsolete',
};

const FORBIDDEN_PATTERNS = [
  { name: 'raw-api-key', pattern: /\b[A-Z0-9_]*(?:API|TOKEN|SECRET|KEY|PASSWD|PASSWORD)[A-Z0-9_]*\s*=\s*\S+/i },
  { name: 'line-user-id', pattern: /\bU[0-9a-f]{32}\b/i },
  { name: 'env-or-certificate', pattern: /(?:^|\s)(?:\.env|Sinopac\.pfx|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|\.pfx|\.pem)(?:\s|$)/i },
  { name: 'raw-log', pattern: /\b(?:完整\s*)?(?:raw\s*)?(?:logs?|turns-\d{4}-\d{2}-\d{2}\.jsonl|stack trace)\b/i },
  { name: 'unverified-intraday-guess', pattern: /未驗證的盤中猜測|看起來會|可能會噴|穩賺|保證|一定漲/i },
];

export function readMemoryEntriesFromJson(value) {
  if (!value) return [];
  const parsed = typeof value === 'string' ? JSON.parse(value) : value;
  return Array.isArray(parsed) ? parsed : [parsed];
}

export function loadMemoryEntryFile(path) {
  if (!path) return [];
  return readMemoryEntriesFromJson(readFileSync(path, 'utf8'));
}

export function normalizeMemoryEntry(entry = {}) {
  const date = String(entry.date || '').slice(0, 10);
  const category = String(entry.category || '').trim();
  const text = String(entry.text || '').replace(/\s+/g, ' ').trim();
  const source = entry.source === undefined ? '' : String(entry.source).replace(/\s+/g, ' ').trim();
  const reason = entry.reason === undefined ? '' : String(entry.reason).replace(/\s+/g, ' ').trim();
  const obsolete = entry.obsolete === true || entry.obsolete === 'true';
  return { date, category, text, source, reason, obsolete };
}

export function validateMemoryEntry(entry = {}) {
  const normalized = normalizeMemoryEntry(entry);
  const reasons = [];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(normalized.date)) reasons.push('missing-or-invalid-date');
  if (!ALLOWED_MEMORY_CATEGORIES.has(normalized.category)) reasons.push('unsupported-category');
  if (!normalized.text) reasons.push('missing-text');

  const combined = [normalized.text, normalized.source, normalized.reason].filter(Boolean).join(' ');
  for (const forbidden of FORBIDDEN_PATTERNS) {
    if (forbidden.pattern.test(combined)) reasons.push(`forbidden-${forbidden.name}`);
  }
  return { ok: reasons.length === 0, reasons, entry: normalized };
}

export function syncDynamicMemory(options = {}) {
  const memoryDir = resolve(options.memoryDir || '.omx/memory');
  const now = options.now ? dateOnly(String(options.now).slice(0, 10)) : dateOnly(new Date().toISOString().slice(0, 10));
  const maxHotEntries = Number.isFinite(Number(options.maxHotEntries)) ? Math.max(1, Number(options.maxHotEntries)) : 20;
  mkdirSync(memoryDir, { recursive: true });

  const existing = loadExistingEntries(memoryDir);
  const validatedExisting = existing.map(validateMemoryEntry);
  const safeExisting = validatedExisting.filter((item) => item.ok).map((item) => item.entry);
  const validations = (options.entries || []).map(validateMemoryEntry);
  const accepted = validations.filter((item) => item.ok).map((item) => item.entry);
  const rejectedEntries = validations.filter((item) => !item.ok);
  const merged = dedupeEntries([...safeExisting, ...accepted]);

  const obsolete = [];
  const dated = [];
  for (const entry of merged) {
    if (entry.obsolete) obsolete.push(entry);
    else dated.push(entry);
  }

  const sorted = sortEntriesNewestFirst(dated);
  const candidateHot = [];
  const warm = [];
  const archive = [];
  for (const entry of sorted) {
    const age = daysBetween(entry.date, now);
    if (age <= 7) candidateHot.push(entry);
    else if (age <= 30) warm.push(entry);
    else archive.push(entry);
  }
  const hot = candidateHot.slice(0, maxHotEntries);
  warm.push(...candidateHot.slice(maxHotEntries));

  const layers = {
    hot: sortEntriesNewestFirst(hot),
    warm: sortEntriesNewestFirst(warm),
    archive: sortEntriesNewestFirst(archive),
    obsolete: sortEntriesNewestFirst(obsolete),
  };

  for (const [layer, entries] of Object.entries(layers)) {
    writeFileSync(join(memoryDir, MEMORY_FILES[layer]), renderMemoryLayer(layer, entries), 'utf8');
  }

  return {
    memoryDir,
    accepted: accepted.length,
    rejected: rejectedEntries.length,
    rejectedEntries: rejectedEntries.map((item) => ({ reasons: item.reasons, entry: item.entry })),
    layers: Object.fromEntries(Object.entries(layers).map(([layer, entries]) => [layer, entries.length])),
    files: Object.fromEntries(Object.entries(MEMORY_FILES).map(([layer, file]) => [layer, join(memoryDir, file)])),
  };
}

export function renderMemorySyncMarkdown(result) {
  return [
    '# Dynamic memory sync',
    '',
    `Memory dir: ${result.memoryDir}`,
    `Accepted: ${result.accepted}`,
    `Rejected: ${result.rejected}`,
    '',
    `Hot: ${result.layers?.hot ?? 0}`,
    `Warm: ${result.layers?.warm ?? 0}`,
    `Archive: ${result.layers?.archive ?? 0}`,
    `Obsolete: ${result.layers?.obsolete ?? 0}`,
    '',
    'Files:',
    `- hot: ${result.files?.hot || ''}`,
    `- warm: ${result.files?.warm || ''}`,
    `- archive: ${result.files?.archive || ''}`,
    `- obsolete: ${result.files?.obsolete || ''}`,
  ].join('\n');
}

function loadExistingEntries(memoryDir) {
  const entries = [];
  for (const file of Object.values(MEMORY_FILES)) {
    const path = join(memoryDir, file);
    if (!existsSync(path)) continue;
    entries.push(...parseMemoryMarkdown(readFileSync(path, 'utf8')));
  }
  return entries;
}

function parseMemoryMarkdown(text) {
  const entries = [];
  for (const line of String(text || '').split(/\r?\n/)) {
    const match = line.match(/^- (\d{4}-\d{2}-\d{2}) \| ([^|]+) \| (.*)$/);
    if (!match) continue;
    const [, date, categoryRaw, restRaw] = match;
    let rest = restRaw.trim();
    let source = '';
    let reason = '';
    let obsolete = false;
    const metaMatch = rest.match(/\s+\(([^()]*)\)$/);
    if (metaMatch) {
      const meta = metaMatch[1];
      const parts = meta.split(';').map((value) => value.trim()).filter(Boolean);
      const parsedMeta = [];
      let validMeta = parts.length > 0;
      for (const part of parts) {
        const [keyRaw, ...valueParts] = part.split(':');
        const key = keyRaw.trim();
        const value = valueParts.join(':').trim();
        const knownKey = key === 'source' || key === 'reason' || key === 'obsolete';
        if (!knownKey || !value) {
          validMeta = false;
          break;
        }
        parsedMeta.push([key, value]);
      }
      if (validMeta) {
        rest = rest.slice(0, metaMatch.index).trim();
        for (const [key, value] of parsedMeta) {
          if (key === 'source') source = value;
          if (key === 'reason') reason = value;
          if (key === 'obsolete') obsolete = value === 'true';
        }
      }
    }
    entries.push(normalizeMemoryEntry({ date, category: categoryRaw.trim(), text: rest, source, reason, obsolete }));
  }
  return entries;
}

function renderMemoryLayer(layer, entries) {
  const lines = [
    `# ${LAYER_TITLES[layer]}`,
    '',
    '<!-- generated by memory-sync; do not store secrets, raw logs, LINE userIds, or unverified trading guesses here -->',
    '',
  ];
  if (!entries.length) {
    lines.push('_No entries._', '');
    return lines.join('\n');
  }
  for (const entry of entries) {
    const meta = [];
    if (entry.source) meta.push(`source: ${entry.source}`);
    if (entry.reason) meta.push(`reason: ${entry.reason}`);
    if (entry.obsolete) meta.push('obsolete: true');
    lines.push(`- ${entry.date} | ${entry.category} | ${entry.text}${meta.length ? ` (${meta.join('; ')})` : ''}`);
  }
  lines.push('');
  return lines.join('\n');
}

function dedupeEntries(entries) {
  const seen = new Set();
  const result = [];
  for (const entry of entries.map(normalizeMemoryEntry)) {
    const key = JSON.stringify([entry.date, entry.category, entry.text, entry.source, entry.reason, entry.obsolete]);
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(entry);
  }
  return result;
}

function sortEntriesNewestFirst(entries) {
  return [...entries].sort((a, b) => {
    const dateOrder = b.date.localeCompare(a.date);
    if (dateOrder !== 0) return dateOrder;
    return b.text.localeCompare(a.text);
  });
}

function dateOnly(value) {
  const [year, month, day] = String(value).slice(0, 10).split('-').map(Number);
  return Date.UTC(year, month - 1, day);
}

function daysBetween(entryDate, nowDateUtc) {
  const diff = (nowDateUtc - dateOnly(entryDate)) / 86_400_000;
  return Math.max(0, Math.floor(diff));
}
