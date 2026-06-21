import test from 'node:test';
import assert from 'node:assert/strict';
import { chooseShioajiCli, shioajiServerEnv } from '../src/shioaji-server.js';

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
