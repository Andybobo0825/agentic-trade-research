import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  addAuthorizedUserId,
  buildLineHandoffReference,
  buildLinePrompt,
  BridgeConfigError,
  buildLineFlexMessages,
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
  assert.equal(discovery.handoffMode, 'once');

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

test('buildLinePrompt includes a compact handoff file reference before user text', () => {
  const dir = mkdtempSync(join(tmpdir(), 'line-bridge-handoff-reference-'));
  const handoffFile = join(dir, 'line-session-handoff.md');
  writeFileSync(handoffFile, '先使用 Fugle quote，並跑兩個 study。');
  const handoffReference = buildLineHandoffReference(handoffFile);
  const prompt = buildLinePrompt('看 2330 可以進場嗎', '', '', handoffReference);

  assert.match(prompt, /LINE session handoff/);
  assert.match(prompt, new RegExp(handoffFile.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(prompt, /請先讀取/);
  assert.doesNotMatch(prompt, /Fugle quote/);
  assert.ok(prompt.indexOf('LINE session handoff') < prompt.indexOf('看 2330 可以進場嗎'));
});


test('buildLineFlexMessages renders markdown tables as LINE Flex rows', () => {
  const messages = buildLineFlexMessages('| 資金 | 動作 |\n|---|---|\n| 30% | 今天先買 0050 或少量台積電 |\n| 40% | 跌到 95 附近再決定 |', { altText: '資金策略' });

  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, 'flex');
  assert.equal(messages[0].altText, '資金策略');
  assert.equal(messages[0].contents.type, 'bubble');
  const bodyTexts = JSON.stringify(messages[0].contents.body.contents);
  assert.match(bodyTexts, /資金/);
  assert.match(bodyTexts, /今天先買 0050/);
  assert.doesNotMatch(bodyTexts, /\|---\|/);
});

test('buildLineFlexMessages uses larger readable text sizes', () => {
  const [message] = buildLineFlexMessages('# 標題\n一般內容\n| 欄位 | 說明 |\n|---|---|\n| 0050 | 分批進場 |', { altText: '字級測試' });
  const contents = message.contents.body.contents;
  const heading = contents.find((item) => item.type === 'text' && item.text === '標題');
  const body = contents.find((item) => item.type === 'text' && item.text === '一般內容');
  const table = contents.find((item) => item.type === 'box');
  const tableHeader = table.contents[0].contents[0].contents[0];
  const tableCell = table.contents[0].contents[0].contents[1];

  assert.equal(heading.size, 'lg');
  assert.equal(body.size, 'md');
  assert.equal(tableHeader.size, 'sm');
  assert.equal(tableCell.size, 'md');
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
    pushMessages: async (to, messages) => calls.push({ type: 'push', to, messages }),
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
    pushMessages: async (to, messages) => calls.push({ type: 'push', to, messages }),
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
  assert.deepEqual(calls.map((call) => [call.type, call.to, call.messages?.[0]?.type, call.messages?.[0]?.altText]), [
    ['push', 'U1', 'flex', '完成摘要'],
    ['push', 'U2', 'flex', '完成摘要'],
  ]);
  assert.deepEqual(result, { started: true, processed: 2 });
  assert.equal(state.busy, false);
  assert.equal(state.queue.length, 0);
});

test('processLineQueue drains queued prompts with an error when tmux target is dead', async () => {
  const calls = [];
  const sent = [];
  const state = {
    busy: false,
    queue: [
      { message: { userId: 'U1', to: 'U1' }, text: 'will not send' },
    ],
  };

  const result = await processLineQueue({
    api: {
      push: async (to, text) => calls.push({ to, text }),
      pushMessages: async (to, messages) => calls.push({ to, messages }),
    },
    config: {
      tmuxTarget: '%0',
      injectResponseFileContract: false,
      responseDir: '/tmp/trade-line-bridge-test-responses-does-not-exist',
      responseRetentionDays: 7,
      responseMaxFiles: 200,
    },
    tmux: {
      isTargetAlive: async () => false,
      sendPrompt: async (prompt) => sent.push(prompt),
    },
    state,
    logger: { log: () => {}, error: () => {} },
  });

  assert.deepEqual(sent, []);
  assert.equal(calls.length, 1);
  assert.match(JSON.stringify(calls[0]), /tmux target %0/);
  assert.deepEqual(result, { started: false, processed: 1, reason: 'tmux-target-dead' });
  assert.equal(state.busy, false);
  assert.equal(state.queue.length, 0);
});



test('processLineQueue injects compact handoff file reference only once per bridge session', async () => {
  const sent = [];
  const calls = [];
  const dir = mkdtempSync(join(tmpdir(), 'line-bridge-handoff-'));
  const handoffFile = join(dir, 'line-session-handoff.md');
  writeFileSync(handoffFile, '只應該留在檔案裡，不應該出現在 prompt context 的完整 handoff');
  const config = {
    commandPrefix: '',
    injectHandoff: true,
    handoffFile,
    injectResponseFileContract: false,
    responseDir: '/tmp/trade-line-bridge-test-responses-does-not-exist',
    responseRetentionDays: 7,
    responseMaxFiles: 200,
    turnLogDir: '/tmp',
    completionTimeoutMs: 60000,
    completionPollMs: 1,
    captureLines: 5,
  };
  const state = {
    busy: false,
    queue: [
      { message: { userId: 'U1', to: 'U1' }, text: '第一則' },
      { message: { userId: 'U1', to: 'U1' }, text: '第二則' },
    ],
  };

  await processLineQueue({
    api: {
      pushMessages: async (to, messages) => calls.push({ to, messages }),
      push: async () => {},
    },
    config,
    tmux: {
      sendPrompt: async (prompt) => sent.push(prompt),
      capture: async () => '',
    },
    state,
    logger: { log: () => {}, error: () => {} },
    waitForCompletion: async () => ({ status: 'complete', text: 'ok' }),
  });

  assert.equal(sent.length, 2);
  assert.match(sent[0], /LINE session handoff/);
  assert.match(sent[0], new RegExp(handoffFile.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.doesNotMatch(sent[0], /只應該留在檔案裡/);
  assert.doesNotMatch(sent[1], /LINE session handoff/);
  assert.equal(state.handoffInjected, true);
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

test('line bridge health reports unhealthy when tmux target is dead', async () => {
  const server = await runLineBridge({
    config: {
      port: 0,
      path: '/line/webhook',
      tmuxTarget: '%0',
      responseDir: '/tmp/trade-line-bridge-test-responses-does-not-exist',
      responseRetentionDays: 7,
      responseMaxFiles: 200,
    },
    tmux: { isTargetAlive: async () => false },
    logger: { log: () => {}, error: () => {} },
  });
  try {
    const { port } = server.address();
    const res = await fetch(`http://127.0.0.1:${port}/health`);
    const json = await res.json();

    assert.equal(res.status, 503);
    assert.equal(json.ok, false);
    assert.equal(json.service, 'line-bridge');
    assert.equal(json.tmuxTarget, '%0');
    assert.equal(json.tmuxTargetAlive, false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
