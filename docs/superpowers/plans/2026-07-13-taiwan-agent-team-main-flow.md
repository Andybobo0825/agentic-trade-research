# Taiwan Agent Team Standard Workflow 1.4 Implementation Plan

> **For Codex:** Execute this plan task-by-task with test-first development, fresh verification, Lore commits, and no order-capable broker calls.

**Goal:** Promote `taiwan-agent-team` to the official deterministic orchestration entry for conditional Phase 3 screening, external confidence research, read-only DOM confidence, and four reference prices.

**Architecture:** Keep `phase3-screen` as the sole eligibility mechanism. Resolve screen/analyze intent before tool execution, run common context independently, allow only eligible screen candidates downstream, run external research before DOM for each target, and synthesize one auditable report across seven named logical agents.

**Tech Stack:** Node.js ES modules, built-in `node:test`, existing CLI/MCP tool registry, Markdown/SVG/draw.io documentation.

---

## Task 1: Lock public intent and input behavior

**Files:**
- Modify: `tests/taiwan-agent-team.test.js`
- Modify: `tests/cli.test.js`
- Modify: `tests/mcp-server.test.js`
- Modify: `src/taiwan-agent-team.js`
- Modify: `src/cli.js`

**Steps:**
1. Add failing tests for auto screen keywords, auto analyze behavior, and explicit overrides.
2. Add failing schema/CLI tests for `mode=auto|screen|analyze`, legacy `brief|full`, `detail=brief|full`, and `evidenceRoot`.
3. Run targeted tests and confirm RED for missing public behavior.
4. Implement `resolveTaiwanAgentTeamMode`, parsing, schema, and request normalization.
5. Re-run targeted tests until GREEN.
6. Commit with Lore trailers.

## Task 2: Implement seven-agent staged orchestration

**Files:**
- Modify: `tests/taiwan-agent-team.test.js`
- Modify: `src/taiwan-agent-team.js`

**Steps:**
1. Add failing analyze-mode test proving no `phase3-dataset`/`phase3-screen`, `not_evaluated` eligibility, external-first ordering, DOM values, and all four prices.
2. Add failing screen-mode test proving `phase3-dataset → phase3-screen`, candidate extraction, eligible-only target calls, and per-target research-before-DOM order.
3. Add failing zero-candidate test proving no ticker snapshot, research, industry, ticker ETF, or DOM calls.
4. Add failing failure-boundary tests: dataset failure stops screening; external failure does not suppress DOM; DOM failure returns explicit null prices.
5. Run targeted tests and confirm RED.
6. Refactor the flat tool-call loop into recorded stages with stable audit ordering and seven named logical agents.
7. Remove legacy signal/daily-decision/chip studies from active research include list.
8. Preserve inventory/backtest artifact reading as audit evidence, not a parallel strategy.
9. Render workflow version, mode, eligibility, target results, DOM metadata, and four price fields.
10. Run targeted tests until GREEN.
11. Commit with Lore trailers.

## Task 3: Promote public CLI/MCP/tool surfaces

**Files:**
- Modify: `tests/cli.test.js`
- Modify: `tests/mcp-server.test.js`
- Modify: `tests/tools.test.js` if registry assertions require it
- Modify: `src/cli.js`
- Modify: `src/tools.js`

**Steps:**
1. Add or finish failing assertions for official orchestration wording and supported arguments.
2. Update CLI help and MCP/tool descriptions.
3. Run CLI/MCP/tool tests until GREEN.
4. Commit with Lore trailers.

## Task 4: Publish Standard Workflow 1.4 guidance and seven-agent README

**Files:**
- Modify: `tests/standard-workflow.test.js`
- Modify: `README.md`
- Modify: `docs/standard-workflow-v1.md`
- Modify: `docs/line-session-handoff.md`
- Modify: `workflows/taiwan-agent-team.md`
- Modify: `docs/diagrams/standard-workflow-v1.drawio`
- Modify: `docs/diagrams/standard-workflow-v1.svg`

**Steps:**
1. Add failing documentation tests for version 1.4, the official `taiwan-agent-team` entry, conditional Phase 3 behavior, and all seven agent names.
2. Run documentation tests and confirm RED.
3. Update README with seven concise agent descriptions and screen/analyze command examples.
4. Update standard workflow and LINE handoff so only screening requests invoke Phase 3.
5. Update workflow documentation and version labels in public diagrams.
6. Run documentation tests until GREEN.
7. Commit with Lore trailers.

## Task 5: Verify safety, behavior, and integration quality

**Files:**
- Review all changed files.

**Steps:**
1. Run targeted Taiwan agent-team, CLI, MCP, tools, and guidance tests.
2. Run the full `npm test` suite.
3. Run `node --check` on changed JavaScript entry points.
4. Scan changed orchestration for forbidden order paths and confirm read-only DOM usage.
5. Run injected analyze and screen smoke tests without live broker access.
6. Inspect `git diff --check` and branch status.
7. Request an independent `code-reviewer` review focused on stage order, eligibility isolation, zero-candidate stop, four-price delivery, safety, and documentation.
8. Fix every blocker/high/medium finding with regression tests and repeat verification.
9. Commit any review fixes with Lore trailers.

## Task 6: Integrate and publish

**Files:**
- No new feature files expected.

**Steps:**
1. Verify the root worktree `main` has no conflicting user changes.
2. Fast-forward local `main` to `taiwan-agent-team-main-flow`.
3. Re-run the full test suite from local `main`.
4. Push `main` to `origin/main` as explicitly authorized.
5. Verify local HEAD, `origin/main`, and remote main resolve to the same commit.
6. Remove the feature worktree and local feature branch after successful publication.
7. Report the formal version, key files, test evidence, commit, and remaining operational limits.

