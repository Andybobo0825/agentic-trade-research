"""Replay the TradingView Pine indicator (台指 MTF BB-SR) over real TMF ticks.

Reproduces the four confirmed signals (帶量突破/帶量跌破/支撐止跌/壓力遇阻)
plus three earlier-firing variants, prices each against the session's own
ticks minus a 3-point round trip, and prints a markdown credibility report.
Spec: docs/superpowers/specs/2026-08-04-pine-signal-report-design.md
"""
from __future__ import annotations

import json
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from tmf_research.features.context_builder import ResearchBuildSpec
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, SegmentManifest
from tmf_research.processing.bars import Bar
from tmf_research.processing.pipeline import ProcessingPipeline
from tmf_research.processing.quote_joiner import QuoteJoiner
from tmf_research.processing.session_resolver import SessionResolver
from tmf_research.validation.dataset_lineage import _session_batches

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


def _warmup(pivot_high: float = 105.0, pivot_low: float = 95.0) -> list[Bar]:
    """22 flat bars with a pivot high/low pair confirmed mid-warmup.

    Layout (5m bars, left=right=2 via the test params): two flat bars, the
    pivot-high spike at index 2 (confirmed at bar 4), the pivot-low spike at
    index 5 (confirmed at bar 7), then flat to 22 bars. Flat highs/lows tie,
    so no further pivots ever confirm.
    """
    start = datetime(2024, 8, 1, 8, 45, tzinfo=TAIPEI)
    flat = (100.0, 100.5, 99.5, 100.0, 100)
    rows = [flat, flat, (100.0, pivot_high, 99.5, 100.0, 100), flat, flat,
            (100.0, 100.5, pivot_low, 100.0, 100)] + [flat] * 16
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
    loud = _run([(100.0, 106.0, 100.0, 106.0, 500)])    # 500 >= 1.8 * 120
    assert quiet[-1] == [], "weak volume must not fire"
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
    out = _run([(95.0, 95.6, 94.9, 95.5, 100)])
    assert out[-1] == [("bounce", 1, 95.0)], f"got {out[-1]}"


def _test_rejection_at_resistance() -> None:
    out = _run([(104.5, 105.1, 104.0, 104.2, 100)])
    assert out[-1] == [("rejection", -1, 105.0)], f"got {out[-1]}"


SIGNAL_DIRECTION = {"breakout": 1, "bounce": 1, "breakdown": -1, "rejection": -1}


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


def pair_lead_times(early: list[SignalEvent], originals: list[SignalEvent],
                    ) -> tuple[list[float], int]:
    """Match each early event to the first same-type same-level original at
    or after it, within the same session. Unmatched events are the false
    alarms — the price paid for earliness."""
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


TESTS = [
    _test_pivot_confirms_right_bars_late,
    _test_pivot_tie_is_not_a_pivot,
    _test_breakout_needs_volume_and_bb,
    _test_breakout_requires_cross_not_position,
    _test_breakdown_mirror,
    _test_bounce_at_support,
    _test_rejection_at_resistance,
    _test_v2_fires_on_cross_with_paced_volume,
    _test_v2_slow_volume_stays_quiet,
    _test_v2_fires_once_per_bar,
    _test_v3_first_zone_entry_only,
    _test_pricing_arithmetic_and_session_clip,
    _test_pricing_short_direction,
    _test_pricing_no_entry_tick,
    _test_lead_time_pairing,
]


def self_test() -> int:
    for test in TESTS:
        test()
        print(f"ok {test.__name__}")
    print(f"{len(TESTS)} self-tests passed")
    return 0


def _period(trading_date: str) -> str:
    if trading_date >= "2026-01-01":
        return "2026+"
    return "2024H2" if trading_date < "2025-01-01" else "2025H1"


TIMEFRAMES = (5, 15, 60)
SIGNALS = ("breakout", "breakdown", "bounce", "rejection")
VARIANTS = ("orig", "v1", "v2", "v3")
VARIANT_SIGNALS = {
    "orig": SIGNALS, "v1": SIGNALS,
    "v2": ("breakout", "breakdown"), "v3": ("bounce", "rejection"),
}


def run(raw_root: Path, calendar_path: Path, start_day: str, end_day: str) -> int:
    spec = ResearchBuildSpec(calendar=calendar_path)
    calendar = spec.trading_calendar()
    resolver = SessionResolver(calendar)
    records = [
        json.loads(line)
        for line in (raw_root / "manifest.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    def in_range(segment_id: str) -> bool:
        _prefix, separator, suffix = segment_id.rpartition("TMFR1-")
        if not separator:
            return True
        return start_day <= suffix[:10] <= end_day

    manifests = tuple(
        SegmentManifest(**record)
        for record in records
        if record["event_type"] == "historical-tick"
        and in_range(str(record["segment_id"]))
    )
    if not manifests:
        print(f"{start_day}..{end_day} 沒有任何 segment", file=sys.stderr)
        return 1
    store = AppendOnlyRawStore(
        raw_root,
        writer_version=manifests[0].writer_version,
        dataset_version=manifests[0].dataset_version,
    )

    engines: dict[tuple[int, str], PineState] = {}
    for tf in TIMEFRAMES:
        engines[(tf, "orig")] = PineState(PRESETS[tf])
        engines[(tf, "v1")] = PineState(PRESETS[tf], right_bars=2)

    cells: dict[tuple[int, str, str, str, str], list[float]] = defaultdict(list)
    events_store: dict[tuple[int, str, str], list[SignalEvent]] = defaultdict(list)
    sessions = 0
    fallback_anchor = 0
    unpriced = 0

    for batch in _session_batches(store, manifests, calendar, resolver, set()):
        resolution = batch.resolution
        if not batch.ticks or not batch.quotes:
            continue
        if resolution.session_start is None or resolution.session_end is None:
            continue
        ordered = sorted(
            (t for t in batch.ticks if not t.simtrade),
            key=lambda t: t.exchange_datetime,
        )
        if not ordered:
            continue
        pipeline = ProcessingPipeline(
            quote_joiner=QuoteJoiner(max_quote_age=timedelta(minutes=2)),
        )
        kwargs = dict(
            ticks=batch.ticks, bidasks=batch.quotes, resolution=resolution,
            end_second=resolution.session_end - timedelta(seconds=1),
            source_manifests=manifests, intervals=TIMEFRAMES,
        )
        try:
            processed = pipeline.process(
                start_second=resolution.session_start, **kwargs,
            )
        except ValueError:
            fallback_anchor += 1
            fallback = min(t.exchange_datetime for t in batch.ticks).replace(
                second=0, microsecond=0,
            )
            processed = pipeline.process(start_second=fallback, **kwargs)
        tick_times = [t.exchange_datetime for t in ordered]
        tick_prices = [t.close for t in ordered]
        tick_vols = [t.volume for t in ordered]
        tape = SessionTape(tick_times, tick_prices)
        period = _period(batch.trading_date)
        session_events: list[SignalEvent] = []
        bars_by_interval = {
            bar_set.interval_minutes: bar_set.bars for bar_set in processed.bar_sets
        }
        for tf in TIMEFRAMES:
            params = PRESETS[tf]
            orig_engine = engines[(tf, "orig")]
            v1_engine = engines[(tf, "v1")]
            fired_levels: set[tuple[str, float]] = set()
            for bar in bars_by_interval[tf]:
                ctx = orig_engine.forming_context()
                lo = bisect_left(tick_times, bar.bar_start)
                hi = bisect_left(tick_times, bar.bar_end)
                bar_ticks = [
                    (tick_times[i], tick_prices[i], tick_vols[i])
                    for i in range(lo, hi)
                ]
                for name, direction, level, when in v2_scan(
                        ctx, bar_ticks, bar.bar_start, tf, params):
                    session_events.append(SignalEvent(
                        tf, name, "v2", direction, when, level,
                        batch.trading_date, batch.session))
                for name, direction, level, when in v3_scan(
                        ctx, bar_ticks, params, fired_levels):
                    session_events.append(SignalEvent(
                        tf, name, "v3", direction, when, level,
                        batch.trading_date, batch.session))
                for name, direction, level in orig_engine.update(bar):
                    session_events.append(SignalEvent(
                        tf, name, "orig", direction, bar.bar_end, level,
                        batch.trading_date, batch.session))
                for name, direction, level in v1_engine.update(bar):
                    session_events.append(SignalEvent(
                        tf, name, "v1", direction, bar.bar_end, level,
                        batch.trading_date, batch.session))
        for event in session_events:
            priced = price_event(event, tape, resolution.session_end)
            if priced is None:
                unpriced += 1
            else:
                for horizon, net in priced.items():
                    cells[(event.timeframe, event.signal, event.variant,
                           horizon, period)].append(net)
            events_store[(event.timeframe, event.signal, event.variant)].append(event)
        sessions += 1
        total_events = sum(len(value) for value in events_store.values())
        print(f"  [{sessions}] {batch.trading_date} {batch.session}"
              f"  事件累計 {total_events:,}", file=sys.stderr, flush=True)

    # Pair per session so the quadratic matcher never sees more than one
    # session's events at a time.
    lead_tables: dict[tuple[int, str, str], tuple[list[float], int, int]] = {}
    for (tf, signal, variant), early in events_store.items():
        if variant == "orig":
            continue
        originals = events_store.get((tf, signal, "orig"), [])
        originals_by_session: dict[tuple[str, str], list[SignalEvent]] = defaultdict(list)
        for event in originals:
            originals_by_session[(event.trading_date, event.session)].append(event)
        early_by_session: dict[tuple[str, str], list[SignalEvent]] = defaultdict(list)
        for event in early:
            early_by_session[(event.trading_date, event.session)].append(event)
        leads: list[float] = []
        unmatched = 0
        for key, group in early_by_session.items():
            group_leads, group_unmatched = pair_lead_times(
                group, originals_by_session.get(key, []))
            leads.extend(group_leads)
            unmatched += group_unmatched
        lead_tables[(tf, signal, variant)] = (leads, unmatched, len(early))
    print_report(cells, lead_tables, sessions, fallback_anchor, unpriced,
                 start_day, end_day)
    return 0


SIGNAL_NAMES = {"breakout": "帶量突破", "breakdown": "帶量跌破",
                "bounce": "支撐止跌", "rejection": "壓力遇阻"}
VARIANT_NAMES = {"orig": "原版", "v1": "V1縮短確認",
                 "v2": "V2盤中觸發", "v3": "V3接近預警"}


def print_report(
    cells: dict[tuple[int, str, str, str, str], list[float]],
    lead_tables: dict[tuple[int, str, str], tuple[list[float], int, int]],
    sessions: int, fallback_anchor: int, unpriced: int,
    start_day: str, end_day: str,
) -> None:
    periods = sorted({key[4] for key in cells})
    horizons = [str(h) for h in HORIZONS] + ["sclose"]
    print(f"# Pine 訊號可信度報告 {start_day}..{end_day}")
    print(f"\n掃描 {sessions} 個時段；anchor fallback {fallback_anchor}；"
          f"無法定價事件 {unpriced}")
    print(f"成本假設：來回 {COST_POINTS:.0f} 點。淨點數在 ±1 點內視同雜訊。"
          "60 分K樣本少，僅供方向參考。訊號出場一律不跨時段（夜盤訊號以該夜盤收盤為界）。\n")
    for tf in TIMEFRAMES:
        print(f"\n## {tf} 分K\n")
        header = "| 訊號 | 變體 | horizon |"
        rule = "|---|---|---|"
        for period in periods:
            header += f" {period} N | 勝率 | 平均淨點 | 中位淨點 |"
            rule += "---|---|---|---|"
        print(header)
        print(rule)
        for signal in SIGNALS:
            for variant in VARIANTS:
                if signal not in VARIANT_SIGNALS[variant]:
                    continue
                for horizon in horizons:
                    row_cells = []
                    any_data = False
                    for period in periods:
                        nets = cells.get((tf, signal, variant, horizon, period))
                        if not nets:
                            row_cells.append(" — | — | — | — |")
                            continue
                        any_data = True
                        n = len(nets)
                        wins = sum(1 for value in nets if value > 0) / n
                        flag = "⚠" if n < 30 else ""
                        row_cells.append(
                            f" {n}{flag} | {wins:.0%} | {sum(nets) / n:+.2f}"
                            f" | {median(nets):+.2f} |")
                    if any_data:
                        print(f"| {SIGNAL_NAMES[signal]} | {VARIANT_NAMES[variant]}"
                              f" | {horizon} |" + "".join(row_cells))
        printed_header = False
        for (tf2, signal, variant), (leads, unmatched, total) in sorted(
                lead_tables.items()):
            if tf2 != tf or not total:
                continue
            if not printed_header:
                print(f"\n### 提早效果（{tf} 分K）\n")
                print("| 訊號 | 變體 | 事件數 | 配對數 | 平均提早(分) |"
                      " 假警報數 | 假警報率 |")
                print("|---|---|---|---|---|---|---|")
                printed_header = True
            mean_lead = f"{sum(leads) / len(leads):.1f}" if leads else "—"
            print(f"| {SIGNAL_NAMES[signal]} | {VARIANT_NAMES[variant]} | {total}"
                  f" | {len(leads)} | {mean_lead} | {unmatched}"
                  f" | {unmatched / total:.0%} |")
    print("\n⚠ = 樣本數 < 30。假警報 = 早期訊號之後，同時段內原版訊號從未在同一價位確認。")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--self-test":
        raise SystemExit(self_test())
    if len(sys.argv) == 5:
        raise SystemExit(run(Path(sys.argv[1]), Path(sys.argv[2]),
                             sys.argv[3], sys.argv[4]))
    print("用法: pine_signal_report.py --self-test | <raw-root> <calendar.json> <起始日> <結束日>",
          file=sys.stderr)
    raise SystemExit(2)
