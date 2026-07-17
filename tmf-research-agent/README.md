# TMF Research Agent

Independent Python sidecar for the micro Taiwan index futures (`TMF`) research
specification in [`../docs/txresearch.md`](../docs/txresearch.md) (v1.1.0).
The executable test mapping lives in
[`../docs/superpowers/specs/2026-07-15-tmf-research-sidecar-phase1-6-test-spec.md`](../docs/superpowers/specs/2026-07-15-tmf-research-sidecar-phase1-6-test-spec.md).

## Current scope

Phases 0 through 6 are implemented as offline, deterministic software:

- **Phase 0** — fail-closed read-only verifier (AST, forbidden symbols,
  import-graph, paper-boundary imports); runs before everything else.
- **Phase 1** — point-in-time contract tracking, Tick/BidAsk callbacks, a
  nonblocking bounded queue with backpressure evidence, immutable raw NDJSON
  segments with checksums, reconnect state, data-quality rejection evidence.
- **Phase 2** — session/trading-date resolution, backward-only quote joins,
  one-second state, session-anchored 1m/5m/15m/60m bars.
- **Phase 3** — point-in-time feature manifests, executable prices, triple
  barrier labels, and the leakage test suite.
- **Phase 4** — baselines, fold-only preprocessing, two-stage logistic
  probabilities, calibration, checksummed model bundle serialization.
- **Phase 5** — nested walk-forward with purge/embargo, locked holdout,
  append-only experiment registry with fixed search budgets, stability and
  ablation evidence, and the approval gate. Every promotion-affecting artifact
  is derived from sealed raw evidence; caller-authored or synthetic values can
  reach `CANDIDATE`/`VALIDATING` at most, never `APPROVED_FOR_PAPER`.
- **Phase 6** — paper fills/risk/ledger/PnL inside the audited paper boundary,
  the fourteen-step fail-closed live-research loop, complete SPEC 36
  prediction JSON, approval-gated registry loading, and canonical replay
  identity with byte-identical cross-process determinism.

The sidecar never connects to the host Node.js strategy and holds no brokerage
authentication, account, certificate, position, margin, order, cancel, modify,
or forwarding capability. That boundary is permanent; `PaperBroker` is the only
trading class and every settled row is immutably `PAPER`.

## Development commands

Run from `tmf-research-agent/`, in this order (the verifier always first):

```bash
PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .
PYTHONPATH=src python3 -m unittest discover -s tests/security -t . -v
PYTHONPATH=src python3 -m unittest discover -s tests/unit -t . -v
PYTHONPATH=src python3 -m unittest discover -s tests/integration -t . -v
PYTHONPATH=src python3 -m unittest discover -s tests/leakage -t . -v
PYTHONPATH=src python3 -m unittest discover -s tests/overfitting -t . -v
PYTHONPATH=src python3 -m unittest discover -s tests/infrastructure -t . -v
PYTHONPATH=src python3 -m unittest discover -s tests/replay -t . -v
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
python3 -m ruff check src tests
python3 -m mypy --strict src tests
PYTHONPATH=src python3 -m compileall -q src tests
```

Pinned development tools install with `pip install -e ".[dev]"`
(`mypy==1.16.1`, `ruff==0.12.3`). The CLI command becomes available as
`tmf verify-readonly` after installing this project; CI installs the sidecar
and runs the exact console command first.

## Generated artifacts and state meanings

- Model bundles serialize to a directory of the SPEC 37 registry files plus
  `checksum.sha256`; any file/metadata/checksum/dimension mismatch at load
  time forces `NO_TRADE`.
- Experiment registries are append-only directories; successful and failed
  attempts are both permanent.
- Replay identity is the SHA-256 of a canonical manifest (raw checksum,
  dataset/feature/label/model versions, experiment, commit, seed, calendar,
  cost policy); a published identity can never be overwritten.
- Model states follow SPEC 42 (`DRAFT` … `APPROVED_FOR_PAPER` … `RETIRED`).
  Only `APPROVED_FOR_PAPER` — proven by the sealed capability issued by the
  Phase 5 decision gate on sufficient real data — enables a paper plan.
  Test-only runtimes stamp every prediction with
  `TEST_ONLY_RUNTIME_EVIDENCE` and are never research evidence.

## Credentialed and real-data gaps

Offline CI has no Shioaji credentials and no network. The following remain
explicitly `CREDENTIALED_VALIDATION_NOT_RUN` and are never converted into a
pass: live authentication and current `TMFR1` payload shape, real Tick/BidAsk
delivery and reconnect recovery, future exchange-calendar changes, sufficient
uncontaminated real history for five outer folds plus the locked holdout, and
any real-data EV/calibration/stability/holdout result. `tests/credentialed`
does not exist yet; when it does, it runs only with `TMF_RUN_CREDENTIALED=1`.

## Definition-of-Done traceability

Each SPEC 46 row maps to executable evidence per the companion test spec
section 12: read-only/no-order (Phase 0 + security gate), stable collection
(P1 offline + credentialed gap recorded), target/rollover (P1-CON), day/night
(P2-SES), raw immutability (P1-RAW), no future features (P3-TIME + leakage
suite), executable labels (P3-LAB), reproducible nested walk-forward
(P5-FOLD + replay determinism), unpolluted holdout (P5-HOLD), overfitting
controls (P5-EXP/STB/SEL), replayable paper trading (P6-PAP/REP), transparent
costs (P6-PAP-004 + cost policy hashes), traceable predictions (P6-INF/REP).

## Phase ordering

Development follows the canonical order in the specification. Later phases may
not weaken the Phase 0 safety checks, and Phase 7 (model expansion) is not
authorized by software completion: it additionally requires the baseline model
to pass every out-of-sample acceptance gate on real data.
