# Pine Signal Credibility Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One standalone script that replays the user's TradingView Pine indicator signals (plus three earlier-firing variants) over real TMF tick data and prints a net-of-cost credibility report.

**Architecture:** A single file `tmf-research-agent/scripts/pine_signal_report.py` in the style of `scripts/label_sweep.py`: stream session batches from the append-only raw store, build 5/15/60-minute session-anchored bars via the existing `ProcessingPipeline`, feed them through a small in-script Pine state machine, price every emitted signal against the session's own ticks, aggregate, print markdown. No changes to `src/`, no sealed-pipeline involvement.

**Tech Stack:** Python stdlib only + existing `tmf_research` modules (imported read-only). Run with `PYTHONPATH=src .venv/bin/python`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-pine-signal-report-design.md` — deviations must be called out in the final report.
- New file only: `tmf-research-agent/scripts/pine_signal_report.py`. Do not modify anything under `src/` or `tests/`.
- Round-trip cost constant: `COST_POINTS = 3.0`.
- Presets (timeframe → pivotBars, zone %, volLen, strongVol ×): 60m → 3, 0.30, 10, 1.5; 15m → 4, 0.20, 20, 1.6; 5m → 5, 0.10, 20, 1.8.
- Pine semantics locked in the spec: population stdev for BB; signals read the *previous* bar's S/R levels; pivots confirm `right` bars late; strict `>` (high) / `<` (low) pivot comparison on both sides.
- Self-test (`--self-test`) must not require the raw store; it uses synthetic `Bar` objects and synthetic ticks.
- Each run covers one block only (Block A `2024-07-29..2025-06-30`, Block B `2026-07-01..`); blocks are never pooled.
- Commit after every task, message style matches repo history (imperative sentence, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer).

---

### Task 1: Indicator core — Bollinger, volume SMA, pivot/level bookkeeping

**Files:**
- Create: `tmf-research-agent/scripts/pine_signal_report.py`

**Interfaces:**
- Produces: `TFParams` (frozen dataclass: `interval:int, pivot_bars:int, zone_pct:float, vol_len:int, vol_ratio:float`), `PRESETS: dict[int, TFParams]`, `PineState` with `__init__(params: TFParams, *, right_bars: int | None = None)`, `update(bar) -> list[tuple[str, int, float]]` (empty until Task 2), `forming_context() -> dict`, `_mk_bar(...)` synthetic-bar helper, `self_test() -> int` runner scaffold dispatching `_test_*` functions.
- Consumes: `tmf_research.processing.bars.Bar` (only in `_mk_bar`).

- [ ] **Step 1: Write the failing self-test for pivot timing and level bookkeeping**

Create the file with module docstring, imports, params, `_mk_bar`, the test, and a `main` that only knows `--self-test`:

```python
"""Replay the TradingView Pine indicator (台指 MTF BB-SR) over real TMF ticks.

Reproduces the four confirmed signals (帶量突破/帶量跌破/支撐止跌/壓力遇阻)
plus three earlier-firing variants, prices each against the session's own
ticks minus a 3-point round trip, and prints a markdown credibility report.
Spec: docs/superpowers/specs/2026-08-04-pine-signal-report-design.md
"""
from __future__ import annotations

import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from tmf_research.processing.bars import Bar

TAIPEI = timezone(timedelta(hours=8))
COST_POINTS = 3.0
HORIZONS = (15, 60, 240)  # minutes; session close is reported as "sclose"
BB_LEN = 20
BB_MULT = 2.0


@dataclass(frozen=True)
class TFParams:
    interval: int
    pivot_bars: int
    zone_pct: float
    vol_len: int
    vol_ratio: float


PRESETS: dict[int, TFParams] = {
    60: TFParams(60, 3, 0.30, 10, 1.5),
    15: TFParams(15, 4, 0.20, 20, 1.6),
    5: TFParams(5, 5, 0.10, 20, 1.8),
}


def _mk_bar(
    start: datetime, o: float, h: float, l: float, c: float, v: int,
    minutes: int = 5,
) -> Bar:
    return Bar(
        target_code="TMF", bar_start=start,
        bar_end=start + timedelta(minutes=minutes),
        open=o, high=h, low=l, close=c, volume=v, trade_count=1,
        buy_volume=0, sell_volume=0, unknown_volume=v, vwap=c,
        bidask_coverage_ratio=1.0, tick_coverage_ratio=1.0, is_complete=True,
    )


def _seq(start: datetime, rows: list[tuple[float, float, float, float, int]],
         minutes: int = 5) -> list[Bar]:
    return [
        _mk_bar(start + timedelta(minutes=minutes * i), *row, minutes=minutes)
        for i, row in enumerate(rows)
    ]


def _test_pivot_confirms_right_bars_late() -> None:
    params = TFParams(5, 2, 0.10, 20, 1.8)  # left = right = 2
    start = datetime(2024, 8, 1, 8, 45, tzinfo=TAIPEI)
    # highs: 10 11 12 11 10 — pivot high 12 at index 2, confirmed at index 4
    rows = [(10, 10, 9, 10, 100), (11, 11, 10, 11, 100),
            (12, 12, 11, 12, 100), (11, 11, 10, 11, 100),
            (10, 10, 9, 10, 100)]
    state = PineState(params)
    for i, bar in enumerate(_seq(start, rows)):
        basis_before = state.resistance
        state.update(bar)
        if i < 4:
            assert state.resistance is None, f"bar {i}: pivot too early"
        else:
            assert basis_before is None, "signal basis must lag confirmation"
            assert state.resistance == 12, "pivot high must land at bar 4"


def _test_pivot_tie_is_not_a_pivot() -> None:
    params = TFParams(5, 2, 0.10, 20, 1.8)
    start = datetime(2024, 8, 1, 8, 45, tzinfo=TAIPEI)
    rows = [(10, 12, 9, 10, 100), (11, 11, 10, 11, 100),
            (12, 12, 11, 12, 100), (11, 11, 10, 11, 100),
            (10, 10, 9, 10, 100)]  # tie 12 at index 0 blocks strict >
    state = PineState(params)
    for bar in _seq(start, rows):
        state.update(bar)
    assert state.resistance is None, "tied highs must not confirm a pivot"


TESTS = [
    _test_pivot_confirms_right_bars_late,
    _test_pivot_tie_is_not_a_pivot,
]


def self_test() -> int:
    for test in TESTS:
        test()
        print(f"ok {test.__name__}")
    print(f"{len(TESTS)} self-tests passed")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    print("用法: pine_signal_report.py --self-test | <raw-root> <calendar.json> <起始日> <結束日>",
          file=sys.stderr)
    raise SystemExit(2)
```

- [ ] **Step 2: Run and verify it fails**

Run: `cd tmf-research-agent && PYTHONPATH=src .venv/bin/python scripts/pine_signal_report.py --self-test`
Expected: `NameError: name 'PineState' is not defined`

- [ ] **Step 3: Implement `PineState` (no signals yet)**

Insert above the tests. The update order is the load-bearing part — snapshot signal basis first, indicators next, signals (Task 2) after indicators, pivots last:

```python
class PineState:
    """Replays the Pine indicator bar by bar.

    Pine's signals compare against `resistance1[1]`/`support1[1]` — the level
    as of the previous bar's close — while BB and the volume SMA include the
    current bar. `update` therefore snapshots the levels before folding the
    bar in, and confirms pivots only after signals would have been read.
    """

    def __init__(self, params: TFParams, *, right_bars: int | None = None) -> None:
        self.p = params
        self.left = params.pivot_bars
        self.right = params.pivot_bars if right_bars is None else right_bars
        window = self.left + self.right + 1
        self._closes: deque[float] = deque(maxlen=BB_LEN)
        self._vols: deque[int] = deque(maxlen=params.vol_len)
        self._highs: deque[float] = deque(maxlen=window)
        self._lows: deque[float] = deque(maxlen=window)
        self.resistance: float | None = None
        self.support: float | None = None
        self.prev_close: float | None = None
        self.prev_bb: tuple[float, float, float] | None = None  # mid, up, low
        self.prev_vol_sma: float | None = None

    def forming_context(self) -> dict[str, object]:
        """Everything the intrabar variants may read while the next bar forms."""
        return {
            "res": self.resistance, "sup": self.support,
            "bb": self.prev_bb, "vol_sma": self.prev_vol_sma,
            "prev_close": self.prev_close,
        }

    def update(self, bar: Bar) -> list[tuple[str, int, float]]:
        if bar.close is None or bar.open is None or bar.high is None or bar.low is None:
            return []
        signal_res, signal_sup = self.resistance, self.support
        self._closes.append(bar.close)
        self._vols.append(bar.volume)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        bb = self._bollinger()
        vol_sma = (
            sum(self._vols) / len(self._vols)
            if len(self._vols) == self.p.vol_len else None
        )
        strong = vol_sma is not None and vol_sma > 0 and bar.volume >= self.p.vol_ratio * vol_sma
        events = self._signals(bar, signal_res, signal_sup, bb, strong)
        self._confirm_pivots()
        self.prev_close = bar.close
        self.prev_bb = bb
        self.prev_vol_sma = vol_sma
        return events

    def _bollinger(self) -> tuple[float, float, float] | None:
        if len(self._closes) < BB_LEN:
            return None
        mid = sum(self._closes) / BB_LEN
        variance = sum((c - mid) ** 2 for c in self._closes) / BB_LEN
        dev = BB_MULT * variance ** 0.5
        return mid, mid + dev, mid - dev

    def _signals(self, bar: Bar, res: float | None, sup: float | None,
                 bb: tuple[float, float, float] | None, strong: bool,
                 ) -> list[tuple[str, int, float]]:
        return []  # Task 2

    def _confirm_pivots(self) -> None:
        if len(self._highs) == self._highs.maxlen:
            highs = tuple(self._highs)
            center = highs[self.left]
            if all(center > h for h in highs[:self.left]) and \
                    all(center > h for h in highs[self.left + 1:]):
                self.resistance = center
        if len(self._lows) == self._lows.maxlen:
            lows = tuple(self._lows)
            center = lows[self.left]
            if all(center < l for l in lows[:self.left]) and \
                    all(center < l for l in lows[self.left + 1:]):
                self.support = center
```

- [ ] **Step 4: Run the self-test, expect both tests pass**

Run: `PYTHONPATH=src .venv/bin/python scripts/pine_signal_report.py --self-test`
Expected: `2 self-tests passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/pine_signal_report.py
git commit -m "Replay the Pine pivot and level bookkeeping outside TradingView"
```

---

### Task 2: The four original close-confirmed signals

**Files:**
- Modify: `tmf-research-agent/scripts/pine_signal_report.py` (fill `PineState._signals`, add tests)

**Interfaces:**
- Produces: `PineState.update` now returns `[(signal, direction, level)]` with `signal ∈ {"breakout","breakdown","bounce","rejection"}`, `direction ∈ {+1,-1}`; constant `SIGNAL_DIRECTION = {"breakout": 1, "bounce": 1, "breakdown": -1, "rejection": -1}`.

- [ ] **Step 1: Add failing tests**

The warmup helper makes conditions unambiguous: 22 flat bars (close 100, high 100.5, low 99.5, volume 100) establish BB≈100 and vol SMA=100, with one early spike planting a pivot. Append to `TESTS` list.

```python
def _warmup(pivot_high: float = 105.0, pivot_low: float = 95.0) -> list[Bar]:
    """22 flat bars with a pivot high/low pair confirmed mid-warmup.

    Layout (5m bars, left=right=2 via the test params): flat, spike-high,
    flat, spike-low, then flat to 22 bars. Pivot high confirms at index 3,
    pivot low at index 5.
    """
    start = datetime(2024, 8, 1, 8, 45, tzinfo=TAIPEI)
    flat = (100.0, 100.5, 99.5, 100.0, 100)
    rows = [flat, (100.0, pivot_high, 99.5, 100.0, 100), flat,
            (100.0, 100.5, pivot_low, 100.0, 100)] + [flat] * 18
    return _seq(start, rows)


TEST_PARAMS = TFParams(5, 2, 0.10, 20, 1.8)


def _run(rows_after_warmup: list[tuple[float, float, float, float, int]],
         ) -> list[list[tuple[str, int, float]]]:
    bars = _warmup()
    extra = _seq(bars[-1].bar_end, rows_after_warmup)
    state = PineState(TEST_PARAMS)
    return [state.update(bar) for bar in bars + extra]


def _test_breakout_needs_volume_and_bb() -> None:
    quiet = _run([(100.0, 106.0, 100.0, 106.0, 150)])   # crosses 105, weak volume
    loud = _run([(100.0, 106.0, 100.0, 106.0, 500)])    # 500 >= 1.8 * ~102
    assert not any(quiet[-1:][0]), "weak volume must not fire"
    assert loud[-1] == [("breakout", 1, 105.0)], f"got {loud[-1]}"


def _test_breakout_requires_cross_not_position() -> None:
    # First bar crosses and fires; staying above must not re-fire.
    out = _run([(100.0, 106.0, 100.0, 106.0, 500),
                (106.0, 107.0, 105.5, 106.5, 500)])
    assert out[-2] == [("breakout", 1, 105.0)]
    assert out[-1] == [], "no cross on the second bar"


def _test_breakdown_mirror() -> None:
    out = _run([(100.0, 100.0, 94.0, 94.0, 500)])
    assert out[-1] == [("breakdown", -1, 95.0)], f"got {out[-1]}"


def _test_bounce_at_support() -> None:
    # Touch the support zone (95 ±0.1%), pierce the BB lower band, close
    # back at/above support with a green body.
    out = _run([(96.0, 96.0, 94.9, 95.5, 100)])
    assert out[-1] == [("bounce", 1, 95.0)], f"got {out[-1]}"


def _test_rejection_at_resistance() -> None:
    out = _run([(104.0, 105.1, 104.0, 104.2, 100)])
    assert out[-1] == [("rejection", -1, 105.0)], f"got {out[-1]}"
```

Register all five in `TESTS`.

- [ ] **Step 2: Run, expect the new tests fail**

Run: `PYTHONPATH=src .venv/bin/python scripts/pine_signal_report.py --self-test`
Expected: `AssertionError` in `_test_breakout_needs_volume_and_bb` (signals list empty).

- [ ] **Step 3: Implement `_signals`**

```python
SIGNAL_DIRECTION = {"breakout": 1, "bounce": 1, "breakdown": -1, "rejection": -1}
```

```python
    def _signals(self, bar: Bar, res: float | None, sup: float | None,
                 bb: tuple[float, float, float] | None, strong: bool,
                 ) -> list[tuple[str, int, float]]:
        if bb is None or self.prev_close is None:
            return []
        mid, upper, lower = bb
        zone = self.p.zone_pct / 100.0
        events: list[tuple[str, int, float]] = []
        if res is not None and bar.close > res and self.prev_close <= res \
                and strong and bar.close > mid:
            events.append(("breakout", 1, res))
        if sup is not None and bar.close < sup and self.prev_close >= sup \
                and strong and bar.close < mid:
            events.append(("breakdown", -1, sup))
        if sup is not None and bar.low <= sup * (1 + zone) \
                and bar.high >= sup * (1 - zone) and bar.low <= lower \
                and bar.close >= sup and bar.close > bar.open:
            events.append(("bounce", 1, sup))
        if res is not None and bar.high >= res * (1 - zone) \
                and bar.low <= res * (1 + zone) and bar.high >= upper \
                and bar.close <= res and bar.close < bar.open:
            events.append(("rejection", -1, res))
        return events
```

Note for the bounce/rejection tests: with 20 flat closes the BB deviation is
small but nonzero (the two spike bars sit inside the window until bar 22+).
The test bars pierce `low ≤ lower` / `high ≥ upper` by construction because
the last rows push well past ±2σ of a ~0.3-point σ window. If a bounce test
fails on the band condition, print `state.prev_bb` in the test to inspect —
do not weaken the condition; adjust the synthetic rows instead.

- [ ] **Step 4: Run, expect all 7 tests pass**

Run: `PYTHONPATH=src .venv/bin/python scripts/pine_signal_report.py --self-test`
Expected: `7 self-tests passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/pine_signal_report.py
git commit -m "Fire the four confirmed Pine signals from replayed bars"
```

---

### Task 3: Early variants V1 (short confirmation), V2 (intrabar cross), V3 (zone entry)

**Files:**
- Modify: `tmf-research-agent/scripts/pine_signal_report.py`

**Interfaces:**
- Produces:
  - `V1` = a second `PineState(params, right_bars=2)` — no new code beyond wiring (Task 6 instantiates it).
  - `v2_scan(ctx: dict, ticks: list[tuple[datetime, float, int]], bar_start: datetime, interval_minutes: int, params: TFParams) -> list[tuple[str, int, float, datetime]]` — intrabar breakout/breakdown with pace-projected volume; at most one event per side per bar.
  - `v3_scan(ctx: dict, ticks: list[tuple[datetime, float, int]], params: TFParams, fired_levels: set[tuple[str, float]]) -> list[tuple[str, int, float, datetime]]` — first zone entry per level per session; signal names `"bounce"`/`"rejection"` (they anticipate those), direction long at support / short at resistance.
  - Tick triple everywhere: `(exchange_datetime, price, volume)`.

- [ ] **Step 1: Add failing tests**

```python
def _ticks(start: datetime, rows: list[tuple[int, float, int]],
           ) -> list[tuple[datetime, float, int]]:
    """rows = (seconds offset, price, volume)."""
    return [(start + timedelta(seconds=s), p, v) for s, p, v in rows]


def _test_v2_fires_on_cross_with_paced_volume() -> None:
    ctx = {"res": 105.0, "sup": 95.0, "bb": (100.0, 101.0, 99.0),
           "vol_sma": 100.0, "prev_close": 100.0}
    start = datetime(2024, 8, 1, 10, 0, tzinfo=TAIPEI)
    # 60s into a 5m bar: cumulative 90 lots → pace 90/(60/300) = 450 ≥ 180.
    ticks = _ticks(start, [(10, 104.0, 30), (30, 104.8, 30), (60, 105.5, 30)])
    out = v2_scan(ctx, ticks, start, 5, TEST_PARAMS)
    assert out == [("breakout", 1, 105.0, start + timedelta(seconds=60))], f"got {out}"


def _test_v2_slow_volume_stays_quiet() -> None:
    ctx = {"res": 105.0, "sup": 95.0, "bb": (100.0, 101.0, 99.0),
           "vol_sma": 100.0, "prev_close": 100.0}
    start = datetime(2024, 8, 1, 10, 0, tzinfo=TAIPEI)
    # Cross at 240s with 90 lots → pace 90/(240/300) = 112.5 < 180.
    ticks = _ticks(start, [(120, 104.0, 30), (200, 104.8, 30), (240, 105.5, 30)])
    assert v2_scan(ctx, ticks, start, 5, TEST_PARAMS) == []


def _test_v2_fires_once_per_bar() -> None:
    ctx = {"res": 105.0, "sup": 95.0, "bb": (100.0, 101.0, 99.0),
           "vol_sma": 100.0, "prev_close": 100.0}
    start = datetime(2024, 8, 1, 10, 0, tzinfo=TAIPEI)
    ticks = _ticks(start, [(10, 105.5, 200), (20, 104.5, 10), (30, 105.5, 10)])
    out = v2_scan(ctx, ticks, start, 5, TEST_PARAMS)
    assert len(out) == 1 and out[0][3] == start + timedelta(seconds=10)


def _test_v3_first_zone_entry_only() -> None:
    ctx = {"res": 105.0, "sup": 95.0, "bb": None, "vol_sma": None,
           "prev_close": 100.0}
    start = datetime(2024, 8, 1, 10, 0, tzinfo=TAIPEI)
    # zone_pct 0.10 → support zone upper edge 95.095
    ticks = _ticks(start, [(5, 96.0, 1), (10, 95.05, 1), (20, 96.0, 1),
                           (30, 95.05, 1)])
    fired: set[tuple[str, float]] = set()
    out = v3_scan(ctx, ticks, TEST_PARAMS, fired)
    assert out == [("bounce", 1, 95.0, start + timedelta(seconds=10))], f"got {out}"
    assert v3_scan(ctx, ticks, TEST_PARAMS, fired) == [], "level already fired"
```

Register the four tests. Run: expect `NameError: v2_scan`.

- [ ] **Step 2: Implement both scans**

```python
def v2_scan(ctx: dict, ticks: list[tuple[datetime, float, int]],
            bar_start: datetime, interval_minutes: int, params: TFParams,
            ) -> list[tuple[str, int, float, datetime]]:
    """Intrabar 帶量突破/跌破: fire at the crossing tick when the projected
    full-bar volume already clears the strong-volume ratio. Reads only the
    previous completed bar's BB/volume state, so nothing peeks ahead."""
    bb, vol_sma, prev_close = ctx["bb"], ctx["vol_sma"], ctx["prev_close"]
    if bb is None or vol_sma is None or vol_sma <= 0 or prev_close is None:
        return []
    mid = bb[0]
    interval_seconds = interval_minutes * 60
    events: list[tuple[str, int, float, datetime]] = []
    fired_up = fired_down = False
    cumulative = 0
    last_price = prev_close
    for when, price, volume in ticks:
        cumulative += volume
        elapsed = max((when - bar_start).total_seconds(), 1.0)
        pace = cumulative / (elapsed / interval_seconds)
        strong = pace >= params.vol_ratio * vol_sma
        res, sup = ctx["res"], ctx["sup"]
        if not fired_up and res is not None and prev_close <= res \
                and last_price <= res < price and strong and price > mid:
            events.append(("breakout", 1, res, when))
            fired_up = True
        if not fired_down and sup is not None and prev_close >= sup \
                and last_price >= sup > price and strong and price < mid:
            events.append(("breakdown", -1, sup, when))
            fired_down = True
        last_price = price
    return events


def v3_scan(ctx: dict, ticks: list[tuple[datetime, float, int]],
            params: TFParams, fired_levels: set[tuple[str, float]],
            ) -> list[tuple[str, int, float, datetime]]:
    """接近預警: first entry into the S/R tolerance zone, toward the level.
    Long side at support, short side at resistance; once per level per
    session (fired_levels is owned by the caller)."""
    zone = params.zone_pct / 100.0
    prev_close = ctx["prev_close"]
    if prev_close is None:
        return []
    events: list[tuple[str, int, float, datetime]] = []
    last_price = prev_close
    for when, price, volume in ticks:
        sup, res = ctx["sup"], ctx["res"]
        if sup is not None and ("bounce", sup) not in fired_levels \
                and last_price > sup * (1 + zone) >= price:
            events.append(("bounce", 1, sup, when))
            fired_levels.add(("bounce", sup))
        if res is not None and ("rejection", res) not in fired_levels \
                and last_price < res * (1 - zone) <= price:
            events.append(("rejection", -1, res, when))
            fired_levels.add(("rejection", res))
        last_price = price
    return events
```

- [ ] **Step 3: Run, expect all 11 tests pass**

Run: `PYTHONPATH=src .venv/bin/python scripts/pine_signal_report.py --self-test`
Expected: `11 self-tests passed`

- [ ] **Step 4: Commit**

```bash
git add scripts/pine_signal_report.py
git commit -m "Add the three earlier-firing signal variants"
```

---

### Task 4: Pricing engine — session tape, horizons, net points

**Files:**
- Modify: `tmf-research-agent/scripts/pine_signal_report.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) SignalEvent`: `timeframe:int, signal:str, variant:str, direction:int, time:datetime, level:float, trading_date:str, session:str`.
  - `SessionTape(times: list[datetime], prices: list[float])` with `entry_after(t) -> tuple[datetime, float] | None` (first trade strictly after `t`) and `exit_at(t) -> float | None` (last trade at or before `t`).
  - `price_event(event: SignalEvent, tape: SessionTape, session_end: datetime) -> dict[str, float] | None` — keys `"15" "60" "240" "sclose"`; `None` when no entry tick exists; a horizon key is omitted when its exit lands at or before the entry tick.

- [ ] **Step 1: Add failing tests**

```python
def _test_pricing_arithmetic_and_session_clip() -> None:
    start = datetime(2024, 8, 1, 13, 0, tzinfo=TAIPEI)
    session_end = datetime(2024, 8, 1, 13, 45, tzinfo=TAIPEI)
    times = [start + timedelta(minutes=m) for m in (1, 5, 20, 40)]
    tape = SessionTape(times, [100.0, 101.0, 104.0, 108.0])
    event = SignalEvent(5, "breakout", "orig", 1, start, 99.0,
                        "2024-08-01", "DAY")
    priced = price_event(event, tape, session_end)
    assert priced is not None
    # entry = first tick after 13:00 → 100 @ 13:01
    # +15 → last ≤ 13:15 = 101; net = 1*(101-100) - 3 = -2
    assert priced["15"] == -2.0
    # +60 clips to session end 13:45 → exit 108; net = 5
    assert priced["60"] == 5.0 and priced["240"] == 5.0
    assert priced["sclose"] == 5.0


def _test_pricing_short_direction() -> None:
    start = datetime(2024, 8, 1, 13, 0, tzinfo=TAIPEI)
    session_end = datetime(2024, 8, 1, 13, 45, tzinfo=TAIPEI)
    tape = SessionTape([start + timedelta(minutes=1),
                        start + timedelta(minutes=14)], [100.0, 96.0])
    event = SignalEvent(5, "breakdown", "orig", -1, start, 101.0,
                        "2024-08-01", "DAY")
    priced = price_event(event, tape, session_end)
    assert priced is not None and priced["15"] == 1.0  # -1*(96-100) - 3


def _test_pricing_no_entry_tick() -> None:
    start = datetime(2024, 8, 1, 13, 44, tzinfo=TAIPEI)
    session_end = datetime(2024, 8, 1, 13, 45, tzinfo=TAIPEI)
    tape = SessionTape([start - timedelta(minutes=1)], [100.0])
    event = SignalEvent(5, "breakout", "orig", 1, start, 99.0,
                        "2024-08-01", "DAY")
    assert price_event(event, tape, session_end) is None
```

Register the three tests; run; expect `NameError: SessionTape`.

- [ ] **Step 2: Implement**

```python
@dataclass(frozen=True)
class SignalEvent:
    timeframe: int
    signal: str
    variant: str
    direction: int
    time: datetime
    level: float
    trading_date: str
    session: str


class SessionTape:
    def __init__(self, times: list[datetime], prices: list[float]) -> None:
        self.times = times
        self.prices = prices

    def entry_after(self, when: datetime) -> tuple[datetime, float] | None:
        index = bisect_right(self.times, when)
        if index >= len(self.times):
            return None
        return self.times[index], self.prices[index]

    def exit_at(self, when: datetime) -> float | None:
        index = bisect_right(self.times, when)
        return self.prices[index - 1] if index else None


def price_event(event: SignalEvent, tape: SessionTape,
                session_end: datetime) -> dict[str, float] | None:
    entry = tape.entry_after(event.time)
    if entry is None:
        return None
    entry_time, entry_price = entry
    results: dict[str, float] = {}
    targets = [(str(h), min(event.time + timedelta(minutes=h), session_end))
               for h in HORIZONS] + [("sclose", session_end)]
    for key, exit_time in targets:
        if exit_time <= entry_time:
            continue
        exit_price = tape.exit_at(exit_time)
        if exit_price is None:
            continue
        results[key] = event.direction * (exit_price - entry_price) - COST_POINTS
    return results if results else None
```

- [ ] **Step 3: Run, expect all 14 tests pass, then commit**

Run: `PYTHONPATH=src .venv/bin/python scripts/pine_signal_report.py --self-test`

```bash
git add scripts/pine_signal_report.py
git commit -m "Price replayed signals against the session tape"
```

---

### Task 5: Lead-time pairing and false alarms

**Files:**
- Modify: `tmf-research-agent/scripts/pine_signal_report.py`

**Interfaces:**
- Produces: `pair_lead_times(early: list[SignalEvent], originals: list[SignalEvent]) -> tuple[list[float], int]` — matches each early event to the first original event with the same `(timeframe, signal, trading_date, session)` and `abs(level difference) < 1e-6` at `original.time >= early.time`; returns (lead minutes list, unmatched count). Each original may absorb multiple early variants' events (variants are independent), but within one variant each original matches at most once.

- [ ] **Step 1: Add failing test**

```python
def _test_lead_time_pairing() -> None:
    day = datetime(2024, 8, 1, 9, 0, tzinfo=TAIPEI)

    def ev(variant: str, minutes: int, level: float = 105.0,
           signal: str = "breakout") -> SignalEvent:
        return SignalEvent(5, signal, variant, 1, day + timedelta(minutes=minutes),
                           level, "2024-08-01", "DAY")

    originals = [ev("orig", 30), ev("orig", 90)]
    early = [ev("v2", 22), ev("v2", 85), ev("v2", 200), ev("v2", 40, level=99.0)]
    leads, unmatched = pair_lead_times(early, originals)
    assert leads == [8.0, 5.0], f"got {leads}"
    assert unmatched == 2  # the 200-minute event and the wrong-level event
```

Run; expect `NameError: pair_lead_times`.

- [ ] **Step 2: Implement**

```python
def pair_lead_times(early: list[SignalEvent], originals: list[SignalEvent],
                    ) -> tuple[list[float], int]:
    used: set[int] = set()
    leads: list[float] = []
    unmatched = 0
    for event in sorted(early, key=lambda e: e.time):
        match = None
        for index, original in enumerate(originals):
            if index in used or original.time < event.time:
                continue
            if (original.timeframe, original.signal, original.trading_date,
                    original.session) != (event.timeframe, event.signal,
                                          event.trading_date, event.session):
                continue
            if abs(original.level - event.level) >= 1e-6:
                continue
            if match is None or original.time < originals[match].time:
                match = index
        if match is None:
            unmatched += 1
        else:
            used.add(match)
            leads.append((originals[match].time - event.time).total_seconds() / 60.0)
    return leads, unmatched
```

- [ ] **Step 3: Run (15 tests pass), commit**

```bash
git add scripts/pine_signal_report.py
git commit -m "Measure what earliness buys: lead minutes and false alarms"
```

---

### Task 6: Real-data streaming loop and markdown report

**Files:**
- Modify: `tmf-research-agent/scripts/pine_signal_report.py`

**Interfaces:**
- Consumes (all existing, exactly as `scripts/label_sweep.py` lines 48–116 uses them): `ResearchBuildSpec(calendar=path).trading_calendar()`, `SessionResolver(calendar)`, `SegmentManifest(**record)` filtered to `event_type == "historical-tick"`, `AppendOnlyRawStore(raw_root, writer_version=…, dataset_version=…)`, `_session_batches(store, manifests, calendar, resolver, set())` yielding batches with `.trading_date, .session, .resolution, .ticks, .quotes`, `ProcessingPipeline(quote_joiner=QuoteJoiner(max_quote_age=timedelta(minutes=2))).process(ticks=…, bidasks=…, resolution=…, start_second=…, end_second=…, source_manifests=…, intervals=(5, 15, 60))` → `processed.bar_sets[i].bars` in `intervals` order.
- Produces: `run(raw_root: Path, calendar_path: Path, start_day: str, end_day: str) -> int` wired into `main`; report printed to stdout.

- [ ] **Step 1: Write the streaming loop**

No self-test here (this is glue over real data; the smoke run in Step 3 is its test). Key decisions, locked:

- Engines persist across sessions within the run (TradingView charts are continuous): one dict `engines[(timeframe, variant_key)]` with `variant_key ∈ {"orig", "v1"}`, created once before the batch loop. `v1` engines use `right_bars=2`.
- Ticks: `sorted(batch.ticks, key=lambda t: t.exchange_datetime)`, drop `simtrade`, then triples `(exchange_datetime, close, volume)`.
- `start_second = resolution.session_start`, `end_second = resolution.session_end - timedelta(seconds=1)` — keeps the bar grid anchored to 08:45/15:00 like TradingView. If `ProcessingPipeline` rejects a session because states precede the first tick, fall back to the `label_sweep` minute-floor of the first tick *for that session only* and count it in a `fallback_anchor` tally printed at the end.
- Per session, per timeframe: iterate bars; **before** `engine.update(bar)` run `v2_scan`/`v3_scan` with `engines[(tf,"orig")].forming_context()` and the tick slice `[bar.bar_start, bar.bar_end)` (bisect on the tick time list); then `update` the `orig` and `v1` engines and wrap their returned tuples into `SignalEvent`s (`time=bar.bar_end` for close-confirmed signals, tick time for v2/v3).
- `v3` `fired_levels` set resets per session per timeframe.
- Price all of the session's events with that session's `SessionTape` before moving on (exit clipping uses `resolution.session_end`); accumulate into `cells: dict[tuple, list[float]]` keyed `(timeframe, signal, variant, horizon, period)` where `period` is `"2024H2"` / `"2025H1"` / `"2026+"` derived from `trading_date`. Keep events-per-`(timeframe, signal, variant)` lists of `SignalEvent` for the pairing tables, but only `(time, level, signal, timeframe, trading_date, session)` — memory stays trivial.
- Progress line per session like `label_sweep` (`[n] 2024-08-01 DAY 事件累計 …`).

```python
def _period(trading_date: str) -> str:
    if trading_date >= "2026-01-01":
        return "2026+"
    return "2024H2" if trading_date < "2025-01-01" else "2025H1"
```

- [ ] **Step 2: Write the report printer**

```python
def print_report(cells, lead_tables, sessions, fallback_anchor) -> None
```

Markdown sections, one per timeframe: table rows `signal × variant × horizon`, columns `N / 勝率 / 平均淨點 / 中位淨點`, one sub-column group per period; append `⚠樣本不足` when `N < 30`. Second section per timeframe: variant lead-time table — `配對數 / 平均提早(分) / 假警報數 / 假警報率`. Close with the standing caveats from the spec (3-point cost is an assumption; ±1 point ≈ noise; 60m rows directional only).

- [ ] **Step 3: Smoke run on two weeks of real data**

Run: `PYTHONPATH=src .venv/bin/python scripts/pine_signal_report.py data data/calendar.json 2024-08-01 2024-08-15`
Expected: completes in minutes, nonzero event counts for 5m/15m signals, report renders. Sanity-check by hand: pick one printed breakout event date (add a temporary `print` if needed, remove before commit) and confirm the 5m bar sequence around it satisfies the conditions.

- [ ] **Step 4: Run the full self-test once more, then commit**

```bash
git add scripts/pine_signal_report.py
git commit -m "Stream real sessions through the Pine replay and print the report"
```

---

### Task 7: Full runs and the deliverable

**Files:**
- Create: `output/pine-signal-report-blockA.md`, `output/pine-signal-report-blockB.md` (redirected stdout; `output/` already exists at repo root and is untracked — if it is gitignored, keep them there anyway and quote the tables in the summary)

- [ ] **Step 1: Block A run**

Run: `PYTHONPATH=src .venv/bin/python scripts/pine_signal_report.py data data/calendar.json 2024-07-29 2025-06-30 | tee ../output/pine-signal-report-blockA.md`
Expected: ~233 trading days streamed; wall time on the order of the `label_sweep` full run (tens of minutes). If it exceeds ~90 minutes, stop and profile before rerunning.

- [ ] **Step 2: Block B run**

Run: `PYTHONPATH=src .venv/bin/python scripts/pine_signal_report.py data data/calendar.json 2026-07-01 2026-08-04 | tee ../output/pine-signal-report-blockB.md`

- [ ] **Step 3: Write the honest interpretation**

Summarize for the user, in Chinese, leading with the verdict per cell family:
which signal × timeframe × horizon cells are net-positive with N ≥ 30 and
consistent sign across periods; what V1/V2/V3 bought in lead minutes and paid
in false alarms; explicitly confirm or refute the prior-research prediction
that short-horizon cells are dead. Any deviation from the spec (e.g. session
close instead of day-session close for night events, anchor fallbacks) is
listed. No Pine changes in this track — end with the finding.

- [ ] **Step 4: Commit the script's final state if Steps 1–3 forced any fix**

```bash
git add scripts/pine_signal_report.py
git commit -m "Adjust the Pine replay after the full-range runs"
```

(Skip if nothing changed.)

---

## Self-Review Notes

- Spec coverage: signal semantics (Task 1–2), variants (Task 3), evaluation/cost (Task 4), pairing/false alarms (Task 5), data blocks/periods/report/flags (Task 6), full runs + interpretation (Task 7). Spec's "day-session close" is implemented as signal-session close — flagged as a deviation to report (night sessions have no same-day day-close inside the tape).
- Type consistency: tick triples `(datetime, float, int)` everywhere; `forming_context` keys `res/sup/bb/vol_sma/prev_close` consumed by both scans; `SignalEvent` fields match `pair_lead_times` and `price_event` usage.
- No placeholders: every code step is complete; Task 6's loop is specified by exact decisions plus the `label_sweep` line-range reference for the boilerplate it mirrors.
