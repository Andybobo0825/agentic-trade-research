import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { toMarkdownTable } from './format.js';

const REGIMES = ['spike', 'tight_channel', 'normal_channel', 'trading_range', 'insufficient_data'];
const EXPERIENCE_ROOT = join('.omx', 'experience');

export function recordExperience(rootDir, { regime, date, ticker, judgment, note } = {}) {
  const label = requireRegime(regime);
  const day = String(date || '').slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) throw new Error('experience entry requires date as YYYY-MM-DD');
  const symbol = String(ticker || '').trim();
  if (!symbol) throw new Error('experience entry requires a ticker');

  const relative = join(EXPERIENCE_ROOT, label, `${day}-${symbol}.json`);
  const absolute = join(rootDir, relative);
  mkdirSync(join(rootDir, EXPERIENCE_ROOT, label), { recursive: true });
  const entry = { regime: label, date: day, ticker: symbol, judgment: judgment ?? null, note: note ?? null, recordedAt: new Date().toISOString() };
  writeFileSync(absolute, `${JSON.stringify(entry, null, 2)}\n`);
  return { path: relative, entry };
}

export function recallExperience(rootDir, { regime, limit = 5 } = {}) {
  const label = requireRegime(regime);
  const dir = join(rootDir, EXPERIENCE_ROOT, label);
  if (!existsSync(dir)) return [];
  const files = readdirSync(dir)
    .filter((name) => name.endsWith('.json'))
    .sort((a, b) => b.localeCompare(a))
    .slice(0, Math.max(1, Number(limit) || 5));
  const entries = [];
  for (const name of files) {
    try {
      entries.push(JSON.parse(readFileSync(join(dir, name), 'utf8')));
    } catch {
      // A corrupt file is skipped rather than blocking the whole recall.
    }
  }
  return entries;
}

export function renderExperienceMarkdown(result) {
  const entries = Array.isArray(result?.entries) ? result.entries : [];
  const lines = [
    `# Experience library: ${result?.regime || '—'}`,
    '',
    `- Entries: ${entries.length}`,
    '- Boundary: 歷史案例僅供參考,不構成當下訊號。',
    '',
    toMarkdownTable(entries, [
      { label: 'Date', value: (r) => r.date },
      { label: 'Ticker', value: (r) => r.ticker },
      { label: 'Direction', value: (r) => r.judgment?.diagnosis?.direction || '—' },
      { label: 'Stance', value: (r) => r.judgment?.decision?.stance || '—' },
      { label: 'Note', value: (r) => r.note || '—' },
    ]),
  ];
  return `${lines.join('\n')}\n`;
}

function requireRegime(regime) {
  const label = String(regime || '').trim();
  if (!REGIMES.includes(label)) {
    throw new Error(`experience regime must be one of ${REGIMES.join(', ')}, got ${JSON.stringify(regime)}`);
  }
  return label;
}
