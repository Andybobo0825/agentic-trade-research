import { UsageError } from './errors.js';

export function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      args._.push(token);
      continue;
    }
    const eq = token.indexOf('=');
    if (eq !== -1) {
      args[token.slice(2, eq)] = token.slice(eq + 1);
      continue;
    }
    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      args[key] = true;
    } else {
      args[key] = next;
      i += 1;
    }
  }
  return args;
}

export function requireArg(args, name) {
  const value = args[name];
  if (value === undefined || value === true || String(value).trim() === '') {
    throw new UsageError(`Missing required argument --${name}`);
  }
  return String(value).trim();
}

export function optionalInt(args, name, fallback) {
  if (args[name] === undefined || args[name] === true) return fallback;
  const value = Number.parseInt(String(args[name]), 10);
  if (!Number.isFinite(value) || value <= 0) {
    throw new UsageError(`--${name} must be a positive integer`);
  }
  return value;
}
