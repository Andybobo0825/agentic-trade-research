import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, rmSync } from 'node:fs';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  chooseShioajiCli,
  ensurePidFileDirectory,
  parseShioajiWrapperArgs,
  shioajiServerArgs,
  shioajiServerEnv,
  shioajiServerSpawnOptions,
  writeShioajiPidFile,
} from '../src/shioaji-server.js';

test('chooseShioajiCli honors explicit SHIOAJI_CLI then local venv then PATH command', () => {
  assert.equal(chooseShioajiCli({ SHIOAJI_CLI: '/custom/shioaji' }, () => false), '/custom/shioaji');
  assert.equal(chooseShioajiCli({}, (path) => path === '.omx/shioaji-venv/bin/shioaji'), '.omx/shioaji-venv/bin/shioaji');
  assert.equal(chooseShioajiCli({}, () => false), 'shioaji');
});

test('shioajiServerEnv maps simulation setting to Shioaji CLI production flag', () => {
  assert.equal(shioajiServerEnv({ SHIOAJI_SIMULATION: 'true' }).SJ_PRODUCTION, 'false');
  assert.equal(shioajiServerEnv({ SHIOAJI_SIMULATION: '0' }).SJ_PRODUCTION, 'true');
  assert.equal(shioajiServerEnv({ SJ_PRODUCTION: 'true', SHIOAJI_SIMULATION: 'true' }).SJ_PRODUCTION, 'true');
});

test('parseShioajiWrapperArgs extracts daemon and pid-file wrapper options', () => {
  assert.deepEqual(parseShioajiWrapperArgs(['--daemon', '--pid-file', '.omx/shioaji-server.pid', '--no-open']), {
    daemon: true,
    pidFile: '.omx/shioaji-server.pid',
    passthrough: ['--no-open'],
  });
});

test('shioajiServerArgs does not pass wrapper-only options to Shioaji CLI', () => {
  assert.deepEqual(
    shioajiServerArgs(['--daemon', '--pid-file', '.omx/shioaji-server.pid']),
    ['server', 'start', '--no-open'],
  );
});

test('shioajiServerSpawnOptions detaches daemon children', () => {
  assert.equal(shioajiServerSpawnOptions({ daemon: true }).detached, true);
  assert.equal(shioajiServerSpawnOptions({ daemon: false }).detached, false);
});

test('ensurePidFileDirectory creates parent directories for wrapper pid files', () => {
  const root = mkdtempSync(join(tmpdir(), 'trade-shioaji-pid-'));
  try {
    const pidFile = join(root, '.omx', 'shioaji-server.pid');
    assert.equal(existsSync(join(root, '.omx')), false);
    ensurePidFileDirectory(pidFile);
    assert.equal(existsSync(join(root, '.omx')), true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('writeShioajiPidFile skips pid-file writes when spawn did not produce a pid', () => {
  const root = mkdtempSync(join(tmpdir(), 'trade-shioaji-write-'));
  try {
    const pidFile = join(root, '.omx', 'shioaji-server.pid');
    assert.equal(writeShioajiPidFile(pidFile, undefined), false);
    assert.equal(existsSync(pidFile), false);
    assert.equal(writeShioajiPidFile(pidFile, 12345), true);
    assert.equal(existsSync(pidFile), true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
