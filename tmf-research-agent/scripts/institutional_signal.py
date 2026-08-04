"""Price institutional positioning against the only control that matters.

Three price-derived attempts have failed — intraday direction to the spread,
basis to being a restatement of price level, daily momentum to buying and
holding. This asks the same questions of an input of a different kind: the
net futures position each institution type carries.

Two rules are non-negotiable here, and both are ways this result would
otherwise be fake:

  The lag. These figures publish after the close, so a position dated day D
  is not knowable during day D. Every reading is shifted one trading day
  before it is allowed to predict anything.

  The control. The index roughly tripled across this sample, so any
  long-biased rule shows a profit while predicting nothing. Buy-and-hold over
  the identical non-overlapping periods is reported beside every result.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "daily_momentum", Path(__file__).with_name("daily_momentum.py"),
)
assert _spec is not None and _spec.loader is not None
_dm = importlib.util.module_from_spec(_spec)
sys.modules["daily_momentum"] = _dm
_spec.loader.exec_module(_dm)

RAW = ("foreign_open", "foreign_trade", "trust_open", "trust_trade",
       "dealer_open", "dealer_trade")
# Investment trusts carry a net long every single day of the sample and
# foreigners a net short on all but 4.5% of them, so the sign of a raw
# position is a standing structural fact rather than a view. What can carry a
# view is the level relative to that party's own recent range, which is what
# the z-score below measures.
SIGNALS = tuple(f"{name}_z" for name in RAW)
ZSCORE_WINDOW = 126
HOLDS = (1, 5, 21, 63)
COST_POINTS = 3.0
# The exchange only serves about three years of these figures, so the split
# sits inside 2023-09..2026-07 rather than at the 2021 boundary the daily
# momentum work used. Roughly two thirds in, one third out.
SPLIT = "2025-07-01"


def joined(quotes: Path, positions: Path) -> list[dict[str, object]]:
    """Pair each day's close with the positions known *before* that day opened."""

    bars = {bar.trading_date: bar for bar in _dm.bars_from_daily_file(quotes)}
    records = [
        json.loads(line)
        for line in positions.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records.sort(key=lambda record: record["trading_date"])
    days = sorted(bars)
    rows: list[dict[str, object]] = []
    for previous, current in zip(records, records[1:]):
        # `previous` is published after its own close, so the first session it
        # could influence is the next trading day.
        if current["trading_date"] not in bars:
            continue
        rows.append({
            "trading_date": current["trading_date"],
            "close": bars[current["trading_date"]].close,
            **{name: previous[name] for name in RAW if name in previous},
        })
    rows = [row for row in rows if all(name in row for name in RAW)]
    if days and rows:
        assert rows[0]["trading_date"] in bars
    return standardised(rows)


def standardised(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Each position against that party's own trailing window, never ahead of it."""

    out: list[dict[str, object]] = []
    for index in range(ZSCORE_WINDOW, len(rows)):
        row = dict(rows[index])
        for name in RAW:
            past = [float(rows[back][name]) for back in range(index - ZSCORE_WINDOW, index)]
            mean = sum(past) / len(past)
            spread = (sum((value - mean) ** 2 for value in past) / len(past)) ** 0.5
            row[f"{name}_z"] = (float(row[name]) - mean) / spread if spread > 0 else 0.0
        out.append(row)
    return out


def report(quotes: Path, positions: Path) -> int:
    rows = joined(quotes, positions)
    if len(rows) < 200:
        print(f"僅 {len(rows)} 天可用,不足以判讀", file=sys.stderr)
        return 1
    split = next(
        (index for index, row in enumerate(rows) if str(row["trading_date"]) >= SPLIT),
        len(rows),
    )
    print(
        f"對齊後 {len(rows)} 天  {rows[0]['trading_date']} .. {rows[-1]['trading_date']}\n"
        f"部位一律延後一個交易日才允許預測(公布時間在收盤後)\n"
    )

    for label, window in (("樣本內", rows[:split]), ("樣本外", rows[split:])):
        print(f"── {label} ({len(window)} 天) " + "─" * 40)
        print(f"{'訊號':<16}" + "".join(f"{f'持有{h}天':>11}" for h in HOLDS))
        for name in SIGNALS:
            cells = []
            for hold in HOLDS:
                past = tuple(
                    float(window[index][name])
                    for index in range(len(window) - hold)
                )
                future = tuple(
                    float(window[index + hold]["close"]) / float(window[index]["close"]) - 1.0
                    for index in range(len(window) - hold)
                )
                value = _dm.spearman(past, future) if len(past) >= 3 else None
                cells.append(f"{'—':>11}" if value is None else f"{value:>+11.3f}")
            print(f"{name:<16}" + "".join(cells))
        print()

    print("── 依訊號正負做多做空,持有期不重疊,對照買進持有 " + "─" * 8)
    header = (
        f"{'訊號':<16}{'持有':>5}{'期間':>7}{'次數':>6}"
        f"{'勝率':>8}{'累積':>10}{'買進持有':>10}{'差額':>10}"
    )
    print(header)
    for name in SIGNALS:
        for hold in (21, 63):
            for label, window in (("內", rows[:split]), ("外", rows[split:])):
                trades: list[float] = []
                holds: list[float] = []
                index = 0
                while index + hold < len(window):
                    close = float(window[index]["close"])
                    forward = float(window[index + hold]["close"]) / close - 1.0
                    friction = COST_POINTS / close
                    direction = 1.0 if float(window[index][name]) > 0 else -1.0
                    trades.append(direction * forward - friction)
                    holds.append(forward - friction)
                    index += hold
                if len(trades) < 5:
                    continue
                total = held = 1.0
                for value in trades:
                    total *= 1.0 + value
                for value in holds:
                    held *= 1.0 + value
                wins = sum(1 for value in trades if value > 0) / len(trades)
                print(
                    f"{name:<16}{hold:>5}{label:>7}{len(trades):>6}{wins:>8.1%}"
                    f"{total - 1.0:>10.1%}{held - 1.0:>10.1%}{total - held:>+10.1%}"
                )
    print(
        "\n差額為正才代表訊號有貢獻。相關係數為正 = 法人偏多時後續上漲,\n"
        "為負 = 法人偏多時後續下跌(反指標)。"
    )
    return 0


if __name__ == "__main__":
    base = Path("data/daily")
    raise SystemExit(report(
        Path(sys.argv[1]) if len(sys.argv) > 1 else base / "mtx-daily.ndjson",
        Path(sys.argv[2]) if len(sys.argv) > 2 else base / "institutional.ndjson",
    ))
