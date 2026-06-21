import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { filterKillablePaneIds, notifyLineShutdown, parseTradstopArgs, resolveManagedAgentSessionName, SHUTDOWN_MESSAGE } from '../src/tradstop.js';
import { readTradeRuntimeState, removeTradeRuntimeState, tradeRuntimeStatePath, writeTradeRuntimeState } from '../src/trade-runtime.js';

test('runtime state helpers write, read, and remove owned tmux pane metadata', () => {
  const cwd = mkdtempSync(join(tmpdir(), 'trade-runtime-'));
  const path = tradeRuntimeStatePath(cwd, {});
  const state = { version: 1, cloudflared: { sessionName: 'trade-line-cloudflared', paneIds: ['%9'] } };
  writeTradeRuntimeState(path, state);
  assert.deepEqual(readTradeRuntimeState(path), state);
  removeTradeRuntimeState(path);
  assert.equal(readTradeRuntimeState(path), null);
});

test('filterKillablePaneIds dedupes panes and never kills the current pane', () => {
  assert.deepEqual(filterKillablePaneIds(['%1', '%2', '%2', 'not-pane', '%3'], '%2'), ['%1', '%3']);
});


test('resolveManagedAgentSessionName uses runtime state before env and default', () => {
  assert.equal(resolveManagedAgentSessionName({ sessionName: 'state-session' }, { TRADE_LINE_AGENT_SESSION: 'env-session' }), 'state-session');
  assert.equal(resolveManagedAgentSessionName({}, { TRADE_LINE_AGENT_SESSION: 'env-session' }), 'env-session');
  assert.equal(resolveManagedAgentSessionName({}, {}), 'trade-line-codex');
});

test('notifyLineShutdown pushes service closed message before shutdown', async () => {
  const cwd = mkdtempSync(join(tmpdir(), 'trade-runtime-notify-'));
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options, body: JSON.parse(options.body) });
    return { ok: true, status: 200, text: async () => '{}' };
  };

  const result = await notifyLineShutdown({
    LINE_CHANNEL_ACCESS_TOKEN: 'token',
    LINE_ALLOWED_USER_IDS: 'U1,U2',
    LINE_BRIDGE_AUTHORIZED_USER_IDS_FILE: join(cwd, 'authorized-users.json'),
  }, fetchImpl);

  assert.deepEqual(result, { skipped: false, sent: ['U1', 'U2'] });
  assert.deepEqual(calls.map((call) => call.body.to), ['U1', 'U2']);
  assert.deepEqual(calls.map((call) => call.body.messages[0].text), [SHUTDOWN_MESSAGE, SHUTDOWN_MESSAGE]);
  assert.equal(calls[0].options.headers.authorization, 'Bearer token');
});


test('tradstop notifications are opt-in only', () => {
  assert.deepEqual(parseTradstopArgs([]), { notify: false });
  assert.deepEqual(parseTradstopArgs(['--notify']), { notify: true });
  assert.deepEqual(parseTradstopArgs(['--no-notify']), { notify: false });
});
