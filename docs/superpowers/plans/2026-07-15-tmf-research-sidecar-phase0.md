# TMF Research Sidecar Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a standalone, testable Phase 0 safety foundation for TMF research without connecting it to the existing strategy.

**Architecture:** Add a Python project under `tmf-research-agent/`. Domain values and a `MarketDataGateway` protocol form the public boundary; only `shioaji_market_data.py` retains raw SDK objects. A static verifier and a minimal paper-only ledger fail closed on forbidden capabilities and dependency violations.

**Tech Stack:** Python 3.11+ standard library, `dataclasses`, `typing.Protocol`, `ast`, `argparse`, `unittest`, existing Node.js test runner for host regression.

---

### Task 1: Scaffold the independent sidecar

**Files:**
- Create: `tmf-research-agent/pyproject.toml`
- Create: `tmf-research-agent/README.md`
- Create: `tmf-research-agent/SPEC.md`
- Create: `tmf-research-agent/AGENTS.md`
- Create: `tmf-research-agent/.gitignore`
- Create: `tmf-research-agent/src/tmf_research/__init__.py`
- Create: `tmf-research-agent/tests/__init__.py`
- Test: `tmf-research-agent/tests/test_project_boundary.py`

- [x] **Step 1: Write the failing project-boundary test**

```python
class ProjectBoundaryTests(unittest.TestCase):
    def test_sidecar_exposes_no_host_integration(self) -> None:
        host_files = ("../src/cli.js", "../src/mcp-server.js", "../src/trade-runtime.js")
        for relative in host_files:
            self.assertNotIn("tmf-research-agent", Path(relative).read_text())
```

- [x] **Step 2: Run the test to verify the package is missing**

Run: `cd tmf-research-agent && python3 -m unittest tests.test_project_boundary -v`
Expected: FAIL because the sidecar package metadata and policy files do not exist.

- [x] **Step 3: Add minimal project metadata and isolation documentation**

Define the `tmf` console entry point, require Python 3.11+, document Phase 0 scope,
point `SPEC.md` to `../docs/txresearch.md`, prohibit main-strategy imports in the
local `AGENTS.md`, and ignore Python caches/build artifacts plus generated data.

- [x] **Step 4: Run the boundary test**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.test_project_boundary -v`
Expected: PASS.

- [x] **Step 5: Commit**

Use a Lore commit recording that the Python project is intentionally isolated
from host entry points.

### Task 2: Define domain values and the read-only gateway

**Files:**
- Create: `tmf-research-agent/src/tmf_research/domain/__init__.py`
- Create: `tmf-research-agent/src/tmf_research/domain/contracts.py`
- Create: `tmf-research-agent/src/tmf_research/infrastructure/__init__.py`
- Create: `tmf-research-agent/src/tmf_research/infrastructure/readonly_gateway.py`
- Create: `tmf-research-agent/src/tmf_research/infrastructure/shioaji_market_data.py`
- Test: `tmf-research-agent/tests/test_readonly_gateway.py`

- [x] **Step 1: Write failing gateway tests**

Cover `TMFR1` resolution, primitive-only `ContractInfo`, tick and bid/ask
subscription delegation, unsubscription, historical tick batches, historical K
bar batches, and rejection of an uncached contract.

```python
gateway = ShioajiMarketDataGateway(
    fake_api,
    tick_quote_type="tick",
    bidask_quote_type="bidask",
    quote_version="v1",
    clock=fixed_clock,
)
contract = gateway.resolve_near_contract()
self.assertEqual(contract.alias_code, "TMFR1")
self.assertEqual(contract.target_code, "TMF202607")
self.assertFalse(hasattr(contract, "raw_contract"))
self.assertIsInstance(gateway, MarketDataGateway)
```

- [x] **Step 2: Run tests and observe the missing modules**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.test_readonly_gateway -v`
Expected: FAIL with `ModuleNotFoundError`.

- [x] **Step 3: Implement immutable domain values and protocol**

Create frozen `ContractInfo`, `TickBatch`, and `KbarBatch` dataclasses. Define the
runtime-checkable protocol with the seven methods fixed by the research spec.

- [x] **Step 4: Implement the single raw-object adapter**

Retain the injected API object and SDK quote constants only in
`shioaji_market_data.py`; cache raw contracts internally by target code; convert
all returned values into domain dataclasses; raise `ContractResolutionError` for
missing or uncached contracts.

- [x] **Step 5: Run the gateway tests**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.test_readonly_gateway -v`
Expected: PASS.

- [x] **Step 6: Commit**

Use a Lore commit documenting raw SDK confinement and the choice to inject quote
constants instead of adding a runtime SDK dependency in Phase 0.

### Task 3: Build the static read-only verifier

**Files:**
- Create: `tmf-research-agent/src/tmf_research/security/__init__.py`
- Create: `tmf-research-agent/src/tmf_research/security/readonly_verifier.py`
- Test: `tmf-research-agent/tests/test_readonly_verifier.py`

- [x] **Step 1: Write failing verifier tests**

Tests must prove a clean source tree passes and temporary source trees detect:

```python
("forbidden-symbol", "place" + "_order")
```

as a name and raw string, an SDK import outside the adapter, a raw-adapter import
from a consumer, a network import from `paper/`, and invalid Python syntax.

- [x] **Step 2: Run tests and observe the missing verifier**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.test_readonly_verifier -v`
Expected: FAIL with `ModuleNotFoundError`.

- [x] **Step 3: Implement deterministic findings and scans**

Create frozen `ReadonlyFinding` and `ReadonlyReport` values. Walk `*.py` files in
sorted order, scan raw text and AST, collect imports, enforce the sole SDK/raw
adapter boundary, enforce the paper network boundary, and sort/deduplicate all
findings by path, line, rule, and symbol.

- [x] **Step 4: Keep the verifier self-clean**

Assemble forbidden capability names from string fragments so no forbidden raw
token exists in production `src/`, while still reconstructing the full policy at
runtime.

- [x] **Step 5: Run verifier tests and scan production source**

Run:

```bash
cd tmf-research-agent
PYTHONPATH=src python3 -m unittest tests.test_readonly_verifier -v
PYTHONPATH=src python3 -c 'from pathlib import Path; from tmf_research.security.readonly_verifier import verify_readonly; raise SystemExit(0 if verify_readonly(Path("src")).ok else 1)'
```

Expected: both commands exit 0.

- [x] **Step 6: Commit**

Use a Lore commit documenting fail-closed static scanning and the deliberate
production/test scan boundary.

### Task 4: Add the paper-only boundary

**Files:**
- Create: `tmf-research-agent/src/tmf_research/domain/paper_trades.py`
- Create: `tmf-research-agent/src/tmf_research/paper/__init__.py`
- Create: `tmf-research-agent/src/tmf_research/paper/broker.py`
- Test: `tmf-research-agent/tests/test_paper_boundary.py`

- [x] **Step 1: Write failing paper-boundary tests**

Cover zero-argument construction, one-contract validation, immutable PAPER
records, duplicate intent rejection, invalid direction rejection, and absence of
API/account/transport constructor parameters.

```python
intent = PaperIntent(intent_id="p-1", direction="LONG", quantity=1, created_at=now)
record = PaperBroker().record_intent(intent)
self.assertEqual(record.execution_mode, "PAPER")
```

- [x] **Step 2: Run tests and observe the missing modules**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.test_paper_boundary -v`
Expected: FAIL with `ModuleNotFoundError`.

- [x] **Step 3: Implement the minimal in-memory boundary**

Validate directions and quantity in immutable domain values. Let `PaperBroker`
record unique intents only; expose records as an immutable tuple; do not model
fills, prices, PnL, or connectivity in Phase 0.

- [x] **Step 4: Run paper and verifier tests**

Run:

```bash
cd tmf-research-agent
PYTHONPATH=src python3 -m unittest tests.test_paper_boundary tests.test_readonly_verifier -v
```

Expected: PASS.

- [x] **Step 5: Commit**

Use a Lore commit recording why Phase 0 records intents without implementing
Phase 6 fill behavior.

### Task 5: Expose `tmf verify-readonly`

**Files:**
- Create: `tmf-research-agent/src/tmf_research/cli.py`
- Test: `tmf-research-agent/tests/test_cli.py`

- [x] **Step 1: Write failing CLI tests**

Test that a clean project prints `READONLY VERIFIED` and returns 0, a violating
temporary project prints findings and returns 1, and a missing source root fails
closed with return code 1.

- [x] **Step 2: Run tests and observe the missing CLI**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.test_cli -v`
Expected: FAIL with `ModuleNotFoundError`.

- [x] **Step 3: Implement the argparse command**

Resolve the project root, run `verify_readonly(project_root / "src")`, render
stable one-line findings, and support `python -m tmf_research.cli`.

- [x] **Step 4: Run CLI tests and the real command**

Run:

```bash
cd tmf-research-agent
PYTHONPATH=src python3 -m unittest tests.test_cli -v
PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .
```

Expected: tests pass and command prints `READONLY VERIFIED`.

- [x] **Step 5: Commit**

Use a Lore commit recording the fail-closed CLI contract.

### Task 6: Full verification and documentation reconciliation

**Files:**
- Modify: `tmf-research-agent/README.md`
- Modify: `docs/superpowers/plans/2026-07-15-tmf-research-sidecar-phase0.md`

- [x] **Step 1: Run all Python tests**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest discover -s tests -v`
Expected: all tests pass with zero failures.

- [x] **Step 2: Run safety and static checks**

Run:

```bash
cd tmf-research-agent
PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .
PYTHONPATH=src python3 -m compileall -q src tests
```

Expected: verifier prints `READONLY VERIFIED`; compilation exits 0.

- [x] **Step 3: Run host regressions**

Run from the worktree root: `npm test`
Expected: 272 tests pass, zero fail.

- [x] **Step 4: Confirm sidecar isolation and forbidden raw tokens**

Run:

```bash
git diff main...HEAD -- src tests package.json workflows
rg -n 'tmf-research-agent|tmf_research' src tests package.json workflows || true
```

Expected: no host integration diff or reference.

- [x] **Step 5: Update README commands and check the diff**

Document the exact test and verifier commands, Phase 0 limitations, and later
phase ordering. Run `git diff --check` and inspect `git status --short`.

- [x] **Step 6: Commit**

Use a Lore commit including all verification evidence and any known validation
gap.
