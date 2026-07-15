# TMF Research Sidecar Phase 1–6 Test Specification

**Target path:** `docs/superpowers/specs/2026-07-15-tmf-research-sidecar-phase1-6-test-spec.md`  
**Authority:** `docs/txresearch.md` v1.1.0  
**Existing baseline:** Phase 0 tests remain mandatory and run first  
**Framework:** deterministic Python 3.11+ `unittest`; offline CI makes no network calls

## 1. Acceptance semantics

Three claims must remain separate:

1. **Software-complete:** Phase 1–6 behavior, rejection paths, persistence,
   replay, and security tests pass.
2. **Research-capable:** real TMF data can enter the same immutable pipeline and
   validation reports can be generated without future/test leakage.
3. **Approved for paper:** a frozen candidate has passed SPEC 22, 24, 30, 43.3,
   and 43.4 on enough uncontaminated real data.

Synthetic fixtures prove gate mechanics, not market efficacy. Insufficient real
data is a successful fail-closed outcome:

```text
model_status = REJECTED_INSUFFICIENT_DATA
signal = NO_TRADE
allow_paper_trade = false
```

Tests must never lower thresholds, move fold/holdout boundaries, or fabricate a
profitable fixture to approve a model.

## 2. Mandatory phase gates

| Gate | Required executable evidence | Blocking rule |
| --- | --- | --- |
| P0 | Existing CLI/gateway/verifier/project/paper-boundary tests | `tmf verify-readonly` runs first; any finding stops all work |
| P1 | Contract resolver, subscriptions, bounded queue, raw writer, reconnect, quality | P2 evidence is ignored while failing |
| P2 | Session/trading date, backward quote join, 1s state, 1m/5m/15m/60m bars | P3 evidence is ignored while failing |
| P3 | Feature formulas/provenance/manifest, executable prices, triple barrier, leakage suite | Any leakage invalidates experiment |
| P4 | Baselines 0–4, two-stage logistic, fold-only transforms, calibration, serialization | Cannot claim validation/approval |
| P5 | Nested walk-forward, purge/embargo, budgets, stability, ablation, locked holdout | Live-paper inference remains disabled |
| P6 | Replay, frozen live inference, paper ledger/fills/PnL, prediction JSON, risk filters | No brokerage path is ever enabled |

CI order:

```bash
tmf verify-readonly
python -m unittest discover -s tests/security -v
python -m unittest discover -s tests/unit -v
python -m unittest discover -s tests/integration -v
python -m unittest discover -s tests/leakage -v
python -m unittest discover -s tests/overfitting -v
python -m unittest discover -s tests/replay -v
python -m unittest discover -s tests/regression -v
npm test
```

## 3. Deterministic fixture contract

| Fixture | Required contents |
| --- | --- |
| F01 Calendar | Asia/Taipei normal day, Friday-to-Monday night, holiday, typhoon/temporary closure, expiry 13:30/no night, normal 13:45, night 15:00–05:00; expected dates are literals |
| F02 Contracts | `TMF202607 -> TMF202608`, unchanged, target-only change, month-only change, missing target, unconfirmed rollover; injected clock |
| F03 Event tape | Tick/BidAsk/connection events; quote before/after/equal tick; stale, duplicate, out-of-order, invalid/crossed/simtrade, empty second, queue loss, reconnect, session boundary |
| F04 Raw segments | Known bytes/checksums/schema/writer/time range; tamper, duplicate ID, interrupted write, new dataset version |
| F05 Features | Hand-computable OHLCV/books/underlying/VWAP/ATR/imbalance/microprice/basis; future sentinel `9_999_999` |
| F06 Labels | LONG-first, SHORT-first, vertical, ambiguous, stale/missing quote for 5m/15m/60m; fixed slippage/ATR/cost |
| F07 Research matrix | Five valid synthetic outer folds plus insufficient variants, correlated columns, stable/flipping coefficients, concentration and fragile/stable neighborhoods |
| F08 Locked holdout | Final suffix behind an access-raising sentinel; single-use unlock token after frozen hashes only |
| F09 Registry bundle | Full SPEC 37 artifacts/metadata/checksums; one-at-a-time mismatch mutations |
| F10 Tripwires | Raw API, socket/HTTP/process/dynamic-import methods raise if paper/replay reaches them |

Fixtures return fresh immutable values. Exchange time, arrival time, and wall time
are distinct. Canonical reports exclude wall-clock duration and paths.

## 4. Phase 1 executable mapping

**Files:** `tests/unit/test_contract_resolver.py`, `test_event_queue.py`,
`test_event_normalization.py`, `test_raw_store.py`, `test_reconnect_manager.py`,
`test_data_quality.py`, `tests/integration/test_live_collector.py`

| ID | SPEC | Assertion |
| --- | --- | --- |
| P1-CON-001 | 2, 7.1, 43.2 | `TMFR1` persists alias, actual target, symbol/category, delivery month/date, resolved time/version; raw contract absent |
| P1-CON-002 | 7.2 | Missing target, hard-coded month, suffix guessing, and alias-only persistence fail closed |
| P1-CON-003 | 7.3 | Target or delivery-month change emits one deterministic complete rollover event |
| P1-CON-004 | 7.3, 34.1 | Unconfirmed rollover forces NO_TRADE and disables paper |
| P1-CON-005 | 7.2 | Cross-contract gap is not a normal return; both targets remain traceable |
| P1-COL-001 | 8 | Tick/BidAsk callbacks only parse minimum fields, stamp receipt time, enqueue, return |
| P1-COL-002 | 8 | Callback tripwires prove no model, aggregation, file, history, paper, wait, or sleep |
| P1-COL-003 | 8.1 | Full queue is non-blocking, increments drops, emits `QUEUE_BACKPRESSURE`, invalidates quality, disables paper; no silent loss |
| P1-COL-004 | 9.1–9.3 | Tick/BidAsk/Connection events contain every specified field and primitive immutable raw payload |
| P1-RAW-001 | 9.4 | Writer is append-only and records checksum, schema/writer versions, time range |
| P1-RAW-002 | 9.4 | Reprocessing creates a new dataset version without changing old bytes/checksum |
| P1-RAW-003 | 9.4 | Tamper, duplicate ID, partial write, path reuse fail closed with evidence |
| P1-QLT-001 | 13 | Every invalid/stale/duplicate/simtrade/crossed/out-of-session/unknown-target/queue-loss reason is retained, never silently deleted |
| P1-QLT-002 | 13 | Per date/session report includes all counts, max gap, coverage, status |

P1 offline tests prove behavior. Stable live collection also requires the
credentialed boundary in section 11.

## 5. Phase 2 executable mapping

**Files:** `tests/unit/test_session_resolver.py`, `test_quote_joiner.py`,
`test_one_second.py`, `test_bars.py`, `tests/integration/test_processing_pipeline.py`

| ID | SPEC | Assertion |
| --- | --- | --- |
| P2-SES-001 | 10.1–10.2 | Exact DAY/NIGHT/CLOSED and trading dates for F01; Friday/holiday/closure never use calendar `+1` |
| P2-SES-002 | 2, 10 | Expiry day ends 13:30/no night; normal day ends 13:45 |
| P2-SES-003 | 10.3 | Bars anchor at 08:45/15:00, never Unix hour multiples |
| P2-JOIN-001 | 11 | Only latest quote with `quote_time <= tick_time`; future-nearest quote never selected |
| P2-JOIN-002 | 11 | Equal-time tie is deterministic; matched time, age, availability persisted |
| P2-JOIN-003 | 11 | Missing/stale quote cannot feed spread/book, executable labels, paper entry/exit |
| P2-AGG-001 | 12.1 | Non-empty 1s state matches hand-calculated price/flow/book/basis/age fields |
| P2-AGG-002 | 12.1 | Empty second may carry quote/book/underlying but never volume/trades/buy/sell or fake OHLC |
| P2-AGG-003 | 12.2 | 1m/5m/15m/60m bars have all fields, coverage, completeness, session anchoring |
| P2-AGG-004 | 12.2–13 | Incomplete bars are marked/excluded; raw-to-bars output is deterministic and raw input unchanged |

## 6. Phase 3 executable mapping

**Files:** feature-group unit tests, `test_feature_pipeline.py`,
`test_executable_prices.py`, `test_triple_barrier.py`, `test_label_pipeline.py`,
and all `tests/leakage/` cases.

| ID | SPEC | Assertion |
| --- | --- | --- |
| P3-TIME-001 | 14 | Every feature has feature/decision/evidence time and version; evidence after decision rejects experiment |
| P3-TIME-002 | 14 | Future sentinel cannot change prior output; centered rolling, backfill, global transforms/quantiles fail |
| P3-TIME-003 | 15.7, 41.2 | Swing appears at right-confirmation time; previous-day fields never use current close |
| P3-MAN-001 | 15, 19.4 | <=40 primary candidates +10 indicators; formal <=30 primary +5 declared interactions |
| P3-FEA-001 | 15.1 | Returns/EMA/consecutive/body/wicks match F05; zero range is finite-safe |
| P3-FEA-002 | 15.2 | Session/rolling VWAP and slopes/crosses match; DAY/NIGHT reset separately |
| P3-FEA-003 | 15.3 | Flow/imbalance/unknown/acceleration/rate/large trade match; large threshold train-only |
| P3-FEA-004 | 15.4 | Spread/mid/microprice/L1-L5 imbalance/depth/cancel/update rate match; invalid quote becomes missing |
| P3-FEA-005 | 15.5 | Basis is TMF-underlying; missing underlying stays missing and never zero |
| P3-FEA-006 | 15.6 | TR/ATR/realized vol/range expansion/percentile match; percentile is past/train-only |
| P3-FEA-007 | 15.7–15.8 | Structure/session/minutes/expiry/rollover features use completed evidence and correct boundaries |
| P3-LAB-001 | 17.1–17.2 | One candidate per complete 1m decision for separate 5m/15m/60m datasets; 15m primary |
| P3-LAB-002 | 17.3 | LONG ask+/bid-, SHORT bid-/ask+ slippage; close-only pricing rejected |
| P3-LAB-003 | 17.4 | Barriers are max(ATR multiple, minimum), selected train/inner-only |
| P3-LAB-004 | 17.5 | LONG/SHORT/vertical/ambiguous map exactly; ambiguous counted but excluded from train |
| P3-LAB-005 | 17.6 | Every specified label, price, barrier, touch, excursion, cost, time, horizon/version field persists |

Mandatory leakage injections: evidence time, future quote, scaler, imputer,
outlier limit, calibrator, parameter selector, threshold selector, swing,
previous-day, correlation selector, label parameters, locked holdout. Each illegal
fixture must reject or leave prior/frozen output unchanged.

## 7. Phase 4 executable mapping

**Files:** `test_baselines.py`, `test_logistic.py`, `test_probability.py`,
`test_scaler.py`, `test_imputer.py`, `test_calibration.py`,
`test_model_serialization.py`, leakage transform-scope tests.

| ID | SPEC | Assertion |
| --- | --- | --- |
| P4-BAS-001 | 18 | Baselines 0–4 deterministic and separately reported per outer fold |
| P4-MOD-001 | 19.1 | Model A fits TRADE vs NO_TRADE and returns bounded trade probabilities |
| P4-MOD-002 | 19.2 | Model B sees only train LONG/SHORT and returns bounded conditional direction |
| P4-MOD-003 | 19.3 | Product formulas exact; final probabilities in [0,1] and sum to one |
| P4-MOD-004 | 19.4 | L2, class weight, deterministic convergence/max iterations, feature order and diagnostics persist; forbidden expansion/selection rejected |
| P4-PRE-001 | 32–33 | Scaler/imputer/outlier/large-trade transforms fit train only; test sentinels cannot change learned values |
| P4-PRE-002 | 32 | Required missing => NO_TRADE; optional missing => train median + indicator; no backfill/future value |
| P4-CAL-001 | 29 | Uncalibrated/Platt/isotonic fit/select inner-only, ordered by Brier/LogLoss/ECE/EV; sparse bins insufficient |
| P4-SER-001 | 19.4, 37 | Round-trip probabilities identical and all registry files/metadata/checksums exist |
| P4-SER-002 | 37 | Any feature/version/order/instrument/session/horizon/schema/checksum/dimension mismatch => NO_TRADE |

## 8. Phase 5 executable mapping

**Files:** `tests/overfitting/test_walk_forward.py`, `test_locked_holdout.py`,
`test_search_budget.py`, `test_experiment_registry.py`, correlation/ablation/
coefficient/sensitivity/gap/sample/stability/model-selection tests; purge/embargo
and selector tests under `tests/leakage/`.

| ID | SPEC | Assertion |
| --- | --- | --- |
| P5-FOLD-001 | 21.1–21.3 | Outer/inner time order and non-overlap; shuffled/random/KFold rejected; outer test inaccessible to selectors |
| P5-FOLD-002 | 21.4 | Train `outcome >= validation_start` and validation `outcome >= test_start` purged, including equality |
| P5-FOLD-003 | 21.5 | Embargo >= maximum horizon; 59m fails 60m model |
| P5-HOLD-001 | 22 | Holdout is final contiguous suffix, >=40 effective days and >=ceil(15%); no pre-freeze read |
| P5-HOLD-002 | 22 | Unlock only after model/features/labels/parameters/thresholds/rules/hashes frozen, and once only |
| P5-HOLD-003 | 22 | Re-run or post-test model change marks contamination and prevents approval |
| P5-HOLD-004 | 22, 30 | Insufficient nested+holdout data => `REJECTED_INSUFFICIENT_DATA` |
| P5-EXP-001 | 23 | Pre-registration complete/immutable; exact limits 2/8/30/12/12/3 enforced |
| P5-EXP-002 | 23, 38 | All successes/failures append-only; deletion, best-only, nearby post-result search fail; incomparable experiment conditions rejected |
| P5-STB-001 | 16 | `abs(r)>0.90` groups and retain choice use train-fold only, ordered completeness/simplicity/stability |
| P5-STB-002 | 27 | All eight feature-group ablations report LogLoss/Brier/NetEV/count/drawdown/fold stability |
| P5-STB-003 | 26 | Coefficient value/sign/magnitude/rank per fold; important sign >=70%; flippers flagged |
| P5-STB-004 | 28 | L2 0.5x/1x/2x, threshold t±0.05, ATR m±0.25; isolated peaks reject overfit |
| P5-STB-005 | 25 | Train/test LogLoss/Brier/EV/PF/frequency and risk rules form gap report |
| P5-SEL-001 | 30 | Fold minimums 5000 train, 500 test, 30 trades, 10 LONG, 10 SHORT; <5 valid folds rejects insufficient |
| P5-SEL-002 | 24, 43.4 | >=70% non-negative NetEV and baseline outperformance; fold/month/direction caps 40/30/85%; non-positive total cannot bypass |
| P5-SEL-003 | 24, 31 | Gate includes Brier/LogLoss/cost/month/direction/event/gap/coefficient/parameter/regime/target-code stability |
| P5-SEL-004 | 39–40 | All classification/trading/stability metrics plus per-fold/mean/median/best/worst/std/IQR; split regions visible |
| P5-SEL-005 | 42–43 | Fixed state transitions; only all-gate frozen candidate may become `APPROVED_FOR_PAPER` |

Synthetic positive and negative cases prove the gate. Real approval requires the
same unchanged gate on sufficient real data.

## 9. Phase 6 executable mapping

**Files:** fill/risk/ledger/PnL/prediction unit tests, live inference/model
registry integration tests, and replay/determinism/fault tests.

| ID | SPEC | Assertion |
| --- | --- | --- |
| P6-PAP-001 | 34 | One contract/one position, no add/average/reverse/cross-session |
| P6-PAP-002 | 34.1 | LONG ask+ and SHORT bid- fills; every listed entry rejection persists reason |
| P6-PAP-003 | 34.2 | Exit priority stop,target,vertical,session,stale,rollover; ambiguous same-bar stop first unless tick resolves |
| P6-PAP-004 | 34.3 | Gross points*10; net subtracts fees/tax/slippage once; incomplete costs permit gross only/no profit claim |
| P6-PAP-005 | 4.4, 41.5 | Every row immutable/non-overridable PAPER; F10 proves no network/account/CA/raw API/broker method |
| P6-INF-001 | 35 | One inference per complete 1m bar, 14 validation/action steps in fail-closed order |
| P6-INF-002 | 35 | Runtime cannot mutate features/coefficients/scaler/threshold/stop/target/horizon; retraining creates version |
| P6-INF-003 | 36 | Complete JSON schema, point value 10, probabilities, trace versions/reasons/missing/warnings |
| P6-INF-004 | 37, 42 | Only `APPROVED_FOR_PAPER` enables plan; other states/mismatches => persisted NO_TRADE |
| P6-REP-001 | 34–36 | Replay shares live event interfaces, uses event time, no network |
| P6-REP-002 | 41.4, 45 | Same raw/dataset/feature/label/model versions and seed => byte-identical features, labels, probabilities, signals, fills, PnL, report checksum in two processes |
| P6-REP-003 | 41.4 | Version/seed change creates new identity and cannot overwrite prior replay |
| P6-REP-004 | 8, 13, 34 | Disconnect/drop/stale/roll/session faults reproduce live NO_TRADE/exit outcomes |
| P6-REP-005 | 46 | Prediction traces raw checksum, dataset, feature/label/model, experiment, commit, ledger |

## 10. Cross-cutting security and determinism gates

Add security cases proving:

- enlarged source still passes the Phase 0 AST/string/import-graph verifier;
- only `shioaji_market_data.py` retains raw SDK/API state;
- collectors depend on `MarketDataGateway`, and model/paper/runtime cannot import
  or reach the raw adapter;
- `PaperBroker` public signatures accept domain values only;
- socket/HTTP/process/dynamic-import/raw-API tripwires are untouched;
- every paper record is `PAPER` and that value cannot be overridden;
- host Node CLI/MCP/runtime/strategy has no sidecar import or invocation;
- no actual or simulated order, CA, account, position, margin, modification,
  cancellation, or forwarding capability exists.

Canonical replay manifests fix raw checksum, dataset/feature/label/model versions,
experiment, commit, seed, calendar, and cost versions. Run twice in separate temp
directories/processes with timezone/locale noise; normalized events, bars,
features, labels, predictions, fills, ledger, reports, and final SHA-256 match
byte-for-byte. Volatile path/duration metadata stays outside checksum content.

## 11. Credentialed and real-data boundary

Default CI has no Shioaji credentials and no network. Offline tests cannot prove:

- live authentication, current `TMFR1` payload/target shape;
- real Tick/BidAsk delivery, rate, latency, order, reconnect recovery;
- future exchange-calendar changes;
- sufficient uncontaminated history for five folds plus locked holdout;
- positive real-data EV/calibration/stability/holdout.

Opt-in only:

```bash
TMF_RUN_CREDENTIALED=1 python -m unittest discover -s tests/credentialed -v
```

It runs the verifier first, accepts market-data gateway only, refuses any
certificate/account/order capability, scrubs secrets/account data, unsubscribes
under timeout, and never tunes/approves from its short sample. Unavailable
credentials/market must report `CREDENTIALED_VALIDATION_NOT_RUN`, not pass.

## 12. Definition-of-Done traceability

| SPEC 46 requirement | Evidence |
| --- | --- |
| Read-only/no order | P0 + security gate |
| Stable collection | P1 offline + successful credentialed smoke, else explicit gap |
| Target/rollover | P1-CON |
| Day/night | P2-SES |
| Raw immutable | P1-RAW |
| No future features | P3-TIME + leakage injections |
| Executable labels | P3-LAB |
| Reproducible nested WF | P5-FOLD + deterministic replay |
| Holdout unpolluted | P5-HOLD + sentinel |
| Overfit/parameter/ablation/coefficients | P5-EXP/STB/SEL |
| Replayable paper | P6-PAP/REP |
| Transparent costs | P6-PAP-004 + cost version |
| Traceable predictions | P6-INF/REP |

Phase 0–6 is software-complete only when every applicable offline test passes and
all credentialed/real-data gaps are stated. It does not authorize Phase 7 or any
actual trading.
