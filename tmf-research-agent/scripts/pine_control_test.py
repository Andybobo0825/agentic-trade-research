"""Pre-registered control test for the one Pine signal worth building on.

WRITTEN AND COMMITTED BEFORE THE RESULT WAS SEEN. The thresholds below are
the whole point: five previous searches on this instrument died from tuning
until something passed, so the candidate, the criteria, and the fallback list
are fixed here in advance and the verdict is whatever they produce.

CANDIDATE (chosen from the aggregate tables in output/pine-signal-report-*.md,
which the author had already read — selection bias is acknowledged, and is
exactly what this test exists to price):

    15-minute 壓力遇阻 (rejection), 原版 variant, SHORT, horizons 60/240/sclose.

CONTROL: random entries drawn uniformly from the same sessions' own traded
moments, same direction, same horizons, same 3-point round-trip cost. Two
forms are reported:
  - plain: all control entries pooled
  - time-matched: control means standardised to the signal's own
    (period x session x 30-minute-of-session) distribution, because signals
    cannot fire until pivots confirm and therefore cluster later in a session

PASS REQUIRES ALL FOUR:
  P1. signal mean net > control mean net in every period, at the horizon
  P2. bootstrap 95% CI (10,000 resamples) of (signal mean - control mean),
      pooled across periods, excludes zero
  P3. signal mean net > 0 after cost in every period
  P4. signal N >= 100 in at least two periods

A horizon passes only if all four hold. The candidate passes if any of its
three horizons passes.

PRE-DECLARED FALLBACKS, in order, at most three, each one a further multiple
comparison (Bonferroni: with 4 candidates tested the P2 threshold becomes a
98.75% CI, reported alongside the nominal 95%):
  F1. same signal/horizons, V1縮短確認 variant
  F2. same signal/horizons, 原版, DAY session only
  F3. 15-minute 帶量跌破 (breakdown), 原版, SHORT — the other short-side
      signal positive in all three periods

Nothing beyond F3 is tested. If all four fail, the answer is that the
indicator has no signal that beats being randomly short, and the Pine
strategy ships labelled as such.

Usage: pine_control_test.py <blockA.ndjson> <blockB.ndjson>
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

COST = 3.0
HORIZONS = ("60", "240", "sclose")
BOOTSTRAP = 10_000
SEED = 20260804
BUCKET_MINUTES = 30
MIN_N_STRONG = 100


def load(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def net(delta: float, direction: int) -> float:
    return direction * delta - COST


def select_signal(rows, *, timeframe, signal, variant, direction, session=None):
    return [
        row for row in rows
        if row["kind"] == "signal" and row["timeframe"] == timeframe
        and row["signal"] == signal and row["variant"] == variant
        and row["direction"] == direction
        and (session is None or row["session"] == session)
    ]


def controls(rows, *, session=None):
    return [
        row for row in rows
        if row["kind"] == "random"
        and (session is None or row["session"] == session)
    ]


def bucket(row) -> tuple:
    return (row["period"], row["session"],
            row["minute_of_session"] // BUCKET_MINUTES)


def matched_control_mean(signal_rows, control_rows, horizon, direction) -> float | None:
    """Control mean standardised to the signal's own time-of-session mix."""
    by_bucket: dict[tuple, list[float]] = defaultdict(list)
    for row in control_rows:
        if horizon in row["deltas"]:
            by_bucket[bucket(row)].append(net(row["deltas"][horizon], direction))
    weights: dict[tuple, int] = defaultdict(int)
    for row in signal_rows:
        if horizon in row["deltas"]:
            weights[bucket(row)] += 1
    total = numerator = 0.0
    for key, weight in weights.items():
        values = by_bucket.get(key)
        if not values:
            continue
        numerator += weight * (sum(values) / len(values))
        total += weight
    return numerator / total if total else None


def bootstrap_ci(sample_a: list[float], sample_b: list[float], rng: random.Random,
                 levels=(0.95, 0.9875)) -> dict[float, tuple[float, float]]:
    diffs = []
    n_a, n_b = len(sample_a), len(sample_b)
    for _ in range(BOOTSTRAP):
        mean_a = sum(sample_a[rng.randrange(n_a)] for _ in range(n_a)) / n_a
        mean_b = sum(sample_b[rng.randrange(n_b)] for _ in range(n_b)) / n_b
        diffs.append(mean_a - mean_b)
    diffs.sort()
    out = {}
    for level in levels:
        tail = (1.0 - level) / 2.0
        lo = diffs[int(tail * BOOTSTRAP)]
        hi = diffs[min(BOOTSTRAP - 1, int((1.0 - tail) * BOOTSTRAP))]
        out[level] = (lo, hi)
    return out


def evaluate(name: str, rows, *, timeframe, signal, variant, direction,
             session=None) -> bool:
    rng = random.Random(SEED)
    signal_rows = select_signal(rows, timeframe=timeframe, signal=signal,
                                variant=variant, direction=direction,
                                session=session)
    control_rows = controls(rows, session=session)
    periods = sorted({row["period"] for row in signal_rows})
    print(f"\n{'=' * 72}\n{name}\n  訊號樣本 {len(signal_rows):,}｜"
          f"對照樣本 {len(control_rows):,}｜期間 {', '.join(periods)}")
    passed_any = False
    for horizon in HORIZONS:
        print(f"\n  ── horizon {horizon} " + "─" * 46)
        p1 = p3 = True
        p4_count = 0
        sig_all: list[float] = []
        ctl_all: list[float] = []
        for period in periods:
            sig = [net(r["deltas"][horizon], direction) for r in signal_rows
                   if r["period"] == period and horizon in r["deltas"]]
            ctl_rows_p = [r for r in control_rows if r["period"] == period]
            ctl = [net(r["deltas"][horizon], direction) for r in ctl_rows_p
                   if horizon in r["deltas"]]
            if not sig or not ctl:
                print(f"    {period}: 資料不足")
                p1 = p3 = False
                continue
            sig_mean = sum(sig) / len(sig)
            ctl_mean = sum(ctl) / len(ctl)
            sig_period_rows = [r for r in signal_rows if r["period"] == period]
            matched = matched_control_mean(sig_period_rows, ctl_rows_p,
                                           horizon, direction)
            sig_all.extend(sig)
            ctl_all.extend(ctl)
            if sig_mean <= ctl_mean:
                p1 = False
            if matched is not None and sig_mean <= matched:
                p1 = False
            if sig_mean <= 0:
                p3 = False
            if len(sig) >= MIN_N_STRONG:
                p4_count += 1
            matched_txt = "—" if matched is None else f"{matched:+.2f}"
            print(f"    {period}: 訊號 N={len(sig):>5} 均 {sig_mean:>+8.2f}"
                  f"｜隨機 N={len(ctl):>5} 均 {ctl_mean:>+7.2f}"
                  f"｜時段對齊隨機 {matched_txt:>8}"
                  f"｜差 {sig_mean - ctl_mean:>+8.2f}")
        if not sig_all or not ctl_all:
            print("    → 失敗（資料不足）")
            continue
        ci = bootstrap_ci(sig_all, ctl_all, rng)
        p2_95 = ci[0.95][0] > 0
        p2_bonf = ci[0.9875][0] > 0
        p4 = p4_count >= 2
        print(f"    合併差值 {sum(sig_all)/len(sig_all) - sum(ctl_all)/len(ctl_all):+.2f}"
              f"｜95% CI [{ci[0.95][0]:+.2f}, {ci[0.95][1]:+.2f}]"
              f"｜98.75% CI [{ci[0.9875][0]:+.2f}, {ci[0.9875][1]:+.2f}]")
        verdict = "通過" if (p1 and p2_95 and p3 and p4) else "失敗"
        print(f"    P1 勝過對照 {'✓' if p1 else '✗'}｜"
              f"P2 CI 排除零 {'✓' if p2_95 else '✗'}"
              f"（Bonferroni {'✓' if p2_bonf else '✗'}）｜"
              f"P3 淨值為正 {'✓' if p3 else '✗'}｜"
              f"P4 樣本足夠 {'✓' if p4 else '✗'}  → {verdict}")
        if p1 and p2_95 and p3 and p4:
            passed_any = True
    return passed_any


def main(paths: list[Path]) -> int:
    rows = load(paths)
    print(f"載入 {len(rows):,} 列")
    candidates = [
        ("候選：15分K 壓力遇阻 原版 做空", dict(
            timeframe=15, signal="rejection", variant="orig", direction=-1)),
        ("F1：15分K 壓力遇阻 V1縮短確認 做空", dict(
            timeframe=15, signal="rejection", variant="v1", direction=-1)),
        ("F2：15分K 壓力遇阻 原版 做空（僅日盤）", dict(
            timeframe=15, signal="rejection", variant="orig", direction=-1,
            session="DAY")),
        ("F3：15分K 帶量跌破 原版 做空", dict(
            timeframe=15, signal="breakdown", variant="orig", direction=-1)),
    ]
    for index, (name, kwargs) in enumerate(candidates):
        if evaluate(name, rows, **kwargs):
            print(f"\n>>> {name} 通過（第 {index + 1} 個測試；"
                  f"多重比較代價：已測 {index + 1} 個候選）")
            return 0
        if index == 0:
            print("\n>>> 主候選失敗，進入預先宣告的 fallback")
    print("\n>>> 四個候選全部失敗：這份指標沒有勝過「隨機做空」的訊號")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main([Path(arg) for arg in sys.argv[1:]]))
