# Phase 3 Cleanup Manifest

Date: 2026-07-13 (Asia/Taipei)

## Result

The repository has one active Phase 3 strategy path: the deterministic, read-only `phase3-screen` flow.

## Retained strategy files

- `src/phase3-data-collector.js` — market and institutional point-in-time evidence only.
- `src/phase3-dataset.js` — immutable evidence and quality audit.
- `src/phase3-candidates.js` — decision-time observations without future outcomes.
- `src/phase3-filter.js` — frozen hard gates and bounded soft ranking.
- `src/phase3-screen.js` — sole CLI/tool/MCP application service.
- Corresponding `tests/phase3-*.test.js` regression and safety tests.

Shared market readers, HMA indicators, IC.TPEX mapping, Cathay cost functions, point-in-time storage, and manual research tools remain because they are not prediction-model components.

## Removed strategy noise

- Logistic regression, model serialization, probability thresholds, and calibration.
- Walk-forward model training and folds.
- Direction sidecars, prediction audits, breadth-model comparisons, hybrid/news model features.
- Demo promotion and execution-certification orchestration.
- Generated prediction, walk-forward, promotion, and direction-research reports.
- Superseded model-era plans, specifications, handoffs, and research-run outputs.
- The stale workflow PNG whose source diagram no longer matched the active workflow.

Git history was not rewritten. Removed research remains auditable through historical commits but is not present in the active tree.

## Safety boundary

- Phase 3 uses only information available by `decisionTime`.
- Future sessions are not required or emitted when generating a signal.
- Optional context can rank but cannot override a hard technical failure.
- `phase3-screen` rejects execution-shaped arguments.
- Static tests verify the retained Phase 3 entry graph contains no order API vocabulary.

## Verification contract

Before integration into `main`:

1. Run all retained Phase 3 tests.
2. Run CLI, tool, MCP, and workflow tests.
3. Run the complete repository test suite.
4. Scan for removed model imports and order APIs.
5. Repeat the same checks from the main worktree after integration.
