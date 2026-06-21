#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { loadDotEnv } from './dotenv.js';

const LOCAL_SHIOAJI_CLI = '.omx/shioaji-venv/bin/shioaji';

export function chooseShioajiCli(env = process.env, exists = existsSync) {
  if (env.SHIOAJI_CLI) return env.SHIOAJI_CLI;
  if (exists(LOCAL_SHIOAJI_CLI)) return LOCAL_SHIOAJI_CLI;
  return 'shioaji';
}

export function shioajiServerEnv(env = process.env) {
  const next = { ...env };
  if (!next.SJ_PRODUCTION && next.SHIOAJI_SIMULATION !== undefined) {
    const simulation = !['0', 'false', 'no'].includes(String(next.SHIOAJI_SIMULATION).toLowerCase());
    next.SJ_PRODUCTION = simulation ? 'false' : 'true';
  }
  return next;
}

export function shioajiServerArgs(argv = process.argv.slice(2)) {
  const args = ['server', 'start'];
  if (!argv.includes('--open') && !argv.includes('--no-open')) args.push('--no-open');
  return [...args, ...argv.filter((arg) => arg !== '--open')];
}

export function runShioajiServer(argv = process.argv.slice(2), env = process.env) {
  loadDotEnv();
  const child = spawn(chooseShioajiCli(process.env), shioajiServerArgs(argv), {
    stdio: 'inherit',
    env: shioajiServerEnv(process.env),
  });
  child.on('exit', (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exitCode = code || 0;
  });
  return child;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  runShioajiServer();
}
