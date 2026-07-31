# Phase3 Stability Demo Promotion Design

Date: 2026-07-09  
Status: Approved design  
Scope: Taiwan equity research and demo execution replay only

## Objective

Make `phase3_stability` the fixed research standard, validate it against historical
intraday market data under realistic execution constraints, and promote it to the
repository's only main strategy only if every promotion gate passes.

The work must never call a real or broker-demo order API. The term "demo" in this
design means a deterministic local replay over read-only market data.

## Non-negotiable boundaries

1. Market-data access is read-only.
2. No component may import, expose, or call order placement, amendment, or
   cancellation functions.
3. No CLI command may accept `--live`, brokerage account, certificate, credential,
   or order-routing parameters.
4. Every result must declare `executionMode: demo_replay`.
5. Missing or invalid evidence fails closed and cannot count toward promotion.
6. Promotion leaves exactly one executable strategy. Strategies must not overlap,
   run in parallel, or combine signals.

## Selected architecture

The implementation uses an event-replay execution simulator rather than an OHLCV
probability model or a broker demo-order connection.

### IC.TPEX peer resolver

The resolver maps each ticker to official IC.TPEX industry-value-chain groups.
It supports a company belonging to multiple chains, stores source URL and retrieval
time, and produces a cache that can be audited and replayed.

Ticker-prefix grouping is removed. If no official mapping is available, the ticker
is rejected from group-health processing; the resolver must not fall back to the
first two ticker digits.

### Read-only market replay

The replay layer consumes saved Shioaji ticks and order-book snapshots. It normalizes
events into chronological market-data records and rejects inverted timestamps,
invalid prices, negative quantities, and malformed book levels.

The layer has no dependency on account or order-routing modules. Historical inputs
must be sufficient to reproduce a run without a broker session.

### Demo execution simulator

The simulator consumes strategy intents and read-only market events. It models:

- available quantity at each price level;
- price-time queue constraints without assuming queue priority that is not present
  in the source data;
- partial fills and residual quantities;
- entry and exit slippage;
- stop-price penetration;
- delayed stop execution when no executable liquidity exists;
- open residual exposure through later events or close-of-session valuation.

It must never assume a stop fills at the stop price merely because an OHLC bar
crossed that price.

## Fixed strategy standard

The initial candidate is the approved `phase3_stability` configuration:

- HMA period: 5
- volume multiplier: 0.8
- hold days: 12
- entry mode: trend
- exit mode: close only
- minimum signal-day price change: 4%
- minimum close position: 0.45
- maximum trades per day: 5
- maximum trades per peer group per day: 1
- disaster stop: -8%
- rolling peer-group health: enabled
- group-health minimum realized trades: 2
- group-health minimum average return: -5%
- group-health minimum win rate: 25%
- drawdown pause: -10%
- drawdown pause duration: 5 trading days
- minimum average turnover: TWD 20,000,000

These signal parameters are locked during execution validation. A failed promotion
run must not be made to pass by lowering the acceptance thresholds.

Evidence from the training/calibration partition may justify changes only to
position sizing, liquidity limits, or stop-execution risk controls. Such a change
creates a new version and must pass the untouched holdout from the beginning.

## Data flow

1. Resolve the historical ticker universe to official IC.TPEX peer groups.
2. Load immutable saved ticks and order-book events for selected sessions.
3. Generate `phase3_stability` intents without changing its signal parameters.
4. Replay each intent through the demo execution simulator.
5. Apply peer-group portfolio gates and rolling peer health using IC.TPEX groups.
6. Apply Cathay Securities transaction costs to each simulated fill.
7. Aggregate fill, exposure, return, drawdown, and stop-execution metrics.
8. Evaluate every promotion gate and write a reproducible evidence report.

## Cathay Securities cost model

For listed and OTC Taiwan stocks submitted electronically, the cost model uses:

- commission on each buy fill: 0.399 per mille of executed consideration;
- commission on each sell fill: 0.399 per mille of executed consideration;
- conservative minimum commission assumption: TWD 20 per fill;
- stock transaction tax on sells: 0.3% of executed consideration;
- no day-trading tax reduction because the candidate normally holds for 12 days.

Each partial fill is costed independently. Executed consideration is calculated
from executed quantity and execution price in whole TWD according to the documented
broker convention.

The public Cathay Taiwan-stock fee page states the 0.399 per mille electronic-order
rate but does not state a general electronic-order minimum. The TWD 20 minimum is
therefore an explicit conservative simulation assumption, not a claim about every
customer's negotiated account tariff.

The fee configuration records an `effectiveDate` so historical reports remain
reproducible after future fee changes.

Sources:

- Cathay Securities Taiwan fee schedule:
  <https://www.cathaysec.com.tw/cathaysec/Products/TradeFee/TWS.aspx>
- Taiwan Stock Exchange fee and tax guide:
  <https://www.twse.com.tw/zh/about/company/guide.html>

## Sampling and partitions

Promotion evidence must include both:

1. at least one continuous block of 20 valid trading sessions; and
2. a fixed-seed random sample of valid sessions.

The suite must include high-volatility, low-liquidity, gap, and near-limit-down
stress cases when available. A session with missing ticks, missing required
order-book evidence, or structurally invalid data is invalid and does not count
toward the 20-session threshold.

Training/calibration data is separate from a fixed holdout. The holdout is opened
only for final validation and cannot be reused for iterative tuning.

## Promotion gates

All gates are mandatory:

- at least 20 valid intraday replay sessions;
- at least 50 simulated completed trades;
- simulated fill rate of at least 80%;
- stop execution rate of at least 95%;
- no residual exposure above the configured position after partial fills;
- positive total return after commissions, taxes, and modeled slippage;
- maximum drawdown no worse than -16%;
- identical results when rerun with the same seed and immutable inputs;
- zero order API imports, symbols, routes, or calls in the replay dependency graph;
- all targeted and repository-wide automated tests pass.

The report must disclose rejected intents, partial fills, unfilled residuals,
slippage distribution, stop latency, stop shortfall, transaction costs, return,
maximum drawdown, sample dates, input hashes, and seed.

## Error handling

- Missing ticks or order books invalidate the session.
- Missing IC.TPEX mapping rejects the ticker from peer-group decisions.
- Stale IC.TPEX cache entries are refreshed before creating a frozen validation
  input; failed refresh prevents a new validation snapshot.
- Timestamp reversal, invalid price, negative quantity, or malformed depth rejects
  the affected event and invalidates the affected trade or session as appropriate.
- A stop with no executable bid remains open and contributes to residual exposure
  and adverse valuation until a later executable event or session close.
- Insufficient sessions, trades, fills, or stop observations fails promotion.
- Every failure is retained as evidence; the evaluator must not silently drop
  adverse trades or sessions.

## Test strategy

Development follows red-green-refactor TDD. Automated tests cover:

- IC.TPEX multi-chain membership, no mapping, refresh, and frozen cache behavior;
- removal of ticker-prefix grouping from universe selection and market backtests;
- chronological replay and invalid-event rejection;
- price-level depth consumption and conservative queue treatment;
- partial, complete, and zero fills;
- slippage through multiple book levels;
- stop gaps, missing bids, delayed fills, and close valuation;
- Cathay 0.399 per mille commission on both sides, TWD 20 conservative minimum,
  and 0.3% sell tax;
- fixed-seed reproducibility and immutable input hashing;
- static and dependency-level rejection of order API symbols;
- fail-closed promotion evaluation;
- existing v1 and v2 risk-control behavior until promotion is completed.

Fresh targeted tests, the complete test suite, deterministic replay, and a source
scan are required before a promotion claim.

## Promotion and single-strategy rule

Before the gates pass, `phase3_stability` remains a challenger and the current main
strategy remains unchanged.

After every gate passes:

1. create a new Standard Workflow version;
2. make `phase3_stability` the repository's only main and executable strategy;
3. remove `R18H6_VOL_exit_only_WR3` from program entry points, strategy options,
   standard workflow instructions, and normal output;
4. do not retain an executable baseline or parallel strategy;
5. retain only version-control history and the promotion decision report as the
   audit record that the old strategy was replaced;
6. update `docs/standard-workflow-v1.md` and `.omx/project-memory.json`;
7. keep all execution permanently locked to local `demo_replay`.

If any gate fails, promotion and old-strategy removal do not occur. The failure
report remains available for the next evidence-backed iteration.

## Completion condition

The task is complete only when either:

- all promotion gates pass and the repository contains exactly one documented,
  executable, demo-only main strategy (`phase3_stability`); or
- the available valid historical intraday evidence is exhausted and a report
  proves which mandatory gate remains unsatisfied without weakening that gate.
