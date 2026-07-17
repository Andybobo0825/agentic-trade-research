# Historical Dataset Adapter — Design Decisions (2026-07-18)

Scope: feed `historical-tick` raw segments (from `tmf backfill`) into the
existing Phase 2→5 research pipeline, offline only. Authority stays with
`docs/txresearch.md` v1.1.0; nothing here weakens a phase gate.

## Decision 1 — Quote events are derived from tick-embedded L1, and say so

Historical ticks carry L1 `bid_price/bid_volume/ask_price/ask_volume` per
tick; there is no historical five-level book. The adapter emits:

- one `TickEvent` per stored historical tick (exchange time = stored
  Taipei-stamped time; receipt time = `received_at` from the record);
- one derived `BidAskEvent` **only when the embedded L1 changes** versus the
  previous tick of the same trading date, populated at L1 only, with the
  source marked `DERIVED_FROM_HISTORICAL_TICK_L1`. Ticks whose embedded
  quote is zero/invalid derive nothing (the quote joiner's staleness rules
  then apply naturally).

## Decision 2 — Reduced feature set is its own frozen version

Feature version `phase3-features-hist-l1-v1`: the full manifest minus every
feature requiring L2–L5 depth or genuine quote-stream frequency (L1–L5
imbalance, depth, cancel/update rates). Features needing only L1 (spread,
midpoint, microprice, L1 volumes) stay. This version never mixes with the
live full-feature version; models trained on it are a separate lineage.

## Decision 3 — Adapter is a pure function from verified segments to events

New module `processing/historical_adapter.py` (consumer side, no adapter
imports): reads segments via `AppendOnlyRawStore.read_verified` using
catalog manifests, groups by trading date (the segment's date), and returns
deterministic `(ticks, bidasks)` tuples ready for the existing
`context_builder`/dataset build path. No network, no mutation, fail-closed
on any malformed record. Trading-date semantics match the backfill window:
`[previous weekday 15:00, date 13:46)` with the night session belonging to
the segment's trading date.

## Non-goals

- No live collection changes; no five-level features; no new thresholds.
- Phase 5 gates run unchanged on the resulting datasets; small history must
  surface as `REJECTED_INSUFFICIENT_DATA`, never as a relaxed gate.

## Test surface (write failing first)

- unit: L1-change detection (emit/skip/zero-quote), event field mapping,
  determinism, malformed record rejection.
- integration: 1-2 stored fixture days → events → existing processing
  pipeline produces 1s states and bars for the correct trading date.
- leakage: derived quote events never carry a time earlier than their
  source tick; evidence times remain point-in-time.
