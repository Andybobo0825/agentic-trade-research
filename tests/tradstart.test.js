import test from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, mkdirSync, readFileSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { cleanupStartupArtifacts, cloudflaredCommand, codexAgentCommand, expandHome, findCloudflaredPids, parseTradstartArgs, resolveBridgeTargetEnv, resolveLineBridgeHandoffEnv, shQuote, summaryText, waitForManagedAgentTarget } from '../src/tradstart.js';
import { STARTUP_MESSAGE } from '../src/line-bridge.js';

test('expandHome expands tilde paths', () => {
  assert.equal(expandHome('/tmp/x'), '/tmp/x');
  assert.match(expandHome('~/.cloudflared/x.yml'), /\.cloudflared\/x\.yml$/);
});

test('shQuote escapes single quotes for shell commands', () => {
  assert.equal(shQuote("a'b"), "'a'\\''b'");
});

test('cloudflaredCommand builds repo-scoped tmux command', () => {
  const command = cloudflaredCommand({ cwd: '/repo path', configPath: '/cfg.yml', tunnelName: 'trade-line', logPath: '/tmp/log file.log' });
  assert.match(command, /cd '\/repo path'/);
  assert.match(command, /cloudflared tunnel --config '\/cfg\.yml' run 'trade-line'/);
  assert.match(command, /tee '\/tmp\/log file\.log'/);
});

test('codexAgentCommand builds repo-scoped Codex tmux command', () => {
  const command = codexAgentCommand({ cwd: '/repo path', env: {}, command: 'codex --ask-for-approval never --sandbox workspace-write' });
  assert.equal(command, "cd '/repo path' && exec env OMX_AUTO_UPDATE='0' CODEX_NON_INTERACTIVE='1' codex --ask-for-approval never --sandbox workspace-write");
});

test('default Codex agent command is unattended for LINE bridge sessions', () => {
  const command = codexAgentCommand({ cwd: '/repo path', env: {} });

  assert.match(command, /OMX_AUTO_UPDATE='0'/);
  assert.match(command, /CODEX_NON_INTERACTIVE='1'/);
  assert.match(command, /codex --ask-for-approval never --sandbox workspace-write/);
});

test('codexAgentCommand keeps explicit noninteractive env overrides', () => {
  const command = codexAgentCommand({
    cwd: '/repo path',
    command: 'omx --madmax --high',
    env: { OMX_AUTO_UPDATE: 'defer', CODEX_NON_INTERACTIVE: 'true' },
  });

  assert.equal(command, "cd '/repo path' && exec env OMX_AUTO_UPDATE='defer' CODEX_NON_INTERACTIVE='true' omx --madmax --high");
});

test('findCloudflaredPids finds matching tunnel process only', () => {
  const ps = [
    '123 cloudflared tunnel --config /Users/me/.cloudflared/trade-line.yml run trade-line',
    '456 cloudflared tunnel --config /Users/me/.cloudflared/other.yml run other',
  ].join('\n');
  assert.deepEqual(findCloudflaredPids(ps, '/Users/me/.cloudflared/trade-line.yml', 'trade-line'), ['123']);
});

test('resolveBridgeTargetEnv prefers live discovery over stale env targets', () => {
  assert.equal(resolveBridgeTargetEnv({ env: { TMUX_PANE: '%9', LINE_BRIDGE_TMUX_TARGET: '%0' }, discoveredTarget: '%1' }), '%1');
  assert.equal(resolveBridgeTargetEnv({ env: { LINE_BRIDGE_TMUX_TARGET: '%0' }, discoveredTarget: '%1' }), '%1');
  assert.equal(resolveBridgeTargetEnv({ env: { LINE_BRIDGE_TMUX_TARGET: '%0' }, discoveredTarget: '' }), '%0');
  assert.equal(resolveBridgeTargetEnv({ env: { OMX_TARGET_PANE: '%2', LINE_BRIDGE_TMUX_TARGET: '%0' }, discoveredTarget: '' }), '%2');
});

test('resolveLineBridgeHandoffEnv injects handoff only for newly created agent sessions by default', () => {
  assert.equal(resolveLineBridgeHandoffEnv({ agent: { created: true }, env: {} }), '1');
  assert.equal(resolveLineBridgeHandoffEnv({ agent: { created: false }, env: {} }), '0');
  assert.equal(resolveLineBridgeHandoffEnv({ agent: { created: false }, env: { LINE_BRIDGE_HANDOFF: '1' } }), '1');
  assert.equal(resolveLineBridgeHandoffEnv({ agent: { created: true }, env: { LINE_BRIDGE_HANDOFF: '0' } }), '0');
});

test('waitForManagedAgentTarget polls until Codex bootstrap exposes the refreshed repo pane', async () => {
  const snapshots = [
    [
      { paneId: '%0', currentPath: '/repo', command: 'zsh', active: true, sessionName: 'trade-line-codex' },
    ],
    [
      { paneId: '%2', currentPath: '/repo', command: 'node', active: true, sessionName: 'omx' },
      { paneId: '%3', currentPath: '/repo', command: 'node', active: false, sessionName: 'omx' },
    ],
  ];
  let calls = 0;

  const result = await waitForManagedAgentTarget('/repo', {
    initialPaneIds: ['%0'],
    attempts: 3,
    intervalMs: 1,
    sleepFn: async () => {},
    listAllPanes: async () => snapshots[Math.min(calls++, snapshots.length - 1)],
  });

  assert.deepEqual(result, { target: '%2', paneIds: ['%2', '%3'] });
  assert.equal(calls, 2);
});

test('summaryText hides health and process details from startup output', () => {
  const text = summaryText({
    lineBridge: { status: 'started', pids: ['1'], target: '%1' },
    agent: { sessionName: 'agent', paneIds: ['%1'] },
    cloudflared: { status: 'started', pids: ['2'], sessionName: 'tunnel' },
    cleanup: { deleted: 1, kept: 2 },
    localHealth: { status: 200, text: '{\"ok\":true}' },
    publicHealth: { status: 200, text: '{\"ok\":true}' },
  });
  assert.equal(text, STARTUP_MESSAGE);
  assert.equal(text.includes('health'), false);
  assert.equal(text.includes('LINE bridge'), false);
});


test('tradstart notifications are opt-in only', () => {
  assert.deepEqual(parseTradstartArgs([]), { notify: false });
  assert.deepEqual(parseTradstartArgs(['--notify']), { notify: true });
  assert.deepEqual(parseTradstartArgs(['--no-notify']), { notify: false });
});

test('cleanupStartupArtifacts removes only expired runtime artifacts', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'trade-cleanup-cwd-'));
  const tmpRoot = await mkdtemp(join(tmpdir(), 'trade-cleanup-tmp-'));
  const codexHome = await mkdtemp(join(tmpdir(), 'trade-cleanup-codex-home-'));
  try {
    const now = Date.parse('2026-06-12T12:00:00Z');
    const old = new Date(now - 8 * 24 * 60 * 60 * 1000);
    const fresh = new Date(now - 2 * 24 * 60 * 60 * 1000);
    const logsDir = join(cwd, '.omx/logs');
    const responsesDir = join(cwd, '.omx/line-bridge/responses');
    const lineBridgeDir = join(cwd, '.omx/line-bridge');
    const sessionsDir = join(cwd, '.omx/state/sessions');
    mkdirSync(logsDir, { recursive: true });
    mkdirSync(responsesDir, { recursive: true });
    mkdirSync(lineBridgeDir, { recursive: true });
    mkdirSync(join(sessionsDir, 'old-session'), { recursive: true });
    mkdirSync(join(sessionsDir, 'fresh-session'), { recursive: true });

    const oldLog = join(logsDir, 'turns-old.jsonl');
    const freshLog = join(logsDir, 'turns-fresh.jsonl');
    const oldResponse = join(responsesDir, 'old.md');
    const freshResponse = join(responsesDir, 'fresh.md');
    const authorizedUsers = join(lineBridgeDir, 'authorized-users.json');
    const oldSessionFile = join(sessionsDir, 'old-session', 'hud-state.json');
    const freshSessionFile = join(sessionsDir, 'fresh-session', 'hud-state.json');
    const oldSmokeDir = join(tmpRoot, 'trade-smoke-old');
    const oldSmokeFile = join(oldSmokeDir, 'artifact.txt');
    const freshSmokeLog = join(tmpRoot, 'trade-api-smoke-fresh.log');
    mkdirSync(oldSmokeDir, { recursive: true });
    writeFileSync(oldLog, 'old');
    writeFileSync(freshLog, 'fresh');
    writeFileSync(oldResponse, 'old');
    writeFileSync(freshResponse, 'fresh');
    writeFileSync(authorizedUsers, '{}');
    writeFileSync(oldSessionFile, '{}');
    writeFileSync(freshSessionFile, '{}');
    writeFileSync(oldSmokeFile, 'old');
    writeFileSync(freshSmokeLog, 'fresh');
    for (const path of [oldLog, oldResponse, oldSessionFile, oldSmokeFile, oldSmokeDir]) utimesSync(path, old, old);
    for (const path of [freshLog, freshResponse, authorizedUsers, freshSessionFile, freshSmokeLog]) utimesSync(path, fresh, fresh);

    const result = cleanupStartupArtifacts({
      cwd,
      tmpDir: tmpRoot,
      codexHomeDir: codexHome,
      retentionDays: 7,
      responseDir: responsesDir,
      responseMaxFiles: 200,
      now,
    });

    assert.equal(result.responses.deleted, 1);
    assert.equal(result.logs.deleted, 1);
    assert.equal(result.sessions.deleted, 1);
    assert.equal(result.tmp.deleted, 1);
    assert.throws(() => readFileSync(oldLog));
    assert.equal(readFileSync(freshLog, 'utf8'), 'fresh');
    assert.throws(() => readFileSync(oldResponse));
    assert.equal(readFileSync(freshResponse, 'utf8'), 'fresh');
    assert.equal(readFileSync(authorizedUsers, 'utf8'), '{}');
    assert.throws(() => readFileSync(oldSessionFile));
    assert.equal(readFileSync(freshSessionFile, 'utf8'), '{}');
    assert.equal(readFileSync(freshSmokeLog, 'utf8'), 'fresh');
  } finally {
    await rm(cwd, { recursive: true, force: true });
    await rm(tmpRoot, { recursive: true, force: true });
    await rm(codexHome, { recursive: true, force: true });
  }
});

test('cleanupStartupArtifacts removes only expired Codex resume session files opened in this cwd', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'trade-cleanup-cwd-'));
  const codexHome = await mkdtemp(join(tmpdir(), 'trade-cleanup-codex-home-'));
  try {
    const now = Date.parse('2026-06-12T12:00:00Z');
    const oldSessionDir = join(codexHome, 'sessions', '2026', '06', '01');
    const freshSessionDir = join(codexHome, 'sessions', '2026', '06', '12');
    const otherSessionDir = join(codexHome, 'sessions', '2026', '05', '30');
    mkdirSync(oldSessionDir, { recursive: true });
    mkdirSync(freshSessionDir, { recursive: true });
    mkdirSync(otherSessionDir, { recursive: true });
    const oldResume = join(oldSessionDir, 'rollout-2026-06-01T09-00-00-019e0000-old.jsonl');
    const freshResume = join(freshSessionDir, 'rollout-2026-06-12T09-00-00-019e0000-fresh.jsonl');
    const otherResume = join(otherSessionDir, 'rollout-2026-05-30T09-00-00-019e0000-other.jsonl');
    writeFileSync(oldResume, `${JSON.stringify({ type: 'turn_context', payload: { cwd } })}\nold`);
    writeFileSync(freshResume, `${JSON.stringify({ type: 'turn_context', payload: { cwd } })}\nfresh`);
    writeFileSync(otherResume, `${JSON.stringify({ type: 'turn_context', payload: { cwd: '/tmp/other-project' } })}\nother`);

    const result = cleanupStartupArtifacts({
      cwd,
      codexHomeDir: codexHome,
      retentionDays: 7,
      now,
    });

    assert.equal(result.codexSessions.deleted, 1);
    assert.throws(() => readFileSync(oldResume));
    assert.match(readFileSync(freshResume, 'utf8'), /fresh/);
    assert.match(readFileSync(otherResume, 'utf8'), /other/);
  } finally {
    await rm(cwd, { recursive: true, force: true });
    await rm(codexHome, { recursive: true, force: true });
  }
});

test('package exposes tradestart while keeping tradstart compatibility', () => {
  const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
  assert.equal(pkg.bin.tradestart, './bin/tradestart');
  assert.equal(pkg.bin.tradstart, './bin/tradstart');
  assert.equal(pkg.scripts.tradestart, 'node src/tradstart.js');
  assert.equal(pkg.scripts.tradstart, 'node src/tradstart.js');
});

test('tradestart bin resolves npm-link symlink before launching node', async () => {
  const tmpRoot = await mkdtemp(join(tmpdir(), 'trade-linked-bin-'));
  try {
    const globalBin = join(tmpRoot, 'bin');
    const fakeBin = join(tmpRoot, 'fake-bin');
    const capture = join(tmpRoot, 'capture.txt');
    mkdirSync(globalBin, { recursive: true });
    mkdirSync(fakeBin, { recursive: true });
    symlinkSync(join(process.cwd(), 'bin', 'tradestart'), join(globalBin, 'tradestart'));
    const fakeNode = join(fakeBin, 'node');
    writeFileSync(fakeNode, [
      '#!/usr/bin/env sh',
      '{',
      '  printf "cwd=%s\\n" "$PWD"',
      '  printf "arg1=%s\\n" "$1"',
      '  printf "arg2=%s\\n" "$2"',
      '} > "$CAPTURE"',
      'exit 0',
      '',
    ].join('\n'));
    chmodSync(fakeNode, 0o755);

    const result = spawnSync(join(globalBin, 'tradestart'), ['--notify'], {
      env: { ...process.env, PATH: `${fakeBin}:${process.env.PATH}`, CAPTURE: capture },
      encoding: 'utf8',
    });

    assert.equal(result.status, 0, result.stderr || result.stdout);
    const output = readFileSync(capture, 'utf8');
    assert.match(output, new RegExp(`^cwd=${process.cwd().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`, 'm'));
    assert.match(output, /^arg1=src\/tradstart\.js$/m);
    assert.match(output, /^arg2=--notify$/m);
  } finally {
    await rm(tmpRoot, { recursive: true, force: true });
  }
});

test('tradestop bin resolves npm-link symlink before launching node', async () => {
  const tmpRoot = await mkdtemp(join(tmpdir(), 'trade-linked-bin-'));
  try {
    const globalBin = join(tmpRoot, 'bin');
    const fakeBin = join(tmpRoot, 'fake-bin');
    const capture = join(tmpRoot, 'capture.txt');
    mkdirSync(globalBin, { recursive: true });
    mkdirSync(fakeBin, { recursive: true });
    symlinkSync(join(process.cwd(), 'bin', 'tradestop'), join(globalBin, 'tradestop'));
    const fakeNode = join(fakeBin, 'node');
    writeFileSync(fakeNode, [
      '#!/usr/bin/env sh',
      '{',
      '  printf "cwd=%s\\n" "$PWD"',
      '  printf "arg1=%s\\n" "$1"',
      '  printf "arg2=%s\\n" "$2"',
      '} > "$CAPTURE"',
      'exit 0',
      '',
    ].join('\n'));
    chmodSync(fakeNode, 0o755);

    const result = spawnSync(join(globalBin, 'tradestop'), ['--notify'], {
      env: { ...process.env, PATH: `${fakeBin}:${process.env.PATH}`, CAPTURE: capture },
      encoding: 'utf8',
    });

    assert.equal(result.status, 0, result.stderr || result.stdout);
    const output = readFileSync(capture, 'utf8');
    assert.match(output, new RegExp(`^cwd=${process.cwd().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`, 'm'));
    assert.match(output, /^arg1=src\/tradstop\.js$/m);
    assert.match(output, /^arg2=--notify$/m);
  } finally {
    await rm(tmpRoot, { recursive: true, force: true });
  }
});
