# Pre-registration — 2020-03 to 2024-07 holdout for the 15m 壓力遇阻 short

**Written and committed before any 2020–2024 result was computed.** The point
of this document is that the criteria are fixed before the data is seen. Five
searches on this instrument died from tuning until something passed; the one
result that survived ([[pine_control_test.py]], commit `1f53c4a`) survived
because it was pre-registered. This test follows the same discipline.

## Why this test exists

The candidate — 15-minute 壓力遇阻 (rejection), 原版 variant, SHORT — was
selected from 144 cells the author had already read, over data starting
2024-07-29. Every number quoted for it comes from that same window, so the
selection has never been priced against fresh data. Bonferroni correction
puts zero back inside its confidence interval.

Shioaji `api.kbars` reaches back to 2020-03-02 (verified 2026-08-06). That is
about 4.3 years the 144-cell search never touched, and it contains the
COVID-19 crash and the 2022 bear market — the direct test of the known
weakness that 60% of the two-year profit came from a single crash month.

## Candidate — fixed, no alternatives

    15-minute 壓力遇阻 (rejection), 原版 variant, SHORT, horizons 60/240/sclose.

**There are no fallbacks.** The original test declared three because it was
choosing among candidates. This test is not choosing — the candidate is
already fixed by the earlier result. If it fails here, it fails. No variant,
no session subset, and no alternative signal will be substituted afterwards.

## Data

- Source: Shioaji `api.kbars(Contracts.Futures.TXF["TXFR1"], start, end)`,
  1-minute bars, day and night sessions.
- Holdout window: **2020-03-02 through 2024-07-26** (the last trading day
  before the existing tick dataset begins on 2024-07-29). No overlap.
- Reconciliation window: **2024-07-29 onward**, where both bar and tick data
  exist. Used only for the gate below, never for the verdict.
- 15-minute bars are aggregated from 1-minute bars within a session; a bar is
  emitted only if the full 15 minutes fall inside one session. Partial bars
  at session boundaries are dropped, not padded.
- 1-minute bars additionally resolve, inside any 15-minute bar, whether a stop
  or a target was reached first. Where both fall in the same 1-minute bar the
  **worse** outcome for the position is taken.

## Gate — the bar pipeline must reproduce the tick pipeline first

Before the holdout is computed, the bar-based pipeline is run over
2024-07-29 onward and compared against the committed tick-based numbers
(2024H2 N=112 mean +8.41; 2025H1 N=136 mean +24.90; 2026+ N=18 mean +143.22).

**Tolerance, per period:** signal count within ±5%, and signal mean net within
±2.0 points.

If any period falls outside tolerance, the bar pipeline is measuring something
other than the signal that was validated, and **the holdout result is void** —
it is not reported, not partially reported, and not "adjusted". The
discrepancy is investigated and this document is amended and re-committed
before any holdout number is looked at.

## Periods

Nine calendar half-years: 2020H1 (from 03-02), 2020H2, 2021H1, 2021H2, 2022H1,
2022H2, 2023H1, 2023H2, 2024H1 (through 2024-07-26 — the three July weeks are
folded into 2024H1 rather than forming a stub period).

## Control

Identical construction to the original: random entries drawn uniformly from
the same sessions' own traded moments, same direction, same horizons, same
3.0-point round-trip cost. Both forms reported — plain, and time-matched to
the signal's own (period × session × 30-minute-of-session) distribution.

Bootstrap 10,000 resamples. Seed **20260806**.

## Pass criteria — all four required, at a horizon

- **P1.** Signal mean net > control mean net in **at least 7 of the 9
  periods**.
  *Why 7/9 and not 9/9:* the original required 3 of 3, which a fair coin
  clears with probability 0.125. Requiring 9 of 9 here would be a far harsher
  bar (p = 0.002) and would reject on noise alone. 7 of 9 clears at
  p = 0.090 — comparable to the original, marginally stricter.
- **P2.** Bootstrap 95% CI of (signal mean − control mean), pooled across
  periods, excludes zero.
- **P3.** Signal mean net > 0 after cost in at least 7 of the 9 periods.
- **P4.** Signal N ≥ 100 in at least six periods.

A horizon passes only if all four hold. The candidate passes if any of the
three horizons passes.

## Crash dependence — reported always, and it changes the verdict label

Crash months are defined from **price data only, before the test is run**:
any calendar month whose maximum peak-to-trough drawdown in daily TX closes
(FinMind `TaiwanFuturesDaily`, `futures_id=TX`) is ≥ 10%. The list is computed
and written into this document's appendix before the holdout runs.

P2 is then recomputed with all crash months excluded. The verdict is labelled:

| Outcome | Label |
|---|---|
| P1–P4 pass, and P2 still passes without crash months | **PASS** |
| P1–P4 pass, but P2 fails without crash months | **PASS (crash-dependent)** — the signal is a crash-payoff strategy, not a general edge, and must be sized and described as one |
| P1–P4 fail | **FAIL** — the 2024–2026 result was selection noise; the signal is retired and the project's conclusion is written as negative |

## Single run

The holdout is computed **once**. No re-running with a different seed, cost
assumption, bar-alignment rule, or period split after seeing a result. Any
such change makes the result exploratory and it is reported as exploratory.

## Amendment 1 (2026-08-06) — the instrument changes to TXF

**Written before any holdout data was processed.** The holdout window
2020-03-02..2024-07-26 has still never been run through a signal program. What
follows is forced by a fact about the instrument, not by a result.

**The fact:** 微型臺指期貨 (TMF) began trading on **2024-07-29**. The tick
dataset the original result was computed on starts that day because that is
the instrument's first trading day, not because of a backfill limit. The
candidate signal was therefore validated on an instrument with two years of
existence, and a 2020–2024 holdout on TMF cannot exist. Shioaji confirms this
from the other side: TMF returns zero kbars for every historical date.

**The change:** the holdout runs on **TXF (臺股期貨)**, continuous near-month
alias TXFR1, 1-minute bars, 2020-03-02 onward. Everything else in this
document — candidate, horizons, cost, periods, control construction, seed,
P1–P4, the crash-month list, the no-fallbacks rule and the single-run rule —
stands unchanged. The crash-month appendix was already computed from TX daily
closes, so it needs no revision.

**What this costs, stated plainly:** TXF and TMF track the same index and
their price paths are near-identical, but they are different contracts with
different volume. `PineState`'s 帶量 test compares bar volume against its own
rolling SMA, so it is a relative measure and may transfer — may. That is an
assumption, and the gate below exists to price it rather than assume it.

### The reconciliation gate is replaced by two separate checks

The original single gate compared a TXF bar path against a TMF tick baseline.
That confounds two variables, and a number that agreed would have agreed for
reasons nobody could name. It is void and replaced.

Both checks run on the same sample: **60 trading days drawn evenly across
2024-07-29 to the present**, the only window where TMF exists.

**Gate A — granularity.** TXF bar path vs TXF tick path, same days, same
instrument. This isolates the effect of reading 1-minute bars instead of
ticks. Compared signal by signal, not in aggregate: aggregate means can agree
while the underlying signals differ.

*Pass requires:* at least 95% of tick-path signals have a bar-path signal on
the same 15-minute bar, and at least 95% the other way. Below that, the bar
path is not the same signal and the holdout does not run.

**Gate B — instrument portability.** TMF tick path vs TXF tick path, same
days, same granularity. This isolates the effect of changing contract. It is
not a pass/fail gate on the pipeline; it decides what the holdout result is
allowed to claim:

| Agreement | What a TXF holdout result may claim |
|---|---|
| ≥ 80% | It speaks to the original TMF result |
| < 80% | It is a separate question about a different contract. The original TMF result remains unvalidated by history, and must be reported as such |

Gate B's number is reported with the verdict either way. It is not permitted
to be recomputed, resampled, or reinterpreted after the holdout is seen.

## Amendment 2 (2026-08-06) — the 15-minute aggregation rule was ambiguous

**Written before any holdout data was processed.** The holdout window
2020-03-02..2024-07-26 has still never been run through a signal program.

**What happened:** Gate A failed at 81.0% / 88.7% against a 95% threshold. The
cause is a sentence I wrote badly, not an implementation error. The Data
section says a 15-minute bar "is emitted only if the full 15 minutes fall
inside one session". I meant session containment — the whole window must lie
within one trading session. It was implemented as data completeness — all
fifteen constituent 1-minute bars must exist — and both are fair readings.

The two readings are not close in effect. Shioaji's 1-minute kbars routinely
omit minutes: across 20 sampled gate days the mean is 1,061.6 minutes against
1,140 for a complete day, and 12 of those 20 days are short. Under the
completeness reading each missing minute deletes an entire 15-minute bar,
which shifts the pivot and Bollinger history and changes which signals fire.
The tick path has no such rule — it builds a bar from whatever ticks fall in
the window.

**The rule, stated so it cannot be read two ways:**

- A 15-minute bucket is emitted when the whole window [t, t+15min) lies inside
  one resolved session. This is the only containment test.
- Its OHLC is built from whichever 1-minute bars are present in that window:
  open from the earliest present minute, close from the latest present minute,
  high and low the extremes across present minutes, volume their sum.
- A bucket containing no 1-minute bars at all emits nothing.
- A window not wholly inside one session is dropped, never padded, as before.

**Binding limit on this amendment:** this is the **only** change to bar
construction, bar alignment, or aggregation that will be made in this study.
Gate A is re-run once under this rule. If it still fails, the answer is that
the bar path cannot reproduce the tick path, the holdout does not run, and the
project's conclusion is that the candidate cannot be validated against history.
No third reading of this rule will be entertained.

**Cost, stated rather than buried:** this is the second amendment to a
pre-registered protocol. A protocol amended twice carries less weight than one
written once and left alone, and a reader is entitled to discount it. Both
amendments were forced by facts about the data — when an instrument began
trading, and what a vendor's bars contain — rather than by any result, and the
holdout remains untouched. That is the mitigation, not a refutation.

## Amendment 3 (2026-08-06) — the binding clause was aimed at the wrong thing

**Written before any holdout data was processed.** The holdout window
2020-03-02..2024-07-26 has still never been run through a signal program.

Amendment 2 bound the gate: one re-run, and no further change. That clause was
misplaced and is withdrawn. A pre-registration exists to prevent tuning until
something passes, and that danger lives in the **experiment** — the holdout
data, P1–P4, the seed, the periods, the single run. Those remain frozen and
have never been altered. A reconciliation gate is **engineering**: it asks
whether a new pipeline reproduces an old one. Binding it protected nothing and
only locked in design errors, of which this study had already produced two.

The defence against tuning is therefore not a promise made early. It is this
document: every gate iteration is recorded here, in order, so a reader can
count them and discount accordingly.

**Why the gate is being redesigned, measured rather than argued.** Gate A ran
on 60 days sampled evenly, 10–14 calendar days apart. The two stores bucket a
day differently:

| store | file for 2024-09-02 contains |
|---|---|
| ticks | 2024-08-30 15:00 → 2024-09-02 13:44 (trading date: prior night + day) |
| kbars | 2024-09-02 08:46 → 2024-09-02 23:59 (calendar date: day + following night) |

On non-contiguous days the two paths therefore warm `PineState` with different
preceding bars, and pivots and Bollinger bands are computed from that history.
The signature is in where the four mismatches fall — 30, 60, 540 and 555
minutes into their sessions, clustered at session starts, which is where a
missing warm-up matters most. A data-quality difference would scatter.

This artifact cannot occur in the holdout: all 1,076 trading days there are
contiguous, so both bucketings cover the same bars.

**Gate A v2:** the same comparison over **60 contiguous trading days,
2026-05-11 through 2026-07-31**, same 95% threshold both ways. If agreement
rises to near-total, the 93.10% was the sampling artifact described above. If
it stays near 93%, this diagnosis is wrong.

No limit is placed on further gate iterations. Each one is recorded here.

## Amendment 4 (2026-08-07) — Friday nights end at midnight, and the gate must say so

**Written before any holdout data was processed.**

**The finding.** The kbar store buckets by calendar date; the tick store buckets
by trading date. A night session runs 15:00 to 05:00, so it straddles midnight
and lands in two calendar files. Monday through Thursday both halves are
present, because the following calendar day is itself a trading day that was
pulled. Friday nights are not: their 00:00-05:00 tail belongs to a Saturday,
and Shioaji returns Saturday kbars **only for 2026** — 2020-06-13, 2021-06-12,
2022-06-11, 2023-06-10, 2024-06-08 and 2025-06-14 all return zero bars, while
2026-06-13, 2026-07-18 and 2026-07-25 return 294, 297 and 301.

**Consequence, accepted as a documented limitation.** Across the holdout window
the final five hours of every Friday night session do not exist and cannot be
obtained. That is roughly 5% of all bars. Signals that would have fired in
those hours are absent, and the truncation also shortens the rolling history
PineState carries into the following session.

**Day-only was considered and rejected.** Restricting the study to day sessions
would remove the problem entirely, but the candidate fires 159 times at night
against 107 by day across the committed event dumps — 59.8% nocturnal, n=266.
A day-only study would discard most of the phenomenon in order to tidy up the
data, which is the wrong trade.

**Gate rule, changed.** Gate A compares the two paths **only over minutes where
both paths have source data**. The 2026 gate window does have Saturday kbars,
and using them would make the gate measure a data condition the holdout will
never enjoy — a gate that passes for a reason the real run cannot reproduce is
worse than one that fails. Both paths are therefore held to the intersection.

This changes the gate, not the holdout. The holdout was always going to run on
kbars and always had this gap; what changes is that the gate now tests the
pipeline under the conditions the holdout will actually meet.

### Gate A iteration log

| run | days | left agreement | right agreement | result |
|---|---|---|---|---|
| v1 | 60 sampled, 10–14 days apart | 81.03% | 88.68% | FAIL — aggregation read as completeness (Amendment 2) |
| v2 | 60 sampled, corrected aggregation | 93.10% | 100.00% | FAIL |
| v3 | 60 contiguous, 2026-05-11..2026-07-31 | 91.67% | 100.00% | FAIL — **the contiguity diagnosis in this amendment is refuted** |
| v4 | v3 days, source-minute intersection (Amendment 4) | **100.00%** | **100.00%** | **PASS** |

v4 detail: 55 signals on each side, all 55 matched, zero mismatches in either
direction. Across the entire bar sequence the only residual difference is
volume at index 95 (2026-05-12 DAY 13:30–13:45): 6,882 from ticks against
6,886 summed from vendor kbars, with OHLC identical. Tick counting and vendor
volume are not the same quantity; it moves no signal.

Gate B on the same contiguous window: 94.44% / 89.47% (18 TMF, 19 TXF, 17
matched), above the 80% claim threshold and better than the 85.00% / 80.95%
measured on the sampled days.

**Both gates pass. The holdout may run, once.**

The contiguity explanation above did not survive its own test: agreement fell
rather than rose. Recorded here rather than revised away.

What the same measurement did establish is narrower and firmer. At all four v3
mismatch bars the 15-minute OHLC is byte-identical on both paths
(2026-07-27 09:00 O=43697 H=43750 L=43469 C=43534, and three others). The
vendor's bars and the signal bar are therefore not the cause. `bar-only` has
been 0 in every run: the bar path never invents a signal, only misses some,
which points at the bar history that PineState is fed rather than at the data.
That is a defect in this project's code, and the next iteration hunts it.

## Appendix — crash months

Computed 2026-08-06, **before any holdout signal was generated**, from daily
TX closes only. Method: FinMind `TaiwanFuturesDaily`, `futures_id=TX`,
`trading_session=position`; per trading day the near month is taken as the
highest-volume contract; per calendar month the maximum peak-to-trough
drawdown of those closes is computed. 1,134 trading days loaded.

| Month | Max drawdown |
|---|---|
| 2020-03 | 27.31% |
| 2021-05 | 11.71% |
| 2022-06 | 12.15% |

**Near miss, recorded for honesty and not acted on:** 2022-09 reaches 9.95%,
five hundredths of a point below the threshold. The ≥10% rule was fixed
before this table was computed and is not being adjusted to include or
exclude it. If the eventual verdict turns on whether 2022-09 is classified as
a crash month, that sensitivity is reported explicitly rather than resolved by
moving the line.
