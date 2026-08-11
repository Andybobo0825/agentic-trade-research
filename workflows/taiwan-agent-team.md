# Taiwan Agent Team Workflow

A Dexter-inspired Taiwan investment research harness that follows Standard Workflow 1.4. `phase3_stability` (via `phase3-dataset` + `phase3-screen`) is the sole technical strategy, with Shioaji, preopen, and Xiaoyu ETF remaining in their defined supporting roles.

## Command

```bash
node src/cli.js taiwan-agent-team --mode screen --format markdown
node src/cli.js taiwan-agent-team --mode analyze --tickers 2330 --format markdown
```

Offline artifact-only mode:

```bash
node src/cli.js taiwan-agent-team --query "整合既有資料" --offline --format markdown
```

## Dexter mapping

This is a **Dexter-inspired deterministic orchestration layer**, not a separate autonomous multi-agent runtime. The repo keeps one auditable process that labels each responsibility as an agent lane, calls existing tools, persists a scratchpad, then renders a report.

- `planner`: Resolve screen/analyze intent, parameters, stage order, and stop conditions.
- `data-agent`: Inventory repository evidence and prepare point-in-time data in screen mode.
- `strategy-agent`: Run Phase 3 dataset and technical screening only for stock-screening requests.
- `market-agent`: Collect read-only index, ticker, pre-open, sector, and peer context.
- `external-confidence-agent`: Collect company, news, announcement, financial, revenue, valuation, ETF, and Gooaye topic evidence.
- `dom-agent`: Read Shioaji DOM after research and preserve four manual reference prices.
- `verifier`: Audit order, failures, eligibility boundaries, redaction, and read-only safety.

Only stock-screening requests run Phase 3; direct ticker analysis in `analyze` mode skips Phase 3. Only eligible candidates proceed to external research and DOM confirmation; zero eligible candidates stop the flow before DOM.

## Artifacts

- Scratchpad: `.omx/agent-team/scratchpad/*.jsonl`
- Markdown report: `.omx/agent-team/reports/*-taiwan-agent-team.md`

Generated artifacts are audit logs. Keep recent runs for review, but rotate or archive old scratchpads/reports if `.omx/agent-team` grows too large.

## Boundaries

- Shioaji remains primary for Taiwan price/volume.
- Forecasts are scenario branches, not guaranteed predictions.
- Existing workflows are called/read; this harness does not overwrite them.
