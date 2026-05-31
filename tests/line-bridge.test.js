import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  addAuthorizedUserId,
  buildLinePrompt,
  BridgeConfigError,
  handleLineMessage,
  lineStatusText,
  maskLineUserId,
  parseLineEvents,
  parseSubmitKeys,
  processLineQueue,
  readLineBridgeConfig,
  runLineBridge,
  STARTUP_MESSAGE,
  splitLineText,
  verifyLineSignature,
} from '../src/line-bridge.js';

test('readLineBridgeConfig requires token, secret, and tmux target', () => {
  assert.throws(() => readLineBridgeConfig({}), BridgeConfigError);
  assert.throws(() => readLineBridgeConfig({ LINE_CHANNEL_ACCESS_TOKEN: 'token' }), /LINE_CHANNEL_SECRET/);
  assert.throws(() => readLineBridgeConfig({ LINE_CHANNEL_ACCESS_TOKEN: 'token', LINE_CHANNEL_SECRET: 'secret' }), /LINE_BRIDGE_TMUX_TARGET/);

  const discovery = readLineBridgeConfig({ LINE_CHANNEL_ACCESS_TOKEN: 'token', LINE_CHANNEL_SECRET: 'secret', LINE_BRIDGE_TMUX_TARGET: '%9' });
  assert.equal(discovery.discoveryOnly, false);
  assert.equal(discovery.autoAuthorizeFriends, true);
  assert.equal(discovery.port, 8787);
  assert.equal(discovery.path, '/line/webhook');
  assert.deepEqual(discovery.submitKeys, ['Enter']);
  assert.equal(discovery.submitDelayMs, 800);
  assert.equal(discovery.clearBeforeSend, true);

  const config = readLineBridgeConfig({ LINE_CHANNEL_ACCESS_TOKEN: 'token', LINE_CHANNEL_SECRET: 'secret', LINE_ALLOWED_USER_IDS: 'U1,U2', LINE_BRIDGE_TMUX_TARGET: '%9', LINE_BRIDGE_PORT: '9999' });
  assert.equal(config.discoveryOnly, false);
  assert.equal(config.port, 9999);
  assert.equal(config.allowedUserIds.has('U1'), true);
});

test('readLineBridgeConfig loads persisted auto-authorized whitelist users', () => {
  const dir = mkdtempSync(join(tmpdir(), 'line-bridge-auth-'));
  const authorizedUserIdsFile = join(dir, 'authorized-users.json');
  const config = readLineBridgeConfig({
    LINE_CHANNEL_ACCESS_TOKEN: 'token',
    LINE_CHANNEL_SECRET: 'secret',
    LINE_BRIDGE_TMUX_TARGET: '%9',
    LINE_ALLOWED_USER_IDS: 'Uenv',
    LINE_BRIDGE_AUTHORIZED_USER_IDS_FILE: authorizedUserIdsFile,
  });

  assert.equal(config.allowedUserIds.has('Uenv'), true);
  assert.equal(addAuthorizedUserId(config, 'Ufile'), true);

  const reloaded = readLineBridgeConfig({
    LINE_CHANNEL_ACCESS_TOKEN: 'token',
    LINE_CHANNEL_SECRET: 'secret',
    LINE_BRIDGE_TMUX_TARGET: '%9',
    LINE_BRIDGE_AUTHORIZED_USER_IDS_FILE: authorizedUserIdsFile,
  });
  assert.equal(reloaded.allowedUserIds.has('Ufile'), true);
  assert.match(readFileSync(authorizedUserIdsFile, 'utf8'), /Ufile/);
});

test('parseSubmitKeys supports comma or whitespace key lists with Enter default', () => {
  assert.deepEqual(parseSubmitKeys(''), ['Enter']);
  assert.deepEqual(parseSubmitKeys('C-j'), ['C-j']);
  assert.deepEqual(parseSubmitKeys('C-j,C-m'), ['C-j', 'C-m']);
  assert.deepEqual(parseSubmitKeys('C-j C-m'), ['C-j', 'C-m']);
});

test('verifyLineSignature validates raw body with HMAC-SHA256 base64', () => {
  const raw = Buffer.from(JSON.stringify({ events: [] }));
  const sig = createHmac('sha256', 'secret').update(raw).digest('base64');
  assert.equal(verifyLineSignature(raw, sig, 'secret'), true);
  assert.equal(verifyLineSignature(raw, sig, 'wrong'), false);
  assert.equal(verifyLineSignature(raw, '', 'secret'), false);
});

test('parseLineEvents extracts text message events', () => {
  const events = parseLineEvents({
    events: [
      { type: 'message', webhookEventId: 'evt1', replyToken: 'reply', source: { type: 'user', userId: 'Uabc' }, message: { id: 'm1', type: 'text', text: ' hello ' } },
      { type: 'message', replyToken: 'ignore', source: { userId: 'Uabc' }, message: { type: 'image' } },
    ],
  });
  assert.equal(events.length, 1);
  assert.deepEqual(events[0], { eventType: 'message', eventId: 'evt1', replyToken: 'reply', text: 'hello', userId: 'Uabc', chatId: 'Uabc', messageId: 'evt1', to: 'Uabc', sourceType: 'user' });
});

test('parseLineEvents extracts follow events for automatic authorization', () => {
  const events = parseLineEvents({
    events: [
      { type: 'follow', webhookEventId: 'evt-follow', replyToken: 'reply-follow', source: { type: 'user', userId: 'Unew' } },
    ],
  });
  assert.deepEqual(events[0], { eventType: 'follow', eventId: 'evt-follow', replyToken: 'reply-follow', text: '', userId: 'Unew', chatId: 'Unew', messageId: 'evt-follow', to: 'Unew', sourceType: 'user' });
});

test('buildLinePrompt includes LINE response file contract', () => {
  assert.equal(buildLinePrompt('看 2330', ''), '看 2330');
  assert.equal(buildLinePrompt('看 2330', '繁中'), '繁中\n\n看 2330');
  const bridged = buildLinePrompt('看 2330', '', '/tmp/line.md');
  assert.match(bridged, /LINE bridge delivery contract/);
  assert.match(bridged, /\/tmp\/line\.md/);
});

test('splitLineText chunks long responses', () => {
  assert.deepEqual(splitLineText('a'.repeat(10), 4), ['aaaa', 'aaaa', 'aa']);
});

test('maskLineUserId hides the middle of long LINE user ids in logs', () => {
  assert.equal(maskLineUserId('U123456789abcdef'), 'U123…cdef');
  assert.equal(maskLineUserId('Ushort'), 'Ushort');
});

test('handleLineMessage rejects unauthorized user and supports status/tail', async () => {
  const calls = [];
  const api = {
    reply: async (replyToken, text) => calls.push({ type: 'reply', replyToken, text }),
    push: async (to, text) => calls.push({ type: 'push', to, text }),
  };
  const config = { allowedUserIds: new Set(['U1']), autoAuthorizeFriends: false, tmuxTarget: '%1', path: '/line/webhook', completionTimeoutMs: 60000, captureLines: 5 };
  const tmux = { capture: async () => 'pane tail' };

  const rejected = await handleLineMessage({ replyToken: 'r0', userId: 'U2', text: 'hello' }, { api, config, tmux, state: { busy: false } });
  assert.equal(rejected.authorized, false);
  assert.match(calls[0].text, /U2/);

  await handleLineMessage({ replyToken: 'r1', userId: 'U1', text: '/status' }, { api, config, tmux, state: { busy: false } });
  await handleLineMessage({ replyToken: 'r2', userId: 'U1', text: '/tail' }, { api, config, tmux, state: { busy: false } });
  assert.match(calls[1].text, /空閒/);
  assert.equal(calls[2].text, 'pane tail');
  assert.match(lineStatusText(config, true), /忙碌/);
});

test('handleLineMessage queues prompt instead of rejecting while busy', async () => {
  const calls = [];
  const api = {
    reply: async (replyToken, text) => calls.push({ type: 'reply', replyToken, text }),
    push: async (to, text) => calls.push({ type: 'push', to, text }),
  };
  const config = { allowedUserIds: new Set(['U1']), autoAuthorizeFriends: false, tmuxTarget: '%1', path: '/line/webhook', completionTimeoutMs: 60000, captureLines: 5 };
  const tmux = { capture: async () => 'pane tail', sendPrompt: async () => { throw new Error('should not run while busy'); } };
  const state = { busy: true, queue: [] };

  const result = await handleLineMessage({ replyToken: 'r1', userId: 'U1', text: 'hello', to: 'U1' }, { api, config, tmux, state, logger: { log: () => {}, error: () => {} } });

  assert.equal(result.queued, true);
  assert.equal(result.position, 2);
  assert.equal(state.queue.length, 1);
  assert.match(calls[0].text, /第 2 位/);
});

test('processLineQueue drains queued prompts in FIFO order', async () => {
  const calls = [];
  const sent = [];
  const api = {
    reply: async (replyToken, text) => calls.push({ type: 'reply', replyToken, text }),
    push: async (to, text) => calls.push({ type: 'push', to, text }),
  };
  const config = {
    allowedUserIds: new Set(['U1', 'U2']),
    autoAuthorizeFriends: false,
    tmuxTarget: '%1',
    path: '/line/webhook',
    completionTimeoutMs: 60000,
    completionPollMs: 1,
    captureLines: 5,
    injectResponseFileContract: false,
    responseDir: '/tmp/trade-line-bridge-test-responses-does-not-exist',
    responseRetentionDays: 7,
    responseMaxFiles: 200,
  };
  const tmux = {
    capture: async () => 'pane tail',
    sendPrompt: async (prompt) => sent.push(prompt),
  };
  const state = {
    busy: false,
    queue: [
      { message: { userId: 'U1', to: 'U1' }, text: 'first' },
      { message: { userId: 'U2', to: 'U2' }, text: 'second' },
    ],
  };

  const result = await processLineQueue({
    api,
    config,
    tmux,
    state,
    logger: { log: () => {}, error: () => {} },
    waitForCompletion: async () => ({ status: 'complete', text: `done ${sent.at(-1)}` }),
  });

  assert.deepEqual(sent, ['first', 'second']);
  assert.deepEqual(calls.map((call) => [call.type, call.to, call.text]), [
    ['push', 'U1', '完成摘要：\n\ndone first'],
    ['push', 'U2', '完成摘要：\n\ndone second'],
  ]);
  assert.deepEqual(result, { started: true, processed: 2 });
  assert.equal(state.busy, false);
  assert.equal(state.queue.length, 0);
});

test('handleLineMessage auto-authorizes LINE friends into the local whitelist', async () => {
  const calls = [];
  const dir = mkdtempSync(join(tmpdir(), 'line-bridge-follow-'));
  const config = {
    allowedUserIds: new Set(),
    authorizedUserIdsFile: join(dir, 'authorized-users.json'),
    autoAuthorizeFriends: true,
    tmuxTarget: '%1',
    path: '/line/webhook',
    completionTimeoutMs: 60000,
    captureLines: 5,
  };
  const api = {
    reply: async (replyToken, text) => calls.push({ type: 'reply', replyToken, text }),
    push: async (to, text) => calls.push({ type: 'push', to, text }),
  };
  const tmux = { capture: async () => 'pane tail' };

  const followed = await handleLineMessage({ eventType: 'follow', replyToken: 'rf', userId: 'Unew', sourceType: 'user', text: '' }, { api, config, tmux, state: { busy: false } });
  assert.equal(followed.authorized, true);
  assert.equal(config.allowedUserIds.has('Unew'), true);
  assert.match(readFileSync(config.authorizedUserIdsFile, 'utf8'), /Unew/);

  await handleLineMessage({ eventType: 'message', replyToken: 'rs', userId: 'Unew', sourceType: 'user', text: '/status' }, { api, config, tmux, state: { busy: false } });
  assert.match(calls.at(-1).text, /空閒/);
});

test('runLineBridge logs only the startup message after listening', async () => {
  const logs = [];
  const server = await runLineBridge({
    config: {
      port: 0,
      path: '/line/webhook',
      tmuxTarget: '%1',
      responseDir: '/tmp/trade-line-bridge-test-responses-does-not-exist',
      responseRetentionDays: 7,
      responseMaxFiles: 200,
    },
    logger: { log: (message) => logs.push(message), error: () => {} },
  });
  await new Promise((resolve) => server.close(resolve));
  assert.deepEqual(logs, [STARTUP_MESSAGE]);
});
