import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

export function tradeRuntimeStatePath(cwd = process.cwd(), env = process.env) {
  return resolve(cwd, env?.TRADE_LINE_RUNTIME_STATE || '.omx/trade-line-runtime.json');
}

export function readTradeRuntimeState(path = tradeRuntimeStatePath()) {
  if (!path || !existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
}

export function writeTradeRuntimeState(path = tradeRuntimeStatePath(), state = {}) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(state, null, 2)}\n`);
  return path;
}

export function removeTradeRuntimeState(path = tradeRuntimeStatePath()) {
  rmSync(path, { force: true });
}
