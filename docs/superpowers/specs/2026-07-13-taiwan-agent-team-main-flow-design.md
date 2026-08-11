# Taiwan Agent Team Main Flow Design

## Status

Approved on 2026-07-13. This design promotes `taiwan-agent-team` into the official Standard Workflow 1.4 orchestration layer while preserving `phase3_stability` as the only technical stock-screening mechanism.

## Objective

Make one auditable agent-team command coordinate the latest research flow:

```text
conditional Phase 3 screening → external confidence research → DOM → four prices → verification
```

Phase 3 runs only when the user explicitly asks for stock screening or candidate discovery. Direct analysis of named tickers skips Phase 3 and must not claim technical eligibility.

## Public Modes

The team resolves one workflow mode:

- `screen`: explicit `--mode screen`, or auto-detected screening intent.
- `analyze`: explicit `--mode analyze`, or a named-ticker research request without screening intent.
- `auto`: infer from the query.

Screening intent includes bounded terms such as `選股`, `股票篩選`, `篩選股票`, `找股票`, `候選股票`, `候選名單`, `全市場掃描`, `stock screen`, and `find stocks`. Explicit `screen` or `analyze` overrides keywords.

The existing `brief` and `full` mode values remain backward-compatible detail aliases: they use auto workflow detection and retain their current output-depth behavior. New `--detail brief|full` is the unambiguous detail control.

## Seven Agent Responsibilities

1. **planner** — resolves screen/analyze intent, parameters, ordered stages, and stop conditions.
2. **data-agent** — inventories repo evidence, checks market-data calls, and updates point-in-time evidence in screen mode.
3. **strategy-agent** — calls `phase3-dataset` then `phase3-screen` only in screen mode and returns eligible candidates only.
4. **market-agent** — obtains Shioaji index/ticker snapshots, pre-open context, sector flow, and IC.TPEX peer context.
5. **external-confidence-agent** — gathers company, news, announcements, financial statements, revenue, valuation, and ETF context after targets are known.
6. **dom-agent** — calls `phase3-dom-confidence` after external research for each target and preserves all four reference prices.
7. **verifier** — records tool order, errors, data gaps, eligibility state, read-only boundaries, and reproducible scratchpad/report paths.

The JavaScript harness remains deterministic and auditable. Codex may additionally assign native subagents when the user invokes the workflow conversationally, but the repo command itself does not pretend separate processes exist.

## Screen Mode Data Flow

1. Run common market-context tools without using them to alter technical eligibility.
2. Run `phase3-dataset` with the requested evidence root/date range.
3. Run `phase3-screen` only if dataset preparation succeeds.
4. Extract `screen.candidates`; these are the only downstream targets.
5. If eligible count is zero, stop target research. Do not call research-pack, IC.TPEX ticker context, Xiaoyu ticker context, or DOM.
6. For each eligible ticker, run external confidence tools.
7. After external research for that ticker completes, run `phase3-dom-confidence`.
8. Verify and render the final report.

Rejected stocks are retained only in Phase 3 audit output when requested by the underlying screen; they never enter downstream research or DOM.

## Analyze Mode Data Flow

1. Use the explicitly supplied ticker list, retaining existing defaults only for backward compatibility when no ticker is supplied.
2. Do not call `phase3-dataset` or `phase3-screen`.
3. Mark every ticker `phase3Eligibility: not_evaluated`.
4. Run market/industry and external confidence research.
5. Run DOM after external research for each ticker.
6. Verify and render the final report.

No analyze-mode wording may imply that a ticker passed Phase 3.

## Tool Calls

Common market context:

- `shioaji-snapshots` for configured indices and target tickers;
- `preopen-brief`;
- `sector-flow`;
- `xiaoyu-etf --mode overview`.

External confidence per target:

- `research-pack` with `tw-company,tw-news,tw-announcements,tw-financials,tw-revenue,tw-valuation,xiaoyu-etf`;
- `ic-tpex-chain`;
- `xiaoyu-etf --mode stock`.

Final timing context per target:

- `phase3-dom-confidence`, read-only, after external confidence calls.

Historical `signal-study`, `daily-decision-study`, and `chip-study` are removed from the active team call list. They remain standalone diagnostics and cannot become a second current-strategy path.

## Output Contract

The result includes:

- `workflowVersion: "1.4"`;
- resolved `workflowMode` and whether screening was requested explicitly or inferred;
- seven named agent lanes and their responsibilities;
- ordered stage/tool audit;
- Phase 3 dataset/screen summaries in screen mode;
- downstream target tickers;
- per-ticker `phase3Eligibility` (`eligible` or `not_evaluated`);
- external research and industry-source availability;
- DOM score, pressure, reliability, interpretation, and risks;
- `activeEntryLimit`, `patientEntryPrice`, `takeProfitPrice`, `stopLossPrice` for every ticker with at least one valid DOM sample;
- null prices and explicit DOM gaps when no sample is valid;
- final bias/stance as evidence synthesis, never a guaranteed prediction;
- scratchpad and Markdown report paths.

## Errors and Stop Conditions

- Individual common market-context failures are recorded and do not fabricate data.
- In screen mode, a failed dataset stage prevents the screen and all target research.
- A failed Phase 3 screen prevents all target research.
- Zero eligible candidates is a valid completed result with no downstream target calls.
- Individual external research failures are recorded; DOM still runs so observable price references are not withheld.
- Individual DOM failures produce unavailable/null price output for that ticker and never trigger an order path.
- Offline mode uses artifacts only and performs no Phase 3, external, market, or DOM tool calls.

## Safety and Strategy Boundaries

- `taiwan-agent-team` is the official orchestration entry, not a new predictive model.
- `phase3-screen` remains the sole technical screening mechanism and runs only for screening intent.
- External research and DOM cannot change Phase 3 eligibility.
- Analyze mode makes no Phase 3 eligibility claim.
- Every Shioaji/DOM operation is read-only; no order API is added.
- The user manually decides and places any trade.

## Documentation Version

Update active guidance from Standard Workflow 1.3 to **Standard Workflow 1.4**. README must introduce all seven agents and show both screen and analyze commands. LINE handoff and workflow docs must describe conditional Phase 3 behavior and mandatory DOM price delivery.

## Verification

- Unit tests for mode resolution and explicit override.
- Orchestration tests proving screen-mode call order and eligible-only downstream calls.
- Tests proving zero eligible candidates stop research/DOM.
- Analyze-mode tests proving Phase 3 is not called and eligibility is `not_evaluated`.
- Tests proving research precedes DOM and all four prices render.
- CLI/MCP schema tests for `mode` and `detail`.
- Guidance tests for Standard Workflow 1.4 and seven README agent descriptions.
- Full test suite, diff checks, order-path scan, injected smoke, and independent code review before local main integration and authorized GitHub main push.
