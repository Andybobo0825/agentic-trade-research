# Phase3 Stability Demo Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate `phase3_stability` with deterministic historical intraday demo replay, real IC.TPEX peer groups, Cathay Securities costs, partial-fill/slippage/stop-liquidity modeling, and promote it to the repository's sole strategy only if every mandatory gate passes.

**Architecture:** Keep signal generation in the existing all-market daily backtest, replace ticker-prefix grouping with frozen IC.TPEX mappings, then route fixed `phase3_stability` trade intents through a read-only L1 order-book replay derived from historical Shioaji ticks. A fail-closed promotion evaluator writes immutable evidence; workflow and memory are changed only after a passing report.

**Tech Stack:** Node.js 20 ESM, built-in `node:test`, Shioaji read-only HTTP data endpoints, official IC.TPEX HTML, JSON replay caches, Markdown reports.

---

## File structure

- Create `src/ic-tpex-peer-groups.js`: Resolve and freeze ticker-to-multiple-IC.TPEX-chain mappings.
- Create `src/cathay-stock-costs.js`: Calculate per-fill Cathay commissions and Taiwan stock tax.
- Create `src/demo-execution-replay.js`: Normalize historical tick L1 books and simulate partial entry/exit fills and stop execution.
- Create `src/phase3-demo-promotion.js`: Freeze phase3 parameters, sample sessions, load replay data, aggregate results, and evaluate promotion gates.
- Create `tests/ic-tpex-peer-groups.test.js`: Peer mapping, cache, multi-chain, and no-fallback tests.
- Create `tests/cathay-stock-costs.test.js`: Broker cost rounding, minimum, partial fill, and sell-tax tests.
- Create `tests/demo-execution-replay.test.js`: Chronology, depth, partial fill, slippage, and stop-liquidity tests.
- Create `tests/phase3-demo-promotion.test.js`: Sampling, reproducibility, gate, evidence, and order-API isolation tests.
- Modify `src/ic-tpex.js`: Parse every chain link on a company page instead of only the first.
- Modify `src/strategy-market-backtest.js`: Carry `peerGroups` arrays and reject missing official mappings without ticker-prefix fallback.
- Modify `src/strategy-universe.js`: Use injected/resolved IC.TPEX peer groups for synchronization.
- Modify `src/shioaji-market.js`: Add cacheable read-only historical tick retrieval without any account API.
- Modify `src/tools.js`: Register and render `phase3-demo-promotion`.
- Modify `src/cli.js`: Add the demo-only command and reject live/account/order arguments.
- Modify `src/mcp-server.js`: Expose the same read-only research operation with no execution-mode switch.
- Modify `tests/strategy-market-backtest.test.js`, `tests/strategy-universe.test.js`, `tests/ic-tpex.test.js`, `tests/shioaji-market.test.js`, `tests/cli.test.js`, and `tests/mcp-server.test.js`: Protect integration behavior.
- Create `.omx/reports/phase3-stability-demo-promotion.json` and `.omx/reports/phase3-stability-demo-promotion.md`: Immutable validation evidence.
- Conditionally modify `docs/standard-workflow-v1.md` and `.omx/project-memory.json`: Promote only after a passing report.
- Conditionally delete `.omx/backtests/MVP_R18H6_VOL_exit_only_WR3.md` and `.omx/backtests/mvp-r18h6-vol-exit-only-wr3-2025-06-01_2026-06-17.json`: Remove the replaced strategy rather than preserving a runnable baseline.

### Task 1: Official IC.TPEX multi-chain peer mapping

**Files:**
- Create: `src/ic-tpex-peer-groups.js`
- Create: `tests/ic-tpex-peer-groups.test.js`
- Modify: `src/ic-tpex.js`
- Modify: `tests/ic-tpex.test.js`

- [ ] **Step 1: Write failing parser and resolver tests**

Add this parser case to `tests/ic-tpex.test.js`:

```js
test('getIcTpexCompanyChain returns every official chain membership', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(`
      <a href="introduce.php?ic=D000&stk_code=2330">半導體</a>
      <a href="introduce.php?ic=5300&stk_code=2330">人工智慧</a>
      <a href="introduce.php?ic=D000&stk_code=2330">重複連結</a>
      <h3>台積電產業鏈</h3>
    `, { status: 200 });
    const result = await getIcTpexCompanyChain({ ticker: '2330' });
    assert.deepEqual(result.ics, ['D000', '5300']);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
```

Create `tests/ic-tpex-peer-groups.test.js` with:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { resolveIcTpexPeerGroups } from '../src/ic-tpex-peer-groups.js';

test('resolver freezes multi-chain memberships and never invents a ticker-prefix group', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'ic-peer-'));
  const cacheFile = join(dir, 'peers.json');
  const result = await resolveIcTpexPeerGroups({
    tickers: ['2330', '2454', '9999'],
    cacheFile,
    fetchedAt: '2026-07-09T00:00:00.000Z',
    fetchCompanyChain: async ({ ticker }) => ({
      ticker,
      ics: ticker === '2330' ? ['D000', '5300'] : ticker === '2454' ? ['D000'] : [],
      url: `https://ic.tpex.org.tw/company_chain.php?stk_code=${ticker}`,
    }),
  });

  assert.deepEqual(result.byTicker['2330'], ['D000', '5300']);
  assert.deepEqual(result.byTicker['2454'], ['D000']);
  assert.equal(result.byTicker['9999'], undefined);
  assert.deepEqual(result.unmappedTickers, ['9999']);
  assert.equal(JSON.parse(await readFile(cacheFile, 'utf8')).groupProxy, 'ic_tpex');
  assert.equal(JSON.stringify(result).includes('"23"'), false);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
node --test tests/ic-tpex.test.js tests/ic-tpex-peer-groups.test.js
```

Expected: failure because `result.ics` and `src/ic-tpex-peer-groups.js` do not exist.

- [ ] **Step 3: Implement multi-chain parsing and frozen mapping**

In `src/ic-tpex.js`, replace single-chain parsing with:

```js
function parseIcsFromCompanyChain(html) {
  return [...new Set(
    [...String(html).matchAll(/introduce\.php\?ic=([0-9A-Za-z]+)(?:&amp;|&)stk_code=/gi)]
      .map((match) => match[1].toUpperCase()),
  )];
}
```

Return both `ic: ics[0]` for compatibility and `ics`.

In `src/ic-tpex-peer-groups.js`, implement:

```js
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { getIcTpexCompanyChain } from './ic-tpex.js';

export async function resolveIcTpexPeerGroups({
  tickers = [],
  cacheFile = '.omx/cache/ic-tpex/peer-groups.json',
  refresh = true,
  fetchedAt = new Date().toISOString(),
  fetchCompanyChain = getIcTpexCompanyChain,
} = {}) {
  if (!refresh) {
    const cached = JSON.parse(await readFile(cacheFile, 'utf8'));
    return cached;
  }
  const byTicker = {};
  const sources = {};
  const unmappedTickers = [];
  for (const ticker of [...new Set(tickers.map(String))].sort()) {
    const row = await fetchCompanyChain({ ticker });
    const groups = [...new Set((row.ics || (row.ic ? [row.ic] : [])).map(String))].sort();
    if (!groups.length) {
      unmappedTickers.push(ticker);
      continue;
    }
    byTicker[ticker] = groups;
    sources[ticker] = row.url;
  }
  const result = { schemaVersion: 1, groupProxy: 'ic_tpex', fetchedAt, byTicker, sources, unmappedTickers };
  await mkdir(dirname(cacheFile), { recursive: true });
  const tempFile = `${cacheFile}.${process.pid}.tmp`;
  await writeFile(tempFile, `${JSON.stringify(result, null, 2)}\n`);
  await rename(tempFile, cacheFile);
  return result;
}
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
node --test tests/ic-tpex.test.js tests/ic-tpex-peer-groups.test.js
```

Expected: all tests pass.

- [ ] **Step 5: Commit the peer resolver**

```bash
git add src/ic-tpex.js src/ic-tpex-peer-groups.js tests/ic-tpex.test.js tests/ic-tpex-peer-groups.test.js
git commit -m "Use official peer chains instead of ticker-shaped guesses" \
  -m "Constraint: Missing IC.TPEX membership must fail closed
Rejected: Falling back to the first two ticker digits | It creates false peer relationships
Confidence: high
Scope-risk: moderate
Tested: node --test tests/ic-tpex.test.js tests/ic-tpex-peer-groups.test.js"
```

### Task 2: Remove ticker-prefix grouping from strategy behavior

**Files:**
- Modify: `src/strategy-market-backtest.js`
- Modify: `src/strategy-universe.js`
- Modify: `tests/strategy-market-backtest.test.js`
- Modify: `tests/strategy-universe.test.js`

- [ ] **Step 1: Write failing official-peer gate tests**

Add to `tests/strategy-market-backtest.test.js`:

```js
test('portfolio and health gates require official peerGroups with no prefix fallback', async () => {
  const { selectTradesByPortfolioGate, applyStrategyControls } = await import('../src/strategy-market-backtest.js');
  const trades = [
    { ticker: '2330', peerGroups: ['D000'], signalDate: '2026-01-01', entryDate: '2026-01-02', exitDate: '2026-01-03', returnPct: -10, signalScore: 10 },
    { ticker: '2454', peerGroups: ['D000', '5300'], signalDate: '2026-01-01', entryDate: '2026-01-02', exitDate: '2026-01-03', returnPct: 5, signalScore: 9 },
    { ticker: '2399', peerGroups: [], signalDate: '2026-01-04', entryDate: '2026-01-05', exitDate: '2026-01-06', returnPct: 5, signalScore: 8 },
  ];
  const selected = selectTradesByPortfolioGate(trades, { maxTradesPerGroupPerDay: 1 });
  assert.deepEqual(selected.map((row) => row.ticker), ['2330']);
  const controlled = applyStrategyControls(trades, { enableGroupHealth: true, groupHealthMinTrades: 1, groupHealthMinAverageReturnPct: -5 });
  assert.equal(controlled.rejections.some((row) => row.ticker === '2399' && row.reason === 'missing_peer_group'), true);
});
```

Add to `tests/strategy-universe.test.js` a fixture where `2330` and `2454` share
`D000` despite different prefixes and assert their `groupPeerCount` is two.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
node --test tests/strategy-market-backtest.test.js tests/strategy-universe.test.js
```

Expected: failure because gates still read `trade.group` or `ticker.slice(0, 2)`.

- [ ] **Step 3: Implement multi-membership gate semantics**

In both strategy files, use:

```js
function peerGroupsOf(row) {
  return [...new Set((row.peerGroups || []).map(String).filter(Boolean))].sort();
}
```

Portfolio selection must reject unmapped rows and reject a candidate when any of its
groups has reached `maxTradesPerGroupPerDay`. Rolling health must evaluate each group
independently and reject when any mapped group is unhealthy. Diagnostics may emit one
row per `(trade, peerGroup)` membership.

Delete every strategy fallback shaped like:

```js
String(trade.ticker || '').slice(0, 2)
```

and change result metadata to:

```js
groupProxy: 'ic_tpex'
```

- [ ] **Step 4: Run strategy tests and verify GREEN**

Run:

```bash
node --test tests/strategy-market-backtest.test.js tests/strategy-universe.test.js
rg -n "ticker\\.slice\\(0, 2\\)|String\\([^\\n]*ticker[^\\n]*\\)\\.slice\\(0, 2\\)|ticker_prefix_2" src/strategy-market-backtest.js src/strategy-universe.js
```

Expected: tests pass and `rg` returns no matches.

- [ ] **Step 5: Commit group behavior**

```bash
git add src/strategy-market-backtest.js src/strategy-universe.js tests/strategy-market-backtest.test.js tests/strategy-universe.test.js
git commit -m "Make peer risk controls reflect official value chains" \
  -m "Constraint: A stock may belong to multiple official chains
Rejected: One synthetic primary group | It hides cross-chain concentration
Confidence: high
Scope-risk: broad
Tested: strategy market and universe tests plus prefix-fallback source scan"
```

### Task 3: Cathay Securities per-fill cost model

**Files:**
- Create: `src/cathay-stock-costs.js`
- Create: `tests/cathay-stock-costs.test.js`

- [ ] **Step 1: Write failing cost tests**

Create `tests/cathay-stock-costs.test.js`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { cathayStockFillCost, summarizeCathayTradeCosts } from '../src/cathay-stock-costs.js';

test('Cathay online stock fills charge 0.399 per mille with conservative TWD 20 minimum', () => {
  assert.deepEqual(cathayStockFillCost({ side: 'buy', price: 100, quantity: 1000 }), {
    side: 'buy', consideration: 100000, commission: 39, transactionTax: 0, totalCost: 39,
  });
  assert.equal(cathayStockFillCost({ side: 'buy', price: 10, quantity: 100 }).commission, 20);
});

test('sell fills add 0.3 percent stock transaction tax and partial fills are costed separately', () => {
  const first = cathayStockFillCost({ side: 'sell', price: 100, quantity: 500 });
  const second = cathayStockFillCost({ side: 'sell', price: 99, quantity: 500 });
  const summary = summarizeCathayTradeCosts([first, second]);
  assert.equal(first.transactionTax, 150);
  assert.equal(summary.commission, 40);
  assert.equal(summary.transactionTax, 298);
  assert.equal(summary.totalCost, 338);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
node --test tests/cathay-stock-costs.test.js
```

Expected: module-not-found failure.

- [ ] **Step 3: Implement exact cost functions**

Create `src/cathay-stock-costs.js`:

```js
export const CATHAY_TW_STOCK_COSTS_2026 = Object.freeze({
  effectiveDate: '2026-01-01',
  commissionRate: 0.000399,
  minimumCommissionTwd: 20,
  sellTaxRate: 0.003,
});

export function cathayStockFillCost({ side, price, quantity }, config = CATHAY_TW_STOCK_COSTS_2026) {
  if (!['buy', 'sell'].includes(side)) throw new Error(`invalid side: ${side}`);
  if (!(price > 0) || !(quantity > 0)) throw new Error('price and quantity must be positive');
  const consideration = Math.floor(price * quantity);
  const commission = Math.max(config.minimumCommissionTwd, Math.floor(consideration * config.commissionRate));
  const transactionTax = side === 'sell' ? Math.floor(consideration * config.sellTaxRate) : 0;
  return { side, consideration, commission, transactionTax, totalCost: commission + transactionTax };
}

export function summarizeCathayTradeCosts(rows = []) {
  return rows.reduce((sum, row) => ({
    commission: sum.commission + row.commission,
    transactionTax: sum.transactionTax + row.transactionTax,
    totalCost: sum.totalCost + row.totalCost,
  }), { commission: 0, transactionTax: 0, totalCost: 0 });
}
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
node --test tests/cathay-stock-costs.test.js
```

Expected: two tests pass.

- [ ] **Step 5: Commit the cost model**

```bash
git add src/cathay-stock-costs.js tests/cathay-stock-costs.test.js
git commit -m "Measure phase3 after the broker costs it would actually face" \
  -m "Constraint: Use Cathay public online-stock pricing and a conservative minimum
Rejected: Reusing percentage-only generic costs | Partial fills make minimum charges material
Confidence: high
Scope-risk: narrow
Tested: node --test tests/cathay-stock-costs.test.js"
```

### Task 4: Deterministic read-only L1 execution replay

**Files:**
- Create: `src/demo-execution-replay.js`
- Create: `tests/demo-execution-replay.test.js`

- [ ] **Step 1: Write failing replay tests**

Create `tests/demo-execution-replay.test.js` with separate tests for invalid chronology,
partial fill, multi-event slippage, and delayed stop:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeTickBooks, simulateMarketableOrder, simulateStopExit } from '../src/demo-execution-replay.js';

const ticks = [
  { datetime: '2026-06-01T09:00:00', close: 100, bidPrice: 99.5, bidVolume: 1, askPrice: 100, askVolume: 1 },
  { datetime: '2026-06-01T09:00:01', close: 100.5, bidPrice: 100, bidVolume: 1, askPrice: 100.5, askVolume: 1 },
];

test('buy replay records partial fills without inventing deeper liquidity', () => {
  const result = simulateMarketableOrder({
    side: 'buy', quantity: 2000, events: normalizeTickBooks(ticks, { lotSize: 1000 }),
  });
  assert.equal(result.filledQuantity, 2000);
  assert.equal(result.fills.length, 2);
  assert.equal(result.averagePrice, 100.25);
  assert.equal(result.slippagePct, 0.25);
});

test('replay rejects reversed timestamps and malformed prices', () => {
  assert.throws(() => normalizeTickBooks([ticks[1], ticks[0]]), /chronological/);
  assert.throws(() => normalizeTickBooks([{ ...ticks[0], askPrice: 0 }]), /price/);
});

test('stop remains exposed until an executable bid appears', () => {
  const events = normalizeTickBooks([
    { datetime: '2026-06-01T10:00:00', close: 92, bidPrice: 0, bidVolume: 0, askPrice: 92.5, askVolume: 10 },
    { datetime: '2026-06-01T10:03:00', close: 90, bidPrice: 89.5, bidVolume: 1, askPrice: 90, askVolume: 5 },
  ], { lotSize: 1000, allowEmptySide: true });
  const result = simulateStopExit({ quantity: 1000, stopPrice: 92, events });
  assert.equal(result.stopTriggeredAt, '2026-06-01T10:00:00');
  assert.equal(result.fills[0].price, 89.5);
  assert.equal(result.latencyMs, 180000);
  assert.ok(result.shortfallPct < 0);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
node --test tests/demo-execution-replay.test.js
```

Expected: module-not-found failure.

- [ ] **Step 3: Implement conservative replay**

Create exports with these contracts:

```js
export function normalizeTickBooks(ticks, { lotSize = 1000, allowEmptySide = false } = {}) {}
export function simulateMarketableOrder({ side, quantity, events, startIndex = 0, referencePrice } = {}) {}
export function simulateStopExit({ quantity, stopPrice, events, startIndex = 0 } = {}) {}
```

Normalization converts Shioaji tick `bidVolume` and `askVolume` from lots to shares,
sort-checks rather than silently sorting, and permits zero bid only when
`allowEmptySide` is true. The simulator consumes only displayed L1 quantity for each
event and never invents deeper levels. Residual quantity advances to later events.
Each fill includes timestamp, price, quantity, and source event index.

`simulateStopExit` triggers on `close <= stopPrice`, then sells only against later
positive bid volume. It returns trigger timestamp, fill ratio, latency, stop shortfall,
and residual quantity.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
node --test tests/demo-execution-replay.test.js
```

Expected: all replay tests pass.

- [ ] **Step 5: Commit replay primitives**

```bash
git add src/demo-execution-replay.js tests/demo-execution-replay.test.js
git commit -m "Let missing liquidity remain visible instead of fabricating fills" \
  -m "Constraint: Historical Shioaji ticks expose L1 bid and ask evidence
Rejected: Filling at crossed OHLC stop prices | It hides gaps and unavailable bids
Confidence: high
Scope-risk: moderate
Tested: node --test tests/demo-execution-replay.test.js"
```

### Task 5: Cache historical ticks and freeze replay inputs

**Files:**
- Modify: `src/shioaji-market.js`
- Modify: `tests/shioaji-market.test.js`
- Create: `src/phase3-demo-promotion.js`
- Create: `tests/phase3-demo-promotion.test.js`

- [ ] **Step 1: Write failing cache, seed, and input-hash tests**

Add a Shioaji test asserting one fetch writes a ticker/date cache and a second call
reads the same immutable payload without another HTTP request.

Create `tests/phase3-demo-promotion.test.js`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { sampleReplaySessions, hashReplayInput, PHASE3_STABILITY } from '../src/phase3-demo-promotion.js';

test('fixed seed produces identical random sessions and immutable input hash', () => {
  const dates = Array.from({ length: 40 }, (_, index) =>
    new Date(Date.UTC(2026, 3, 1 + index)).toISOString().slice(0, 10));
  assert.deepEqual(sampleReplaySessions(dates, { seed: 3005, count: 20 }), sampleReplaySessions(dates, { seed: 3005, count: 20 }));
  assert.equal(hashReplayInput({ b: 2, a: 1 }), hashReplayInput({ a: 1, b: 2 }));
});

test('phase3 signal parameters are frozen', () => {
  assert.equal(Object.isFrozen(PHASE3_STABILITY), true);
  assert.equal(PHASE3_STABILITY.period, 5);
  assert.equal(PHASE3_STABILITY.volumeMultiplier, 0.8);
  assert.equal(PHASE3_STABILITY.holdDays, 12);
  assert.equal(PHASE3_STABILITY.disasterStopPct, -0.08);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
node --test tests/shioaji-market.test.js tests/phase3-demo-promotion.test.js
```

Expected: failure because cache and promotion module exports are absent.

- [ ] **Step 3: Implement immutable tick cache and deterministic helpers**

Add `getCachedShioajiTicks()` to `src/shioaji-market.js` with a default path:

```text
.omx/cache/shioaji/replay/ticks/<YYYY-MM-DD>/<exchange>-<ticker>.json
```

Write cache files atomically and store `source`, `readOnly`, request parameters,
retrieval time, and raw normalized ticks.

In `src/phase3-demo-promotion.js`, export a deeply frozen phase3 configuration,
xorshift32 fixed-seed sampling, recursively key-sorted SHA-256 JSON hashing, and
chronological partition helpers. Use May and June 2026 as the initial untouched
holdout because the existing phase3 monthly evidence contains 106 trades there,
leaving January through April for calibration.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
node --test tests/shioaji-market.test.js tests/phase3-demo-promotion.test.js
```

Expected: all tests pass.

- [ ] **Step 5: Commit replay input freezing**

```bash
git add src/shioaji-market.js src/phase3-demo-promotion.js tests/shioaji-market.test.js tests/phase3-demo-promotion.test.js
git commit -m "Freeze replay evidence before judging phase3" \
  -m "Constraint: Final holdout cannot drift between runs
Rejected: Fetching mutable broker data during every evaluation | It prevents reproducibility
Confidence: high
Scope-risk: moderate
Tested: Shioaji market and phase3 promotion helper tests"
```

### Task 6: Fail-closed promotion evaluator and read-only command surface

**Files:**
- Modify: `src/phase3-demo-promotion.js`
- Modify: `tests/phase3-demo-promotion.test.js`
- Modify: `src/tools.js`
- Modify: `src/cli.js`
- Modify: `src/mcp-server.js`
- Modify: `tests/cli.test.js`
- Modify: `tests/mcp-server.test.js`

- [ ] **Step 1: Write failing gate and safety tests**

Add:

```js
test('promotion fails closed until every mandatory threshold passes', async () => {
  const { evaluatePhase3Promotion } = await import('../src/phase3-demo-promotion.js');
  const result = evaluatePhase3Promotion({
    validSessions: 20,
    completedTrades: 50,
    fillRatePct: 79.99,
    stopExecutionRatePct: 100,
    maxResidualExposureRatio: 1,
    totalReturnPct: 1,
    maxDrawdownPct: -10,
    deterministic: true,
    orderApiSafe: true,
    testsPassed: true,
  });
  assert.equal(result.passed, false);
  assert.deepEqual(result.failedGates, ['fill_rate']);
});

test('demo replay dependency graph rejects order API symbols', async () => {
  const { assertReplayDependencySafety } = await import('../src/phase3-demo-promotion.js');
  assert.throws(() => assertReplayDependencySafety({
    entry: 'src/phase3-demo-promotion.js',
    sources: new Map([['src/phase3-demo-promotion.js', 'broker.placeOrder(intent)']]),
  }), /order API/i);
});
```

Add CLI and MCP tests asserting:

- command/tool name is `phase3-demo-promotion`;
- output contains `executionMode: demo_replay`;
- `--live`, `--account`, `--credential`, and `--place-order` are rejected;
- no order argument exists in the MCP schema.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
node --test tests/phase3-demo-promotion.test.js tests/cli.test.js tests/mcp-server.test.js
```

Expected: failures because evaluator and command are not wired.

- [ ] **Step 3: Implement promotion orchestration**

The orchestration must:

1. run the existing market backtest with the frozen phase3 parameters;
2. attach frozen IC.TPEX `peerGroups`;
3. reject unmapped tickers;
4. load all entry-through-exit historical tick sessions needed to test the -8% stop;
5. simulate entry and exit quantities against L1 books;
6. apply Cathay costs to every fill;
7. compute valid sessions, completed trades, fill rate, stop execution rate, maximum
   residual exposure ratio, net return, and maximum drawdown;
8. evaluate thresholds exactly as specified;
9. write JSON and Markdown with seed, sample dates, hashes, rejections, partial fills,
   residuals, slippage, stop latency, stop shortfall, costs, return, and drawdown;
10. set `executionMode: 'demo_replay'` unconditionally.

The evaluator gate table is:

```js
const gates = {
  valid_sessions: metrics.validSessions >= 20,
  completed_trades: metrics.completedTrades >= 50,
  fill_rate: metrics.fillRatePct >= 80,
  stop_execution_rate: metrics.stopExecutionRatePct >= 95,
  residual_exposure: metrics.maxResidualExposureRatio <= 1,
  positive_net_return: metrics.totalReturnPct > 0,
  max_drawdown: metrics.maxDrawdownPct >= -16,
  deterministic: metrics.deterministic === true,
  order_api_safe: metrics.orderApiSafe === true,
  tests_passed: metrics.testsPassed === true,
};
```

- [ ] **Step 4: Wire the command without execution switches**

Register `phase3-demo-promotion` in `src/tools.js`, `src/cli.js`, and
`src/mcp-server.js`. Supported inputs are dates, seed, cache paths, report paths,
and refresh flags only. Reject forbidden keys before invoking the tool:

```js
const forbidden = ['live', 'account', 'credential', 'certificate', 'placeOrder', 'place-order'];
for (const key of forbidden) {
  if (args[key] !== undefined) throw new Error(`phase3-demo-promotion forbids ${key}`);
}
```

- [ ] **Step 5: Run integration tests and verify GREEN**

Run:

```bash
node --test tests/phase3-demo-promotion.test.js tests/cli.test.js tests/mcp-server.test.js
```

Expected: all tests pass.

- [ ] **Step 6: Commit the evaluator and command**

```bash
git add src/phase3-demo-promotion.js src/tools.js src/cli.js src/mcp-server.js tests/phase3-demo-promotion.test.js tests/cli.test.js tests/mcp-server.test.js
git commit -m "Make promotion depend on replay evidence rather than optimism" \
  -m "Constraint: The command may read market data but can never route an order
Rejected: Broker demo orders | Account coupling creates an avoidable live-order hazard
Confidence: high
Scope-risk: broad
Directive: Keep executionMode hard-coded to demo_replay
Tested: promotion, CLI, and MCP integration tests"
```

### Task 7: Collect holdout evidence and iterate only permitted controls

**Files:**
- Create: `.omx/reports/phase3-stability-demo-promotion.json`
- Create: `.omx/reports/phase3-stability-demo-promotion.md`
- Modify when evidence requires a permitted control: `src/phase3-demo-promotion.js`
- Modify when evidence requires a permitted control: `tests/phase3-demo-promotion.test.js`

- [ ] **Step 1: Verify the Shioaji read-only server**

Run:

```bash
curl -fsS http://127.0.0.1:8080/api/v1/health
node src/cli.js shioaji-quote --ticker 2330 --format markdown
node src/cli.js shioaji-ticks --ticker 2330 --exchange TSE --date 2026-06-18 --all true --format json >/tmp/phase3-sample-ticks.json
```

Expected: healthy server, successful quote, and a non-empty historical tick array.

- [ ] **Step 2: Freeze IC.TPEX and tick inputs**

Run:

```bash
node src/cli.js phase3-demo-promotion \
  --start-date 2026-01-01 \
  --end-date 2026-06-30 \
  --holdout-start 2026-05-01 \
  --holdout-end 2026-06-30 \
  --seed 3005 \
  --refresh-peer-cache true \
  --refresh-tick-cache true \
  --report-json .omx/reports/phase3-stability-demo-promotion.json \
  --report-markdown .omx/reports/phase3-stability-demo-promotion.md \
  --format markdown
```

Expected: an evidence report is written even when a gate fails.

- [ ] **Step 3: Re-run frozen inputs and prove determinism**

Run the same command with both refresh flags false and change the report paths to:

```bash
--report-json /tmp/phase3-promotion-rerun.json \
--report-markdown /tmp/phase3-promotion-rerun.md
```

Then compare:

```bash
node - <<'NODE'
import fs from 'node:fs';
const first = JSON.parse(fs.readFileSync('.omx/reports/phase3-stability-demo-promotion.json'));
const second = JSON.parse(fs.readFileSync('/tmp/phase3-promotion-rerun.json'));
if (first.inputHash !== second.inputHash || first.resultHash !== second.resultHash) process.exit(1);
console.log(first.resultHash);
NODE
```

Expected: identical input and result hashes.

- [ ] **Step 4: Apply only evidence-backed execution-risk iteration if needed**

If fill rate, stop execution rate, residual exposure, return, or drawdown fails,
write a failing regression test for the observed case before changing only one of:

- whole-lot position sizing;
- maximum percentage of displayed L1 volume used per event;
- minimum L1 executable value;
- maximum stop residual holding time;
- no-entry rule when opening spread exceeds the measured threshold.

Do not change HMA period, volume multiplier, hold days, entry mode, close-position
threshold, price-change threshold, disaster-stop percentage, drawdown threshold, or
promotion thresholds. Re-run Tasks 4 through 7 after each permitted change and keep
each failed report with a numeric suffix.

- [ ] **Step 5: Commit evidence**

```bash
git add .omx/reports/phase3-stability-demo-promotion.json .omx/reports/phase3-stability-demo-promotion.md
git commit -m "Record whether phase3 survives executable market conditions" \
  -m "Constraint: Holdout evidence is immutable and demo-only
Rejected: Reporting daily-bar returns as executable returns | It ignores liquidity and costs
Confidence: high
Scope-risk: narrow
Tested: Fixed-seed rerun with matching input and result hashes"
```

### Task 8: Promote exactly one strategy only after a passing report

**Files:**
- Modify: `docs/standard-workflow-v1.md`
- Modify: `.omx/project-memory.json`
- Modify: `tests/cli.test.js`
- Modify: `tests/mcp-server.test.js`
- Delete: `.omx/backtests/MVP_R18H6_VOL_exit_only_WR3.md`
- Delete: `.omx/backtests/mvp-r18h6-vol-exit-only-wr3-2025-06-01_2026-06-17.json`

- [ ] **Step 1: Assert the report passed before editing workflow state**

Run:

```bash
node - <<'NODE'
import fs from 'node:fs';
const report = JSON.parse(fs.readFileSync('.omx/reports/phase3-stability-demo-promotion.json'));
if (report.executionMode !== 'demo_replay') throw new Error('unexpected execution mode');
if (report.promotion?.passed !== true) throw new Error(`promotion blocked: ${(report.promotion?.failedGates || []).join(', ')}`);
console.log(report.resultHash);
NODE
```

Expected: exit zero. If it fails, stop this task without deleting or promoting any
strategy; the evidence report is the completion artifact for the failed iteration.

- [ ] **Step 2: Write failing sole-strategy regression tests**

Add tests that read the workflow and project memory and assert:

```js
assert.match(workflow, /phase3_stability/);
assert.doesNotMatch(workflow, /R18H6_VOL_exit_only_WR3/);
assert.equal(memory.standing_instructions.filter((row) => row.id === 'current-main-strategy').length, 1);
assert.match(JSON.stringify(memory.standing_instructions.find((row) => row.id === 'current-main-strategy')), /phase3_stability/);
assert.doesNotMatch(JSON.stringify(memory), /R18H6_VOL_exit_only_WR3/);
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
node --test tests/cli.test.js tests/mcp-server.test.js
```

Expected: failure because Standard Workflow 1.01 still names the old MVP.

- [ ] **Step 4: Promote phase3 and remove the replaced strategy**

Update `docs/standard-workflow-v1.md` to a new version that names
`phase3_stability` as the only main strategy, embeds the exact frozen parameters,
links the passing replay report, and states that execution remains `demo_replay`.
Remove old sidecar language that allows overlapping strategy choices.

Update `.omx/project-memory.json` by replacing `current-mvp-strategy` with exactly one
`current-main-strategy` instruction for `phase3_stability`, updating the workflow
version and timestamp, and removing old strategy references.

Delete both old canonical MVP backtest files. Git history and the promotion report
remain the audit trail; no executable baseline remains.

- [ ] **Step 5: Run tests and sole-strategy scans**

Run:

```bash
npm test
rg -n "R18H6_VOL_exit_only_WR3|ticker_prefix_2|ticker\\.slice\\(0, 2\\)" src tests docs .omx/project-memory.json \
  --glob '!docs/superpowers/specs/2026-07-09-phase3-stability-demo-promotion-design.md' \
  --glob '!.omx/reports/phase3-stability-demo-promotion.md'
rg -n "placeOrder|place_order|updateOrder|update_order|cancelOrder|cancel_order" \
  src/phase3-demo-promotion.js src/demo-execution-replay.js src/cathay-stock-costs.js src/ic-tpex-peer-groups.js
```

Expected: full suite passes; all scans return no matches.

- [ ] **Step 6: Commit sole-strategy promotion**

```bash
git add docs/standard-workflow-v1.md .omx/project-memory.json tests/cli.test.js tests/mcp-server.test.js
git add -u .omx/backtests
git commit -m "Use the one strategy that passed executable replay evidence" \
  -m "Constraint: Trading decisions must not combine or overlap multiple strategies
Rejected: Keeping the replaced MVP as a runnable baseline | The user requires one strategy only
Confidence: high
Scope-risk: broad
Directive: phase3_stability remains demo_replay until a separate explicit live-order project is approved
Tested: Full npm test, sole-strategy scan, peer-prefix scan, and order-API safety scan"
```

### Task 9: Final adversarial verification

**Files:**
- Verify only; fix the smallest responsible file if a check fails.

- [ ] **Step 1: Run targeted tests**

```bash
node --test \
  tests/ic-tpex.test.js \
  tests/ic-tpex-peer-groups.test.js \
  tests/cathay-stock-costs.test.js \
  tests/demo-execution-replay.test.js \
  tests/phase3-demo-promotion.test.js \
  tests/strategy-market-backtest.test.js \
  tests/strategy-universe.test.js \
  tests/shioaji-market.test.js
```

- [ ] **Step 2: Run complete tests**

```bash
npm test
```

- [ ] **Step 3: Validate report schema and thresholds**

```bash
node - <<'NODE'
import fs from 'node:fs';
const report = JSON.parse(fs.readFileSync('.omx/reports/phase3-stability-demo-promotion.json'));
const required = ['validSessions', 'completedTrades', 'fillRatePct', 'stopExecutionRatePct', 'totalReturnPct', 'maxDrawdownPct'];
for (const key of required) if (!Number.isFinite(report.metrics?.[key])) throw new Error(`missing metric ${key}`);
if (report.executionMode !== 'demo_replay') throw new Error('unsafe execution mode');
if (!report.inputHash || !report.resultHash) throw new Error('missing reproducibility hashes');
console.log(JSON.stringify({ promotion: report.promotion, metrics: report.metrics }, null, 2));
NODE
```

- [ ] **Step 4: Inspect final diff and repository state**

```bash
git diff --check
git status --short
git log --oneline -12
```

- [ ] **Step 5: Report evidence without overstating promotion**

If the report passed, state that `phase3_stability` is the sole demo-only main
strategy and quote the measured replay metrics. If it failed, state that promotion
did not occur, list failed gates, and identify the exhausted or missing historical
evidence. Never describe a failed or incomplete replay as production-ready.
