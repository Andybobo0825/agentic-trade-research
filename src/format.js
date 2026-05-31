export function compactNumber(value) {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000_000) return `${(n / 1_000_000_000_000).toFixed(2)}T`;
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(2)}K`;
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

export function toMarkdownTable(rows, columns) {
  if (!rows.length) return '_No rows returned._';
  const header = `| ${columns.map((c) => c.label).join(' | ')} |`;
  const sep = `| ${columns.map(() => '---').join(' | ')} |`;
  const body = rows.map((row) => `| ${columns.map((c) => sanitizeCell(c.value(row))).join(' | ')} |`);
  return [header, sep, ...body].join('\n');
}

function sanitizeCell(value) {
  return String(value ?? '—').replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

export function output(data, { format = 'json' } = {}) {
  if (format === 'json') return `${JSON.stringify(data, null, 2)}\n`;
  if (format === 'text') return `${String(data)}\n`;
  return `${data}\n`;
}

export function normalizeFieldList(fields) {
  if (!fields) return [];
  if (Array.isArray(fields)) return fields.map(String).map((s) => s.trim()).filter(Boolean);
  return String(fields).split(',').map((s) => s.trim()).filter(Boolean);
}

export function compactJson(data) {
  return JSON.stringify(data);
}

export function shapeForTokenBudget(data, { fields, maxRows } = {}) {
  const selectedFields = normalizeFieldList(fields);
  const rowLimit = Number.isFinite(Number(maxRows)) && Number(maxRows) > 0 ? Math.floor(Number(maxRows)) : undefined;
  return shapeValue(data, selectedFields, rowLimit);
}

function shapeValue(value, fields, maxRows) {
  if (Array.isArray(value)) {
    const rows = maxRows ? value.slice(0, maxRows) : value;
    return rows.map((row) => shapeRow(row, fields, maxRows));
  }
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, shapeValue(child, fields, maxRows)]));
}

function shapeRow(row, fields, maxRows) {
  if (!row || typeof row !== 'object' || Array.isArray(row)) return shapeValue(row, fields, maxRows);
  if (!fields.length) return shapeValue(row, fields, maxRows);
  const selected = {};
  for (const field of fields) {
    if (row[field] !== undefined) selected[field] = row[field];
  }
  return selected;
}
