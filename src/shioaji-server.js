#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
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

export function parseShioajiWrapperArgs(argv = process.argv.slice(2)) {
  const passthrough = [];
  let daemon = false;
  let pidFile = '';
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--daemon') {
      daemon = true;
      continue;
    }
    if (arg === '--pid-file') {
      pidFile = argv[i + 1] || '';
      i += 1;
      continue;
    }
    if (arg.startsWith('--pid-file=')) {
      pidFile = arg.slice('--pid-file='.length);
      continue;
    }
    passthrough.push(arg);
  }
  return { daemon, pidFile, passthrough };
}

export function shioajiServerArgs(argv = process.argv.slice(2)) {
  const { passthrough } = parseShioajiWrapperArgs(argv);
  const args = ['server', 'start'];
  if (!passthrough.includes('--open') && !passthrough.includes('--no-open')) args.push('--no-open');
  return [...args, ...passthrough.filter((arg) => arg !== '--open')];
}

export function shioajiServerSpawnOptions({ daemon = false, env = process.env } = {}) {
  return {
    stdio: 'inherit',
    env: shioajiServerEnv(env),
    detached: Boolean(daemon),
  };
}

export function ensurePidFileDirectory(pidFile) {
  if (!pidFile) return null;
  mkdirSync(dirname(pidFile), { recursive: true });
  return pidFile;
}

export function writeShioajiPidFile(pidFile, pid) {
  if (!pidFile || !pid) return false;
  ensurePidFileDirectory(pidFile);
  writeFileSync(pidFile, `${pid}\n`);
  return true;
}

export function runShioajiServer(argv = process.argv.slice(2), env = process.env) {
  loadDotEnv();
  const wrapper = parseShioajiWrapperArgs(argv);
  ensurePidFileDirectory(wrapper.pidFile);
  const child = spawn(
    chooseShioajiCli(process.env),
    shioajiServerArgs(argv),
    shioajiServerSpawnOptions({ daemon: wrapper.daemon, env: process.env }),
  );
  if (wrapper.pidFile && child.pid) {
    writeShioajiPidFile(wrapper.pidFile, child.pid);
  } else if (wrapper.pidFile) {
    child.once('error', () => rmSync(wrapper.pidFile, { force: true }));
  }
  if (wrapper.daemon) {
    child.unref();
    return child;
  }
  child.on('exit', (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exitCode = code || 0;
  });
  return child;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  runShioajiServer();
}
