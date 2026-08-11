# TMF Research Sidecar Phase 0 Design

## Outcome

Create the read-only safety foundation for the TMF research system described in
`docs/txresearch.md`. The new code lives in an independent Python sidecar named
`tmf-research-agent/` and is not imported, registered, or invoked by the existing
Node.js strategy, CLI, MCP server, or runtime.

## Scope

This delivery implements specification Phase 0 only:

- a typed `MarketDataGateway` protocol;
- the single infrastructure boundary allowed to retain a raw Shioaji API object;
- a static read-only verifier covering forbidden symbols, imports, dependency
  direction, and the paper boundary;
- a minimal `PaperBroker` boundary that records paper-only intents without
  network or brokerage dependencies;
- a `tmf verify-readonly` command and automated security tests.

Live subscriptions, historical downloads, event queues, storage, feature
engineering, training, validation, inference, and paper fills remain outside this
phase. They must be implemented sequentially in later phases.

## Isolation

The sidecar is rooted at `tmf-research-agent/` with its own `pyproject.toml`,
`src/`, and `tests/`. The existing repository files under root `src/` remain
unchanged. The verifier scans the sidecar source tree rather than the host
repository's Node.js source tree, so its policy applies to the system governed by
the TMF specification without silently changing the existing strategy.

No root `package.json` script, CLI command, MCP tool, workflow document, or
runtime service references the sidecar in Phase 0.

## Architecture

### Domain contracts

`tmf_research.domain.contracts` defines immutable, primitive-only values for
resolved contracts and historical batches. A contract value never exposes the
raw SDK contract object.

### Read-only gateway

`tmf_research.infrastructure.readonly_gateway` defines the runtime-checkable
`MarketDataGateway` protocol. Consumers depend on this module only.

`tmf_research.infrastructure.shioaji_market_data` is the sole module that may
retain a raw API object. It resolves `TMFR1`, caches raw contracts internally,
delegates quote and historical market-data calls, and returns domain values. It
does not authenticate, activate certificates, inspect accounts, or construct any
order-capable object.

Quote-type values are injected into the adapter rather than importing the SDK at
module import time. This keeps Phase 0 installable without adding a Shioaji
dependency while preserving the single raw-object boundary for the existing
runtime to compose in a later phase.

### Static safety verifier

`tmf_research.security.readonly_verifier` parses every Python source file under
the sidecar `src/` tree and returns structured findings. It performs:

1. raw string scanning for forbidden capabilities;
2. AST scanning for forbidden names, attributes, and imports;
3. import-graph checks preventing SDK imports outside the sole adapter;
4. dependency checks preventing non-infrastructure modules from importing the
   raw adapter;
5. paper-boundary checks preventing network and raw-adapter imports.

The verifier's policy vocabulary is assembled from harmless fragments so the
verifier does not violate its own raw-source policy. Tests may contain explicit
unsafe fixtures because the production scan is intentionally scoped to `src/`.

### Paper boundary

`tmf_research.paper.broker.PaperBroker` accepts only immutable paper intents,
marks every record as `PAPER`, and stores them in memory. Its constructor takes no
API, account, certificate, transport, or callback. It performs no fill simulation
in Phase 0.

### CLI

`tmf_research.cli` exposes one subcommand, `verify-readonly`. It prints a concise
report and returns a non-zero status when findings exist. `pyproject.toml` maps
the console command `tmf` to this entry point.

## Error Handling

- Adapter methods raise explicit lookup errors when the near contract cannot be
  resolved or when an uncached contract is requested.
- The verifier reports every finding in deterministic path/line/rule order and
  does not stop at the first violation.
- The CLI fails closed on an invalid source root or any safety finding.
- `PaperBroker` rejects non-paper intents and duplicate identifiers.

## Testing

Tests use Python's standard `unittest` package and require no new dependency.

- Gateway tests use a fake market-data-only API object and prove domain values do
  not leak raw SDK contracts.
- Verifier tests prove the clean tree passes and isolated unsafe fixtures fail for
  symbol, import, dependency, and paper-network violations.
- Paper tests prove all records remain paper-only, duplicates fail, and the
  constructor surface cannot accept external capabilities.
- CLI tests prove success and failure exit codes.
- Final verification runs the sidecar test suite, the verifier command, Python
  bytecode compilation, and the existing Node.js regression suite.

## Non-Goals and Forward Constraints

- No model is trained or approved in Phase 0.
- No real or simulated brokerage endpoint is available.
- No live market-data connection is started by tests or CLI.
- Phase 1 must reuse the protocol and adapter boundary rather than exposing the
  raw API object to collection code.
- Phase 6 must extend the paper ledger without weakening the Phase 0 verifier.
