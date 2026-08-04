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
