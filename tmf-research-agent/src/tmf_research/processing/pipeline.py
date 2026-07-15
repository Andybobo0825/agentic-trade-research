from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from tmf_research.domain.events import BidAskEvent, TickEvent
from tmf_research.domain.sessions import SessionResolution
from tmf_research.infrastructure.raw_store import SegmentManifest
from tmf_research.processing.bars import Bar, BarAggregator
from tmf_research.processing.one_second import OneSecondAggregator, OneSecondState
from tmf_research.processing.quality_report import QualityReport, QualityReportBuilder
from tmf_research.processing.quote_joiner import QuoteJoinResult, QuoteJoiner


@dataclass(frozen=True, slots=True)
class BarSet:
    interval_minutes: int
    bars: tuple[Bar, ...]


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    source_manifests: tuple[SegmentManifest, ...]
    quote_joins: tuple[QuoteJoinResult, ...]
    states: tuple[OneSecondState, ...]
    bar_sets: tuple[BarSet, ...]
    quality_report: QualityReport


class ProcessingPipeline:
    """Deterministically derives Phase 2 values without mutating raw evidence."""

    def __init__(self, *, quote_joiner: QuoteJoiner) -> None:
        self._quote_joiner = quote_joiner

    def process(
        self,
        *,
        ticks: tuple[TickEvent, ...],
        bidasks: tuple[BidAskEvent, ...],
        resolution: SessionResolution,
        start_second: datetime,
        end_second: datetime,
        source_manifests: tuple[SegmentManifest, ...],
        intervals: tuple[int, ...] = (1, 5, 15, 60),
    ) -> ProcessingResult:
        if (
            resolution.session not in ("DAY", "NIGHT")
            or resolution.trading_date is None
            or resolution.session_start is None
        ):
            raise ValueError("processing requires an open resolved session")
        if end_second < start_second:
            raise ValueError("end_second cannot precede start_second")
        quote_joins = tuple(
            self._quote_joiner.join(tick, bidasks)
            for tick in sorted(
                ticks,
                key=lambda event: (event.exchange_datetime, event.event_id),
            )
        )
        aggregator = OneSecondAggregator()
        states: list[OneSecondState] = []
        previous: OneSecondState | None = None
        second = start_second
        while second <= end_second:
            next_second = second + timedelta(seconds=1)
            second_ticks = tuple(
                event
                for event in ticks
                if second <= event.exchange_datetime < next_second
            )
            second_quotes = tuple(
                event
                for event in bidasks
                if second <= event.exchange_datetime < next_second
            )
            previous = aggregator.aggregate(
                second,
                second_ticks,
                second_quotes,
                previous=previous,
            )
            states.append(previous)
            second = next_second
        frozen_states = tuple(states)
        bar_sets = tuple(
            BarSet(
                interval_minutes=interval,
                bars=BarAggregator(interval_minutes=interval).aggregate(
                    frozen_states,
                    session_start=resolution.session_start,
                ),
            )
            for interval in intervals
        )
        expected_seconds = len(frozen_states)
        quality = QualityReportBuilder().build(
            trading_date=resolution.trading_date,
            session=resolution.session,
            ticks=ticks,
            bidasks=bidasks,
            expected_seconds=expected_seconds,
        )
        return ProcessingResult(
            source_manifests=tuple(source_manifests),
            quote_joins=quote_joins,
            states=frozen_states,
            bar_sets=bar_sets,
            quality_report=quality,
        )
