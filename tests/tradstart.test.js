import test from 'node:test';
import assert from 'node:assert/strict';
import { cloudflaredCommand, codexAgentCommand, expandHome, findCloudflaredPids, resolveBridgeTargetEnv, shQuote, summaryText } from '../src/tradstart.js';
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
  assert.equal(codexAgentCommand({ cwd: '/repo path', command: 'codex' }), "cd '/repo path' && exec codex");
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
