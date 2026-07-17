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
        rejection_reasons: tuple[str, ...] = (),
        queue_drop_count: int = 0,
        connection_drop_count: int = 0,
    ) -> ProcessingResult:
        session = resolution.session
        if (
            (session != "DAY" and session != "NIGHT")
            or resolution.trading_date is None
            or resolution.session_start is None
            or resolution.session_end is None
        ):
            raise ValueError("processing requires an open resolved session")
        if end_second < start_second:
            raise ValueError("end_second cannot precede start_second")
        requested_end = end_second + timedelta(seconds=1)
        window_end = min(requested_end, resolution.session_end)
        if start_second < resolution.session_start or start_second >= window_end:
            raise ValueError("processing range is outside the resolved session")
        window_ticks = tuple(
            event
            for event in ticks
            if start_second <= event.exchange_datetime < window_end
        )
        window_bidasks = tuple(
            event
            for event in bidasks
            if start_second <= event.exchange_datetime < window_end
        )
        quote_joins = tuple(
            self._quote_joiner.join(tick, window_bidasks)
            for tick in sorted(
                window_ticks,
                key=lambda event: (event.exchange_datetime, event.event_id),
            )
        )
        aggregator = OneSecondAggregator(
            max_bidask_age=self._quote_joiner.max_quote_age,
        )
        states: list[OneSecondState] = []
        previous: OneSecondState | None = None
        second = start_second
        while second < window_end:
            next_second = second + timedelta(seconds=1)
            second_ticks = tuple(
                event
                for event in window_ticks
                if second <= event.exchange_datetime < next_second
            )
            second_quotes = tuple(
                event
                for event in window_bidasks
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
                    session_end=resolution.session_end,
                ),
            )
            for interval in intervals
        )
        expected_seconds = len(frozen_states)
        quality = QualityReportBuilder().build(
            trading_date=resolution.trading_date,
            session=session,
            ticks=window_ticks,
            bidasks=window_bidasks,
            rejection_reasons=rejection_reasons,
            queue_drop_count=queue_drop_count,
            connection_drop_count=connection_drop_count,
            expected_seconds=expected_seconds,
        )
        return ProcessingResult(
            source_manifests=tuple(source_manifests),
            quote_joins=quote_joins,
            states=frozen_states,
            bar_sets=bar_sets,
            quality_report=quality,
        )
