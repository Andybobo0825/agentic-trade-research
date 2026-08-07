# What this project searched for, and what it found

**Conclusion, 2026-08-07: no tradeable edge was found. Every hypothesis tested
has been closed negative, the last one by a pre-registered holdout that the
project's only positive result failed.**

This document exists so the work does not get repeated. Each section says what
was tried, what it cost, what the answer was, and what would have to be
different for the question to be worth asking again.

## The question

Whether a systematic, testable edge exists in Taiwan index futures at intraday
horizons — first through machine-learned microstructure features, later through
a chart-pattern indicator the author had been using by eye.

The standard applied throughout: a candidate must beat a **random entry in the
same direction, at the same times, after costs**. Being profitable is not
enough; being profitable while random entry would also have been profitable
proves nothing.

## Five searches, five negatives

### 1. Historical microstructure features — negative, holdout-confirmed (2026-07-21)

25 features over 245 trading days of real TMF tick data, 210,298 development
samples. Five model families — logistic regression, histogram gradient
boosting, random forest, MLP, with and without isotonic calibration and
confidence-based selective trading — across 30+ configurations.

A pattern appeared mid-search where tighter confidence filtering improved
expected value. Per-fold inspection showed it was driven by a *different single
fold* depending on the model, which is the fingerprint of small-sample noise
rather than signal.

One candidate was frozen before the locked holdout was opened. All seven
confidence quantiles came back negative, −1.22 to −3.85 points per trade, and
the filtering trend did not replicate — the tightest filter was the worst
result. Independent pure-Python and sklearn implementations agreed
(mean test EV −1.38, 0 of 5 folds positive).

*Would change the answer:* nothing within this feature set. The ceiling was
reached and it sits below the cost hurdle.

### 2. Basis — negative (2026-08-03)

Historical Shioaji data carries no spot index, so the basis feature group had
never been testable. Live collection ran for two weeks specifically to test it.

On 1,111 live samples, `basis_points` correlates with `microprice` at **+0.825**
rank, and in the part that does not overlap it subtracts rather than adds:
price level alone predicts the forward move better (IC −0.269) than basis does
(−0.182). The z-score, which removes price level from basis, has essentially no
relationship left (−0.011).

Basis is a degraded proxy for price level. Price level had already been
rejected in search 1. The strongest thing this search could have shown was a
weaker version of something known to lose money.

*Would change the answer:* nothing. Collection was stopped.

### 3. Institutional positioning (籌碼) — negative (2026-08-04)

The raw position sign turned out to be a structural constant rather than a
varying signal. The failure verdict rests on only 12 out-of-sample trades, so
this one is closed on weak evidence rather than strong — recorded honestly as
such.

*Would change the answer:* a longer out-of-sample record, if anyone thought the
hypothesis was worth the wait. Nobody did.

### 4. The Pine indicator — an apparent positive (2026-08-04)

The author's TradingView indicator (Bollinger bands plus confirmed pivot
support/resistance) was replayed over real ticks. 144 signal/variant/direction
cells were computed and read. One was selected: **15-minute 壓力遇阻
(rejection), 原版 variant, SHORT**.

It was then tested against random same-direction entry under a control test
pre-registered and committed *before* the result was computed:

| period | N | signal | random | matched | difference |
|---|---:|---:|---:|---:|---:|
| 2024H2 | 112 | +8.41 | −3.95 | −0.55 | +12.37 |
| 2025H1 | 136 | +24.90 | −8.71 | −10.75 | +33.61 |
| 2026+ | 18 | +143.22 | +19.51 | +52.39 | +123.72 |

Pooled difference +30.04, 95% CI [+5.89, +56.73]. A two-year strategy backtest
gave 204 trades, +4,529 points, 48% win rate, profit factor 1.42.

Three weaknesses were recorded at the time and never resolved: the candidate
was chosen from 144 cells already read, so roughly seven false positives are
expected at 95%; Bonferroni correction puts zero back inside the interval; and
60% of the two-year profit came from a single crash month, with 2024H2 flat at
profit factor 1.03.

That is why search 5 happened.

### 5. The out-of-sample test — the positive did not survive (2026-08-07)

**Protocol:** `docs/pre-registration-2026-08-06-pine-holdout-2020-2024.md`.
**Report:** `output/pine-holdout-verdict-2026-08-07.txt`.

4.3 years the 144-cell search had never touched — 2020-03-02 to 2024-07-26,
1,076 trading days, 1,148,889 one-minute bars, **1,278 candidate signals**
across nine half-year periods.

| criterion | 60m | 240m | session close | required |
|---|---|---|---|---|
| P1 signal beats control | 3/9 | 2/9 | 2/9 | ≥ 7/9 |
| P3 signal net > 0 after cost | 1/9 | 0/9 | 1/9 | ≥ 7/9 |
| P4 N ≥ 100 | 8/9 | 8/9 | 8/9 | ≥ 6/9 |

**Verdict: FAIL**, at every horizon.

And it is worse than an absence of edge. At 240 minutes and session close the
pooled 95% confidence interval excludes zero on the **negative** side — plain
`[−9.94, −1.97]` and `[−9.96, −1.21]`. The signal loses to random
same-direction entry by one to ten points per trade, significantly. Excluding
the three pre-declared crash months changes nothing.

**Limitations, and why they do not rescue it.** The holdout ran on TXF rather
than TMF, because micro futures did not begin trading until 2024-07-29 and a
2020–2024 TMF test cannot exist. Friday nights are missing their 00:00–05:00
tail, roughly 5% of bars, because Shioaji archives Saturday kbars only for
2026. The protocol was amended four times, each amendment recorded and
countable in the document. All of that is real. None of it turns 2/9 into 7/9.

## What is established, and what is not

**Established.** The specific candidate is dead. Its in-sample result was
selection noise, which is exactly what its own recorded caveats predicted —
seven false positives expected from 144 cells, and this was one of them.

**Not established.** That no edge exists in Taiwan index futures. Five
hypotheses were tested, not the space of hypotheses. What has been shown is
that this project's particular lines of attack — historical microstructure
features, basis, institutional positioning, and one chart pattern — are closed.

**Also established, and worth more than any of the individual results:** the
protocol works. The one candidate that looked good in-sample was killed by
out-of-sample data, on schedule, by criteria written before the numbers were
seen. Five earlier searches in this project died from tuning until something
passed. This one did not, and that is why its negative can be trusted.

## What would be worth trying next, if anything

Not another pass over price history. The lever with genuine prior probability
was always live-collected data the historical archive structurally lacks, and
the one instance of that — basis — has now been tested and closed.

If this line resumes, it should start from a hypothesis that is *not* a
function of past prices at intraday horizons, and it should be pre-registered
before the data is looked at. The discipline is the only asset this project
accumulated, and it is transferable to whatever comes next.

## Where the evidence lives

| what | where |
|---|---|
| Holdout protocol and its four amendments | `docs/pre-registration-2026-08-06-pine-holdout-2020-2024.md` |
| Holdout verdict report | `output/pine-holdout-verdict-2026-08-07.txt` |
| Original control test, committed before its result | `tmf-research-agent/scripts/pine_control_test.py` |
| Holdout verdict script | `tmf-research-agent/scripts/pine_holdout_verdict.py` |
| Bar-path event dump | `tmf-research-agent/scripts/pine_bar_dump.py` |
| Gate checks A and B | `tmf-research-agent/scripts/pine_gate_checks.py` |
| Indicator and strategy source | `pine/taiwan-mtf-bb-sr.pine`, `pine/taiwan-mtf-bb-sr-strategy.pine` |
| Research sidecar specification | `docs/txresearch.md` |
