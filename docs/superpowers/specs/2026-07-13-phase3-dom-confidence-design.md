# Phase 3 DOM Confidence Overlay Design

## Goal

Add a read-only Shioaji Depth of Market confidence overlay after Phase 3 technical eligibility and external news, earnings-call, and financial-statement research. The overlay must always return the available market-depth data plus reference entry, waiting, take-profit, and stop-loss prices. It must not alter Phase 3 eligibility, enter the point-in-time dataset, or place an order.

## Main Workflow

The sole active strategy remains `phase3_stability`:

1. Update point-in-time evidence with `phase3-dataset`.
2. Produce technically eligible candidates with `phase3-screen`.
3. Research news, earnings calls, financial statements, Gooaye transcripts, and industry context to adjust investment confidence outside the Phase 3 dataset.
4. Run `phase3-dom-confidence` for the selected eligible ticker.
5. Deliver the DOM measurements, DOM confidence score, reference prices, and risks for manual execution.

`phase3-dom-confidence` is a post-screen execution-information overlay, not a second strategy and not a Phase 3 filter feature.

## Public Interface

Add one read-only CLI/tool/MCP command:

```sh
node src/cli.js phase3-dom-confidence \
  --ticker 2330 \
  --exchange TSE \
  --samples 3 \
  --interval-ms 5000 \
  --timeout-ms 3000 \
  --format markdown
```

The fixed production defaults are three samples with five seconds between sample starts, covering approximately ten seconds. Input schemas remain closed and reject live/order-shaped arguments.

## Components

### `src/phase3-dom-confidence.js`

Owns DOM validation, scoring, reference-price selection, and report rendering. It depends only on the existing read-only `getShioajiOrderBook()` market reader and an injectable sleep function.

The module exports:

- a frozen configuration;
- a pure one-snapshot pressure calculator;
- a pure multi-snapshot confidence evaluator;
- the asynchronous three-sample application service;
- Markdown rendering.

### Existing Shioaji market reader

`getShioajiOrderBook()` continues to own subscribe, SSE read, normalization, and unsubscribe. No order API, order guard override, credentials for trading, or broker execution endpoint is introduced.

## Sampling and Validation

For one ticker, collect three snapshots at approximately 0, 5, and 10 seconds.

A sample is valid only when:

- the returned ticker matches the requested ticker;
- at least one finite positive bid price/volume pair and one finite positive ask price/volume pair exist;
- best bid is strictly below best ask;
- the stock is not suspended;
- the sample contains no malformed negative volume.

Invalid samples are retained in the audit output with an error reason but do not enter the score. Two or three valid samples produce normal confidence. One valid sample produces a low-reliability score and still returns all price fields available from that snapshot. Zero valid samples returns `unavailable`, null price fields, and explicit errors; prices are never fabricated.

## DOM Measurements

For each valid sample:

1. Weight levels from nearest to farthest with `[5, 4, 3, 2, 1]`.
2. Calculate weighted bid and ask depth.
3. Calculate depth imbalance:

   `(weightedBid - weightedAsk) / (weightedBid + weightedAsk)`

4. Calculate order-change pressure from `diffVolume`, bounded to `[-1, 1]`.
5. Calculate sample pressure as `80% depth imbalance + 20% change pressure`.

Across valid samples:

- use mean pressure as the principal measurement;
- add a small bounded persistence component when all usable samples keep the same pressure direction;
- map the final measurement to a separate `domConfidenceScore` from 0 to 100;
- expose a bounded `domConfidenceAdjustment` from -5 to +8 for human synthesis only;
- label the result `strong_buy_pressure`, `buy_pressure`, `balanced`, `sell_pressure`, or `strong_sell_pressure`.

Neither score nor adjustment can change `phase3-screen` eligibility.

## Reference Prices

All reported prices come directly from the latest valid five-level DOM snapshot, so no synthetic tick rounding is required.

For a long Phase 3 candidate:

- `activeEntryLimit`: best ask when DOM confidence is at least 65; otherwise best bid.
- `patientEntryPrice`: the bid level with the largest weighted displayed volume.
- `takeProfitPrice`: the ask immediately before the largest weighted ask wall; if the wall is best ask, use best ask.
- `stopLossPrice`: the next displayed bid below the selected support wall; if no lower bid is visible, use the lowest visible bid and mark the stop reference as low reliability.

The report always includes these four fields when at least one valid sample exists. A weak or selling DOM may produce `wait` as the interpretation, but the prices remain present. These are reference levels for manual decisions, not guaranteed fills or automatic instructions.

## Output Contract

Return:

- `ticker`, source, endpoint, read-only mode, requested and valid sample counts;
- each sample timestamp, five-level bids/asks, weighted depths, imbalance, change pressure, and validation error;
- `domConfidenceScore`, `domConfidenceAdjustment`, pressure label, persistence, and reliability;
- `activeEntryLimit`, `patientEntryPrice`, `takeProfitPrice`, `stopLossPrice`;
- the exact DOM levels used to derive each price;
- `interpretation` and `risks` without suppressing prices;
- a deterministic result hash over the collected sample payload and derived result.

## Error Handling

- Individual sample timeouts or malformed snapshots are recorded and sampling continues.
- The tool never fails merely because the score indicates selling pressure.
- If every sample fails, return a structured unavailable report rather than pretending there is no opportunity.
- Unknown, live, order, or execution arguments fail before any Shioaji call.
- The service always attempts unsubscribe through the existing Shioaji reader.

## Safety Boundaries

- Read-only Shioaji BidAsk SSE endpoints only.
- No order placement, account position, balance, certificate, or live-order dependency.
- No DOM record enters `phase3-dataset`, candidate artifacts, or Phase 3 hard/soft technical score.
- News and fundamental confidence remain separate research output; DOM is evaluated afterward.
- The user remains responsible for manual execution.

## Testing

Use test-first development to cover:

- weighted depth and imbalance math;
- persistence and bounded confidence scoring;
- bullish, balanced, and bearish pressure labels;
- three samples with two injected waits;
- partial timeout and malformed-sample handling;
- zero-sample unavailable output without fabricated prices;
- entry, patient-entry, take-profit, and stop-loss selection;
- weak DOM still returns every available price field;
- CLI/tool/MCP closed read-only schemas;
- no Phase 3 dataset/filter integration;
- no order API vocabulary in the new entry graph;
- active workflow documentation orders DOM after external confidence research;
- complete repository regression suite.

## Completion Criteria

The feature is complete when the new command gathers three read-only DOM samples, produces auditable pressure metrics and all four reference prices whenever depth exists, remains independent from Phase 3 data and eligibility, appears after external confidence research in the active workflow, passes independent review, and is integrated into `main` with a clean worktree.
