"""Test the one futures result with broad independent support, at our scale.

Time-series momentum — a contract's own past return predicting its next
return — is documented across 58 liquid futures, but at holding periods of
one to twelve months. The intraday search that preceded this found nothing
that survived a three-point spread, which is consistent with that literature:
the published effect lives at a horizon four orders of magnitude longer than
fifteen minutes.

This asks whether any of it is visible at the horizons our stored history can
actually reach. It reads daily bars straight from the historical-tick
segments — one file is one trading date — and reports two things per
lookback/holding pair: the rank correlation between past and future return,
and what a barrier label at that horizon would produce.

Note the honest limit: the contiguous block is under a year, so a 12-month
lookback is untestable here. Weeks, not months, is the most this can say.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Trading days: ~21 to a month, so 252 is the twelve-month lookback the
# time-series-momentum literature reports.
LOOKBACKS = (5, 21, 63, 126, 252)
HOLDS = (1, 5, 21, 63)


@dataclass(frozen=True, slots=True)
class DailyBar:
    trading_date: str
    open: float
    high: float
    low: float
    close: float
    ticks: int


def bars_from_daily_file(path: Path) -> list[DailyBar]:
    """Exchange daily download: one JSON object per trading date."""

    bars = [
        DailyBar(
            row["trading_date"], float(row["open"]), float(row["high"]),
            float(row["low"]), float(row["close"]), int(row.get("volume", 0)),
        )
        for row in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    ]
    bars.sort(key=lambda bar: bar.trading_date)
    return bars


def daily_bars(segments: Path) -> list[DailyBar]:
    bars: list[DailyBar] = []
    for path in sorted(segments.glob("backfill-tick-TMFR1-*.ndjson")):
        day = path.stem.rpartition("TMFR1-")[2]
        prices: list[tuple[str, float]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            close = record["fields"].get("close")
            if isinstance(close, (int, float)) and close > 0:
                prices.append((str(record["exchange_datetime"]), float(close)))
        if not prices:
            continue
        # Vendor arrays occasionally misplace a night tick after the day close,
        # so open and close come from timestamp order rather than file order.
        prices.sort(key=lambda item: item[0])
        values = [price for _when, price in prices]
        bars.append(DailyBar(
            day, values[0], max(values), min(values), values[-1], len(values),
        ))
    return bars


def ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2.0 + 1.0
        for index in order[position:end + 1]:
            result[index] = shared
        position = end + 1
    return tuple(result)


def spearman(xs: tuple[float, ...], ys: tuple[float, ...]) -> float | None:
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (sx * sy) if sx and sy else None


def _blocks(bars: list[DailyBar]) -> list[list[DailyBar]]:
    """Split where the archive has a gap, so returns never span the API void."""

    blocks: list[list[DailyBar]] = [[bars[0]]]
    for previous, current in zip(bars, bars[1:]):
        year_gap = int(current.trading_date[:4]) - int(previous.trading_date[:4])
        month_gap = int(current.trading_date[5:7]) - int(previous.trading_date[5:7])
        if year_gap * 12 + month_gap > 1:
            blocks.append([])
        blocks[-1].append(current)
    return blocks


def report(source: Path) -> int:
    bars = bars_from_daily_file(source) if source.is_file() else daily_bars(source)
    if len(bars) < 30:
        print(f"只有 {len(bars)} 個交易日,不足以判讀", file=sys.stderr)
        return 1
    blocks = _blocks(bars)
    print(f"日線 {len(bars)} 天  {bars[0].trading_date} .. {bars[-1].trading_date}")
    for block in blocks:
        print(f"  連續區塊: {block[0].trading_date} .. {block[-1].trading_date}  ({len(block)} 天)")

    print(f"\n過去報酬 vs 未來報酬的等級相關(僅用連續區塊內的配對)\n")
    header = f"{'回看':>6}" + "".join(f"{f'持有{h}天':>12}" for h in HOLDS)
    print(header)
    print("-" * len(header))
    for lookback in LOOKBACKS:
        cells = []
        for hold in HOLDS:
            past: list[float] = []
            future: list[float] = []
            for block in blocks:
                for index in range(lookback, len(block) - hold):
                    before = block[index - lookback].close
                    now = block[index].close
                    after = block[index + hold].close
                    if before <= 0 or now <= 0:
                        continue
                    past.append(now / before - 1.0)
                    future.append(after / now - 1.0)
            value = spearman(tuple(past), tuple(future)) if len(past) >= 3 else None
            cells.append(
                f"{'—':>12}" if value is None else f"{value:>+9.3f}({len(past):>d})"
            )
        print(f"{lookback:>6}" + "".join(cells))
    print(
        "\n正值 = 動量(漲的續漲),負值 = 反轉(漲的回落)。括號內為重疊配對數。\n"
        "回看 21/63/126/252 天約等於 1/3/6/12 個月。獨立觀察數約為\n"
        "「配對數 ÷ 持有天數」,判讀強弱時要以獨立數為準,不是括號裡的數字。"
    )
    return 0


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "data/daily/mtx-daily.ndjson"
    )
    raise SystemExit(report(root))
