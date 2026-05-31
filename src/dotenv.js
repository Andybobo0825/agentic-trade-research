import { existsSync, readFileSync } from 'node:fs';

export function loadDotEnv(path = '.env', env = process.env) {
  if (!existsSync(path)) return false;
  const text = readFileSync(path, 'utf8');
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const idx = line.indexOf('=');
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    if (!key || env[key] !== undefined) continue;
    env[key] = stripQuotes(line.slice(idx + 1).trim());
  }
  return true;
}

function stripQuotes(value) {
  if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
    return value.slice(1, -1);
  }
  return value;
}
