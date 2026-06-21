#!/usr/bin/env node
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { loadDotEnv } from './dotenv.js';
import { readLineBridgeConfig, STARTUP_MESSAGE } from './line-bridge.js';

export function parseTmuxPaneList(text) {
  return String(text || '')
    .split(/\r?\n/)
    .map((line) => {
      const [paneId, currentPath, command, active, sessionName, windowIndex, paneIndex] = line.split('\t');
      if (!paneId) return null;
      return { paneId, currentPath, command, active: active === '1', sessionName, windowIndex, paneIndex };
    })
    .filter(Boolean);
}

export function paneExists(panes, target) {
  return Boolean(target && panes.some((pane) => pane.paneId === target));
}

export function chooseTmuxTarget(panes, cwd = process.cwd(), currentPane = process.env.TMUX_PANE) {
  const repo = resolve(cwd);
  const candidates = panes.filter((pane) => pane.currentPath && resolve(pane.currentPath) === repo);
  if (currentPane && candidates.some((pane) => pane.paneId === currentPane)) return currentPane;
  const active = candidates.find((pane) => pane.active);
  if (active) return active.paneId;
  if (candidates[0]) return candidates[0].paneId;
  return paneExists(panes, currentPane) ? currentPane : '';
}

export function findLineBridgePids(processListText, cwd = process.cwd()) {
  const repo = resolve(cwd);
  return String(processListText || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.includes('node src/line-bridge.js') && line.includes(repo))
    .map((line) => line.match(/^(\d+)/)?.[1])
    .filter(Boolean);
}

export async function getLineBridgeHealth(port = 8787, fetchImpl = globalThis.fetch) {
  try {
    const res = await fetchImpl(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(1500) });
    if (!res.ok) return null;
    return await res.json().catch(() => null);
  } catch {
    return null;
  }
}

export async function isLineBridgeHealthy(port = 8787, fetchImpl = globalThis.fetch) {
  const json = await getLineBridgeHealth(port, fetchImpl);
  return json?.service === 'line-bridge';
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

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function killPids(pids) {
  for (const pid of [...new Set(pids.filter(Boolean))]) {
    await run('kill', [pid]).catch(() => undefined);
  }
}

async function main() {
  loadDotEnv();
  const cwd = process.cwd();
  const panesText = await run('tmux', ['list-panes', '-a', '-F', '#{pane_id}	#{pane_current_path}	#{pane_current_command}	#{pane_active}	#{session_name}	#{window_index}	#{pane_index}']);
  const panes = parseTmuxPaneList(panesText.stdout);
  const discoveredTarget = chooseTmuxTarget(panes, cwd, process.env.TMUX_PANE);
  const envTarget = [process.env.OMX_TARGET_PANE, process.env.LINE_BRIDGE_TMUX_TARGET].find((candidate) => paneExists(panes, candidate));
  const target = discoveredTarget || envTarget || '';
  if (!target) throw new Error('Could not find a live tmux target pane. Run inside the OMX/tmux pane or set LINE_BRIDGE_TMUX_TARGET to an existing pane id.');
  process.env.LINE_BRIDGE_TMUX_TARGET = target;

  const config = readLineBridgeConfig();
  const health = await getLineBridgeHealth(config.port);
  if (health?.service === 'line-bridge' && health.tmuxTarget === target) {
    console.log(STARTUP_MESSAGE);
    return;
  }

  const ps = await run('ps', ['-axo', 'pid=,command=']);
  const existingPids = findLineBridgePids(ps.stdout, cwd);
  if (existingPids.length > 0) {
    await killPids(existingPids);
    await sleep(500);
  }

  const env = { ...process.env, LINE_BRIDGE_TMUX_TARGET: target };
  const child = spawn(process.execPath, ['src/line-bridge.js'], {
    cwd,
    env,
    detached: true,
    stdio: ['ignore', 'ignore', 'ignore'],
  });
  child.unref();
  console.log(STARTUP_MESSAGE);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
