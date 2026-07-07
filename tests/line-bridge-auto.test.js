import test from 'node:test';
import assert from 'node:assert/strict';
import { chooseTmuxTarget, findLineBridgePids, getLineBridgeHealth, isLineBridgeHealthy, lineBridgeHealthMatchesConfig, paneExists, parseTmuxPaneList, resolveAutoLineBridgeHandoffEnv } from '../src/line-bridge-auto.js';

test('parseTmuxPaneList parses tab-separated tmux pane metadata', () => {
  const panes = parseTmuxPaneList('%0\t/repo\tzsh\t1\ts\t0\t0\n%1\t/tmp\tnode\t0\ts\t0\t1');
  assert.deepEqual(panes[0], { paneId: '%0', currentPath: '/repo', command: 'zsh', active: true, sessionName: 's', windowIndex: '0', paneIndex: '0' });
  assert.equal(panes.length, 2);
});

test('chooseTmuxTarget prefers current pane when it is in the repo', () => {
  const panes = parseTmuxPaneList('%0\t/repo\tzsh\t0\ts\t0\t0\n%1\t/repo\tzsh\t1\ts\t0\t1');
  assert.equal(chooseTmuxTarget(panes, '/repo', '%0'), '%0');
});

test('chooseTmuxTarget falls back to active repo pane', () => {
  const panes = parseTmuxPaneList('%0\t/tmp\tzsh\t1\ts\t0\t0\n%1\t/repo\tzsh\t1\ts\t0\t1');
  assert.equal(chooseTmuxTarget(panes, '/repo', '%0'), '%1');
});


test('chooseTmuxTarget does not return a stale missing pane id', () => {
  const panes = parseTmuxPaneList('%2\t/tmp\tzsh\t1\ts\t0\t0');
  assert.equal(chooseTmuxTarget(panes, '/repo', '%1'), '');
  assert.equal(paneExists(panes, '%1'), false);
  assert.equal(paneExists(panes, '%2'), true);
});

test('findLineBridgePids detects repo-local bridge process', () => {
  const ps = '123 node src/line-bridge.js /repo\n456 node src/other.js /repo';
  assert.deepEqual(findLineBridgePids(ps, '/repo'), ['123']);
  assert.deepEqual(findLineBridgePids(ps, '/other'), []);
});

test('isLineBridgeHealthy checks the local health JSON', async () => {
  const okFetch = async () => ({
    ok: true,
    json: async () => ({ service: 'line-bridge' }),
  });
  const badFetch = async () => ({
    ok: true,
    json: async () => ({ service: 'other' }),
  });
  assert.equal(await isLineBridgeHealthy(8787, okFetch), true);
  assert.equal(await isLineBridgeHealthy(8787, badFetch), false);
});

test('getLineBridgeHealth returns target so auto-start can reject stale panes', async () => {
  const fetchImpl = async () => ({
    ok: true,
    json: async () => ({ service: 'line-bridge', tmuxTarget: '%2' }),
  });

  assert.deepEqual(await getLineBridgeHealth(8787, fetchImpl), { service: 'line-bridge', tmuxTarget: '%2' });
});

test('resolveAutoLineBridgeHandoffEnv disables handoff when attaching to existing resume pane by default', () => {
  assert.equal(resolveAutoLineBridgeHandoffEnv({ env: {} }), '0');
  assert.equal(resolveAutoLineBridgeHandoffEnv({ env: { LINE_BRIDGE_HANDOFF: '1' } }), '1');
  assert.equal(resolveAutoLineBridgeHandoffEnv({ env: { LINE_BRIDGE_HANDOFF: '0' } }), '0');
});

test('lineBridgeHealthMatchesConfig rejects stale bridge handoff config', () => {
  const config = { tmuxTarget: '%1', injectHandoff: false, handoffMode: 'once' };
  assert.equal(lineBridgeHealthMatchesConfig({ service: 'line-bridge', tmuxTarget: '%1', injectHandoff: false, handoffMode: 'once' }, config), true);
  assert.equal(lineBridgeHealthMatchesConfig({ service: 'line-bridge', tmuxTarget: '%1', injectHandoff: true, handoffMode: 'once' }, config), false);
  assert.equal(lineBridgeHealthMatchesConfig({ service: 'line-bridge', tmuxTarget: '%1' }, config), false);
});
