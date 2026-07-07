#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { openSync } from 'node:fs';
import { existsSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { loadDotEnv } from './dotenv.js';
import { cleanupResponseFiles, LineApi, readLineBridgeConfig, STARTUP_MESSAGE } from './line-bridge.js';
import { chooseTmuxTarget, findLineBridgePids, lineBridgeHealthMatchesConfig, paneExists, parseTmuxPaneList } from './line-bridge-auto.js';
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

function defaultAgentCommand(env = process.env) {
  return env.TRADE_LINE_AGENT_COMMAND || 'codex --ask-for-approval never --sandbox workspace-write';
}

function agentStartupEnv(env = process.env) {
  return {
    OMX_AUTO_UPDATE: env.OMX_AUTO_UPDATE || '0',
    CODEX_NON_INTERACTIVE: env.CODEX_NON_INTERACTIVE || '1',
  };
}

function envPrefix(env) {
  return Object.entries(env)
    .map(([key, value]) => `${key}=${shQuote(value)}`)
    .join(' ');
}

export function codexAgentCommand({ cwd, command, env = process.env } = {}) {
  const agentCommand = command || defaultAgentCommand(env);
  return [`cd ${shQuote(cwd)}`, `exec env ${envPrefix(agentStartupEnv(env))} ${agentCommand}`].join(' && ');
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

export function resolveLineBridgeHandoffEnv({ agent = {}, env = process.env } = {}) {
  if (env.LINE_BRIDGE_HANDOFF !== undefined && env.LINE_BRIDGE_HANDOFF !== '') return env.LINE_BRIDGE_HANDOFF;
  return agent.created ? '1' : '0';
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

export async function waitForManagedAgentTarget(cwd, {
  initialPaneIds = [],
  attempts = positiveInt(process.env.TRADE_LINE_AGENT_TARGET_WAIT_ATTEMPTS, 20),
  intervalMs = positiveInt(process.env.TRADE_LINE_AGENT_TARGET_WAIT_MS, 500),
  currentPane = process.env.TMUX_PANE,
  listAllPanes = listAllTmuxPanes,
  sleepFn = sleep,
} = {}) {
  let fallbackTarget = initialPaneIds[0] || '';
  let fallbackPaneIds = initialPaneIds;
  const initial = new Set(initialPaneIds);

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const panes = await listAllPanes();
    const repoPaneIds = panes
      .filter((pane) => {
        try {
          return pane.currentPath && resolve(pane.currentPath) === resolve(cwd);
        } catch {
          return false;
        }
      })
      .map((pane) => pane.paneId);
    const target = chooseTmuxTarget(panes, cwd, currentPane);
    if (target) {
      fallbackTarget = target;
      fallbackPaneIds = repoPaneIds.length ? repoPaneIds : [target];
      if (!initial.has(target)) return { target, paneIds: fallbackPaneIds };
    }
    if (attempt < attempts - 1) await sleepFn(intervalMs);
  }

  return { target: fallbackTarget, paneIds: fallbackPaneIds };
}

async function ensureCodexAgentSession(cwd) {
  const sessionName = process.env.TRADE_LINE_AGENT_SESSION || 'trade-line-codex';
  const command = codexAgentCommand({ cwd });
  const sessionExists = await commandOk('tmux', ['has-session', '-t', sessionName]);
  if (!sessionExists) {
    await run('tmux', ['new-session', '-d', '-s', sessionName, command]);
  }
  await sleep(1200);
  const initialPaneIds = await listTmuxPaneIds(sessionName);
  const resolved = await waitForManagedAgentTarget(cwd, { initialPaneIds });
  const target = resolved.target || '';
  if (!target) throw new Error(`Could not create or find tmux pane for Codex agent session: ${sessionName}`);
  return { target, agent: { created: !sessionExists, sessionName, paneIds: resolved.paneIds || initialPaneIds, command } };
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

function latestMtimeMs(path) {
  const stat = statSync(path);
  if (!stat.isDirectory()) return stat.mtimeMs;
  const childTimes = readdirSync(path).map((name) => latestMtimeMs(join(path, name)));
  return childTimes.length ? Math.max(...childTimes) : stat.mtimeMs;
}

function cleanupByAge({ dir, include, retentionDays, now = Date.now(), maxFiles = 0, recursive = false }) {
  if (!dir || !existsSync(dir)) return { deleted: 0, kept: 0 };
  const retentionMs = retentionDays * 24 * 60 * 60 * 1000;
  const entries = readdirSync(dir)
    .filter((name) => !include || include(name))
    .map((name) => {
      const path = join(dir, name);
      return { name, path, mtimeMs: latestMtimeMs(path) };
    })
    .sort((a, b) => b.mtimeMs - a.mtimeMs);

  const toDelete = new Set();
  if (retentionDays > 0) {
    for (const entry of entries) {
      if (now - entry.mtimeMs > retentionMs) toDelete.add(entry.path);
    }
  }
  if (maxFiles > 0) {
    for (const entry of entries.slice(maxFiles)) toDelete.add(entry.path);
  }

  for (const path of toDelete) rmSync(path, { recursive, force: true });
  return { deleted: toDelete.size, kept: entries.length - toDelete.size };
}

function rolloutTimeMs(name) {
  const match = String(name).match(/^rollout-(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const [, year, month, day, hour, minute, second] = match;
  const parsed = Date.parse(`${year}-${month}-${day}T${hour}:${minute}:${second}Z`);
  return Number.isFinite(parsed) ? parsed : null;
}

function pruneEmptyDirs(dir, stopDir) {
  if (!dir || dir === stopDir || !existsSync(dir)) return 0;
  let removed = 0;
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) removed += pruneEmptyDirs(path, stopDir);
  }
  if (dir !== stopDir && readdirSync(dir).length === 0) {
    rmSync(dir, { recursive: true, force: true });
    removed += 1;
  }
  return removed;
}

function sessionOpenedInCwd(path, cwd) {
  if (!cwd) return false;
  const targetCwd = resolve(cwd);
  try {
    const lines = readFileSync(path, 'utf8').split(/\r?\n/, 50);
    for (const line of lines) {
      if (!line.includes('"turn_context"') || !line.includes('"cwd"')) continue;
      const entry = JSON.parse(line);
      const sessionCwd = entry?.payload?.cwd;
      if (sessionCwd && resolve(sessionCwd) === targetCwd) return true;
    }
  } catch {
    return false;
  }
  return false;
}

function cleanupCodexResumeSessions({ cwd, codexHomeDir = process.env.CODEX_HOME || join(homedir(), '.codex'), retentionDays, now = Date.now() } = {}) {
  const sessionsDir = resolve(codexHomeDir, 'sessions');
  if (!sessionsDir || !existsSync(sessionsDir) || retentionDays <= 0) return { deleted: 0, kept: 0, prunedDirs: 0, dir: sessionsDir };
  const retentionMs = retentionDays * 24 * 60 * 60 * 1000;
  let deleted = 0;
  let kept = 0;

  function visit(dir) {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      const stat = statSync(path);
      if (stat.isDirectory()) {
        visit(path);
        continue;
      }
      if (!/^rollout-.*\.jsonl$/.test(name)) continue;
      const startedAt = rolloutTimeMs(name) ?? stat.mtimeMs;
      if (now - startedAt > retentionMs && sessionOpenedInCwd(path, cwd)) {
        rmSync(path, { force: true });
        deleted += 1;
      } else {
        kept += 1;
      }
    }
  }

  visit(sessionsDir);
  const prunedDirs = pruneEmptyDirs(sessionsDir, sessionsDir);
  return { deleted, kept, prunedDirs, dir: sessionsDir };
}

export function cleanupStartupArtifacts({
  cwd = process.cwd(),
  tmpDir = tmpdir(),
  codexHomeDir = process.env.CODEX_HOME || join(homedir(), '.codex'),
  retentionDays = 7,
  responseDir = '.omx/line-bridge/responses',
  responseMaxFiles = 200,
  logDir = '.omx/logs',
  now = Date.now(),
} = {}) {
  const resolvedResponseDir = resolve(cwd, responseDir);
  const resolvedLogDir = resolve(cwd, logDir);
  const sessionsDir = resolve(cwd, '.omx/state/sessions');
  const responses = cleanupResponseFiles({
    responseDir: resolvedResponseDir,
    responseRetentionDays: retentionDays,
    responseMaxFiles,
  }, now);
  const logs = cleanupByAge({
    dir: resolvedLogDir,
    include: (name) => /\.(jsonl|log)$/.test(name),
    retentionDays,
    now,
  });
  const sessions = cleanupByAge({
    dir: sessionsDir,
    include: () => true,
    retentionDays,
    now,
    recursive: true,
  });
  const codexSessions = cleanupCodexResumeSessions({
    cwd,
    codexHomeDir,
    retentionDays,
    now,
  });
  const tmp = cleanupByAge({
    dir: tmpDir,
    include: (name) => /^trade-smoke-/.test(name) || /^trade-api-smoke-.*\.log$/.test(name) || /^trade-line-bridge-smoke-.*\.log$/.test(name),
    retentionDays,
    now,
    recursive: true,
  });
  const deleted = responses.deleted + logs.deleted + sessions.deleted + codexSessions.deleted + tmp.deleted;
  const kept = responses.kept + logs.kept + sessions.kept + codexSessions.kept + tmp.kept;
  return { deleted, kept, responses, logs, sessions, codexSessions, tmp };
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
  if (lineBridgeHealthMatchesConfig(health, config)) {
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

export function parseTradstartArgs(argv) {
  return {
    notify: argv.includes('--notify') && !argv.includes('--no-notify'),
  };
}

function parseArgs(argv) {
  return parseTradstartArgs(argv);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function tradstart({ cwd = process.cwd(), argv = process.argv.slice(2) } = {}) {
  loadDotEnv();
  const args = parseArgs(argv);
  const { target, agent } = await chooseOrCreateTarget(cwd);
  process.env.LINE_BRIDGE_TMUX_TARGET = target;
  process.env.LINE_BRIDGE_HANDOFF = resolveLineBridgeHandoffEnv({ agent, env: process.env });
  const config = readLineBridgeConfig();
  const retentionDays = positiveInt(process.env.TRADE_LINE_ARTIFACT_RETENTION_DAYS, config.responseRetentionDays || 7);
  const cleanup = cleanupStartupArtifacts({
    cwd,
    retentionDays,
    responseDir: config.responseDir,
    responseMaxFiles: config.responseMaxFiles,
    logDir: config.turnLogDir,
  });
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
  const notification = args.notify ? await notifyLine(config, text).catch((error) => ({ skipped: true, reason: error.message })) : { skipped: true, reason: 'notify disabled; pass --notify to broadcast startup' };
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
