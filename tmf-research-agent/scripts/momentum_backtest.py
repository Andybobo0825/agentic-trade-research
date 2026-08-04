"""Price the daily momentum signal, with the three controls that decide it.

A rank correlation says a relationship exists; it does not say the
relationship pays. Three things separate the two here, and all three are the
ways this kind of result usually turns out to be nothing:

  Overlap — rolling windows share most of their data, so 2,695 pairs is
  really about 43 independent holds. Positions here are non-overlapping.

  Selection — the strongest cell was chosen after seeing all twenty, so its
  number is optimistic by construction. Every cell is priced, not just that
  one, and the split below is what the choice is actually judged on.

  Direction — the index roughly tripled over this sample, so any long-biased
  rule looks profitable without predicting anything. Buy-and-hold over the
  identical periods is the control every result is reported against.

Costs are charged per round trip in index points; at a three-month hold they
are close to irrelevant, which is the whole reason this horizon is worth
pricing after an intraday search died on a three-point spread.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "daily_momentum", Path(__file__).with_name("daily_momentum.py"),
)
assert _spec is not None and _spec.loader is not None
_dm = importlib.util.module_from_spec(_spec)
sys.modules["daily_momentum"] = _dm
_spec.loader.exec_module(_dm)

LOOKBACKS = (5, 21, 63, 126, 252)
HOLDS = (21, 63)
COST_POINTS = 3.0
SPLIT = "2021-01-01"


@dataclass(frozen=True, slots=True)
class Result:
    trades: int
    win_rate: float
    mean_return: float
    total_return: float
    hold_return: float


def run(bars: list[object], lookback: int, hold: int, cost: float) -> Result | None:
    """Long when the past return is positive, short when negative, held to term."""

    returns: list[float] = []
    holds: list[float] = []
    index = lookback
    while index + hold < len(bars):
        past = bars[index].close / bars[index - lookback].close - 1.0
        forward = bars[index + hold].close / bars[index].close - 1.0
        friction = cost / bars[index].close
        direction = 1.0 if past > 0 else -1.0
        returns.append(direction * forward - friction)
        holds.append(forward - friction)
        index += hold
    if len(returns) < 5:
        return None
    compounded = 1.0
    for value in returns:
        compounded *= 1.0 + value
    held = 1.0
    for value in holds:
        held *= 1.0 + value
    return Result(
        trades=len(returns),
        win_rate=sum(1 for value in returns if value > 0) / len(returns),
        mean_return=sum(returns) / len(returns),
        total_return=compounded - 1.0,
        hold_return=held - 1.0,
    )


def report(path: Path) -> int:
    bars = _dm.bars_from_daily_file(path)
    split = next(
        (index for index, bar in enumerate(bars) if bar.trading_date >= SPLIT),
        len(bars),
    )
    periods = (
        ("樣本內", bars[:split]),
        ("樣本外", bars[split:]),
    )
    print(
        f"日線 {len(bars)} 天  {bars[0].trading_date} .. {bars[-1].trading_date}\n"
        f"樣本內 {bars[0].trading_date}..{bars[split - 1].trading_date} / "
        f"樣本外 {bars[split].trading_date}..{bars[-1].trading_date}\n"
        f"每次來回成本 {COST_POINTS:.0f} 點,持有期不重疊\n"
    )
    for label, window in periods:
        print(f"── {label} ({len(window)} 天) " + "─" * 44)
        header = (
            f"{'回看':>6}{'持有':>6}{'次數':>6}{'勝率':>8}"
            f"{'每次平均':>10}{'累積':>10}{'買進持有':>10}{'差額':>10}"
        )
        print(header)
        for lookback in LOOKBACKS:
            for hold in HOLDS:
                result = run(window, lookback, hold, COST_POINTS)
                if result is None:
                    continue
                edge = result.total_return - result.hold_return
                print(
                    f"{lookback:>6}{hold:>6}{result.trades:>6}"
                    f"{result.win_rate:>8.1%}{result.mean_return:>10.2%}"
                    f"{result.total_return:>10.1%}{result.hold_return:>10.1%}"
                    f"{edge:>+10.1%}"
                )
        print()
    print(
        "「買進持有」是同一段期間、同樣不重疊地一直做多的結果,是這裡唯一的對照組。\n"
        "差額為正才代表訊號本身有貢獻;差額為負代表不如什麼都不做直接持有。"
    )
    return 0


if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/daily/mtx-daily.ndjson")
    raise SystemExit(report(source))
