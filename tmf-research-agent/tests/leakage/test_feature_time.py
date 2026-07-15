from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tmf_research.features.definitions import FeatureRow


NOW = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


class FeatureTimeLeakageTests(unittest.TestCase):
    def test_rejects_evidence_after_decision_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence_available_at"):
            FeatureRow(
                feature_time=NOW,
                decision_time=NOW,
                evidence_available_at=NOW + timedelta(microseconds=1),
                feature_version="v1",
                values={"return_1m": 0.1},
                missing_indicators={},
            )


if __name__ == "__main__":
    unittest.main()
