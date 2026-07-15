from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from tmf_research.domain.events import BidAskEvent, TickEvent


@dataclass(frozen=True, slots=True)
class QualityReport:
    trading_date: date
    session: Literal["DAY", "NIGHT"]
    tick_count: int
    bidask_count: int
    duplicate_count: int
    out_of_order_count: int
    invalid_price_count: int
    invalid_depth_count: int
    stale_tick_count: int
    stale_bidask_count: int
    simtrade_count: int
    queue_drop_count: int
    connection_drop_count: int
    maximum_gap_seconds: float
    tick_coverage_ratio: float
    bidask_coverage_ratio: float
    quality_status: Literal["VALID", "INVALID"]


class QualityReportBuilder:
    """Produces complete per-trading-date/session collection evidence."""

    def build(
        self,
        *,
        trading_date: date,
        session: Literal["DAY", "NIGHT"],
        ticks: tuple[TickEvent, ...],
        bidasks: tuple[BidAskEvent, ...],
        rejection_reasons: tuple[str, ...] = (),
        queue_drop_count: int = 0,
        connection_drop_count: int = 0,
        expected_seconds: int,
    ) -> QualityReport:
        if expected_seconds <= 0:
            raise ValueError("expected_seconds must be positive")
        if queue_drop_count < 0 or connection_drop_count < 0:
            raise ValueError("drop counts cannot be negative")
        reasons = Counter(rejection_reasons)
        tick_coverage = _coverage(
            tuple(event.exchange_datetime for event in ticks),
            expected_seconds,
        )
        bidask_coverage = _coverage(
            tuple(event.exchange_datetime for event in bidasks),
            expected_seconds,
        )
        invalid_count = sum(reasons.values()) + queue_drop_count + connection_drop_count
        status: Literal["VALID", "INVALID"] = (
            "VALID"
            if invalid_count == 0
            and tick_coverage == 1.0
            and bidask_coverage == 1.0
            else "INVALID"
        )
        return QualityReport(
            trading_date=trading_date,
            session=session,
            tick_count=len(ticks),
            bidask_count=len(bidasks),
            duplicate_count=reasons["DUPLICATE"],
            out_of_order_count=reasons["OUT_OF_ORDER"],
            invalid_price_count=reasons["INVALID_PRICE"],
            invalid_depth_count=reasons["INVALID_DEPTH"],
            stale_tick_count=reasons["STALE_TICK"],
            stale_bidask_count=reasons["STALE_BIDASK"],
            simtrade_count=reasons["SIMTRADE"],
            queue_drop_count=queue_drop_count,
            connection_drop_count=connection_drop_count,
            maximum_gap_seconds=max(
                _maximum_gap(tuple(event.exchange_datetime for event in ticks)),
                _maximum_gap(tuple(event.exchange_datetime for event in bidasks)),
            ),
            tick_coverage_ratio=tick_coverage,
            bidask_coverage_ratio=bidask_coverage,
            quality_status=status,
        )


def _coverage(values: tuple[datetime, ...], expected_seconds: int) -> float:
    seconds = {value.replace(microsecond=0) for value in values}
    return min(1.0, len(seconds) / expected_seconds)


def _maximum_gap(values: tuple[datetime, ...]) -> float:
    ordered = sorted(set(values))
    return max(
        (
            (current - previous).total_seconds()
            for previous, current in zip(ordered, ordered[1:], strict=False)
        ),
        default=0.0,
    )
