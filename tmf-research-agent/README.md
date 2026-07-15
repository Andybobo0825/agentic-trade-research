# TMF Research Agent

Independent Python sidecar for the micro Taiwan index futures (`TMF`) research
specification in [`../docs/txresearch.md`](../docs/txresearch.md).

## Current scope

Phase 0 establishes fail-closed read-only boundaries. Phase 1 adds isolated
market-data collection primitives: point-in-time contract tracking, Tick and
BidAsk callbacks, a nonblocking bounded queue with backpressure evidence,
immutable raw NDJSON segments with checksums, reconnect/resubscribe state, and
explicit data-quality rejection evidence.

The sidecar still does not connect to the host Node.js strategy, own brokerage
credentials, train a model, produce a signal, or simulate a fill. Processing,
features, models, and paper inference remain later phases.

## Development commands

```bash
PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src tests
```

The CLI command becomes available as `tmf verify-readonly` after installing this
project. Local source development can use the module form without mutating its
environment; CI installs the sidecar and runs the exact console command first.

## Phase ordering

Development follows the canonical order in the specification. Market-data
collection is Phase 1, processing is Phase 2, features and labels are Phase 3,
the baseline model is Phase 4, overfitting controls are Phase 5, and paper
inference is Phase 6. Later phases may not weaken the Phase 0 safety checks.
