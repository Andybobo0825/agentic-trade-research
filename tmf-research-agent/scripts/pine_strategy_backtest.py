"""Backtest the Pine strategy rules, not just the signals' expectancy.

The signal report prices every signal independently and lets them overlap.
The Pine strategy holds one position at a time, so a signal arriving while
a trade is open is skipped and never becomes a trade. That difference
changes the trade count, the win rate and the drawdown, which is why the
TradingView tester can never reproduce the report — this reproduces the
tester instead, over two years instead of four months.

Reads the events dumped by pine_control_dump.py. Positions never cross a
session, matching both the Pine clock-time exit and the dump's own
session-clipped deltas.

Usage:
  pine_strategy_backtest.py <events.ndjson>... [--tf 15] [--signal rejection]
      [--variant orig] [--direction -1] [--hold 240] [--cost 3.0]
      [--point-value 50]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HOLD_KEY = {15: "15", 60: "60", 240: "240"}


def load(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def simulate_combo(rows: list[dict], specs: list[tuple[int, str, str, int]], *,
                   hold_minutes: int, cost: float) -> list[dict]:
    """Several signals sharing one position slot, as the Pine strategy does.

    Enabling two signals is not the same as running two strategies: whichever
    fires first occupies the slot and the other is skipped, so the combined
    result is not the sum of the parts.
    """
    horizon = HOLD_KEY.get(hold_minutes, "sclose")
    wanted = {(tf, sig, var, direction) for tf, sig, var, direction in specs}
    candidates = [
        row for row in rows
        if row["kind"] == "signal" and horizon in row["deltas"]
        and (row["timeframe"], row["signal"], row["variant"],
             row["direction"]) in wanted
    ]
    candidates.sort(key=lambda row: row["when"])
    trades: list[dict] = []
    blocked_until: dict[tuple[str, str], datetime] = {}
    for row in candidates:
        key = (row["trading_date"], row["session"])
        when = datetime.fromisoformat(row["when"])
        if key in blocked_until and when < blocked_until[key]:
            continue
        blocked_until[key] = when + timedelta(minutes=hold_minutes)
        trades.append({
            "when": when, "period": row["period"], "session": row["session"],
            "trading_date": row["trading_date"], "signal": row["signal"],
            "net": row["direction"] * row["deltas"][horizon] - cost,
        })
    return trades


def simulate(rows: list[dict], *, timeframe: int, signal: str, variant: str,
             direction: int, hold_minutes: int, cost: float,
             ) -> list[dict]:
    """Walk signals in time order, one position at a time."""
    horizon = HOLD_KEY.get(hold_minutes, "sclose")
    candidates = [
        row for row in rows
        if row["kind"] == "signal" and row["timeframe"] == timeframe
        and row["signal"] == signal and row["variant"] == variant
        and row["direction"] == direction and horizon in row["deltas"]
    ]
    candidates.sort(key=lambda row: row["when"])
    trades: list[dict] = []
    # A position closes at the session end at the latest, so a block only
    # applies inside the session that opened it.
    blocked_until: dict[tuple[str, str], datetime] = {}
    for row in candidates:
        key = (row["trading_date"], row["session"])
        when = datetime.fromisoformat(row["when"])
        if key in blocked_until and when < blocked_until[key]:
            continue
        blocked_until[key] = when + timedelta(minutes=hold_minutes)
        trades.append({
            "when": when, "period": row["period"], "session": row["session"],
            "trading_date": row["trading_date"],
            "net": direction * row["deltas"][horizon] - cost,
        })
    return trades


def metrics(trades: list[dict]) -> dict[str, float]:
    if not trades:
        return {}
    nets = [trade["net"] for trade in trades]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value <= 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in nets:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": len(nets),
        "net": sum(nets),
        "mean": sum(nets) / len(nets),
        "win_rate": len(wins) / len(nets),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        "max_drawdown": max_drawdown,
        "best": max(nets),
        "worst": min(nets),
    }


def report(name: str, trades: list[dict], point_value: float) -> None:
    print(f"\n{'=' * 70}\n{name}")
    if not trades:
        print("  沒有任何交易")
        return
    by_period: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        by_period[trade["period"]].append(trade)
    header = (f"  {'期間':<8}{'交易':>6}{'淨點數':>11}{'每筆':>9}"
              f"{'勝率':>8}{'獲利因子':>10}{'最大回撤':>11}")
    print(header)
    for period in sorted(by_period):
        stats = metrics(by_period[period])
        print(f"  {period:<8}{stats['trades']:>6}{stats['net']:>+11.0f}"
              f"{stats['mean']:>+9.2f}{stats['win_rate']:>8.0%}"
              f"{stats['profit_factor']:>10.2f}{stats['max_drawdown']:>11.0f}")
    total = metrics(trades)
    print(f"  {'合計':<8}{total['trades']:>6}{total['net']:>+11.0f}"
          f"{total['mean']:>+9.2f}{total['win_rate']:>8.0%}"
          f"{total['profit_factor']:>10.2f}{total['max_drawdown']:>11.0f}")
    print(f"  換算金額（每點 {point_value:.0f} 元）："
          f"淨損益 {total['net'] * point_value:+,.0f} 元｜"
          f"最大回撤 {total['max_drawdown'] * point_value:,.0f} 元｜"
          f"單筆最好 {total['best']:+.0f} 點／最差 {total['worst']:+.0f} 點")


def main(argv: list[str]) -> int:
    paths: list[Path] = []
    flags: dict[str, str] = {}
    index = 0
    while index < len(argv):
        if argv[index].startswith("--"):
            flags[argv[index][2:]] = argv[index + 1]
            index += 2
        else:
            paths.append(Path(argv[index]))
            index += 1
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    rows = load(paths)
    cost = float(flags.get("cost", 3.0))
    point_value = float(flags.get("point-value", 50.0))
    hold = int(flags.get("hold", 240))

    if "combo" in flags:
        # e.g. --combo 15:breakdown:orig:-1,15:breakout:orig:1
        specs = []
        for part in flags["combo"].split(","):
            tf, signal, variant, direction = part.split(":")
            specs.append((int(tf), signal, variant, int(direction)))
        trades = simulate_combo(rows, specs, hold_minutes=hold, cost=cost)
        print(f"載入 {len(rows):,} 列事件｜持有 {hold} 分鐘｜成本 {cost} 點／筆")
        report(f"組合：{flags['combo']}", trades, point_value)
        by_month: dict[str, list[dict]] = defaultdict(list)
        for trade in trades:
            by_month[trade["trading_date"][:7]].append(trade)
        print(f"\n  月別分布（看獲利是分散還是集中在單一個月）")
        print(f"  {'月份':<10}{'交易':>6}{'淨點數':>11}{'累計':>11}")
        cumulative = 0.0
        for month in sorted(by_month):
            stats = metrics(by_month[month])
            cumulative += stats["net"]
            print(f"  {month:<10}{stats['trades']:>6}{stats['net']:>+11.0f}"
                  f"{cumulative:>+11.0f}")
        return 0

    if "signal" in flags:
        configs = [(int(flags.get("tf", 15)), flags["signal"],
                    flags.get("variant", "orig"), int(flags.get("direction", -1)))]
    else:
        # The shipped Pine default first, then the signals it leaves off, so
        # the cost of enabling each one is visible rather than assumed.
        configs = [
            (15, "rejection", "orig", -1),
            (15, "breakdown", "orig", -1),
            (15, "breakout", "orig", 1),
            (15, "bounce", "orig", 1),
            (5, "rejection", "orig", -1),
            (60, "rejection", "orig", -1),
        ]
    print(f"載入 {len(rows):,} 列事件｜持有 {hold} 分鐘｜成本 {cost} 點／筆")
    for timeframe, signal, variant, direction in configs:
        side = "做空" if direction < 0 else "做多"
        trades = simulate(rows, timeframe=timeframe, signal=signal,
                          variant=variant, direction=direction,
                          hold_minutes=hold, cost=cost)
        report(f"{timeframe} 分K {signal} {variant} {side}", trades, point_value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
