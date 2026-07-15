from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import unittest

from tmf_research.validation.purging import purge_outcomes, validate_embargo


@dataclass(frozen=True)
class Row:
    decision_time: datetime
    outcome_time: datetime


class PurgeEmbargoTests(unittest.TestCase):
    def test_purge_excludes_outcome_equal_to_boundary(self) -> None:
        boundary = datetime(2026, 1, 2, tzinfo=UTC)
        rows = (
            Row(boundary - timedelta(hours=3), boundary - timedelta(seconds=1)),
            Row(boundary - timedelta(hours=2), boundary),
            Row(boundary - timedelta(hours=1), boundary + timedelta(seconds=1)),
        )
        self.assertEqual(purge_outcomes(rows, boundary), rows[:1])

    def test_59_minutes_fails_60_minute_horizon(self) -> None:
        with self.assertRaises(ValueError):
            validate_embargo(59, (5, 15, 60))
        self.assertEqual(validate_embargo(60, (5, 15, 60)), timedelta(minutes=60))


if __name__ == "__main__":
    unittest.main()
