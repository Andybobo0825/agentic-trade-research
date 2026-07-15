from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalibrationRow:
    lower: float
    upper: float
    count: int
    mean_probability: float | None
    observed_rate: float | None
    average_net_pnl: float | None
    sufficient: bool


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    log_loss: float
    brier_score: float
    roc_auc: float | None
    precision: float
    recall: float
    f1: float
    confusion_matrix: tuple[tuple[int, int], tuple[int, int]]
    expected_calibration_error: float
    calibration_table: tuple[CalibrationRow, ...]


@dataclass(frozen=True, slots=True)
class TradeResult:
    direction: str
    net_points: float
    gross_points: float
    holding_minutes: float
    trading_date: str

    def __post_init__(self) -> None:
        if self.direction not in ("LONG", "SHORT"):
            raise ValueError("trade direction must be LONG or SHORT")
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
            for value in (self.net_points, self.gross_points, self.holding_minutes)
        ):
            raise ValueError("trade values must be finite")
        if self.holding_minutes < 0 or not self.trading_date.strip():
            raise ValueError("invalid trade holding period/date")


@dataclass(frozen=True, slots=True)
class TradingMetrics:
    trade_count: int
    long_count: int
    short_count: int
    win_rate: float
    average_win: float
    average_loss: float
    average_net_points: float
    gross_pnl: float
    net_pnl: float
    profit_factor: float
    maximum_drawdown: float
    longest_losing_streak: int
    expected_value_per_trade: float
    expected_value_per_day: float
    average_holding_time: float
    exposure_ratio: float
    turnover: float
    trade_frequency: float


def classification_metrics(
    outcomes: Sequence[int],
    probabilities: Sequence[float],
    *,
    net_returns: Sequence[float] | None = None,
    threshold: float = 0.5,
    bin_count: int = 10,
    minimum_bin_size: int = 20,
) -> ClassificationMetrics:
    if (
        not outcomes or len(outcomes) != len(probabilities)
        or any(isinstance(value, bool) or value not in (0, 1) for value in outcomes)
        or not 0.0 <= threshold <= 1.0 or bin_count <= 0 or minimum_bin_size <= 0
    ):
        raise ValueError("paired binary classification evidence is required")
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in probabilities):
        raise ValueError("probabilities must be finite and bounded")
    returns = tuple(0.0 for _ in outcomes) if net_returns is None else tuple(net_returns)
    if len(returns) != len(outcomes) or any(not math.isfinite(value) for value in returns):
        raise ValueError("paired finite net returns are required")
    epsilon = 1e-15
    log_loss = -sum(
        outcome * math.log(max(epsilon, probability))
        + (1 - outcome) * math.log(max(epsilon, 1.0 - probability))
        for outcome, probability in zip(outcomes, probabilities, strict=True)
    ) / len(outcomes)
    brier = sum((probability - outcome) ** 2 for outcome, probability in zip(outcomes, probabilities, strict=True)) / len(outcomes)
    predictions = tuple(int(probability >= threshold) for probability in probabilities)
    tp = sum(outcome == 1 and prediction == 1 for outcome, prediction in zip(outcomes, predictions, strict=True))
    tn = sum(outcome == 0 and prediction == 0 for outcome, prediction in zip(outcomes, predictions, strict=True))
    fp = sum(outcome == 0 and prediction == 1 for outcome, prediction in zip(outcomes, predictions, strict=True))
    fn = sum(outcome == 1 and prediction == 0 for outcome, prediction in zip(outcomes, predictions, strict=True))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    table: list[CalibrationRow] = []
    ece = 0.0
    for index in range(bin_count):
        lower, upper = index / bin_count, (index + 1) / bin_count
        members = tuple(
            item
            for item in zip(outcomes, probabilities, returns, strict=True)
            if lower <= item[1] <= upper and (index == bin_count - 1 or item[1] < upper)
        )
        if not members:
            table.append(CalibrationRow(lower, upper, 0, None, None, None, False))
            continue
        mean_probability = sum(item[1] for item in members) / len(members)
        observed = sum(item[0] for item in members) / len(members)
        mean_net = sum(item[2] for item in members) / len(members)
        ece += len(members) / len(outcomes) * abs(mean_probability - observed)
        table.append(CalibrationRow(lower, upper, len(members), mean_probability, observed, mean_net, len(members) >= minimum_bin_size))
    return ClassificationMetrics(
        log_loss,
        brier,
        _roc_auc(outcomes, probabilities),
        precision,
        recall,
        f1,
        ((tn, fp), (fn, tp)),
        ece,
        tuple(table),
    )


def trading_metrics(
    trades: Sequence[TradeResult],
    *,
    candidate_count: int,
    total_available_minutes: float,
) -> TradingMetrics:
    if (
        isinstance(candidate_count, bool) or candidate_count <= 0
        or isinstance(total_available_minutes, bool) or total_available_minutes <= 0
        or not math.isfinite(total_available_minutes)
    ):
        raise ValueError("positive candidate/time exposure denominator is required")
    count = len(trades)
    long_count = sum(trade.direction == "LONG" for trade in trades)
    short_count = count - long_count
    wins = tuple(trade.net_points for trade in trades if trade.net_points > 0)
    losses = tuple(trade.net_points for trade in trades if trade.net_points < 0)
    gross_pnl = sum(trade.gross_points for trade in trades)
    net_pnl = sum(trade.net_points for trade in trades)
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    profit_factor = gross_profit / max(gross_loss, 1e-12) if gross_profit > 0 else 0.0
    peak = 0.0
    equity = 0.0
    maximum_drawdown = 0.0
    losing_streak = 0
    longest = 0
    for trade in trades:
        equity += trade.net_points
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
        losing_streak = losing_streak + 1 if trade.net_points < 0 else 0
        longest = max(longest, losing_streak)
    days = len({trade.trading_date for trade in trades})
    holding = sum(trade.holding_minutes for trade in trades)
    return TradingMetrics(
        count,
        long_count,
        short_count,
        len(wins) / count if count else 0.0,
        sum(wins) / len(wins) if wins else 0.0,
        sum(losses) / len(losses) if losses else 0.0,
        net_pnl / count if count else 0.0,
        gross_pnl,
        net_pnl,
        profit_factor,
        maximum_drawdown,
        longest,
        net_pnl / count if count else 0.0,
        net_pnl / days if days else 0.0,
        holding / count if count else 0.0,
        min(1.0, holding / total_available_minutes),
        count / max(1, days),
        count / candidate_count,
    )


def _roc_auc(outcomes: Sequence[int], probabilities: Sequence[float]) -> float | None:
    positives = tuple(index for index, value in enumerate(outcomes) if value == 1)
    negatives = tuple(index for index, value in enumerate(outcomes) if value == 0)
    if not positives or not negatives:
        return None
    score = 0.0
    for positive in positives:
        for negative in negatives:
            if probabilities[positive] > probabilities[negative]:
                score += 1.0
            elif probabilities[positive] == probabilities[negative]:
                score += 0.5
    return score / (len(positives) * len(negatives))
