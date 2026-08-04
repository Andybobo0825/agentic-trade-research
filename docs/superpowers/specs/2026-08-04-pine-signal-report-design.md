# Pine Signal Credibility Report — Design

Date: 2026-08-04
Status: approved by user (conversation), Track 2 of the TradingView indicator work.
Companion artifact: the indicator itself is archived at `pine/taiwan-mtf-bb-sr.pine`.

## Goal

Measure, on real TMF tick data, whether the four signals in the user's
TradingView indicator (台指 MTF BB-SR) carry any net-of-cost edge, and whether
earlier-firing variants of those signals gain lead time or only noise. The
deliverable is a report table, not a strategy and not a Pine change. The user
has not traded these signals live; this is a credibility read before any
capital or further Pine work.

## Non-goals

- No Pine v2 in this track (the user chose Track 2 only for now).
- No use of the Phase 3–6 sealed pipeline, registries, or holdout — those are
  model-promotion machinery; this is a descriptive sweep in the style of
  `scripts/label_sweep.py`.
- No parameter optimization / grid search beyond the three declared variants.
  This avoids manufacturing an in-sample winner.

## Data

- Raw store: `tmf-research-agent/data` (append-only NDJSON segments,
  manifest, calendar `data/calendar.json`).
- Block A: 2024-07-29 → 2025-06-30 (~233 trading days, contiguous).
- Block B: 2026-07-01 → present fragments. Reported separately; never pooled
  with Block A (the 1-year API void between them breaks chronology).
- Bars: session-anchored 5/15/60-minute bars via the existing
  `SessionResolver` + `ProcessingPipeline` + `BarAggregator` path used by
  `label_sweep.py`.

## Signal semantics (faithful Pine reproduction)

Per-timeframe presets copied from the indicator's auto mode:

| timeframe | pivotBars | zone % | volLen | strongVol × |
|---|---|---|---|---|
| 60m | 3 | 0.30 | 10 | 1.5 |
| 15m | 4 | 0.20 | 20 | 1.6 |
| 5m  | 5 | 0.10 | 20 | 1.8 |

Shared state per timeframe series:

- Bollinger: SMA(close, 20) ± 2.0 × stdev(close, 20) (population stdev,
  matching Pine `ta.stdev`).
- Pivot high/low: left = right = pivotBars; a pivot is only known
  `pivotBars` bars after it forms. S/R levels (`resistance1`, `support1`)
  update on confirmation; signals evaluate against the *previous bar's*
  levels (`resistance1[1]` / `support1[1]`), exactly as the Pine does.
- Volume: SMA(volume, volLen); strongVolume = volume ≥ ratio × SMA.

Four signals, all evaluated at bar close (the Pine's
`barstate.isconfirmed`):

1. **breakout**: close crosses above `signalResistance` (prev close ≤ it),
   strongVolume, close > BB middle.
2. **breakdown**: mirror below `signalSupport`, close < BB middle.
3. **supportBounce**: bar touches support zone (± zone%), low ≤ BB lower,
   close ≥ signalSupport, close > open.
4. **resistanceRejection**: mirror at resistance, high ≥ BB upper,
   close ≤ signalResistance, close < open.

Direction: breakout/supportBounce = LONG; breakdown/resistanceRejection =
SHORT.

## Early variants

| variant | change relative to original |
|---|---|
| V1 shorter confirmation | pivot right bars = 2 (left stays at preset); everything else unchanged |
| V2 intrabar trigger | using ticks inside the forming bar: fire the moment price crosses the S/R level; volume test uses pace-projected volume = cumulative bar volume ÷ elapsed fraction of the bar; BB/middle checks use the last completed bar's values |
| V3 zone-entry warning | fire when price first enters the S/R tolerance zone heading toward the level (long side at support, short side at resistance); no volume or BB condition |

Pairing rule for lead time: an early-variant event is matched to the nearest
subsequent original event of the same signal type and level within one
session; matched pairs report `minutes earlier`. Unmatched early events are
the false-alarm count — reported explicitly, since that is the price of
earliness.

## Evaluation

- Entry: first tick trade price strictly after the signal timestamp.
- Exits (each horizon evaluated independently): +15 min, +60 min, +240 min,
  and day-session close; exit price = last tick trade at or before the exit
  timestamp. Horizons that cross a session end simply stop at session close
  (the day-session-close row is then identical; that is acceptable).
- Net points = direction × (exit − entry) − 3.0 (round-trip cost assumption
  carried over from the prior TMF research cost policy).
- Cell = (signal × timeframe × variant × horizon): N, win rate,
  mean net, median net.
- Stability split: 2024H2 / 2025H1 / 2026-07+ reported per cell.
- N < 30 cells are printed but flagged `insufficient`.

## Output

`scripts/pine_signal_report.py` prints a markdown report to stdout
(per-block sections, cells as above, plus the false-alarm and lead-time
tables for variants). The run's output for the record is saved by the
operator (or by redirecting stdout) — the script itself writes nothing
into `data/`.

## Verification (success check, agreed up front)

1. `pine_signal_report.py --self-test` constructs small synthetic bar series
   with hand-computed expected trigger positions for every signal and every
   variant (including pivot-confirmation timing and the `resistance1[1]`
   one-bar delay) and exits nonzero on any mismatch.
2. Full run over Block A and Block B completes and produces the report.
3. The conversation deliverable is the table plus an honest interpretation,
   including which cells are dead — the prior research predicts short-horizon
   cells will be negative, and the report must say so plainly if confirmed.

## Known limitations

- 60m rows will have few events over one year; they are directional reads
  only.
- TradingView volume is whatever contract the user charts (likely TXF/MXF);
  our series is TMF. Volume *ratios* are comparable, absolute volumes are
  not.
- Ticks are day+night session; bars are session-anchored, so overnight gaps
  never sit inside a bar.
- The 3-point cost is an assumption, not a fill simulation; results within
  ±1 point of zero are indistinguishable from noise.
