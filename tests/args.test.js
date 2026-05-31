import test from 'node:test';
import assert from 'node:assert/strict';
import { parseArgs, optionalInt, requireArg } from '../src/args.js';
import { UsageError } from '../src/errors.js';

test('parseArgs supports positional commands and --key value', () => {
  assert.deepEqual(parseArgs(['statement', '--ticker', 'AAPL', '--limit=5']), { _: ['statement'], ticker: 'AAPL', limit: '5' });
});

test('requireArg throws clear usage error', () => {
  assert.throws(() => requireArg({ _: [] }, 'ticker'), UsageError);
});

test('optionalInt validates positive integers', () => {
  assert.equal(optionalInt({ limit: '3' }, 'limit', 1), 3);
  assert.throws(() => optionalInt({ limit: 'x' }, 'limit', 1), UsageError);
});
