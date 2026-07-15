from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tmf_research.domain.events import BidAskEvent, TickEvent
from tmf_research.domain.sessions import TradingCalendar, TradingDay
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore
from tmf_research.processing.pipeline import ProcessingPipeline
from tmf_research.processing.quote_joiner import QuoteJoiner
from tmf_research.processing.session_resolver import SessionResolver


START = datetime(2026, 7, 20, 8, 45, tzinfo=timezone.utc)


def tick() -> TickEvent:
    occurred_at = START + timedelta(milliseconds=100)
    return TickEvent(
        event_id="tick-1",
        received_at=occurred_at,
        exchange_datetime=occurred_at,
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        code="TMF202607",
        close=100.0,
        volume=1,
        tick_type=1,
        underlying_price=99.0,
        simtrade=False,
        raw_payload={"source": "fixture"},
    )


def quote() -> BidAskEvent:
    return BidAskEvent(
        event_id="quote-1",
        received_at=START,
        exchange_datetime=START,
        alias_code="TMFR1",
        target_code="TMF202607",
        delivery_month="202607",
        code="TMF202607",
        bid_prices=(99.0,),
        bid_volumes=(1,),
        ask_prices=(101.0,),
        ask_volumes=(1,),
        simtrade=False,
        raw_payload={"source": "fixture"},
    )


class ProcessingPipelineTests(unittest.TestCase):
    def test_pipeline_is_deterministic_and_preserves_raw_segments(self) -> None:
        calendar = TradingCalendar(
            version="fixture-v1",
            timezone="UTC",
            days=(
                TradingDay(
                    trading_date=date(2026, 7, 20),
                    day_close=time(13, 45),
                    night_open=None,
                    night_close=None,
                ),
            ),
        )
        resolver = SessionResolver(calendar)
        resolution = resolver.resolve(START)
        pipeline = ProcessingPipeline(
            quote_joiner=QuoteJoiner(max_quote_age=timedelta(seconds=2)),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = AppendOnlyRawStore(root, writer_version="test-v1")
            tick_manifest = store.append_segment(
                "tick",
                (tick(),),
                segment_id="ticks",
                created_at=START,
            )
            quote_manifest = store.append_segment(
                "bidask",
                (quote(),),
                segment_id="quotes",
                created_at=START,
            )
            before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

            first = pipeline.process(
                ticks=(tick(),),
                bidasks=(quote(),),
                resolution=resolution,
                start_second=START,
                end_second=START + timedelta(seconds=59),
                source_manifests=(tick_manifest, quote_manifest),
                intervals=(1, 5, 15, 60),
            )
            second = pipeline.process(
                ticks=(tick(),),
                bidasks=(quote(),),
                resolution=resolution,
                start_second=START,
                end_second=START + timedelta(seconds=59),
                source_manifests=(tick_manifest, quote_manifest),
                intervals=(1, 5, 15, 60),
            )
            after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

        self.assertEqual(first, second)
        self.assertEqual(before, after)
        self.assertEqual(first.source_manifests, (tick_manifest, quote_manifest))
        self.assertEqual(len(first.states), 60)
        self.assertEqual(first.bar_sets[0].bars[0].bar_start, START)
        self.assertTrue(first.bar_sets[0].bars[0].is_complete)
        self.assertEqual(first.quality_report.tick_count, 1)


if __name__ == "__main__":
    unittest.main()
