"""Rank-correlate each feature against the move it is supposed to anticipate.

The cheapest question worth asking of a new feature group: before folds,
models, or a locked holdout, does the number move with what happens next at
all? A group whose information coefficient sits at zero across every session
will not become predictive downstream, and finding that out costs one pass
over a sample cache rather than months of collection.

Reads a cache written by `tmf phase5-status --sample-cache`, which is produced
even when the build is rejected for having too few trading days.
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


def ranks(values: tuple[float, ...]) -> tuple[float, ...]:
    """Average ranks, so ties do not manufacture an ordering that isn't there."""

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
    if len(xs) != len(ys):
        raise ValueError("paired series must be the same length")
    if len(xs) < 3:
        return None
    rank_x, rank_y = ranks(xs), ranks(ys)
    mean_x = sum(rank_x) / len(rank_x)
    mean_y = sum(rank_y) / len(rank_y)
    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(rank_x, rank_y))
    spread_x = math.sqrt(sum((a - mean_x) ** 2 for a in rank_x))
    spread_y = math.sqrt(sum((b - mean_y) ** 2 for b in rank_y))
    if spread_x == 0.0 or spread_y == 0.0:
        return None
    return covariance / (spread_x * spread_y)


def _load(path: Path) -> list[dict[str, object]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def report(path: Path) -> int:
    rows = [row for row in _load(path) if "sample" in row]
    if not rows:
        print("樣本快取是空的")
        return 1

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped["全部"].append(row)
        grouped[str(row["sample"]["trading_date"])].append(row)

    names = sorted(rows[0]["sample"]["source"]["features"])
    print(f"樣本 {len(rows)}   目標: long_gross_points（做多方向的實際點數）\n")
    header = f"{'特徵':<30}" + "".join(f"{key:>14}" for key in sorted(grouped))
    print(header)
    print("-" * len(header))
    for name in names:
        cells = []
        for key in sorted(grouped):
            pairs = [
                (row["sample"]["source"]["features"][name], row["outcome"]["long_gross_points"])
                for row in grouped[key]
                if row["sample"]["source"]["features"][name] is not None
                and row["outcome"]["long_gross_points"] is not None
            ]
            if len(pairs) < 3:
                cells.append(f"{'—':>14}")
                continue
            value = spearman(*(tuple(series) for series in zip(*pairs)))
            cells.append(f"{'—':>14}" if value is None else f"{value:>+14.4f}")
        print(f"{name:<30}" + "".join(cells))
    print(
        "\nIC 是等級相關係數,範圍 -1 到 1。單一特徵的 |IC| 在 0.03 以上就值得留意,"
        "\n低於 0.01 基本上等於沒有關係。這裡看的是「有沒有關係」,不是「能不能賺錢」。"
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: feature_ic.py <sample-cache.ndjson.gz>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(report(Path(sys.argv[1])))
