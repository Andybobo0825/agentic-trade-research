# TMF Research Sidecar Phase 1–6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the read-only TMF research sidecar from deterministic market-data collection through leakage-safe validation, replay, frozen inference, and paper-only accounting without integrating it into the host strategy or enabling any brokerage capability.

**Architecture:** Preserve the Phase 0 dependency boundary: only `infrastructure/shioaji_market_data.py` may retain raw SDK state, and every downstream module consumes immutable domain values through `MarketDataGateway`. Build append-only, versioned stages in strict Phase 1 → 6 order; every stage fails closed to `NO_TRADE` when provenance, quality, compatibility, validation, or approval evidence is missing. Historical replay and live research inference share event-time domain interfaces, while paper execution remains a local deterministic ledger with no network/account/certificate surface.

**Tech Stack:** Python 3.11+, standard-library `dataclasses`, `typing`, `zoneinfo`, `datetime`, `hashlib`, `json`, `sqlite3`, `pathlib`, `queue`, `unittest`, and deterministic numerical routines for the initial logistic baseline; pinned `ruff` and `mypy` development tools in `tmf-research-agent/pyproject.toml`; existing Node.js test runner for host-isolation regression.

**Authority:** `docs/txresearch.md` v1.1.0 and `docs/superpowers/specs/2026-07-15-tmf-research-sidecar-phase1-6-test-spec.md`.

---

## Locked boundaries and phase gates

- All production implementation stays under `tmf-research-agent/src/tmf_research/`.
- Path-scoped CI and documentation are the only permitted changes outside the sidecar.
- Do not import, register, or invoke the sidecar from root `src/`, host CLI, MCP, runtime, or strategy code.
- `tmf verify-readonly` runs before every phase suite and remains a hard gate.
- Default CI is offline. Credentialed smoke tests are opt-in and may only prove the market-data boundary.
- Synthetic data proves mechanics, not market effectiveness. Insufficient real data must produce `REJECTED_INSUFFICIENT_DATA`, `NO_TRADE`, and disabled paper plans.
- Phase 6 starts only after Phase 5 verification. Phase 7 is not authorized.

## File responsibility map

| Area | Files | Responsibility |
| --- | --- | --- |
| Domain | `domain/contracts.py`, `events.py`, `sessions.py`, `predictions.py`, `paper_trades.py` | Frozen primitive-only values and enums; no I/O |
| Collection | `infrastructure/contract_resolver.py`, `reconnect_manager.py`, `raw_store.py`, `data_catalog.py`; `collection/*.py` | Resolve actual contracts, normalize callbacks, queue without blocking, append immutable raw segments |
| Processing | `processing/normalize.py`, `session_resolver.py`, `quote_joiner.py`, `one_second.py`, `bars.py` | Event-time normalization, exchange-calendar sessions, backward quote joins, session-anchored aggregates |
| Features/labels | `features/*.py`, `labeling/*.py` | Causal feature provenance, fold-safe transforms, executable-price triple-barrier labels |
| Models | `models/*.py` | Baselines, two-stage logistic probabilities, calibration, frozen serialization |
| Validation/experiments | `validation/*.py`, `experiments/*.py` | Nested walk-forward, purge/embargo, holdout lock, budgets, metrics, stability, approval gates |
| Replay/runtime/paper | `paper/*.py`, `runtime/*.py` | Event-time replay, fail-closed live inference, deterministic paper fills/PnL/ledger |
| Evidence | `tests/{unit,integration,leakage,overfitting,replay,security,regression,fixtures,credentialed}` | Executable acceptance mapping from the companion test specification |

### Task 1: Establish deterministic fixtures and CI phase gates

**Files:**
- Modify: `tmf-research-agent/pyproject.toml`
- Modify: `tmf-research-agent/src/tmf_research/cli.py`
- Create: `tmf-research-agent/tests/fixtures/calendar.py`
- Create: `tmf-research-agent/tests/fixtures/contracts.py`
- Create: `tmf-research-agent/tests/fixtures/events.py`
- Create: `tmf-research-agent/tests/fixtures/raw_segments.py`
- Create: `tmf-research-agent/tests/fixtures/features.py`
- Create: `tmf-research-agent/tests/fixtures/labels.py`
- Create: `tmf-research-agent/tests/fixtures/research.py`
- Create: `tmf-research-agent/tests/fixtures/registry.py`
- Create: `tmf-research-agent/tests/fixtures/tripwires.py`
- Modify: `.github/workflows/tmf-research-sidecar.yml`
- Test: `tmf-research-agent/tests/regression/test_fixture_determinism.py`

- [ ] **Step 1: Write failing fixture determinism tests**

Define literal Asia/Taipei timestamps, expected trading dates, contract transitions, raw bytes/checksums, future sentinels, and tripwires. Tests call every fixture twice and compare values while asserting object identity differs.

```python
first = event_tape()
second = event_tape()
self.assertEqual(first, second)
self.assertIsNot(first, second)
self.assertEqual(first.future_sentinel, 9_999_999)
```

- [ ] **Step 2: Run the fixture regression and observe missing modules**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.regression.test_fixture_determinism -v`

Expected: FAIL with missing fixture modules.

- [ ] **Step 3: Implement F01–F10 as fresh immutable values**

Use frozen dataclasses and tuple/mapping values. Keep exchange time, receipt time, and wall time distinct. Tripwire methods raise `AssertionError` on raw API, socket, HTTP, process, or dynamic-import access.

- [ ] **Step 4: Add ordered phase command surfaces**

Add `dev = ["mypy==1.16.1", "ruff==0.12.3"]` under `[project.optional-dependencies]`. Extend the sidecar CLI with offline commands whose handlers run the verifier first and return non-zero on the first failing suite. Keep credentialed validation behind `TMF_RUN_CREDENTIALED=1`; a missing credential or closed market prints `CREDENTIALED_VALIDATION_NOT_RUN`.

- [ ] **Step 5: Run fixture, CLI, and Phase 0 regressions**

Run:

```bash
cd tmf-research-agent
PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .
PYTHONPATH=src python3 -m unittest tests.regression.test_fixture_determinism tests.test_cli tests.test_project_boundary -v
```

Expected: `READONLY VERIFIED`; all tests PASS.

- [ ] **Step 6: Commit**

Commit a Lore record explaining that literal deterministic fixtures and verifier-first ordering prevent tests from hiding temporal, safety, or environment drift.

### Task 2: Implement Phase 1 contract resolution and collection boundaries

**Files:**
- Modify: `tmf-research-agent/src/tmf_research/domain/contracts.py`
- Create: `tmf-research-agent/src/tmf_research/domain/events.py`
- Create: `tmf-research-agent/src/tmf_research/infrastructure/contract_resolver.py`
- Create: `tmf-research-agent/src/tmf_research/infrastructure/reconnect_manager.py`
- Create: `tmf-research-agent/src/tmf_research/collection/event_queue.py`
- Create: `tmf-research-agent/src/tmf_research/collection/live_collector.py`
- Create: `tmf-research-agent/src/tmf_research/collection/historical_downloader.py`
- Test: `tmf-research-agent/tests/unit/test_contract_resolver.py`
- Test: `tmf-research-agent/tests/unit/test_event_queue.py`
- Test: `tmf-research-agent/tests/unit/test_event_normalization.py`
- Test: `tmf-research-agent/tests/unit/test_reconnect_manager.py`
- Test: `tmf-research-agent/tests/integration/test_live_collector.py`

- [ ] **Step 1: Write P1-CON and P1-COL failing tests**

Cover actual-code persistence, deterministic rollover events, unconfirmed-rollover fail-close, minimal callback work, no-block queue overflow, reconnect evidence, and all Tick/BidAsk/Connection fields.

```python
result = resolver.resolve()
self.assertEqual(result.contract.alias_code, "TMFR1")
self.assertEqual(result.contract.target_code, "TMF202607")
self.assertFalse(result.allow_paper_trade if result.rollover_unconfirmed else False)

accepted = event_queue.offer(tick_event)
self.assertFalse(accepted)
self.assertEqual(event_queue.dropped_event_count, 1)
self.assertEqual(event_queue.connection_events[-1].event_type, "QUEUE_BACKPRESSURE")
```

- [ ] **Step 2: Run tests to prove Phase 1 is absent**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_contract_resolver tests.unit.test_event_queue tests.unit.test_event_normalization tests.unit.test_reconnect_manager tests.integration.test_live_collector -v`

Expected: FAIL with missing modules/classes.

- [ ] **Step 3: Implement primitive-only contracts and events**

Use frozen values with explicit schema versions. `ContractResolver` consumes `MarketDataGateway`, persists alias plus actual contract, and emits one rollover event when target or delivery month changes. Never infer a month from a symbol suffix.

- [ ] **Step 4: Implement non-blocking callback isolation**

Callbacks parse only required primitives, stamp injected receipt time, call `put_nowait`, and return. Overflow increments a counter, records `QUEUE_BACKPRESSURE`, invalidates quality, and disables downstream paper eligibility.

- [ ] **Step 5: Implement deterministic reconnect state**

Represent attempts and state transitions as `ConnectionEvent` values. Subscribe/unsubscribe only through `MarketDataGateway`; no collection module imports the raw adapter.

- [ ] **Step 6: Run Phase 1 collection tests and verifier**

Run:

```bash
cd tmf-research-agent
PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_*event*.py' -v
PYTHONPATH=src python3 -m unittest tests.unit.test_contract_resolver tests.unit.test_reconnect_manager tests.integration.test_live_collector -v
```

Expected: verifier and P1-CON/P1-COL cases PASS.

- [ ] **Step 7: Commit**

Commit a Lore record documenting callback isolation, fail-closed rollover state, and gateway-only collection dependencies.

### Task 3: Implement Phase 1 append-only raw storage and quality reports

**Files:**
- Create: `tmf-research-agent/src/tmf_research/infrastructure/raw_store.py`
- Create: `tmf-research-agent/src/tmf_research/infrastructure/data_catalog.py`
- Create: `tmf-research-agent/src/tmf_research/collection/raw_writer.py`
- Create: `tmf-research-agent/src/tmf_research/processing/normalize.py`
- Test: `tmf-research-agent/tests/unit/test_raw_store.py`
- Test: `tmf-research-agent/tests/unit/test_data_quality.py`
- Test: `tmf-research-agent/tests/integration/test_collection_pipeline.py`

- [ ] **Step 1: Write P1-RAW and P1-QLT failing tests**

Assert exclusive-create writes, SHA-256 over canonical bytes, schema/writer/time metadata, duplicate/tamper/partial-write rejection, immutable prior versions, and complete rejection-reason accounting.

```python
manifest = store.append_segment(segment)
self.assertEqual(manifest.checksum_sha256, sha256(segment.canonical_bytes).hexdigest())
with self.assertRaises(SegmentAlreadyExists):
    store.append_segment(segment)
self.assertEqual(old_path.read_bytes(), original_bytes)
```

- [ ] **Step 2: Run tests and observe missing raw storage**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_raw_store tests.unit.test_data_quality tests.integration.test_collection_pipeline -v`

Expected: FAIL with missing modules/classes.

- [ ] **Step 3: Implement atomic append-only segments and catalog**

Write to a unique temporary path, fsync, rename once to a never-reused content path, then append the manifest. Reject existing paths, duplicate event IDs, checksum mismatch, invalid schema, and incomplete temporary artifacts.

- [ ] **Step 4: Implement normalization and quality evidence**

Return accepted and rejected immutable records. Preserve a reason for simtrade, non-positive price, crossed book, negative volume, invalid time, unknown target, duplicate, out-of-session, stale quote, incomplete session, and queue loss. Produce every SPEC 13 counter, maximum gap, coverage ratio, and status per trading date/session.

- [ ] **Step 5: Run all Phase 1 tests**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_contract_resolver tests.unit.test_event_queue tests.unit.test_event_normalization tests.unit.test_raw_store tests.unit.test_reconnect_manager tests.unit.test_data_quality tests.integration.test_live_collector tests.integration.test_collection_pipeline -v`

Expected: all P1 mappings PASS; original raw bytes/checksums remain unchanged.

- [ ] **Step 6: Commit**

Commit a Lore record explaining exclusive-create storage, canonical checksums, and retained rejection evidence.

### Task 4: Implement Phase 2 session resolution and causal quote joining

**Files:**
- Create: `tmf-research-agent/src/tmf_research/domain/sessions.py`
- Create: `tmf-research-agent/src/tmf_research/processing/session_resolver.py`
- Create: `tmf-research-agent/src/tmf_research/processing/quote_joiner.py`
- Test: `tmf-research-agent/tests/unit/test_session_resolver.py`
- Test: `tmf-research-agent/tests/unit/test_quote_joiner.py`

- [ ] **Step 1: Write P2-SES and P2-JOIN failing tests**

Use F01 literal dates for DAY/NIGHT/CLOSED, Friday-to-Monday, holiday/closure, expiry 13:30/no-night, and normal 13:45. Prove a quote after the tick is never selected even when it is closer.

```python
joined = joiner.join(tick_at_090000, (quote_at_085959, quote_at_090001))
self.assertEqual(joined.matched_bidask_at, quote_at_085959.exchange_datetime)
self.assertGreaterEqual(joined.quote_age_ms, 0)
self.assertFalse(joiner.join(tick_at_090000, (stale_quote,)).bidask_available)
```

- [ ] **Step 2: Run tests to prove Phase 2 is absent**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_session_resolver tests.unit.test_quote_joiner -v`

Expected: FAIL with missing modules/classes.

- [ ] **Step 3: Implement injected exchange-calendar resolution**

Resolve trading date from explicit valid-day/closure data in `Asia/Taipei`; never use calendar `+1`. Return CLOSED outside exact session bounds, use 13:30 on expiry day, and anchor session starts at 08:45/15:00.

- [ ] **Step 4: Implement deterministic backward as-of join**

Select the latest quote whose exchange time is less than or equal to tick time; break equal-time ties with stable event order. Persist matched time, age, availability, and stale reason. Missing/stale results expose no executable price or book-derived feature inputs.

- [ ] **Step 5: Run causal processing tests**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_session_resolver tests.unit.test_quote_joiner -v`

Expected: all P2-SES/P2-JOIN cases PASS.

- [ ] **Step 6: Commit**

Commit a Lore record documenting injected calendars and strictly backward quote evidence.

### Task 5: Implement Phase 2 one-second state and session-anchored bars

**Files:**
- Create: `tmf-research-agent/src/tmf_research/processing/one_second.py`
- Create: `tmf-research-agent/src/tmf_research/processing/bars.py`
- Test: `tmf-research-agent/tests/unit/test_one_second.py`
- Test: `tmf-research-agent/tests/unit/test_bars.py`
- Test: `tmf-research-agent/tests/integration/test_processing_pipeline.py`

- [ ] **Step 1: Write P2-AGG failing tests**

Hand-check OHLC, volume, trade counts, buy/sell/unknown flow, book, basis, and age fields. Empty seconds may carry the last valid book/underlying but must retain zero volume/counts and no fabricated trade OHLC.

- [ ] **Step 2: Verify tests fail before implementation**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_one_second tests.unit.test_bars tests.integration.test_processing_pipeline -v`

Expected: FAIL with missing aggregators.

- [ ] **Step 3: Implement 1-second state**

Calculate the complete SPEC 12.1 schema with finite-safe midpoint, microprice, L1/L3/L5 imbalance, and basis. Carry only allowed quote/book/underlying values; reset flow counters every second.

- [ ] **Step 4: Implement 1m/5m/15m/60m bars**

Calculate bucket index from elapsed time since 08:45 or 15:00, never Unix hour boundaries. Persist all SPEC 12.2 fields, coverage ratios, and completeness; exclude incomplete bars from research outputs without mutating raw inputs.

- [ ] **Step 5: Run the complete Phase 2 gate**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_session_resolver tests.unit.test_quote_joiner tests.unit.test_one_second tests.unit.test_bars tests.integration.test_processing_pipeline -v`

Expected: all Phase 2 tests PASS and repeated pipeline output is identical.

- [ ] **Step 6: Commit**

Commit a Lore record documenting session-relative buckets and the no-fake-trades empty-second rule.

### Task 6: Implement Phase 3 causal feature manifests and formulas

**Files:**
- Create: `tmf-research-agent/src/tmf_research/features/definitions.py`
- Create: `tmf-research-agent/src/tmf_research/features/price.py`
- Create: `tmf-research-agent/src/tmf_research/features/volume.py`
- Create: `tmf-research-agent/src/tmf_research/features/orderflow.py`
- Create: `tmf-research-agent/src/tmf_research/features/orderbook.py`
- Create: `tmf-research-agent/src/tmf_research/features/basis.py`
- Create: `tmf-research-agent/src/tmf_research/features/volatility.py`
- Create: `tmf-research-agent/src/tmf_research/features/structure.py`
- Create: `tmf-research-agent/src/tmf_research/features/time_features.py`
- Create: `tmf-research-agent/src/tmf_research/features/pipeline.py`
- Test: `tmf-research-agent/tests/unit/test_feature_manifest.py`
- Test: `tmf-research-agent/tests/unit/test_feature_pipeline.py`
- Test: `tmf-research-agent/tests/leakage/test_feature_time.py`

- [ ] **Step 1: Write P3-TIME/P3-MAN/P3-FEA failing tests**

Assert every feature has `feature_time`, `decision_time`, `evidence_available_at`, and `feature_version`; future sentinel changes cannot alter prior rows; manifest limits are 40 primary + 10 missing indicators and formal models use at most 30 primary + 5 declared interactions.

```python
prior = pipeline.compute(history, decision_time)
mutated = pipeline.compute(history + (future_sentinel,), decision_time)
self.assertEqual(prior, mutated)
self.assertTrue(all(row.evidence_available_at <= row.decision_time for row in prior))
```

- [ ] **Step 2: Run feature/leakage tests to prove absence**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_feature_manifest tests.unit.test_feature_pipeline tests.leakage.test_feature_time -v`

Expected: FAIL with missing feature modules.

- [ ] **Step 3: Implement formulas by market mechanism**

Implement the exact SPEC 15 price/trend, separate-session VWAP, order flow, five-level book, basis, volatility, structure, and time/contract definitions. Keep missing underlying as missing; use finite-safe denominators; make swing evidence available only after right-side confirmation.

- [ ] **Step 4: Enforce causal provenance and manifest budgets**

Reject evidence after decision time, centered windows, backward fill, global transforms, and future bar confirmation. Record missing indicators and declared interaction definitions in a versioned manifest.

- [ ] **Step 5: Run Phase 3 feature and leakage cases**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest discover -s tests/leakage -v && PYTHONPATH=src python3 -m unittest tests.unit.test_feature_manifest tests.unit.test_feature_pipeline -v`

Expected: future injections are rejected or leave prior output unchanged; all formula fixtures PASS.

- [ ] **Step 6: Commit**

Commit a Lore record documenting evidence-time enforcement and bounded feature complexity.

### Task 7: Implement Phase 3 executable prices and triple-barrier labels

**Files:**
- Create: `tmf-research-agent/src/tmf_research/labeling/executable_prices.py`
- Create: `tmf-research-agent/src/tmf_research/labeling/triple_barrier.py`
- Create: `tmf-research-agent/src/tmf_research/labeling/pipeline.py`
- Test: `tmf-research-agent/tests/unit/test_executable_prices.py`
- Test: `tmf-research-agent/tests/unit/test_triple_barrier.py`
- Test: `tmf-research-agent/tests/unit/test_label_pipeline.py`
- Test: `tmf-research-agent/tests/leakage/test_label_parameter_scope.py`

- [ ] **Step 1: Write P3-LAB failing tests**

Create one candidate after each complete 1m close for independent 5m/15m/60m datasets. Verify LONG uses ask-plus entry/bid-minus exit, SHORT uses bid-minus entry/ask-plus exit, ambiguous order is counted/excluded, and all SPEC 17.6 fields persist.

- [ ] **Step 2: Run label tests and observe missing implementation**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_executable_prices tests.unit.test_triple_barrier tests.unit.test_label_pipeline tests.leakage.test_label_parameter_scope -v`

Expected: FAIL with missing labeling modules.

- [ ] **Step 3: Implement executable-price and barrier values**

Calculate target/stop as `max(atr_multiplier * atr, minimum_points)`. Reject close-only pricing and missing/stale quotes. Accept label parameters only from an immutable train/inner-selected configuration carrying its version and fit interval.

- [ ] **Step 4: Implement deterministic first-touch classification**

Return LONG, SHORT, NO_TRADE, or AMBIGUOUS with touch time, excursion, barrier, cost, horizon, and provenance fields. Never include AMBIGUOUS in training rows.

- [ ] **Step 5: Run the complete Phase 3 gate**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest discover -s tests/leakage -v && PYTHONPATH=src python3 -m unittest tests.unit.test_feature_manifest tests.unit.test_feature_pipeline tests.unit.test_executable_prices tests.unit.test_triple_barrier tests.unit.test_label_pipeline -v`

Expected: all P3 mappings PASS with separate horizon datasets.

- [ ] **Step 6: Commit**

Commit a Lore record explaining executable-side prices, train-only barriers, and ambiguous exclusion.

### Task 8: Implement Phase 4 baselines, fold-only preprocessing, and two-stage logistic probabilities

**Files:**
- Create: `tmf-research-agent/src/tmf_research/models/baselines.py`
- Create: `tmf-research-agent/src/tmf_research/models/scaler.py`
- Create: `tmf-research-agent/src/tmf_research/models/imputer.py`
- Create: `tmf-research-agent/src/tmf_research/models/logistic.py`
- Create: `tmf-research-agent/src/tmf_research/models/calibration.py`
- Create: `tmf-research-agent/src/tmf_research/models/inference.py`
- Create: `tmf-research-agent/src/tmf_research/models/serialization.py`
- Test: `tmf-research-agent/tests/unit/test_baselines.py`
- Test: `tmf-research-agent/tests/unit/test_logistic.py`
- Test: `tmf-research-agent/tests/unit/test_probability.py`
- Test: `tmf-research-agent/tests/unit/test_scaler.py`
- Test: `tmf-research-agent/tests/unit/test_imputer.py`
- Test: `tmf-research-agent/tests/unit/test_calibration.py`
- Test: `tmf-research-agent/tests/unit/test_model_serialization.py`
- Test: `tmf-research-agent/tests/leakage/test_transform_scope.py`

- [ ] **Step 1: Write Phase 4 failing tests**

Cover Baselines 0–4, Model A TRADE/NO_TRADE, Model B train LONG/SHORT only, exact probability products and sum-to-one, L2/class weights/convergence records, train-only transforms, calibration priority, and round-trip identity.

```python
probability = combine(p_trade=0.6, p_long_given_trade=0.75)
self.assertAlmostEqual(probability.long, 0.45)
self.assertAlmostEqual(probability.short, 0.15)
self.assertAlmostEqual(probability.no_trade, 0.40)
self.assertAlmostEqual(sum(probability.as_tuple()), 1.0)
```

- [ ] **Step 2: Run tests and observe missing model modules**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_baselines tests.unit.test_logistic tests.unit.test_probability tests.unit.test_scaler tests.unit.test_imputer tests.unit.test_calibration tests.unit.test_model_serialization tests.leakage.test_transform_scope -v`

Expected: FAIL with missing modules/classes.

- [ ] **Step 3: Implement immutable train-fitted preprocessing**

Fit scaler, median imputer, outlier limits, and large-trade thresholds on train only; persist fit interval, feature order, dimensions, and hash. Required missing values return a fail-closed decision; optional values use train median plus indicator.

- [ ] **Step 4: Implement deterministic models and calibration**

Fit the two L2 logistic stages with fixed seed/order/convergence/max iterations and class weights. Fit uncalibrated, Platt, and isotonic alternatives on inner data only; choose by Brier, LogLoss, ECE, then EV, rejecting insufficient calibration bins.

- [ ] **Step 5: Implement stable serialization and mismatch rejection**

Persist all SPEC 37 bundle files and SHA-256. Loading rejects feature/version/order/instrument/session/horizon/schema/checksum/dimension mismatch and returns a structured NO_TRADE reason.

- [ ] **Step 6: Run the complete Phase 4 gate**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_baselines tests.unit.test_logistic tests.unit.test_probability tests.unit.test_scaler tests.unit.test_imputer tests.unit.test_calibration tests.unit.test_model_serialization tests.leakage.test_transform_scope -v`

Expected: all Phase 4 tests PASS; serialization probabilities are identical before/after load.

- [ ] **Step 7: Commit**

Commit a Lore record documenting two-stage probabilities, fold-only transforms, and strict registry compatibility.

### Task 9: Implement Phase 5 nested walk-forward, purge/embargo, and locked holdout

**Files:**
- Create: `tmf-research-agent/src/tmf_research/validation/folds.py`
- Create: `tmf-research-agent/src/tmf_research/validation/purging.py`
- Create: `tmf-research-agent/src/tmf_research/validation/nested_walk_forward.py`
- Create: `tmf-research-agent/src/tmf_research/validation/locked_holdout.py`
- Test: `tmf-research-agent/tests/overfitting/test_walk_forward.py`
- Test: `tmf-research-agent/tests/overfitting/test_locked_holdout.py`
- Test: `tmf-research-agent/tests/leakage/test_purge_embargo.py`
- Test: `tmf-research-agent/tests/leakage/test_locked_holdout_access.py`

- [ ] **Step 1: Write P5-FOLD/P5-HOLD failing tests**

Reject random/shuffled/KFold inputs, prove outer tests are inaccessible to selectors, purge equality boundaries, require embargo at least maximum horizon, and keep the final `max(40 effective days, ceil(15%))` suffix behind an access-raising sentinel.

- [ ] **Step 2: Run tests and observe missing validation modules**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.overfitting.test_walk_forward tests.overfitting.test_locked_holdout tests.leakage.test_purge_embargo tests.leakage.test_locked_holdout_access -v`

Expected: FAIL with missing modules/classes.

- [ ] **Step 3: Implement ordered nested folds and boundary exclusion**

Create chronological outer train/test and inner train/validation ranges. Remove train rows with `outcome_time >= validation_start` and validation rows with `outcome_time >= test_start`; enforce embargo duration against model horizon.

- [ ] **Step 4: Implement single-use holdout capability**

Before unlock, any read raises. Issue one unlock token only after immutable hashes exist for model, features, labels, parameters, thresholds, and rules. A rerun or post-test mutation marks the candidate contaminated and prevents approval.

- [ ] **Step 5: Run fold/holdout tests**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.overfitting.test_walk_forward tests.overfitting.test_locked_holdout tests.leakage.test_purge_embargo tests.leakage.test_locked_holdout_access -v`

Expected: P5-FOLD/P5-HOLD cases PASS; insufficient data returns `REJECTED_INSUFFICIENT_DATA`.

- [ ] **Step 6: Commit**

Commit a Lore record documenting temporal isolation, equality purging, horizon embargo, and single-use holdout access.

### Task 10: Implement Phase 5 research budgets, stability evidence, metrics, and approval states

**Files:**
- Create: `tmf-research-agent/src/tmf_research/experiments/registry.py`
- Create: `tmf-research-agent/src/tmf_research/experiments/search_budget.py`
- Create: `tmf-research-agent/src/tmf_research/experiments/comparison.py`
- Create: `tmf-research-agent/src/tmf_research/validation/metrics.py`
- Create: `tmf-research-agent/src/tmf_research/validation/stability.py`
- Create: `tmf-research-agent/src/tmf_research/validation/overfitting.py`
- Create: `tmf-research-agent/src/tmf_research/validation/ablation.py`
- Create: `tmf-research-agent/src/tmf_research/validation/report.py`
- Test: `tmf-research-agent/tests/overfitting/test_search_budget.py`
- Test: `tmf-research-agent/tests/overfitting/test_experiment_registry.py`
- Test: `tmf-research-agent/tests/overfitting/test_stability.py`
- Test: `tmf-research-agent/tests/overfitting/test_model_selection.py`

- [ ] **Step 1: Write P5-EXP/STB/SEL failing tests**

Enforce exact budgets 2/8/30/12/12/3, append all successes/failures, compare only identical data/folds/cost/label/period, group train-only `abs(r) > 0.90`, execute eight ablations, coefficient/sign/rank reports, neighbor sensitivity, minimum samples, concentration caps, and fixed state transitions.

- [ ] **Step 2: Run Phase 5 evidence tests before implementation**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest discover -s tests/overfitting -v`

Expected: FAIL for missing experiment/stability/report modules.

- [ ] **Step 3: Implement append-only pre-registration and budget accounting**

Require experiment ID, hypothesis, feature set, label version, parameter space, metrics, periods, and holdout state before execution. Freeze search space; record every attempt and reject deletion, best-only persistence, nearby post-result expansion, and incomparable comparisons.

- [ ] **Step 4: Implement stability and overfitting reports**

Calculate SPEC 25–31 and 39–40 metrics by fold and regime, including mean/median/best/worst/std/IQR. Run all eight feature-group ablations, coefficient stability, parameter neighborhoods, train/test gaps, sample minimums, and fold/month/direction contribution caps.

- [ ] **Step 5: Implement fail-closed model states**

Permit `APPROVED_FOR_PAPER` only when all frozen gates pass with sufficient evidence. Return `REJECTED_INSUFFICIENT_DATA`, `REJECTED_OVERFIT_RISK`, or another fixed SPEC 42 state without bypassing a failed gate.

- [ ] **Step 6: Run the complete Phase 5 gate**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest discover -s tests/leakage -v && PYTHONPATH=src python3 -m unittest discover -s tests/overfitting -v`

Expected: all Phase 5 mappings PASS for synthetic positive/negative mechanics; no market-effectiveness claim is emitted.

- [ ] **Step 7: Commit**

Commit a Lore record documenting immutable experiment budgets, multi-dimensional stability gates, and evidence-separated approval states.

### Task 11: Implement Phase 6 paper fills, risk rules, immutable ledger, and PnL

**Files:**
- Modify: `tmf-research-agent/src/tmf_research/domain/paper_trades.py`
- Modify: `tmf-research-agent/src/tmf_research/paper/broker.py`
- Create: `tmf-research-agent/src/tmf_research/paper/fill_model.py`
- Create: `tmf-research-agent/src/tmf_research/paper/risk.py`
- Create: `tmf-research-agent/src/tmf_research/paper/ledger.py`
- Test: `tmf-research-agent/tests/unit/test_paper_fill.py`
- Test: `tmf-research-agent/tests/unit/test_paper_risk.py`
- Test: `tmf-research-agent/tests/unit/test_paper_ledger.py`
- Test: `tmf-research-agent/tests/unit/test_paper_pnl.py`
- Test: `tmf-research-agent/tests/security/test_paper_tripwires.py`

- [ ] **Step 1: Write P6-PAP failing tests**

Assert one contract/position, no add/average/reverse/cross-session, executable-side fills, every entry rejection reason, exit priority, stop-first same-bar ambiguity, point value 10, one-time costs, gross-only incomplete costs, immutable PAPER rows, and untouched F10 tripwires.

- [ ] **Step 2: Run paper/security tests before implementation**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_paper_fill tests.unit.test_paper_risk tests.unit.test_paper_ledger tests.unit.test_paper_pnl tests.security.test_paper_tripwires -v`

Expected: FAIL with missing Phase 6 paper modules.

- [ ] **Step 3: Implement domain-only fill/risk decisions**

Accept immutable market/model/config values only. LONG fills ask plus slippage; SHORT fills bid minus slippage. Reject missing/stale quote, excess spread, invalid quality/model/features, open position, rollover, session end, and incomplete cost config with persisted reasons.

- [ ] **Step 4: Implement deterministic exits and append-only ledger**

Evaluate stop, target, vertical, session, stale, rollover in that order. Use tick order when available; otherwise stop first for same-bar ambiguity. Persist immutable rows with non-overridable `PAPER` mode and content checksum.

- [ ] **Step 5: Implement transparent PnL**

Calculate `gross_pnl_ntd = gross_pnl_points * 10`; subtract entry fee, exit fee, tax, and slippage exactly once. Missing costs permit gross output but no net value or profitability claim.

- [ ] **Step 6: Run Phase 6 paper and readonly tests**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root . && PYTHONPATH=src python3 -m unittest tests.unit.test_paper_fill tests.unit.test_paper_risk tests.unit.test_paper_ledger tests.unit.test_paper_pnl tests.security.test_paper_tripwires tests.test_paper_boundary -v`

Expected: verifier and all P6-PAP tests PASS; no tripwire is called.

- [ ] **Step 7: Commit**

Commit a Lore record documenting local paper-only accounting and the absence of any transport/account/raw-API surface.

### Task 12: Implement Phase 6 frozen inference, prediction JSON, registry enforcement, and replay

**Files:**
- Create: `tmf-research-agent/src/tmf_research/domain/predictions.py`
- Create: `tmf-research-agent/src/tmf_research/runtime/feature_state.py`
- Create: `tmf-research-agent/src/tmf_research/runtime/health.py`
- Create: `tmf-research-agent/src/tmf_research/runtime/live_research.py`
- Create: `tmf-research-agent/src/tmf_research/paper/replay.py`
- Test: `tmf-research-agent/tests/unit/test_prediction.py`
- Test: `tmf-research-agent/tests/integration/test_live_inference.py`
- Test: `tmf-research-agent/tests/integration/test_model_registry.py`
- Test: `tmf-research-agent/tests/replay/test_replay.py`
- Test: `tmf-research-agent/tests/replay/test_determinism.py`
- Test: `tmf-research-agent/tests/replay/test_faults.py`

- [ ] **Step 1: Write P6-INF/P6-REP failing tests**

Assert one inference per complete 1m bar, the 14 SPEC 35 checks in order, immutable frozen configuration, complete SPEC 36 JSON, `APPROVED_FOR_PAPER` enforcement, shared live/replay event interfaces, event-time operation, byte-identical two-process replay, version non-overwrite, fault equivalence, and complete trace IDs.

- [ ] **Step 2: Run inference/replay tests before implementation**

Run: `cd tmf-research-agent && PYTHONPATH=src python3 -m unittest tests.unit.test_prediction tests.integration.test_live_inference tests.integration.test_model_registry tests.replay.test_replay tests.replay.test_determinism tests.replay.test_faults -v`

Expected: FAIL with missing runtime/replay modules.

- [ ] **Step 3: Implement fail-closed frozen inference**

Execute connection, target, rollover, tick freshness, BidAsk freshness, quality, features, feature version, model checksum, probability, thresholds, prediction, paper handoff, persistence in exact order. Any failure persists a reasoned NO_TRADE result. Runtime setters for features, coefficients, scaler, thresholds, stop, target, and horizon do not exist.

- [ ] **Step 4: Implement complete prediction serialization**

Serialize the exact SPEC 36 schema with point value 10, probabilities, signal, paper plan, quality, model/feature/label versions, reasons, missing features, warnings, and traceability to raw checksum/dataset/experiment/commit/ledger.

- [ ] **Step 5: Implement event-time replay and canonical manifests**

Replay consumes the same immutable events as live research, performs no network access, and derives time only from event data. Canonical manifests fix raw checksum, dataset/feature/label/model versions, experiment, commit, seed, calendar, and cost versions; exclude volatile path/duration metadata from canonical output.

- [ ] **Step 6: Prove cross-process determinism and fault equivalence**

Run two subprocesses in different temporary directories with timezone/locale noise. Compare normalized events, bars, features, labels, probabilities, signals, fills, PnL, reports, and final SHA-256 byte-for-byte. Inject disconnect, drop, stale, rollover, and session faults and compare live/replay NO_TRADE or exit outcomes.

- [ ] **Step 7: Run the complete Phase 6 gate**

Run:

```bash
cd tmf-research-agent
PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .
PYTHONPATH=src python3 -m unittest discover -s tests/security -v
PYTHONPATH=src python3 -m unittest discover -s tests/replay -v
PYTHONPATH=src python3 -m unittest tests.unit.test_prediction tests.integration.test_live_inference tests.integration.test_model_registry -v
```

Expected: all P6 mappings PASS; only approved compatible bundles enable paper plans.

- [ ] **Step 8: Commit**

Commit a Lore record documenting shared event-time interfaces, immutable runtime configuration, and canonical replay identity.

### Task 13: Reconcile documentation, CI, and complete the final quality gates

**Files:**
- Modify: `tmf-research-agent/README.md`
- Modify: `tmf-research-agent/SPEC.md`
- Modify: `.github/workflows/tmf-research-sidecar.yml`
- Modify: `docs/superpowers/plans/2026-07-15-tmf-research-sidecar-phase1-6.md`

- [ ] **Step 1: Run verifier and all offline sidecar suites in phase order**

Run:

```bash
cd tmf-research-agent
PYTHONPATH=src python3 -m tmf_research.cli verify-readonly --root .
PYTHONPATH=src python3 -m unittest discover -s tests/security -v
PYTHONPATH=src python3 -m unittest discover -s tests/unit -v
PYTHONPATH=src python3 -m unittest discover -s tests/integration -v
PYTHONPATH=src python3 -m unittest discover -s tests/leakage -v
PYTHONPATH=src python3 -m unittest discover -s tests/overfitting -v
PYTHONPATH=src python3 -m unittest discover -s tests/replay -v
PYTHONPATH=src python3 -m unittest discover -s tests/regression -v
```

Expected: verifier prints `READONLY VERIFIED`; every offline suite exits 0.

- [ ] **Step 2: Run lint, strict typecheck, compile/install smoke**

Run the pinned lint and strict typecheck commands, then:

```bash
cd tmf-research-agent
python3 -m ruff check src tests
python3 -m mypy --strict src tests
PYTHONPATH=src python3 -m compileall -q src tests
python3 -m pip install --no-deps --target /tmp/tmf-research-install-smoke .
PYTHONPATH=/tmp/tmf-research-install-smoke python3 -m tmf_research.cli verify-readonly --root .
```

Expected: all commands exit 0 and the installed CLI prints `READONLY VERIFIED`.

- [ ] **Step 3: Run host regressions and isolation audit**

Run from repository root:

```bash
npm test
git diff main...HEAD -- src tests package.json workflows
rg -n 'tmf-research-agent|tmf_research' src tests package.json workflows || true
```

Expected: host tests PASS; no host integration diff/reference exists.

- [ ] **Step 4: Record credentialed/real-data evidence honestly**

If authorized credentials and an open market are available, run only:

```bash
cd tmf-research-agent
TMF_RUN_CREDENTIALED=1 PYTHONPATH=src python3 -m unittest discover -s tests/credentialed -v
```

Otherwise record `CREDENTIALED_VALIDATION_NOT_RUN`. Never translate an unavailable boundary into PASS and never claim positive EV, calibration, stability, or paper approval from synthetic fixtures.

- [ ] **Step 5: Reconcile README, traceability, and plan checkboxes**

Document exact commands, phase gates, generated artifact locations, state meanings, credentialed gaps, and the permanent no-brokerage boundary. Map every SPEC 46 row to P0–P6 evidence from the companion test spec.

- [ ] **Step 6: Run final repository checks**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Expected: no whitespace errors, no debug artifacts, and only approved sidecar/CI/docs paths changed.

- [ ] **Step 7: Independent reviews and final Lore commit**

Obtain independent code-reviewer and architect approval after the full evidence is fresh. Commit a Lore record with constraints, rejected unsafe alternatives, confidence, scope risk, exact tests, and explicit not-tested credentialed/real-data gaps.

## Completion claims

- **Software-complete** requires every applicable offline Phase 0–6 test, readonly verification, lint, strict typecheck, compile/install smoke, host regressions, architecture audit, and independent reviews.
- **Research-capable** additionally requires real TMF market data to traverse the unchanged immutable pipeline.
- **Approved for paper** additionally requires a frozen candidate to pass the locked holdout, sample, calibration, stability, cost, and overfitting gates on sufficient uncontaminated real data.
- None of these states authorize Phase 7 or any actual/simulated brokerage order path.
