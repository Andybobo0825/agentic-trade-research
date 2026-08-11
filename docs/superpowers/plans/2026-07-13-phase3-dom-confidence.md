# Phase 3 DOM Confidence Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only three-sample Shioaji DOM confidence overlay that runs after Phase 3 and external research and always returns available entry, waiting, take-profit, and stop-loss reference prices.

**Architecture:** A focused `phase3-dom-confidence` module owns pure depth math, multi-sample scoring, price-reference selection, sampling orchestration, and Markdown output. It calls the existing `getShioajiOrderBook()` reader through dependency injection, remains separate from Phase 3 candidates/filter/dataset, and is exposed through one closed CLI/tool/MCP command.

**Tech Stack:** Node.js 20 ESM, built-in `node:test`, existing Shioaji HTTP/SSE reader, existing CLI/tool/MCP registries.

---

### Task 1: Lock pure DOM pressure and confidence behavior

**Files:**
- Create: `tests/phase3-dom-confidence.test.js`
- Create: `src/phase3-dom-confidence.js`

- [ ] **Step 1: Write failing tests for one-snapshot depth math**

Create normalized five-level fixtures and import the wished-for API:

```js
import {
  PHASE3_DOM_CONFIG,
  evaluateDomSnapshot,
  evaluateDomConfidence,
} from '../src/phase3-dom-confidence.js';

const bullish = {
  code: '2330', date: '2026-07-13', time: '10:00:00', suspend: false,
  bids: [
    { price: 100, volume: 100, diffVolume: 10 },
    { price: 99.5, volume: 80, diffVolume: 5 },
  ],
  asks: [
    { price: 100.5, volume: 20, diffVolume: -5 },
    { price: 101, volume: 10, diffVolume: 0 },
  ],
};

test('weights near DOM levels and calculates bounded buy pressure', () => {
  const result = evaluateDomSnapshot(bullish, { ticker: '2330' });
  assert.equal(result.valid, true);
  assert.ok(result.weightedBidDepth > result.weightedAskDepth);
  assert.ok(result.depthImbalance > 0);
  assert.ok(result.pressure > 0 && result.pressure <= 1);
});
```

Also test ticker mismatch, suspended rows, crossed books, empty sides, and negative displayed volume return stable invalid reasons.

- [ ] **Step 2: Run the test and verify RED**

Run: `node --test tests/phase3-dom-confidence.test.js`

Expected: FAIL because `src/phase3-dom-confidence.js` does not exist.

- [ ] **Step 3: Implement the frozen config and snapshot evaluator**

Implement:

```js
export const PHASE3_DOM_CONFIG = deepFreeze({
  samples: 3,
  intervalMs: 5000,
  timeoutMs: 3000,
  levelWeights: [5, 4, 3, 2, 1],
  activeEntryMinimumScore: 65,
});

export function evaluateDomSnapshot(orderBook, { ticker, capturedAt } = {}) {
  // Strictly validate code, suspend, positive finite prices/volumes, and bid < ask.
  // weightedDepth = sum(volume * levelWeight)
  // depthImbalance = (bidDepth - askDepth) / (bidDepth + askDepth)
  // changePressure = (weightedBidDiff - weightedAskDiff)
  //   / (abs(weightedBidDiff) + abs(weightedAskDiff)), with zero fallback.
  // pressure = clamp(depthImbalance * 0.8 + changePressure * 0.2, -1, 1)
}
```

Never coerce `null`, strings, booleans, or negative displayed volume into valid numbers.

- [ ] **Step 4: Add failing multi-sample scoring tests**

Assert three bullish samples produce persistent buy pressure, three bearish samples produce persistent sell pressure, mixed samples are balanced, and every score/adjustment is bounded:

```js
const result = evaluateDomConfidence([bull1, bull2, bull3]);
assert.equal(result.pressureLabel, 'strong_buy_pressure');
assert.equal(result.persistence, 1);
assert.ok(result.domConfidenceScore >= 70);
assert.equal(result.domConfidenceAdjustment, 8);
```

Lock the scoring formula:

```text
score = clamp(round(50 + 40 * meanPressure + 10 * signedPersistence), 0, 100)
adjustment = +8 / +4 / 0 / -2 / -5 by score band
```

- [ ] **Step 5: Implement minimal multi-sample scoring and verify GREEN**

Implement `evaluateDomConfidence()` with labels:

- score `>= 70`: `strong_buy_pressure`
- score `>= 58`: `buy_pressure`
- score `> 42`: `balanced`
- score `> 30`: `sell_pressure`
- otherwise: `strong_sell_pressure`

Reliability is `high` for three valid samples, `medium` for two, `low` for one, and `unavailable` for zero. Run:

`node --test tests/phase3-dom-confidence.test.js`

Expected: all pure evaluator tests pass.

- [ ] **Step 6: Commit the pure behavior**

Create a Lore commit containing only the new module/test behavior lock.

### Task 2: Always produce auditable reference prices when depth exists

**Files:**
- Modify: `src/phase3-dom-confidence.js`
- Modify: `tests/phase3-dom-confidence.test.js`

- [ ] **Step 1: Write failing tests for all four price outputs**

Use a final snapshot where the strongest bid wall is level 2 and strongest ask wall is level 3. Assert:

```js
assert.deepEqual(result.referencePrices, {
  activeEntryLimit: 100.5,
  patientEntryPrice: 99.5,
  takeProfitPrice: 101,
  stopLossPrice: 99,
  stopReliability: 'normal',
});
```

Add a bearish-score test asserting `activeEntryLimit` changes to best bid but all four fields remain present. Add a lowest-visible-support case expecting `stopReliability: 'low'` rather than an invented lower price.

- [ ] **Step 2: Run the targeted tests and verify RED**

Run: `node --test --test-name-pattern='reference|weak DOM' tests/phase3-dom-confidence.test.js`

Expected: FAIL because reference-price selection is absent.

- [ ] **Step 3: Implement reference-price selection**

Select only prices already present in the latest valid snapshot:

```js
activeEntryLimit = score >= 65 ? asks[0].price : bids[0].price;
patientEntryPrice = bids[indexOfMax(volume * levelWeight)].price;
takeProfitPrice = asks[Math.max(0, askWallIndex - 1)].price;
stopLossPrice = bids[Math.min(bids.length - 1, bidWallIndex + 1)].price;
```

Return source level indexes and volumes alongside the prices. Never omit prices solely because interpretation is `wait_near_support`.

- [ ] **Step 4: Verify GREEN and commit**

Run: `node --test tests/phase3-dom-confidence.test.js`

Expected: all DOM confidence tests pass. Commit the reference-price behavior in Lore format.

### Task 3: Add three-sample read-only orchestration

**Files:**
- Modify: `src/phase3-dom-confidence.js`
- Modify: `tests/phase3-dom-confidence.test.js`

- [ ] **Step 1: Write failing orchestration tests**

Inject `getOrderBook`, `sleep`, and `now`:

```js
const calls = [];
const result = await runPhase3DomConfidence({ ticker: '2330' }, {
  getOrderBook: async () => ({ readOnly: true, data: snapshots[calls.length] }),
  sleep: async (ms) => calls.push(ms),
  now: () => new Date('2026-07-13T02:00:00.000Z'),
});
assert.equal(result.requestedSampleCount, 3);
assert.equal(result.validSampleCount, 3);
assert.deepEqual(calls, [5000, 5000]);
```

Add tests for one timeout plus two valid samples, all failures returning structured `unavailable`, and unknown/order arguments failing before `getOrderBook` is called.

- [ ] **Step 2: Run and verify RED**

Run: `node --test --test-name-pattern='samples|timeout|unavailable|arguments' tests/phase3-dom-confidence.test.js`

Expected: FAIL because the application service does not exist.

- [ ] **Step 3: Implement the application service**

Export:

```js
export const PHASE3_DOM_INPUTS = Object.freeze([
  'ticker', 'exchange', 'samples', 'intervalMs', 'timeoutMs',
  'reportJson', 'reportMarkdown',
]);

export function assertPhase3DomArgs(args = {}) { /* closed schema and bounds */ }
export async function runPhase3DomConfidence(args = {}, dependencies = {}) { /* sample loop */ }
export function renderPhase3DomConfidenceMarkdown(result) { /* metrics and prices */ }
```

Default to the existing `getShioajiOrderBook`, use two injected waits for three calls, catch individual failures, preserve every sample audit row, and hash the result core. JSON/Markdown report writes use atomic temporary files.

- [ ] **Step 4: Verify GREEN and commit**

Run: `node --test tests/phase3-dom-confidence.test.js tests/shioaji-market.test.js`

Expected: all tests pass and unsubscribe behavior remains covered. Commit in Lore format.

### Task 4: Expose the command through CLI, tools, and MCP

**Files:**
- Modify: `src/cli.js`
- Modify: `src/tools.js`
- Modify: `src/mcp-server.js`
- Modify: `tests/cli.test.js`
- Modify: `tests/tools.test.js`
- Modify: `tests/mcp-server.test.js`

- [ ] **Step 1: Write failing public-surface tests**

Assert help/tools/MCP include `phase3-dom-confidence`, require `ticker`, expose only exchange/sample/interval/timeout/report options, and reject `live`, `order`, and unknown properties.

```js
assert.match(help, /phase3-dom-confidence/);
assert.ok(tools['phase3-dom-confidence']);
assert.equal(schema.additionalProperties, false);
assert.deepEqual(schema.required, ['ticker']);
```

- [ ] **Step 2: Run and verify RED**

Run: `node --test tests/cli.test.js tests/tools.test.js tests/mcp-server.test.js`

Expected: FAIL because the command is not registered.

- [ ] **Step 3: Wire the public command**

Add CLI kebab-to-camel mapping, tool registration using `runPhase3DomConfidence`, Markdown rendering, and a closed MCP schema. Keep `phase3-screen` unchanged and deterministic.

- [ ] **Step 4: Verify GREEN and commit**

Run: `node --test tests/cli.test.js tests/tools.test.js tests/mcp-server.test.js tests/phase3-dom-confidence.test.js`

Expected: all public-surface tests pass. Commit in Lore format.

### Task 5: Integrate the post-research workflow and safety regression

**Files:**
- Modify: `docs/standard-workflow-v1.md`
- Modify: `docs/line-session-handoff.md`
- Modify: `README.md`
- Modify: `tests/standard-workflow.test.js`
- Modify: `tests/phase3-cleanup.test.js`

- [ ] **Step 1: Write failing workflow and safety tests**

Assert active guidance orders the flow as Phase 3, external confidence research, then DOM; explicitly states DOM does not enter Phase 3 data/eligibility; and requires all four price fields even for a wait conclusion. Extend the Phase 3 entry-graph scan to the new DOM module and forbid all order API calls/imports.

- [ ] **Step 2: Run and verify RED**

Run: `node --test tests/standard-workflow.test.js tests/phase3-cleanup.test.js`

Expected: FAIL because active guidance and the safety graph do not mention the new overlay.

- [ ] **Step 3: Update active guidance**

Document this exact sequence:

```text
phase3-dataset → phase3-screen → news/earnings/financial confidence
→ phase3-dom-confidence → manual decision
```

State that DOM returns `activeEntryLimit`, `patientEntryPrice`, `takeProfitPrice`, and `stopLossPrice` whenever at least one valid depth sample exists, including when interpretation is to wait.

- [ ] **Step 4: Verify GREEN and commit**

Run: `node --test tests/standard-workflow.test.js tests/phase3-cleanup.test.js`

Expected: workflow and safety tests pass. Commit in Lore format.

### Task 6: Full verification, independent review, and main integration

**Files:**
- Verify all files changed above

- [ ] **Step 1: Run targeted verification**

```sh
node --test tests/phase3-dom-confidence.test.js tests/shioaji-market.test.js \
  tests/cli.test.js tests/tools.test.js tests/mcp-server.test.js \
  tests/standard-workflow.test.js tests/phase3-cleanup.test.js
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run complete verification**

```sh
npm test
git diff --check main..HEAD
rg -n "place_order|placeOrder|submitOrder|buyOrder|sellOrder" src/phase3-dom-confidence.js
```

Expected: full suite passes, diff is clean, and no order call/import appears.

- [ ] **Step 3: Run a dependency-injected three-sample smoke**

Use a local Node ESM script with three normalized fixtures and zero-delay injected sleep. Assert all four price fields, `readOnly: true`, and a 64-character result hash.

- [ ] **Step 4: Request independent review**

Ask a `code-reviewer` to inspect the complete `main..HEAD` range for scoring correctness, fail-closed input handling, mandatory price delivery, no dataset contamination, no order path, and documentation consistency. Resolve every blocker/high/medium finding with test-first fixes.

- [ ] **Step 5: Integrate and reverify**

Fast-forward the approved branch into local `main`, delete the integration branch, and rerun the full suite plus the smoke/static checks from `main`. Leave the worktree clean and report that remote push was not performed unless explicitly requested.
