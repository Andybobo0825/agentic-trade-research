#!/usr/bin/env node
import { createHmac, timingSafeEqual } from 'node:crypto';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { loadDotEnv } from './dotenv.js';

export const STARTUP_MESSAGE = '投資小幫手已上線';

const LINE_MAX_MESSAGE = 4900;

export class BridgeConfigError extends Error {
  constructor(message) {
    super(message);
    this.name = 'BridgeConfigError';
  }
}

export function parseIdList(value) {
  if (!value) return new Set();
  return new Set(
    String(value)
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean),
  );
}

export function readAuthorizedUserIdsFile(path) {
  if (!path || !existsSync(path)) return new Set();
  const text = readFileSync(path, 'utf8').trim();
  if (!text) return new Set();

  try {
    const parsed = JSON.parse(text);
    if (Array.isArray(parsed)) return parseIdList(parsed.join(','));
    if (Array.isArray(parsed?.authorizedUserIds)) return parseIdList(parsed.authorizedUserIds.join(','));
  } catch {
    // Fall through to plain text parsing for hand-edited whitelist files.
  }

  return parseIdList(text.replace(/\r?\n/g, ','));
}

export function writeAuthorizedUserIdsFile(path, userIds, now = new Date()) {
  if (!path) return;
  mkdirSync(dirname(path), { recursive: true });
  const authorizedUserIds = [...new Set([...userIds].map(String).filter(Boolean))].sort();
  writeFileSync(path, `${JSON.stringify({ version: 1, updatedAt: now.toISOString(), authorizedUserIds }, null, 2)}\n`);
}

export function addAuthorizedUserId(config, userId) {
  const value = String(userId || '').trim();
  if (!value) return false;
  if (config.allowedUserIds.has(value)) return false;
  config.allowedUserIds.add(value);
  writeAuthorizedUserIdsFile(config.authorizedUserIdsFile, config.allowedUserIds);
  return true;
}

function positiveInt(value, fallback) {
  if (value === undefined || value === '') return fallback;
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return parsed;
}

export function parseSubmitKeys(value) {
  const keys = String(value || '')
    .split(/[\s,]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  return keys.length ? keys : ['Enter'];
}

export class TmuxBridge {
  constructor(target, { submitKeys = ['Enter'], submitDelayMs = 800, clearBeforeSend = true } = {}) {
    this.target = target;
    this.submitKeys = submitKeys;
    this.submitDelayMs = submitDelayMs;
    this.clearBeforeSend = clearBeforeSend;
  }

  async sendPrompt(prompt) {
    const bufferName = `line-bridge-${Date.now()}`;
    if (this.clearBeforeSend) await runProcess('tmux', ['send-keys', '-t', this.target, 'C-u']);
    await runProcess('tmux', ['load-buffer', '-b', bufferName, '-'], { input: prompt });
    await runProcess('tmux', ['paste-buffer', '-p', '-r', '-b', bufferName, '-t', this.target]);
    await sleep(this.submitDelayMs);
    for (const key of this.submitKeys) {
      await runProcess('tmux', ['send-keys', '-t', this.target, key]);
    }
    await runProcess('tmux', ['delete-buffer', '-b', bufferName]).catch(() => undefined);
  }

  async capture(lines = 140) {
    const result = await runProcess('tmux', ['capture-pane', '-t', this.target, '-p', '-S', `-${lines}`]);
    return result.stdout.trim();
  }
}

function runProcess(command, args, { input } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ['pipe', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${command} ${args.join(' ')} exited ${code}: ${stderr || stdout}`));
    });
    if (input !== undefined) child.stdin.end(input);
    else child.stdin.end();
  });
}

export function createResponseFilePath(config, message, now = Date.now()) {
  const safeChatId = String(message.chatId || 'chat').replace(/[^a-zA-Z0-9_-]/g, '_');
  const safeMessageId = String(message.messageId || message.eventId || now).replace(/[^a-zA-Z0-9_-]/g, '_');
  mkdirSync(config.responseDir, { recursive: true });
  return resolve(config.responseDir, `${now}-${safeChatId}-${safeMessageId}.md`);
}

export function readResponseFileIfReady(path, sinceMs) {
  if (!path || !existsSync(path)) return null;
  const stat = statSync(path);
  if (stat.mtimeMs < sinceMs || stat.size === 0) return null;
  const text = readFileSync(path, 'utf8').trim();
  return text ? { text, mtimeMs: stat.mtimeMs, path } : null;
}

export function cleanupResponseFiles(config, now = Date.now()) {
  const dir = config.responseDir;
  if (!dir || !existsSync(dir)) return { deleted: 0, kept: 0 };

  const retentionMs = config.responseRetentionDays * 24 * 60 * 60 * 1000;
  const files = readdirSync(dir)
    .filter((name) => name.endsWith('.md'))
    .map((name) => {
      const path = join(dir, name);
      const stat = statSync(path);
      return { name, path, mtimeMs: stat.mtimeMs };
    })
    .sort((a, b) => b.mtimeMs - a.mtimeMs);

  const toDelete = new Set();
  if (config.responseRetentionDays > 0) {
    for (const file of files) {
      if (now - file.mtimeMs > retentionMs) toDelete.add(file.path);
    }
  }
  if (config.responseMaxFiles > 0) {
    for (const file of files.slice(config.responseMaxFiles)) toDelete.add(file.path);
  }

  for (const path of toDelete) rmSync(path, { force: true });
  return { deleted: toDelete.size, kept: files.length - toDelete.size };
}

export function findLatestTurnCompletion(logDir, sinceMs) {
  if (!existsSync(logDir)) return null;
  const files = readdirSync(logDir)
    .filter((name) => /^turns-.*\.jsonl$/.test(name))
    .map((name) => join(logDir, name));

  let latest = null;
  for (const file of files) {
    const text = readFileSync(file, 'utf8');
    for (const line of text.split(/\r?\n/)) {
      if (!line.trim()) continue;
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        continue;
      }
      if (event.type !== 'agent-turn-complete') continue;
      const ts = Date.parse(event.timestamp || '');
      if (!Number.isFinite(ts) || ts < sinceMs) continue;
      if (!latest || ts > latest.ts) {
        latest = {
          ts,
          timestamp: event.timestamp,
          output: event.output_preview || event.output || '',
          raw: event,
        };
      }
    }
  }
  return latest;
}

export async function waitForCompletion({ logDir, sinceMs, timeoutMs, pollMs, captureFallback, responseFilePath }) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const fileResponse = readResponseFileIfReady(responseFilePath, sinceMs);
    if (fileResponse) return { status: 'complete', source: 'response-file', text: fileResponse.text, path: fileResponse.path };

    const completion = findLatestTurnCompletion(logDir, sinceMs);
    if (completion?.output && completion.output.length > 0) {
      const settledFileResponse = readResponseFileIfReady(responseFilePath, sinceMs);
      if (settledFileResponse) return { status: 'complete', source: 'response-file', text: settledFileResponse.text, path: settledFileResponse.path };
      return { status: 'complete', source: 'omx-turn-log-preview', text: completion.output, timestamp: completion.timestamp };
    }
    await sleep(pollMs);
  }
  const fileResponse = readResponseFileIfReady(responseFilePath, sinceMs);
  if (fileResponse) return { status: 'complete', source: 'response-file', text: fileResponse.text, path: fileResponse.path };
  const fallback = captureFallback ? await captureFallback() : '';
  return { status: 'timeout', source: 'tmux-capture', text: fallback || 'Timed out waiting for an OMX turn-complete log or response file.' };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function nonNegativeInt(value, fallback) {
  if (value === undefined || value === '') return fallback;
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed) || parsed < 0) return fallback;
  return parsed;
}

export function readLineBridgeConfig(env = process.env) {
  const channelAccessToken = env.LINE_CHANNEL_ACCESS_TOKEN;
  if (!channelAccessToken) throw new BridgeConfigError('LINE_CHANNEL_ACCESS_TOKEN is required. Create/enable a LINE Messaging API channel and set its long-lived channel access token in .env.');

  const channelSecret = env.LINE_CHANNEL_SECRET;
  if (!channelSecret) throw new BridgeConfigError('LINE_CHANNEL_SECRET is required. Copy it from the LINE Developers Console Basic settings tab.');

  const authorizedUserIdsFile = env.LINE_BRIDGE_AUTHORIZED_USER_IDS_FILE || env.LINE_AUTHORIZED_USER_IDS_FILE || '.omx/line-bridge/authorized-users.json';
  const allowedUserIds = new Set([
    ...parseIdList(env.LINE_ALLOWED_USER_IDS),
    ...readAuthorizedUserIdsFile(authorizedUserIdsFile),
  ]);
  const autoAuthorizeFriends = env.LINE_BRIDGE_AUTO_AUTHORIZE_FRIENDS !== '0' && env.LINE_BRIDGE_AUTO_AUTHORIZE_FRIENDS !== 'false';
  const tmuxTarget = env.LINE_BRIDGE_TMUX_TARGET || env.OMX_TARGET_PANE || env.TMUX_PANE;
  if (!tmuxTarget) throw new BridgeConfigError('LINE_BRIDGE_TMUX_TARGET is required. Set it to the OMX/tmux pane id, e.g. %12.');

  return {
    channelAccessToken,
    channelSecret,
    allowedUserIds,
    authorizedUserIdsFile,
    autoAuthorizeFriends,
    tmuxTarget,
    port: positiveInt(env.LINE_BRIDGE_PORT, 8787),
    path: env.LINE_BRIDGE_PATH || '/line/webhook',
    completionTimeoutMs: positiveInt(env.LINE_BRIDGE_COMPLETION_TIMEOUT_MS, 10 * 60 * 1000),
    completionPollMs: positiveInt(env.LINE_BRIDGE_COMPLETION_POLL_MS, 2000),
    turnLogDir: env.LINE_BRIDGE_TURN_LOG_DIR || '.omx/logs',
    captureLines: positiveInt(env.LINE_BRIDGE_CAPTURE_LINES, 140),
    commandPrefix: env.LINE_BRIDGE_COMMAND_PREFIX || '',
    responseDir: env.LINE_BRIDGE_RESPONSE_DIR || '.omx/line-bridge/responses',
    injectResponseFileContract: env.LINE_BRIDGE_RESPONSE_FILE_CONTRACT !== '0' && env.LINE_BRIDGE_RESPONSE_FILE_CONTRACT !== 'false',
    responseRetentionDays: nonNegativeInt(env.LINE_BRIDGE_RESPONSE_RETENTION_DAYS, 7),
    responseMaxFiles: nonNegativeInt(env.LINE_BRIDGE_RESPONSE_MAX_FILES, 200),
    submitKeys: parseSubmitKeys(env.LINE_BRIDGE_SUBMIT_KEYS || 'Enter'),
    submitDelayMs: positiveInt(env.LINE_BRIDGE_SUBMIT_DELAY_MS, 800),
    clearBeforeSend: env.LINE_BRIDGE_CLEAR_BEFORE_SEND !== '0' && env.LINE_BRIDGE_CLEAR_BEFORE_SEND !== 'false',
    discoveryOnly: allowedUserIds.size === 0 && !autoAuthorizeFriends,
  };
}

export class LineApi {
  constructor(channelAccessToken, fetchImpl = globalThis.fetch) {
    this.channelAccessToken = channelAccessToken;
    this.fetch = fetchImpl;
    this.baseUrl = 'https://api.line.me/v2/bot/message';
  }

  async call(path, payload = {}) {
    const res = await this.fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${this.channelAccessToken}`,
      },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    if (!res.ok) throw new Error(`LINE ${path} failed (${res.status}): ${text.slice(0, 500)}`);
    return text ? JSON.parse(text) : {};
  }

  reply(replyToken, text) {
    return this.call('/reply', { replyToken, messages: [{ type: 'text', text: clipLineText(text) }] });
  }

  push(to, text) {
    return this.call('/push', { to, messages: [{ type: 'text', text: clipLineText(text) }] });
  }
}

function clipLineText(text) {
  const value = String(text || '(empty)');
  return value.length > 5000 ? value.slice(0, 4990) + '\n...(truncated)' : value;
}

export function verifyLineSignature(rawBody, signature, channelSecret) {
  if (!signature || !channelSecret) return false;
  const expected = createHmac('sha256', channelSecret).update(rawBody).digest('base64');
  const expectedBuffer = Buffer.from(expected);
  const signatureBuffer = Buffer.from(String(signature));
  return expectedBuffer.length === signatureBuffer.length && timingSafeEqual(expectedBuffer, signatureBuffer);
}

export function parseLineEvents(payload) {
  const events = Array.isArray(payload?.events) ? payload.events : [];
  return events
    .map((event) => {
      const userId = event.source?.userId || '';
      if (event?.type === 'follow') {
        return {
          eventType: 'follow',
          eventId: event.webhookEventId || event.replyToken || Date.now(),
          replyToken: event.replyToken,
          text: '',
          userId: String(userId),
          chatId: String(userId || 'line'),
          messageId: String(event.webhookEventId || event.replyToken || Date.now()),
          to: String(userId),
          sourceType: event.source?.type || '',
        };
      }
      if (event?.type !== 'message' || event.message?.type !== 'text') return null;
      return {
        eventType: 'message',
        eventId: event.webhookEventId || event.replyToken || Date.now(),
        replyToken: event.replyToken,
        text: String(event.message.text || '').trim(),
        userId: String(userId),
        chatId: String(userId || event.source?.groupId || event.source?.roomId || 'line'),
        messageId: String(event.webhookEventId || event.message?.id || event.replyToken || Date.now()),
        to: String(userId),
        sourceType: event.source?.type || '',
      };
    })
    .filter(Boolean);
}

export function isLineAuthorized(message, allowedUserIds) {
  return allowedUserIds.has(String(message.userId));
}

export function canAutoAuthorizeLineUser(message, config) {
  return Boolean(config.autoAuthorizeFriends && message.userId && message.sourceType === 'user');
}

export function maskLineUserId(userId) {
  const value = String(userId || '');
  if (value.length <= 8) return value || '(missing)';
  return `${value.slice(0, 4)}…${value.slice(-4)}`;
}

export function buildLinePrompt(text, commandPrefix = '', responseFilePath = '') {
  const parts = [];
  if (commandPrefix) parts.push(commandPrefix);
  if (responseFilePath) parts.push([
    '[LINE bridge delivery contract]',
    `請在完成任務後，把「要回傳到 LINE 的完整最終回覆」寫入這個檔案：${responseFilePath}`,
    '檔案內容請使用純 Markdown；不要包含 raw API token、完整 secrets、或不必要的工具原始輸出。',
    '寫入檔案後，再正常回覆使用者同一份內容。',
    '[End LINE bridge delivery contract]',
  ].join('\n'));
  parts.push(text.trim());
  return parts.join('\n\n');
}

export function splitLineText(text, maxLen = LINE_MAX_MESSAGE) {
  const chunks = [];
  let rest = String(text || '');
  while (rest.length > maxLen) {
    let cut = rest.lastIndexOf('\n', maxLen);
    if (cut < maxLen * 0.5) cut = maxLen;
    chunks.push(rest.slice(0, cut));
    rest = rest.slice(cut).trimStart();
  }
  if (rest) chunks.push(rest);
  return chunks.length ? chunks : ['(empty)'];
}

export function lineStatusText(config, busy, queueLength = 0) {
  return [
    config.discoveryOnly ? '狀態：尚未授權使用者；目前只會回覆 LINE userId，不會執行 prompt。' : busy ? '狀態：忙碌中，正在等待 OMX 回覆。' : '狀態：空閒，可以送 prompt。',
    `佇列等待數：${queueLength}`,
    `授權模式：${config.autoAuthorizeFriends ? '加入好友/首次私訊自動加入本機白名單' : '固定白名單'}`,
    `已授權人數：${config.allowedUserIds?.size || 0}`,
    `tmux target：${config.tmuxTarget}`,
    `webhook path：${config.path}`,
    `completion timeout：${Math.round(config.completionTimeoutMs / 1000)}s`,
  ].join('\n');
}

function ensureQueue(state) {
  if (!Array.isArray(state.queue)) state.queue = [];
  return state.queue;
}

export async function processLineQueue(context) {
  const { api, config, tmux, state, logger = console } = context;
  const waitForCompletionImpl = context.waitForCompletion || waitForCompletion;
  const queue = ensureQueue(state);
  if (state.busy) return { started: false, reason: 'busy' };

  state.busy = true;
  let processed = 0;
  try {
    while (queue.length > 0) {
      const job = queue.shift();
      const { message, text } = job;
      const startedAtMs = Date.now() - 1000;
      const responseFilePath = config.injectResponseFileContract ? createResponseFilePath(config, message) : '';
      logger.log?.(`[line-queue] start user=${maskLineUserId(message.userId)} remaining=${queue.length}`);
      try {
        await tmux.sendPrompt(buildLinePrompt(text, config.commandPrefix, responseFilePath));
        const completion = await waitForCompletionImpl({
          logDir: config.turnLogDir,
          sinceMs: startedAtMs,
          timeoutMs: config.completionTimeoutMs,
          pollMs: config.completionPollMs,
          captureFallback: () => tmux.capture(config.captureLines),
          responseFilePath,
        });
        const prefix = completion.status === 'complete' ? '完成摘要' : '等待逾時，回傳目前 tmux 畫面';
        await sendLongLineMessage(api, message.to || message.userId, `${prefix}：\n\n${completion.text}`);
        cleanupResponseFiles(config);
        processed += 1;
        logger.log?.(`[line-queue] complete user=${maskLineUserId(message.userId)} remaining=${queue.length}`);
      } catch (error) {
        await sendLongLineMessage(api, message.to || message.userId, `Bridge 執行失敗：${error.message}`);
        processed += 1;
        logger.error?.(`[line-queue] failed user=${maskLineUserId(message.userId)} error=${error.stack || error.message}`);
      }
    }
    return { started: true, processed };
  } finally {
    state.busy = false;
  }
}

export async function handleLineMessage(message, context) {
  const { api, config, tmux, state, logger = console } = context;
  if (message.eventType === 'follow') {
    if (canAutoAuthorizeLineUser(message, config)) {
      const added = addAuthorizedUserId(config, message.userId);
      logger.log?.(`[line-auth] follow ${added ? 'auto-authorized' : 'already-authorized'} user=${maskLineUserId(message.userId)} whitelistCount=${config.allowedUserIds.size}`);
      await api.reply(message.replyToken, [
        added ? '已加入好友並自動授權。' : '你已在授權白名單中。',
        '之後可直接傳文字給我，我會送進 Mac 上的 OMX/tmux agent。',
        '可用指令：/help /status /tail',
      ].join('\n'));
      return { handled: true, authorized: true, autoAuthorized: added, command: 'follow' };
    }
    logger.log?.(`[line-auth] follow not-authorized user=${maskLineUserId(message.userId)} reason=auto-authorize-disabled-or-non-user-source source=${message.sourceType || '(missing)'}`);
    await api.reply(message.replyToken, `已加入好友，但目前未啟用自動授權。你的 LINE userId 是：${message.userId || '(LINE did not include a userId)'}`);
    return { handled: true, authorized: false, command: 'follow' };
  }

  if (!isLineAuthorized(message, config.allowedUserIds)) {
    if (canAutoAuthorizeLineUser(message, config)) {
      const added = addAuthorizedUserId(config, message.userId);
      logger.log?.(`[line-auth] message ${added ? 'auto-authorized' : 'already-authorized'} user=${maskLineUserId(message.userId)} whitelistCount=${config.allowedUserIds.size}`);
    } else {
      logger.log?.(`[line-auth] message rejected user=${maskLineUserId(message.userId)} reason=not-in-whitelist source=${message.sourceType || '(missing)'} autoAuthorize=${Boolean(config.autoAuthorizeFriends)}`);
      await api.reply(message.replyToken, `未授權。你的 LINE userId 是：${message.userId || '(LINE did not include a userId)'}\n請先加入 LINE 官方帳號好友，或請管理者加入白名單。`);
      return { handled: true, authorized: false };
    }
  } else {
    logger.log?.(`[line-auth] message authorized user=${maskLineUserId(message.userId)} source=${message.sourceType || '(missing)'}`);
  }

  const text = message.text;
  if (text === '/start' || text === '/help') {
    await api.reply(message.replyToken, [
      'LINE OMX bridge 已連線。',
      '直接傳文字：送進 Mac 上的 OMX/tmux agent。',
      '忙碌時會自動排入 FIFO 佇列，完成後 push 回覆。',
      '/status：查看狀態',
      '/tail：抓取目前 tmux pane 最近輸出',
      `你的 LINE userId：${message.userId}`,
    ].join('\n'));
    return { handled: true, command: 'help' };
  }

  if (text === '/status') {
    await api.reply(message.replyToken, lineStatusText(config, state.busy, ensureQueue(state).length));
    return { handled: true, command: 'status' };
  }

  if (text === '/tail') {
    const tail = await tmux.capture(config.captureLines);
    await api.reply(message.replyToken, tail || '(tmux pane is empty)');
    return { handled: true, command: 'tail' };
  }

  if (text.startsWith('/')) {
    await api.reply(message.replyToken, '未知指令。可用：/help /status /tail，或直接傳 prompt。');
    return { handled: true, command: 'unknown' };
  }

  const queue = ensureQueue(state);
  queue.push({ message, text });
  const position = queue.length + (state.busy ? 1 : 0);
  await api.reply(message.replyToken, position === 1
    ? '收到，已排入隊列，目前第 1 位，開始處理；完成後會回覆。'
    : `收到，已排入隊列，目前第 ${position} 位；完成後會回覆。`);
  processLineQueue(context).catch((error) => {
    logger.error?.(`LINE bridge queue processing failed: ${error.stack || error.message}`);
  });
  return { handled: true, prompt: true, queued: true, position };
}

async function sendLongLineMessage(api, to, text) {
  for (const chunk of splitLineText(text)) {
    await api.push(to, chunk);
  }
}

function readRequestBody(req, maxBytes = 1024 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > maxBytes) {
        reject(new Error('Request body too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

export function createLineWebhookServer({ api, config, tmux, logger = console } = {}) {
  const state = { busy: false, queue: [] };
  return createServer(async (req, res) => {
    try {
      const url = new URL(req.url || '/', `http://${req.headers.host || 'localhost'}`);
      if (req.method === 'GET' && url.pathname === '/health') {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ ok: true, service: 'line-bridge', busy: state.busy, queued: state.queue.length, tmuxTarget: config.tmuxTarget }));
        return;
      }
      if (req.method !== 'POST' || url.pathname !== config.path) {
        res.writeHead(404, { 'content-type': 'text/plain' });
        res.end('not found');
        return;
      }

      const rawBody = await readRequestBody(req);
      const signature = req.headers['x-line-signature'];
      if (!verifyLineSignature(rawBody, signature, config.channelSecret)) {
        res.writeHead(401, { 'content-type': 'text/plain' });
        res.end('invalid signature');
        return;
      }

      const payload = JSON.parse(rawBody.toString('utf8'));
      const messages = parseLineEvents(payload);
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ ok: true, accepted: messages.length }));

      for (const message of messages) {
        handleLineMessage(message, { api, config, tmux, state, logger }).catch((error) => {
          logger.error(`LINE bridge message handling failed: ${error.stack || error.message}`);
        });
      }
    } catch (error) {
      logger.error(`LINE bridge request failed: ${error.stack || error.message}`);
      if (!res.headersSent) {
        res.writeHead(500, { 'content-type': 'text/plain' });
        res.end(error.message);
      }
    }
  });
}

export async function runLineBridge({ api, config, tmux, logger = console } = {}) {
  cleanupResponseFiles(config);
  const server = createLineWebhookServer({ api, config, tmux, logger });
  await new Promise((resolve) => server.listen(config.port, '127.0.0.1', resolve));
  logger.log(STARTUP_MESSAGE);
  return server;
}

async function main() {
  loadDotEnv();
  const config = readLineBridgeConfig();
  const api = new LineApi(config.channelAccessToken);
  const tmux = new TmuxBridge(config.tmuxTarget, { submitKeys: config.submitKeys, submitDelayMs: config.submitDelayMs, clearBeforeSend: config.clearBeforeSend });
  await runLineBridge({ api, config, tmux });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
