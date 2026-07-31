# Taiwan Agent Team Workflow

A Dexter-inspired Taiwan investment research harness that **adds** an agent-team layer on top of the existing repo tools. It does not delete, replace, or weaken Standard Workflow 1.01, Shioaji, preopen, Xiaoyu ETF, or MVP backtest flows.

## Command

```bash
node src/cli.js taiwan-agent-team \
  --query "盤前、回測、量價、ETF 籌碼與明日情境" \
  --tickers 2330,00981A,00991A,4915 \
  --capital 500000 \
  --format markdown
```

Offline artifact-only mode:

```bash
node src/cli.js taiwan-agent-team --query "整合既有資料" --offline --format markdown
```

## Dexter mapping

This is a **Dexter-inspired deterministic orchestration layer**, not a separate autonomous multi-agent runtime. The repo keeps one auditable process that labels each responsibility as an agent lane, calls existing tools, persists a scratchpad, then renders a report.

- planner: decomposes the research question into reproducible tasks.
- data-agent: inventories `.omx` caches, reports, backtests, and repo workflows.
- market-agent: calls Shioaji snapshots, preopen, and sector flow when online.
- strategy-agent: reads MVP/backtest artifacts and runs per-ticker research packs.
- etf-agent: integrates Xiaoyu ETF lens.
- scenario-agent: produces bull/base/bear scenario triggers.
- verifier: writes JSONL scratchpad and records data gaps.

## Artifacts

- Scratchpad: `.omx/agent-team/scratchpad/*.jsonl`
- Markdown report: `.omx/agent-team/reports/*-taiwan-agent-team.md`

Generated artifacts are audit logs. Keep recent runs for review, but rotate or archive old scratchpads/reports if `.omx/agent-team` grows too large.

## Boundaries

- Shioaji remains primary for Taiwan price/volume.
- Forecasts are scenario branches, not guaranteed predictions.
- Existing workflows are called/read; this harness does not overwrite them.
