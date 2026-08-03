from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tmf_research.features.context_builder import ResearchBuildSpec


def _calendar(root: Path) -> Path:
    path = root / "calendar.json"
    path.write_text(json.dumps({
        "version": "calendar-v1",
        "timezone": "UTC",
        "days": [{
            "trading_date": "2026-01-01",
            "day_open": "08:45",
            "day_close": "13:45",
        }],
    }), encoding="utf-8")
    return path


class BarrierWidthSpecTests(unittest.TestCase):
    """Barrier width decides what the model is asked to predict.

    A two-year sweep showed the shipped 1.0x ATR barriers leave 1% of
    candidates untouched and split long/short within 2% every quarter — the
    target is settled by path noise. Widening it is a different research
    question, so datasets built either way must never be mistaken for each
    other.
    """

    def test_width_changes_the_build_spec_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calendar = _calendar(Path(directory))
            narrow = ResearchBuildSpec(calendar=calendar)
            wide = ResearchBuildSpec(calendar=calendar, barrier_atr_multiplier=4.0)

            self.assertEqual(narrow.barrier_atr_multiplier, 1.0, "default must not move")
            self.assertNotEqual(narrow.content_hash, wide.content_hash)
            self.assertEqual(
                wide.content_hash,
                ResearchBuildSpec(calendar=calendar, barrier_atr_multiplier=4.0).content_hash,
            )

    def test_rejects_a_width_that_cannot_describe_a_barrier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calendar = _calendar(Path(directory))
            for invalid in (0.0, -1.0, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    ResearchBuildSpec(calendar=calendar, barrier_atr_multiplier=invalid)


if __name__ == "__main__":
    unittest.main()
