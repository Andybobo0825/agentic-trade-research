#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { openSync } from 'node:fs';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { loadDotEnv } from './dotenv.js';
import { cleanupResponseFiles, LineApi, readLineBridgeConfig, STARTUP_MESSAGE } from './line-bridge.js';
import { chooseTmuxTarget, findLineBridgePids, paneExists, parseTmuxPaneList } from './line-bridge-auto.js';
import { tradeRuntimeStatePath, writeTradeRuntimeState } from './trade-runtime.js';

export function expandHome(path) {
  if (!path) return path;
  return path === '~' ? homedir() : path.startsWith('~/') ? `${homedir()}${path.slice(1)}` : path;
}

export function shQuote(value) {
  return `'${String(value).replaceAll("'", `'\\''`)}'`;
}

export function cloudflaredCommand({ cwd, configPath, tunnelName, logPath }) {
  return [
    `cd ${shQuote(cwd)}`,
    `cloudflared tunnel --config ${shQuote(configPath)} run ${shQuote(tunnelName)} 2>&1 | tee ${shQuote(logPath)}`,
  ].join(' && ');
}

export function codexAgentCommand({ cwd, command = process.env.TRADE_LINE_AGENT_COMMAND || 'codex' }) {
  return [`cd ${shQuote(cwd)}`, `exec ${command}`].join(' && ');
}

export function findCloudflaredPids(processListText, configPath, tunnelName) {
  const normalizedConfig = expandHome(configPath);
  return String(processListText || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.includes('cloudflared tunnel') && line.includes(normalizedConfig) && line.includes(`run ${tunnelName}`))
    .map((line) => line.match(/^(\d+)/)?.[1])
    .filter(Boolean);
}

export function resolveBridgeTargetEnv({ env = process.env, discoveredTarget = '' } = {}) {
  return discoveredTarget || env.TMUX_PANE || env.OMX_TARGET_PANE || env.LINE_BRIDGE_TMUX_TARGET || '';
}

function positiveInt(value, fallback) {
  if (value === undefined || value === '') return fallback;
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return parsed;
}

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { ...options, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} ${args.join(' ')} exited ${code}: ${stderr || stdout}`));
    });
  });
}


async function listTmuxPaneIds(target) {
  if (!target) return [];
  try {
    const result = await run('tmux', ['list-panes', '-t', target, '-F', '#{pane_id}']);
    return result.stdout.split(/\s+/).filter(Boolean);
  } catch {
    return [];
  }
}

async function commandOk(command, args) {
  try {
    await run(command, args);
    return true;
  } catch {
    return false;
  }
}

async function listAllTmuxPanes() {
  const panesText = await run('tmux', ['list-panes', '-a', '-F', '#{pane_id}	#{pane_current_path}	#{pane_current_command}	#{pane_active}	#{session_name}	#{window_index}	#{pane_index}']).catch(() => ({ stdout: '' }));
  return parseTmuxPaneList(panesText.stdout);
}

async function ensureCodexAgentSession(cwd) {
  const sessionName = process.env.TRADE_LINE_AGENT_SESSION || 'trade-line-codex';
  const command = codexAgentCommand({ cwd });
  const sessionExists = await commandOk('tmux', ['has-session', '-t', sessionName]);
  if (!sessionExists) {
    await run('tmux', ['new-session', '-d', '-s', sessionName, command]);
    await sleep(1200);
  }
  const paneIds = await listTmuxPaneIds(sessionName);
  const target = paneIds[0] || '';
  if (!target) throw new Error(`Could not create or find tmux pane for Codex agent session: ${sessionName}`);
  return { target, agent: { created: !sessionExists, sessionName, paneIds, command } };
}

async function chooseOrCreateTarget(cwd) {
  const panes = await listAllTmuxPanes();
  const discoveredTarget = chooseTmuxTarget(panes, cwd, process.env.TMUX_PANE);
  const envTarget = [process.env.OMX_TARGET_PANE, process.env.LINE_BRIDGE_TMUX_TARGET].find((candidate) => paneExists(panes, candidate));
  const target = discoveredTarget || envTarget || '';
  if (target) return { target, agent: { created: false, sessionName: '', paneIds: [] } };
  return ensureCodexAgentSession(cwd);
}

async function fetchLineBridgeHealth(port, fetchImpl = globalThis.fetch) {
  try {
    const res = await fetchImpl(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(1500) });
    if (!res.ok) return null;
    return await res.json().catch(() => null);
  } catch {
    return null;
  }
}

async function findPortListenerPids(port) {
  try {
    const result = await run('lsof', [`-tiTCP:${port}`, '-sTCP:LISTEN']);
    return result.stdout.split(/\s+/).filter(Boolean);
  } catch {
    return [];
  }
}

async function killPids(pids) {
  const unique = [...new Set(pids.filter(Boolean))];
  for (const pid of unique) {
    await run('kill', [pid]).catch(() => undefined);
  }
  return unique;
}

async function lineBridgeProcessPids(cwd, port, { includePortListeners = false } = {}) {
  const ps = await run('ps', ['-axo', 'pid=,command=']);
  return [...new Set([
    ...findLineBridgePids(ps.stdout, cwd),
    ...(includePortListeners ? await findPortListenerPids(port) : []),
  ])];
}

async function ensureLineBridge(cwd, config) {
  const health = await fetchLineBridgeHealth(config.port);
  if (health?.service === 'line-bridge' && health.tmuxTarget === config.tmuxTarget) {
    return { status: 'already-running', pids: await lineBridgeProcessPids(cwd, config.port, { includePortListeners: true }), target: config.tmuxTarget, health: true };
  }

  if (health?.service === 'line-bridge') {
    await killPids(await lineBridgeProcessPids(cwd, config.port, { includePortListeners: true }));
    await sleep(500);
  } else {
    const existingPids = await lineBridgeProcessPids(cwd, config.port);
    if (existingPids.length > 0) {
      await killPids(existingPids);
      await sleep(500);
    }
  }

  const logPath = process.env.TRADE_LINE_BRIDGE_LOG || '/tmp/trade-line-bridge.log';
  const out = openSync(logPath, 'a');
  const child = spawn(process.execPath, ['src/line-bridge.js'], {
    cwd,
    env: { ...process.env, LINE_BRIDGE_TMUX_TARGET: config.tmuxTarget },
    detached: true,
    stdio: ['ignore', out, out],
  });
  child.unref();
  await sleep(800);
  return { status: health?.service === 'line-bridge' ? 'restarted' : 'started', pids: [String(child.pid)], target: config.tmuxTarget, logPath };
}

async function ensureCloudflared(cwd, options) {
  const { configPath, tunnelName, sessionName, logPath } = options;
  const expandedConfigPath = expandHome(configPath);
  if (!existsSync(expandedConfigPath)) throw new Error(`Cloudflare tunnel config not found: ${expandedConfigPath}`);

  const ps = await run('ps', ['-axo', 'pid=,command=']);
  const existingPids = findCloudflaredPids(ps.stdout, expandedConfigPath, tunnelName);
  if (existingPids.length > 0) return { status: 'already-running', pids: existingPids, sessionName, paneIds: await listTmuxPaneIds(sessionName) };

  const sessionExists = await commandOk('tmux', ['has-session', '-t', sessionName]);
  if (sessionExists) await run('tmux', ['kill-session', '-t', sessionName]);

  const command = cloudflaredCommand({ cwd, configPath: expandedConfigPath, tunnelName, logPath });
  await run('tmux', ['new-session', '-d', '-s', sessionName, command]);
  await sleep(2500);

  const after = await run('ps', ['-axo', 'pid=,command=']);
  return { status: 'started', pids: findCloudflaredPids(after.stdout, expandedConfigPath, tunnelName), sessionName, paneIds: await listTmuxPaneIds(sessionName) };
}

export function summaryText() {
  return STARTUP_MESSAGE;
}

async function notifyLine(config, text) {
  if (!config.allowedUserIds || config.allowedUserIds.size === 0) return { skipped: true, reason: 'authorized LINE user whitelist empty' };
  const api = new LineApi(config.channelAccessToken);
  const sent = [];
  for (const userId of config.allowedUserIds) {
    await api.push(userId, text);
    sent.push(userId);
  }
  return { skipped: false, sent };
}

function parseArgs(argv) {
  return {
    notify: !argv.includes('--no-notify'),
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function tradstart({ cwd = process.cwd(), argv = process.argv.slice(2) } = {}) {
  loadDotEnv();
  const args = parseArgs(argv);
  const { target, agent } = await chooseOrCreateTarget(cwd);
  process.env.LINE_BRIDGE_TMUX_TARGET = target;
  const config = readLineBridgeConfig();
  const cleanup = cleanupResponseFiles(config);
  const lineBridge = await ensureLineBridge(cwd, config);
  const cloudflared = await ensureCloudflared(cwd, {
    configPath: process.env.TRADE_LINE_TUNNEL_CONFIG || '~/.cloudflared/trade-line.yml',
    tunnelName: process.env.TRADE_LINE_TUNNEL_NAME || 'trade-line',
    sessionName: process.env.TRADE_LINE_TUNNEL_SESSION || 'trade-line-cloudflared',
    logPath: process.env.TRADE_LINE_TUNNEL_LOG || '/tmp/trade-line-cloudflared.log',
  });

  const port = positiveInt(process.env.LINE_BRIDGE_PORT, 8787);
  const result = { cleanup, lineBridge, agent, cloudflared };
  const runtimeStatePath = tradeRuntimeStatePath(cwd);
  writeTradeRuntimeState(runtimeStatePath, {
    version: 1,
    updatedAt: new Date().toISOString(),
    cwd,
    lineBridge: { pids: lineBridge.pids || [], target: lineBridge.target, port },
    agent: { created: agent.created, sessionName: agent.sessionName, paneIds: agent.paneIds || [] },
    cloudflared: { pids: cloudflared.pids || [], sessionName: cloudflared.sessionName, paneIds: cloudflared.paneIds || [] },
  });
  const text = summaryText(result);
  const notification = args.notify ? await notifyLine(config, text).catch((error) => ({ skipped: true, reason: error.message })) : { skipped: true, reason: '--no-notify' };
  return { ...result, notification, runtimeStatePath, text };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  tradstart().then((result) => {
    console.log(result.text);
  }).catch((error) => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  });
}
