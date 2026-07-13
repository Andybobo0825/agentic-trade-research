# Phase 3 Pure Filter Main Integration Design

## Goal

Remove the Phase 3 prediction-model research stack, preserve the deterministic Phase 3 technical screening strategy, and make that screen the repository's single active strategy path on `main`.

## Scope

This change is intentionally limited to Phase 3 strategy selection and its public command surfaces. It does not add automated order placement, portfolio execution, a new prediction model, or a replacement research framework.

## Decisions

1. Phase 3 becomes a deterministic screen, not a probability model.
2. A signal may use only information available at its decision time.
3. Historical outcomes are evaluated after signal generation and must not be required to create a signal.
4. Market breadth, peer context, foreign-flow continuity, and similar context may rank or softly penalize candidates; they do not silently become new hard gates.
5. The fixed anti-chase controls remain `maximumMomentum5Pct = 18` and `maximumClosePosition = 0.72`.
6. The base technical screen retains HMA9 trigger, HMA20 regime, maximum 6% distance above HMA9, and minimum average turnover of TWD 20 million.
7. The strategy is read-only. No Phase 3 module or command may import or call a broker order API.
8. `phase3-screen` is the only public Phase 3 strategy command after the migration.

## Architecture

### `src/phase3-filter.js`

Owns the frozen Phase 3 configuration and pure decision-time evaluation. It accepts normalized technical observations and returns a structured result containing:

- `eligible`: whether all hard technical gates passed;
- `reasons`: stable reason codes for every failed hard gate;
- `diagnostics`: the calculated values used by the decision;
- `softScore`: a deterministic ranking score whose bounded adjustments cannot turn an ineligible observation into an eligible one.

The module does not load files, train models, inspect future sessions, or perform execution simulation.

### `src/phase3-candidates.js`

Builds decision-time observations from point-in-time market and institutional records. Candidate construction stops at the decision session. Future highs, lows, labels, breakout days, outcome timestamps, and realized returns are excluded from the live candidate schema.

Historical evaluation code may join later sessions to already-created signals in a separate module, but that join cannot affect the original signal artifact or hash.

### `src/phase3-screen.js`

Provides the application service for the CLI and MCP tool. It loads or refreshes read-only evidence, builds decision-time candidates, applies `phase3-filter`, sorts eligible candidates by deterministic score and ticker, and emits JSON or Markdown with pass/fail reasons. It rejects live/order arguments and contains no broker execution dependency.

### Public surfaces

The CLI, tools registry, and MCP schema expose `phase3-screen`. The former `phase3-demo-promotion` command is removed rather than retained as an alias, preventing two overlapping Phase 3 workflows.

## Retained Components

- HMA indicator utilities.
- Point-in-time market and institutional evidence storage required by the screen.
- IC.TPEX peer-group mapping as optional context.
- Shioaji and public market-data readers.
- Cathay fee utilities for separate historical performance reporting.
- General-purpose repository modules that are used outside prediction research.

## Removed Components

- `src/logistic-regression.js` and its tests.
- Continuous walk-forward model training, calibration, thresholds, probability output, and model serialization.
- Direction-label and direction-research sidecars.
- Prediction audit/export modules.
- Breadth-role model comparison.
- Model-specific news features.
- Demo promotion and execution-certification orchestration.
- Generated prediction, promotion, walk-forward, and direction-research artifacts.
- Superseded Phase 3 model plans/specifications that would otherwise remain active-looking documentation.

Generic point-in-time storage, market readers, peer mapping, cost functions, and execution simulators used by non-Phase-3 features are not deleted merely because prediction research imported them.

## Data Flow

1. Read market and institutional records whose `availableAt` is not later than the decision time.
2. Compute HMA9, HMA20, turnover, volume, momentum, close position, foreign-flow continuity, and context diagnostics.
3. Create an immutable decision-time candidate without outcome fields.
4. Apply the Phase 3 hard gates.
5. Apply bounded context adjustments only to ranking.
6. Return eligible candidates and rejected candidates with explicit reason codes.
7. If historical performance is requested, join future sessions only after the signal artifact is frozen.

## Error Handling and Safety

- Invalid dates, non-finite required values, missing HMA history, or missing liquidity evidence fail closed with explicit reason codes.
- Optional context absence produces a neutral adjustment and a diagnostic, not fabricated data.
- CLI and MCP schemas reject `live`, `order`, `placeOrder`, and equivalent execution arguments.
- A static dependency test scans the Phase 3 entry graph for order-API imports and calls.
- Deterministic input produces byte-stable candidate ordering and hashes.

## Main-Tree Integration

The feature worktree contains mixed historical research changes, so integration must use scoped commits only. The process is:

1. Commit only the pure-filter implementation, tests, public-surface updates, documentation, and explicit prediction-file deletions.
2. Rebase or merge against the current clean `main` without resetting either worktree.
3. Resolve conflicts by preserving unrelated `main` behavior.
4. Run targeted Phase 3 tests and the complete test suite in the main worktree.
5. Update the standard workflow to name `phase3-screen` as the sole active strategy and remove model/promotion claims.

No untracked research output or unrelated modified file from the feature worktree may enter `main` implicitly.

## Testing

Regression tests lock the existing approved gates before extraction:

- HMA9/HMA20 trend eligibility;
- minimum average turnover;
- maximum 6% HMA distance;
- maximum five-day momentum of 18%;
- maximum close position of 0.72;
- soft context cannot override a hard failure;
- no future fields are required or emitted by signal generation;
- missing required data fails closed with a reason;
- deterministic ranking and output;
- CLI/tool/MCP expose only `phase3-screen`;
- Phase 3 dependency graph contains no order API;
- removed prediction modules have no remaining imports;
- full repository test suite passes after main integration.

## Completion Criteria

The work is complete when `main` contains one documented Phase 3 screen, all prediction-model and promotion paths are absent, `phase3-screen` works from read-only decision-time data, no order API is reachable, and targeted plus full tests pass in the main worktree.
