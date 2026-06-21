#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { loadDotEnv } from './dotenv.js';
import { LineApi, parseIdList, readAuthorizedUserIdsFile } from './line-bridge.js';
import { findLineBridgePids } from './line-bridge-auto.js';
import { readTradeRuntimeState, removeTradeRuntimeState, tradeRuntimeStatePath } from './trade-runtime.js';
import { expandHome, findCloudflaredPids } from './tradstart.js';

export const SHUTDOWN_MESSAGE = '服務關閉';

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

async function commandOk(command, args) {
  try {
    await run(command, args);
    return true;
  } catch {
    return false;
  }
}

export function filterKillablePaneIds(paneIds = [], currentPane = process.env.TMUX_PANE) {
  return [...new Set(paneIds)]
    .filter((paneId) => typeof paneId === 'string' && paneId.startsWith('%'))
    .filter((paneId) => paneId !== currentPane);
}

export function resolveManagedAgentSessionName(agent = {}, env = process.env) {
  return agent.sessionName || env.TRADE_LINE_AGENT_SESSION || 'trade-line-codex';
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

async function tmuxTargetExists(target) {
  if (!target) return false;
  return commandOk('tmux', ['display-message', '-p', '-t', target, '#{pane_id}']);
}

async function killTmuxPanes(paneIds) {
  const killed = [];
  for (const paneId of filterKillablePaneIds(paneIds)) {
    if (!(await tmuxTargetExists(paneId))) continue;
    await run('tmux', ['kill-pane', '-t', paneId]).catch(() => undefined);
    killed.push(paneId);
  }
  return killed;
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

export async function notifyLineShutdown(env = process.env, fetchImpl = globalThis.fetch) {
  const channelAccessToken = env.LINE_CHANNEL_ACCESS_TOKEN;
  const authorizedUserIdsFile = env.LINE_BRIDGE_AUTHORIZED_USER_IDS_FILE || env.LINE_AUTHORIZED_USER_IDS_FILE || '.omx/line-bridge/authorized-users.json';
  const allowedUserIds = new Set([
    ...parseIdList(env.LINE_ALLOWED_USER_IDS),
    ...readAuthorizedUserIdsFile(authorizedUserIdsFile),
  ]);
  if (!channelAccessToken) return { skipped: true, reason: 'LINE_CHANNEL_ACCESS_TOKEN empty' };
  if (allowedUserIds.size === 0) return { skipped: true, reason: 'authorized LINE user whitelist empty' };

  const api = new LineApi(channelAccessToken, fetchImpl);
  const sent = [];
  for (const userId of allowedUserIds) {
    await api.push(userId, SHUTDOWN_MESSAGE);
    sent.push(userId);
  }
  return { skipped: false, sent };
}

async function stopLineBridge(cwd, port) {
  const health = await fetchLineBridgeHealth(port);
  const ps = await run('ps', ['-axo', 'pid=,command=']);
  const pids = [...new Set([
    ...findLineBridgePids(ps.stdout, cwd),
    ...(health?.service === 'line-bridge' ? await findPortListenerPids(port) : []),
  ])];
  const killed = await killPids(pids);
  return { status: killed.length ? 'stopped' : 'not-running', pids: killed, port, wasHealthy: health?.service === 'line-bridge' };
}


async function stopAgentSession(agent = {}) {
  const sessionName = resolveManagedAgentSessionName(agent);
  let panes = [];
  if (sessionName && await commandOk('tmux', ['has-session', '-t', sessionName])) {
    panes = await listTmuxPaneIds(sessionName);
    if (panes.includes(process.env.TMUX_PANE)) {
      const killed = await killTmuxPanes(panes);
      return { status: killed.length ? 'partially-stopped-current-session' : 'current-session-kept', sessionName, panes: killed };
    }
    await run('tmux', ['kill-session', '-t', sessionName]).catch(() => undefined);
    return { status: 'stopped', sessionName, panes };
  }
  panes = await killTmuxPanes(agent.paneIds || []);
  return { status: panes.length ? 'stopped' : 'not-running', sessionName, panes };
}

async function stopCloudflared({ configPath, tunnelName, sessionName, ownedPaneIds = [] }) {
  const expandedConfigPath = expandHome(configPath);
  const ps = await run('ps', ['-axo', 'pid=,command=']);
  const pids = findCloudflaredPids(ps.stdout, expandedConfigPath, tunnelName);
  const killed = await killPids(pids);
  let session = 'not-found';
  let panes = [];
  if (await commandOk('tmux', ['has-session', '-t', sessionName])) {
    panes = await listTmuxPaneIds(sessionName);
    await run('tmux', ['kill-session', '-t', sessionName]).catch(() => undefined);
    session = 'killed';
  } else {
    panes = await killTmuxPanes(ownedPaneIds);
  }
  return { status: killed.length || session === 'killed' || panes.length ? 'stopped' : 'not-running', pids: killed, sessionName, session, panes };
}

function summaryText(result) {
  return [
    'tradestop 關閉完成。',
    '',
    `LINE bridge：${result.lineBridge.status}${result.lineBridge.pids.length ? ` (${result.lineBridge.pids.join(', ')})` : ''}`,
    `Codex tmux session：${result.agent.sessionName || 'none'} ${result.agent.status}${result.agent.panes.length ? ` (${result.agent.panes.join(', ')})` : ''}`,
    `Cloudflare tunnel：${result.cloudflared.status}${result.cloudflared.pids.length ? ` (${result.cloudflared.pids.join(', ')})` : ''}`,
    `Tunnel tmux session：${result.cloudflared.sessionName} ${result.cloudflared.session}`,
    `Tunnel tmux panes：${result.cloudflared.panes.length ? `cleared (${result.cloudflared.panes.join(', ')})` : 'none'}`,
  ].join('\n');
}

export function parseTradstopArgs(argv) {
  return {
    notify: argv.includes('--notify') && !argv.includes('--no-notify'),
  };
}

export async function tradstop({ cwd = process.cwd(), argv = process.argv.slice(2) } = {}) {
  loadDotEnv();
  const args = parseTradstopArgs(argv);
  const runtimeStatePath = tradeRuntimeStatePath(cwd);
  const runtimeState = readTradeRuntimeState(runtimeStatePath);
  const port = positiveInt(process.env.LINE_BRIDGE_PORT, 8787);
  const notification = args.notify ? await notifyLineShutdown().catch((error) => ({ skipped: true, reason: error.message })) : { skipped: true, reason: 'notify disabled; pass --notify to broadcast shutdown' };
  const lineBridge = await stopLineBridge(cwd, port);
  const cloudflared = await stopCloudflared({
    configPath: process.env.TRADE_LINE_TUNNEL_CONFIG || '~/.cloudflared/trade-line.yml',
    tunnelName: process.env.TRADE_LINE_TUNNEL_NAME || 'trade-line',
    sessionName: process.env.TRADE_LINE_TUNNEL_SESSION || runtimeState?.cloudflared?.sessionName || 'trade-line-cloudflared',
    ownedPaneIds: runtimeState?.cloudflared?.paneIds || [],
  });
  const agent = await stopAgentSession(runtimeState?.agent || {});
  removeTradeRuntimeState(runtimeStatePath);
  const result = { lineBridge, agent, cloudflared };
  return { ...result, notification, runtimeStatePath, text: summaryText(result) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  tradstop().then((result) => {
    console.log(result.text);
  }).catch((error) => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  });
}
