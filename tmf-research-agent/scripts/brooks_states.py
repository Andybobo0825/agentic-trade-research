"""Test a price-action framework on its own stated prediction.

Every signal tried so far was a number squeezed out of the data and then
interpreted. This one arrives with a claim attached: PA_Agent's encoding of
Al Brooks says a spike resolves 60% into a channel, 30% into a trading range,
and 10% into a reversal. That is falsifiable without any model, so it is
worth more than another information coefficient.

Two departures from the source, both deliberate and both weakening:

  Brooks is applied to five-minute charts by eye. Fixed thresholds on daily
  bars are a different object; phrases like "negligible wicks" hide judgement
  that has to be invented as a number here.

  Daily bars are the choice because the intraday search died on a three-point
  spread, not because Brooks is a daily method. If a structural state only
  pays intraday, this will not find it.

Thresholds come from the framework as recorded, not tuned here: a spike needs
at least two consecutive trend bars with body overlap under 30%; exhaustion
is a wick over half the body, a body under 30% of the recent mean, or a bar
against the run.
"""
from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "daily_momentum", Path(__file__).with_name("daily_momentum.py"),
)
assert _spec is not None and _spec.loader is not None
_dm = importlib.util.module_from_spec(_spec)
sys.modules["daily_momentum"] = _dm
_spec.loader.exec_module(_dm)

TREND_BODY_RATIO = 0.5
SPIKE_MAX_OVERLAP = 0.30
EXHAUSTION_WICK_RATIO = 0.50
EXHAUSTION_BODY_RATIO = 0.30
RESOLUTION_WINDOW = 10


@dataclass(frozen=True, slots=True)
class Spike:
    end_index: int
    length: int
    direction: int


def body(bar: object) -> float:
    return abs(bar.close - bar.open)


def is_trend_bar(bar: object) -> bool:
    span = bar.high - bar.low
    return span > 0 and body(bar) / span > TREND_BODY_RATIO


def direction(bar: object) -> int:
    return 1 if bar.close > bar.open else -1 if bar.close < bar.open else 0


def body_overlap(first: object, second: object) -> float:
    """Shared fraction of two bodies; 0 means they do not overlap at all."""

    low = max(min(first.open, first.close), min(second.open, second.close))
    high = min(max(first.open, first.close), max(second.open, second.close))
    shared = max(0.0, high - low)
    reference = (body(first) + body(second)) / 2.0
    return shared / reference if reference > 0 else 1.0


def find_spikes(bars: list[object]) -> list[Spike]:
    """Runs of same-direction trend bars whose bodies barely overlap."""

    spikes: list[Spike] = []
    index = 0
    while index < len(bars) - 1:
        if not is_trend_bar(bars[index]):
            index += 1
            continue
        way = direction(bars[index])
        if way == 0:
            index += 1
            continue
        end = index
        while (
            end + 1 < len(bars)
            and is_trend_bar(bars[end + 1])
            and direction(bars[end + 1]) == way
            and body_overlap(bars[end], bars[end + 1]) < SPIKE_MAX_OVERLAP
        ):
            end += 1
        if end - index + 1 >= 2:
            spikes.append(Spike(end, end - index + 1, way))
            index = end + 1
        else:
            index += 1
    return spikes


def resolution(bars: list[object], spike: Spike, window: int) -> str | None:
    """What the framework says happens next: channel, range, or reversal."""

    start = spike.end_index
    if start + window >= len(bars):
        return None
    after = bars[start + 1:start + 1 + window]
    entry = bars[start].close
    move = (after[-1].close - entry) / entry * spike.direction
    span = max(bar.high for bar in after) - min(bar.low for bar in after)
    spike_span = abs(bars[start].close - bars[start - spike.length + 1].open)
    if move < 0 and abs(move) * entry > spike_span * 0.5:
        return "reversal"
    if spike_span > 0 and span < spike_span * 0.75:
        return "trading_range"
    return "channel"


def report(source: Path) -> int:
    bars = _dm.bars_from_daily_file(source)
    spikes = find_spikes(bars)
    print(f"日線 {len(bars)} 天  {bars[0].trading_date} .. {bars[-1].trading_date}")
    print(f"偵測到尖峰 {len(spikes)} 次  (連續 >=2 根趨勢棒,實體重疊 <30%)\n")

    lengths = Counter(spike.length for spike in spikes)
    print("尖峰長度分佈: " + "  ".join(
        f"{length} 根 x{count}" for length, count in sorted(lengths.items())
    ))
    ways = Counter("上漲" if spike.direction > 0 else "下跌" for spike in spikes)
    print("方向: " + "  ".join(f"{key} {value}" for key, value in ways.items()))

    outcomes = Counter()
    for spike in spikes:
        result = resolution(bars, spike, RESOLUTION_WINDOW)
        if result is not None:
            outcomes[result] += 1
    total = sum(outcomes.values())
    print(f"\n尖峰之後 {RESOLUTION_WINDOW} 天的結果  (可判定 {total} 次)")
    print(f"{'結果':<16}{'實測':>10}{'框架宣稱':>12}")
    claimed = {"channel": 0.60, "trading_range": 0.30, "reversal": 0.10}
    labels = {"channel": "通道(續勢)", "trading_range": "交易區間", "reversal": "反轉"}
    for key in ("channel", "trading_range", "reversal"):
        share = outcomes[key] / total if total else 0.0
        print(f"{labels[key]:<16}{share:>10.1%}{claimed[key]:>12.0%}")

    print(f"\n尖峰後續報酬(順著尖峰方向,持有 N 天)")
    print(f"{'天數':>6}{'次數':>8}{'平均':>10}{'勝率':>9}{'買進持有':>10}{'差額':>10}")
    for hold in (1, 5, 10, 21):
        aligned: list[float] = []
        held: list[float] = []
        for spike in spikes:
            end = spike.end_index
            if end + hold >= len(bars):
                continue
            forward = bars[end + hold].close / bars[end].close - 1.0
            aligned.append(forward * spike.direction)
            held.append(forward)
        if len(aligned) < 5:
            continue
        mean = sum(aligned) / len(aligned)
        wins = sum(1 for value in aligned if value > 0) / len(aligned)
        base = sum(held) / len(held)
        print(
            f"{hold:>6}{len(aligned):>8}{mean:>10.2%}{wins:>9.1%}"
            f"{base:>10.2%}{mean - base:>+10.2%}"
        )
    print(
        "\n「買進持有」是同樣這些時點單純做多的平均報酬。差額為正,\n"
        "才代表順著尖峰方向操作比不管方向直接做多更好。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(report(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/daily/mtx-daily.ndjson")
    ))
