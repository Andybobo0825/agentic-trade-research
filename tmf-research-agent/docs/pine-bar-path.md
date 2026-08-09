# Bar-sourced Pine replay

`scripts/pine_bar_dump.py` is a data adapter around the existing
`scripts/pine_signal_report.py` implementation. It imports and uses the same
`PineState`, `PRESETS`, `HORIZONS`, `_period`, `SignalEvent`, and V2/V3 scanner
symbols; it does not duplicate the signal formulas.

## Fixed bar choices

- The Shioaji `ts` in the stored raw record is a **minute closing label**. The
  first day-session row is `08:46` for the `08:45..08:46` minute. Raw
  `fields.ts` is unchanged; `minute_kbars_from_records` normalizes the
  in-memory `MinuteKbar.timestamp` to the interval start.
- A Pine timeframe bucket is anchored to the resolved session start and is
  emitted when its full window is within that session and at least one
  one-minute constituent is present. OHLC comes from the earliest/latest
  present minute and the extrema across present minutes; volume is their sum.
  This drops partial boundary buckets and empty windows and never joins
  day/night sessions.
- The kbar `Volume` column is carried unchanged and summed into timeframe
  bars. It is not converted to the tick feed's volume. On the post-2024-07-29
  TXFR1 sample, `Amount / (Close * Volume)` was approximately one (min
  `0.998914`, max `1.001836`, mean `1.000016` over 839 rows), establishing
  that `Volume` is the vendor's traded-quantity field rather than a bar count.
  It is not interchangeable with the TMFR1 tick stream: on the same wall
  clock sample the matched totals were 98,246 TXFR1 kbar units versus 20,036
  TMFR1 tick units.
- The tape uses one-minute closes. A signal enters at the first minute close
  strictly after its event time, and each exit is the latest minute close at
  or before the horizon or session close. This is a one-minute, close-only
  approximation; no intraminute OHLC path is invented.
- Random controls use the same uniform selection and 20 entries per session
  as `pine_control_dump.py`, with the pre-registered bar-path seed `20260806`.

The broker returned exact duplicate timestamp/OHLCV rows on some post-2024
requests. Storage retains every raw row (duplicate event IDs receive an
index suffix). The pure aggregation adapter coalesces exact duplicates for
processing and fails closed on conflicting duplicate values.

## Amendment 2 gate result

The original aggregate-mean gate is **void**. It compared TXF kbars with the
TMF tick baseline, so it changed instrument and granularity at once. Amendment
2 changes only the kbar bucket rule above. Gate A was rerun once on the same
60 post-2024-07-29 TXF days; Gate B was not rerun because it is tick-vs-tick
and is unaffected by this change. The gate runner is
`scripts/pine_gate_checks.py`:

```text
python scripts/pine_gate_checks.py data data/calendar-v2.json /tmp/gate-days.txt /tmp/pine-gates
```

It replays only the supplied post-2024 sample days, keeps the authoritative
`PineState` alive across those selected sessions, and compares the candidate
`15-minute / rejection / orig / SHORT` signal by
`trading_date + session + minute_of_session`. It does not read the holdout.
The TXF stores contained all 60 requested days. The TMF store contained 30;
Gate B therefore uses those 30 common days and reports the other 30 as
missing rather than inventing a comparison.
The evidence calendar has a gap over some of the sampled post-2024 dates, so
the runner fills only those sampled dates in a temporary calendar using the
repository's existing session helper; it leaves the checked-in calendar
untouched. TXF records that the resolver classified as `CLOSED` (including the
pre-calendar lead records in the first supplied segment) are dropped rather
than assigned to a session.

| gate | left N | right N | matched | left-only | right-only | left agreement | right agreement | result |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A: TXF tick vs TXF bar | 58 | 54 | 54 | 4 | 0 | 93.10% | 100.00% | **FAIL** (both directions must be ≥95%) |
| B: TMF tick vs TXF tick | 20 | 21 | 17 | 3 | 4 | 85.00% | 80.95% | claim reference met (both directions ≥80% on the 30 common days) |

Gate A still fails: tick-to-bar agreement is 93.10%, below 95%, while
bar-to-tick agreement is 100.00%. The remaining disagreement is four
TXF-tick-only signals and no bar-only signals. No threshold, session boundary,
or volume rule was tuned to close the gap. Gate B's earlier result is retained
as a portability qualification, not rerun here and not a pass/fail replacement
for Gate A.

Representative mismatch bars:

- Gate A tick-only: `2024-09-02 DAY 09:45`, `2024-11-18 DAY 09:15`,
  `2026-01-26 NIGHT minute 540 (when 2026-01-24T00:00:00+08:00)`,
  `2026-01-26 NIGHT minute 555 (when 2026-01-24T00:15:00+08:00)`.
- Gate A bar-only: none.
- Gate B TMF-only: `2024-10-11 DAY 10:30`, `2025-02-19 DAY 10:00`,
  `2026-07-31 NIGHT 03:30`.
- Gate B TXF-only: `2024-09-02 DAY 09:15`, `2024-11-18 DAY 09:15`,
  `2025-04-22 DAY 09:00`, `2026-07-21 DAY 09:00`.
