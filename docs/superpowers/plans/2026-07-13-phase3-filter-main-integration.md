# Phase 3 Pure Filter Main Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Phase 3 prediction stack with one deterministic, decision-time-only `phase3-screen` strategy and integrate it safely into `main`.

**Architecture:** A pure `phase3-filter` owns hard gates and bounded ranking adjustments. `phase3-candidates` creates outcome-free point-in-time observations, while `phase3-screen` is the only public strategy service and CLI/MCP entry. Model, walk-forward, promotion, and prediction-research paths are deleted rather than disabled.

**Tech Stack:** Node.js 20 ESM, built-in `node:test`, existing CLI/tool/MCP registries, existing point-in-time evidence store and HMA indicators.

---

### Task 1: Lock the approved Phase 3 gate behavior

**Files:**
- Create: `tests/phase3-filter.test.js`
- Create: `src/phase3-filter.js`

- [ ] **Step 1: Write failing tests for the frozen hard gates**

Create fixtures whose `featureNames` and `features` include `hma9SlopePct`, `hma20SlopePct`, `closeToHma9Pct`, raw `averageTurnover`, `momentum5Pct`, `closePosition`, `volumeRatio`, `relativeMomentum3Pct`, `marketBreadth1d`, `foreignBuyStreak`, and `foreignThreeDayIntensity`. `averageTurnoverLog10` may remain diagnostic-only and must never be reconstructed into the hard liquidity gate. Assert that the baseline passes and each boundary fails with a stable code:

```js
assert.equal(evaluatePhase3Filter(baseline).eligible, true);
assert.deepEqual(evaluatePhase3Filter(withFeature('momentum5Pct', 18.01)).reasons,
  ['momentum_5d_above_maximum']);
assert.deepEqual(evaluatePhase3Filter(withFeature('closePosition', 0.721)).reasons,
  ['close_position_above_maximum']);
```

Also assert HMA9 slope `<= 0`, HMA20 slope `< 0`, close below HMA9, HMA distance `> 6`, and turnover below TWD 20 million fail closed.

- [ ] **Step 2: Run the filter test and verify RED**

Run: `node --test tests/phase3-filter.test.js`

Expected: FAIL because `src/phase3-filter.js` does not exist.

- [ ] **Step 3: Implement the frozen configuration and pure evaluator**

Export:

```js
export const PHASE3_FILTER_CONFIG = deepFreeze({
  minimumAverageTurnover: 20_000_000,
  minimumHma9SlopePct: 0,
  minimumHma20SlopePct: 0,
  minimumCloseToHma9Pct: 0,
  maximumHmaDistancePct: 6,
  maximumMomentum5Pct: 18,
  maximumClosePosition: 0.72,
});

export function evaluatePhase3Filter(candidate, config = PHASE3_FILTER_CONFIG) {
  return { eligible, reasons, diagnostics, softScore, softAdjustments };
}
```

Required data that is missing, non-numeric, or non-finite must produce a stable `missing_<feature>` reason. Candidate construction must omit sessions with no valid daily high-low range instead of fabricating `closePosition`. Soft adjustments must be individually bounded, deterministic, and unable to change `eligible`.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `node --test tests/phase3-filter.test.js`

Expected: all Phase 3 filter tests pass.

- [ ] **Step 5: Commit the behavior lock**

Stage only `src/phase3-filter.js` and `tests/phase3-filter.test.js`, then create a Lore-format commit recording the frozen thresholds and tests.

### Task 2: Make candidate generation decision-time only

**Files:**
- Modify: `src/phase3-candidates.js`
- Modify: `tests/phase3-candidates.test.js`

- [ ] **Step 1: Add failing tests that forbid future outcome fields**

Update candidate fixtures to assert the latest eligible market session can produce an observation without five future sessions:

```js
const latest = candidates.at(-1);
assert.equal(latest.decisionDate, finalFixtureSession.date);
for (const field of ['label', 'outcomeTime', 'outcomePath', 'entryPrice', 'exitPrice',
  'leadDays', 'falseSignal', 'maximumThreeSessionReturnPct']) {
  assert.equal(Object.hasOwn(latest, field), false);
}
```

Assert `decisionTime` is not earlier than any `evidenceAvailableAt` value and the candidate artifact remains deterministic.

- [ ] **Step 2: Run candidate tests and verify RED**

Run: `node --test tests/phase3-candidates.test.js`

Expected: FAIL because the current builder requires five future sessions and emits labels/outcomes.

- [ ] **Step 3: Refactor candidate construction**

Change `candidateFor` to compute only decision-time features and evidence. Remove future-session joins, labels, simulated entry/exit values, and performance fields. Replace `entryDate` with `decisionDate`. Iterate through the final market row rather than stopping five rows early. Increment `PHASE3_CANDIDATE_SCHEMA_VERSION` so stale model-era artifacts rebuild.

Do not hard-filter HMA, turnover, momentum, or close position in the builder; emit observations and let `phase3-filter` return explicit rejection reasons.

- [ ] **Step 4: Run candidate and filter tests**

Run: `node --test tests/phase3-candidates.test.js tests/phase3-filter.test.js`

Expected: all tests pass and no candidate contains future outcome fields.

- [ ] **Step 5: Commit the point-in-time candidate boundary**

Stage only the candidate source/test pair and create a Lore-format commit.

### Task 3: Add the sole Phase 3 application service

**Files:**
- Create: `src/phase3-screen.js`
- Create: `tests/phase3-screen.test.js`

- [ ] **Step 1: Write failing service tests**

Cover argument allowlisting, latest-date default behavior, explicit date windows, deterministic ranking, rejected reason reporting, report writing, and order argument rejection:

```js
assert.throws(() => assertPhase3ScreenArgs({ live: true }), /forbids live/);
assert.deepEqual(result.candidates.map((row) => row.ticker), ['A', 'B']);
assert.equal(result.executionMode, 'read_only');
```

Inject the candidate loader in tests so no network access is required.

- [ ] **Step 2: Run the service test and verify RED**

Run: `node --test tests/phase3-screen.test.js`

Expected: FAIL because the service module does not exist.

- [ ] **Step 3: Implement `runPhase3Screen` and Markdown rendering**

Export:

```js
export const PHASE3_SCREEN_INPUTS = Object.freeze([
  'evidenceRoot', 'candidateArtifact', 'startDate', 'endDate', 'top',
  'includeRejected', 'rebuild', 'reportJson', 'reportMarkdown',
]);
export function assertPhase3ScreenArgs(args = {}) { /* reject unknown keys */ }
export async function runPhase3Screen(args = {}, dependencies = {}) { /* read-only */ }
export function renderPhase3ScreenMarkdown(result) { /* candidates + reasons */ }
```

Default to `.omx/evidence/phase3`, select the latest decision date when no date range is supplied, sort eligible rows by descending `softScore` and then ticker, and include stable configuration plus artifact hashes in the result.

- [ ] **Step 4: Run service tests and verify GREEN**

Run: `node --test tests/phase3-screen.test.js tests/phase3-filter.test.js tests/phase3-candidates.test.js`

Expected: all tests pass.

- [ ] **Step 5: Commit the application service**

Stage only `src/phase3-screen.js` and `tests/phase3-screen.test.js`, then create a Lore-format commit.

### Task 4: Replace public model/promotion surfaces

**Files:**
- Modify: `src/cli.js`
- Modify: `src/tools.js`
- Modify: `src/mcp-server.js`
- Modify: `tests/cli.test.js`
- Modify: `tests/tools.test.js`
- Modify: `tests/mcp-server.test.js`

- [ ] **Step 1: Change tests to require only `phase3-screen`**

Assert CLI help, the tools registry, and MCP list contain `phase3-screen`; assert `phase3-demo-promotion` is absent. Verify the MCP schema contains only screen inputs and rejects `live`.

- [ ] **Step 2: Run public-surface tests and verify RED**

Run: `node --test tests/cli.test.js tests/tools.test.js tests/mcp-server.test.js`

Expected: FAIL because old promotion registration remains and screen registration is missing.

- [ ] **Step 3: Replace registrations and parsing**

Import `assertPhase3ScreenArgs`, `runPhase3Screen`, and `renderPhase3ScreenMarkdown`; remove the promotion imports, command branch, tool entry, and MCP schema. Register only `phase3-screen` with the exact allowlisted inputs from Task 3.

- [ ] **Step 4: Run public-surface tests and verify GREEN**

Run: `node --test tests/cli.test.js tests/tools.test.js tests/mcp-server.test.js tests/phase3-screen.test.js`

Expected: all tests pass.

- [ ] **Step 5: Commit the sole public strategy entry**

Stage the six public-surface files and create a Lore-format commit.

### Task 5: Remove prediction and promotion code without deleting shared utilities

**Files:**
- Delete: `src/logistic-regression.js`
- Delete: `src/phase3-walk-forward.js`
- Delete: `src/phase3-demo-promotion.js`
- Delete: `src/phase3-direction-labels.js`
- Delete: `src/phase3-direction-research.js`
- Delete: `src/phase3-main-audit.js`
- Delete: `src/phase3-breadth-role-comparison.js`
- Delete: `src/phase3-news-features.js`
- Delete corresponding tests under `tests/`
- Modify: `src/phase3-dataset.js`
- Modify: `tests/phase3-dataset.test.js`

- [ ] **Step 1: Add a failing no-model dependency assertion**

Update dataset tests so readiness reports evidence/candidate counts without folds, labels, positive-label counts, or model readiness. Add a repository scan asserting no source import contains `logistic-regression`, `phase3-walk-forward`, `phase3-demo-promotion`, `phase3-direction`, or `phase3-main-audit`.

- [ ] **Step 2: Run the dataset test and verify RED**

Run: `node --test tests/phase3-dataset.test.js`

Expected: FAIL while dataset readiness imports walk-forward functions.

- [ ] **Step 3: Simplify dataset reporting and delete model files**

Keep evidence collection, immutable manifests, universe loading, and decision-time candidate artifacts. Remove fold construction, label/class-distribution requirements, and prediction readiness. Delete only model/promotion-specific files and tests; retain generic point-in-time storage, IC.TPEX mapping, Shioaji readers, Cathay costs, and shared execution simulation.

- [ ] **Step 4: Scan imports and run all remaining Phase 3 tests**

Run:

```bash
rg -n "logistic-regression|phase3-walk-forward|phase3-demo-promotion|phase3-direction|phase3-main-audit" src tests
node --test tests/phase3-*.test.js
```

Expected: the scan has no hits and all remaining Phase 3 tests pass.

- [ ] **Step 5: Commit model-stack deletion**

Stage only the explicit deletion list and dataset source/test changes, then create a Lore-format commit.

### Task 6: Clean documentation and generated research noise

**Files:**
- Modify: `docs/standard-workflow-v1.md`
- Modify when tracked: `docs/line-session-handoff.md`
- Delete: model-era Phase 3 plans/specifications under `docs/superpowers/`
- Delete when tracked: model/promotion/walk-forward reports under `.omx/reports/`
- Delete when untracked and generated: `research-run/`
- Modify: `PHASE3_CLEANUP_MANIFEST.md`
- Modify: `phase3-main-allowlist.txt`
- Modify: `phase3-experiment-delete-list.txt`
- Modify: `tests/standard-workflow.test.js`

- [ ] **Step 1: Update the workflow regression test**

Assert the standard workflow names `phase3-screen`, contains `maximumClosePosition = 0.72` and `maximumMomentum5Pct = 18`, states that external information is confidence weighting only, and does not contain logistic regression, prediction thresholds, walk-forward promotion, or `phase3-demo-promotion`.

- [ ] **Step 2: Run the workflow test and verify RED**

Run: `node --test tests/standard-workflow.test.js`

Expected: FAIL against the model-era workflow document.

- [ ] **Step 3: Rewrite active documentation and remove generated noise**

Describe Phase 3 as the sole deterministic filter. Document the technical hard gates, soft ranking context, read-only data policy, and separate post-signal historical evaluation. Remove active-looking model and promotion documents/artifacts. Update the cleanup manifest and allowlist to match the retained tree exactly.

- [ ] **Step 4: Verify documentation and repository hygiene**

Run:

```bash
node --test tests/standard-workflow.test.js
rg -n "logistic_l2|phase3-demo-promotion|walk-forward promotion|prediction threshold" docs src tests
git diff --check
```

Expected: tests pass, active docs/source/tests have no model-era references, and diff check passes. Historical commit messages are outside this scan.

- [ ] **Step 5: Commit documentation cleanup**

Stage only the explicit documentation, manifest, test, and generated-artifact paths and create a Lore-format commit.

### Task 7: Verify the feature branch and review the final diff

**Files:**
- No new production files expected.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
node --test tests/phase3-filter.test.js tests/phase3-candidates.test.js \
  tests/phase3-screen.test.js tests/phase3-dataset.test.js \
  tests/cli.test.js tests/tools.test.js tests/mcp-server.test.js \
  tests/standard-workflow.test.js
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run the complete suite**

Run: `npm test`

Expected: all repository tests pass with zero failures.

- [ ] **Step 3: Run static safety and hygiene checks**

Run scans for order APIs reachable from Phase 3, deleted-model references, future outcome fields in screen output, ticker-prefix industry proxies, and `git diff --check`. Expected: no forbidden matches and no whitespace errors.

- [ ] **Step 4: Review scoped commits against the design**

Use `git diff main...HEAD --stat`, `git status --short`, and explicit commit file lists. Verify unrelated dirty files are not included in any integration commit.

- [ ] **Step 5: Obtain independent code review**

Dispatch an OMX `code-reviewer` subagent over the scoped commit range. Fix blocker/high findings, rerun affected tests, and record the review result.

### Task 8: Integrate into the clean main tree

**Files:**
- Main worktree files introduced by the scoped commit range.

- [ ] **Step 1: Reconfirm main is clean and current**

Run:

```bash
git -C /Users/chentingwei/Desktop/SideProject/trade status --short
git -C /Users/chentingwei/Desktop/SideProject/trade branch --show-current
```

Expected: no status output and branch `main`.

- [ ] **Step 2: Integrate only scoped Phase 3 commits**

Cherry-pick or merge the reviewed commits in dependency order. Do not include unrelated feature-worktree modifications or generated outputs.

- [ ] **Step 3: Resolve conflicts conservatively**

Preserve current main behavior outside the explicit Phase 3 public surfaces and documentation. Never use hard reset, clean, or broad checkout commands.

- [ ] **Step 4: Verify in the main worktree**

Run targeted tests followed by `npm test`, the order-API scan, deleted-model scan, and `git diff --check` from `/Users/chentingwei/Desktop/SideProject/trade`.

Expected: all tests pass, only `phase3-screen` is exposed, and no prediction/order path remains.

- [ ] **Step 5: Report integration evidence**

Report main commit hash, changed/deleted files by responsibility, targeted/full test counts, safety scan results, and any remaining data limitation. Do not claim predictive performance because the model path has been intentionally removed.
