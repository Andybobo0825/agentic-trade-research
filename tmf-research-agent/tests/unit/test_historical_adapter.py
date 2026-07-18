from __future__ import annotations

import unittest
from collections.abc import Mapping
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from tmf_research.processing.historical_adapter import (
    HISTORICAL_QUOTE_SOURCE,
    HistoricalAdapterError,
    decode_historical_day,
)
from tmf_research.processing.raw_decoder import validate_research_event


TAIPEI = ZoneInfo("Asia/Taipei")
DAY = "2026-07-16"
FETCHED = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc).isoformat()


def record(
    index: int,
    time_iso: str,
    *,
    close: float = 46700.0,
    bid: float = 46699.0,
    bid_volume: int = 5,
    ask: float = 46701.0,
    ask_volume: int = 7,
    volume: int = 2,
) -> dict[str, object]:
    return {
        "schema_version": "1.1.0",
        "event_id": f"hist-tick-TMFR1-{DAY}-{index:06d}",
        "exchange_datetime": time_iso,
        "received_at": FETCHED,
        "source": "SHIOAJI_HISTORICAL_TICKS_CONTINUOUS_NEAR",
        "alias_code": "TMFR1",
        "derived_target_code": "TMF202608",
        "derived_delivery_date": "2026-08-19",
        "target_derivation": "taifex-third-wednesday-v1",
        "fields": {
            "close": close,
            "volume": volume,
            "bid_price": bid,
            "bid_volume": bid_volume,
            "ask_price": ask,
            "ask_volume": ask_volume,
            "tick_type": 1,
        },
    }


NIGHT_TIME = "2026-07-15T15:00:00.019000+08:00"
DAY_TIME = "2026-07-16T09:01:00.500000+08:00"


class HistoricalTickDecodingTests(unittest.TestCase):
    def test_maps_night_and_day_ticks_with_research_valid_semantics(self) -> None:
        ticks, quotes = decode_historical_day(
            DAY, [record(0, NIGHT_TIME), record(1, DAY_TIME)],
        )

        self.assertEqual(len(ticks), 2)
        night, day = ticks
        self.assertEqual(night.session, "NIGHT")
        self.assertEqual(day.session, "DAY")
        for event in ticks:
            self.assertEqual(event.trading_date, DAY)
            self.assertEqual(event.target_code, "TMF202608")
            self.assertEqual(event.code, "TMF202608")
            self.assertEqual(event.delivery_month, "202608")
            self.assertEqual(event.alias_code, "TMFR1")
            self.assertEqual(event.close, 46700.0)
            self.assertEqual(event.volume, 2)
            self.assertFalse(event.simtrade)
            self.assertEqual(validate_research_event(event), ())
        self.assertEqual(
            night.exchange_datetime,
            datetime(2026, 7, 15, 15, 0, 0, 19000, tzinfo=TAIPEI),
        )
        self.assertEqual(len(quotes), 1)

    def test_deterministic_output_for_identical_input(self) -> None:
        rows = [record(0, NIGHT_TIME), record(1, DAY_TIME, bid=46700.0)]

        first = decode_historical_day(DAY, rows)
        second = decode_historical_day(DAY, rows)

        self.assertEqual(first, second)


class DerivedQuoteTests(unittest.TestCase):
    def test_quotes_emit_only_when_l1_changes(self) -> None:
        rows = [
            record(0, NIGHT_TIME),
            record(1, "2026-07-15T15:00:01+08:00"),
            record(2, "2026-07-15T15:00:02+08:00", bid=46700.0),
            record(3, "2026-07-15T15:00:03+08:00", bid=46700.0),
            record(4, "2026-07-15T15:00:04+08:00", ask_volume=9),
        ]

        _ticks, quotes = decode_historical_day(DAY, rows)

        self.assertEqual(len(quotes), 3)
        self.assertEqual(
            [quote.event_id for quote in quotes],
            [
                f"hist-tick-TMFR1-{DAY}-000000-q",
                f"hist-tick-TMFR1-{DAY}-000002-q",
                f"hist-tick-TMFR1-{DAY}-000004-q",
            ],
        )

    def test_quote_carries_source_marker_and_single_level(self) -> None:
        _ticks, quotes = decode_historical_day(DAY, [record(0, NIGHT_TIME)])

        quote = quotes[0]
        self.assertEqual(quote.bid_prices, (46699.0,))
        self.assertEqual(quote.bid_volumes, (5,))
        self.assertEqual(quote.ask_prices, (46701.0,))
        self.assertEqual(quote.ask_volumes, (7,))
        self.assertEqual(quote.raw_payload["source"], HISTORICAL_QUOTE_SOURCE)
        self.assertEqual(quote.trading_date, DAY)
        self.assertEqual(validate_research_event(quote), ())

    def test_quote_time_never_precedes_its_source_tick(self) -> None:
        ticks, quotes = decode_historical_day(
            DAY, [record(0, NIGHT_TIME), record(1, DAY_TIME, bid=46700.0)],
        )

        by_id = {tick.event_id: tick for tick in ticks}
        for quote in quotes:
            source_tick = by_id[quote.event_id.removesuffix("-q")]
            self.assertEqual(quote.exchange_datetime, source_tick.exchange_datetime)
            self.assertEqual(quote.received_at, source_tick.received_at)

    def test_zero_or_crossed_embedded_quotes_derive_nothing(self) -> None:
        rows = [
            record(0, NIGHT_TIME, bid=0.0, bid_volume=0, ask=0.0, ask_volume=0),
            record(1, "2026-07-15T15:00:01+08:00", bid=46702.0, ask=46701.0),
        ]

        _ticks, quotes = decode_historical_day(DAY, rows)

        self.assertEqual(quotes, ())


class FailClosedTests(unittest.TestCase):
    def test_rejects_wrong_source_day_mismatch_and_missing_fields(self) -> None:
        wrong_source = record(0, NIGHT_TIME)
        wrong_source["source"] = "SOMETHING_ELSE"
        with self.assertRaisesRegex(HistoricalAdapterError, "source"):
            decode_historical_day(DAY, [wrong_source])

        wrong_day = record(0, NIGHT_TIME)
        wrong_day["event_id"] = "hist-tick-TMFR1-2026-07-15-000000"
        with self.assertRaisesRegex(HistoricalAdapterError, "day"):
            decode_historical_day(DAY, [wrong_day])

        incomplete = record(0, NIGHT_TIME)
        original = incomplete["fields"]
        assert isinstance(original, dict)
        fields = dict(original)
        del fields["close"]
        incomplete["fields"] = fields
        with self.assertRaisesRegex(HistoricalAdapterError, "close"):
            decode_historical_day(DAY, [incomplete])

    def test_rejects_non_monotonic_times_and_mixed_targets(self) -> None:
        backwards = [record(0, DAY_TIME), record(1, NIGHT_TIME)]
        with self.assertRaisesRegex(HistoricalAdapterError, "order"):
            decode_historical_day(DAY, backwards)

        mixed = [record(0, NIGHT_TIME), record(1, DAY_TIME)]
        mixed[1]["derived_target_code"] = "TMF202609"
        with self.assertRaisesRegex(HistoricalAdapterError, "target"):
            decode_historical_day(DAY, mixed)

    def test_rejects_times_outside_any_session(self) -> None:
        lunchless = record(0, "2026-07-16T07:00:00+08:00")
        with self.assertRaisesRegex(HistoricalAdapterError, "session"):
            decode_historical_day(DAY, [lunchless])


def _mapping_keys(value: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(value)


if __name__ == "__main__":
    unittest.main()
