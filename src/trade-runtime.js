import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

export function tradeRuntimeStatePath(cwd = process.cwd(), env = process.env) {
  return resolve(cwd, env.TRADE_LINE_RUNTIME_STATE || '.omx/trade-line-runtime.json');
}

export function readTradeRuntimeState(path) {
  if (!path || !existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch {
    return null;
  }
}

export function writeTradeRuntimeState(path, state) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(state, null, 2)}\n`);
}

export function removeTradeRuntimeState(path) {
  if (path) rmSync(path, { force: true });
}
