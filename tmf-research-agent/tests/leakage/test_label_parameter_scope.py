from __future__ import annotations

import unittest
from datetime import timedelta

from tmf_research.labeling.executable_prices import ExecutablePricePolicy
from tmf_research.labeling.triple_barrier import TripleBarrierLabeler

from tests.unit.test_executable_prices import state
from tests.unit.test_triple_barrier import NOW, future_bar, parameters


class LabelParameterLeakageTests(unittest.TestCase):
    def test_future_bars_beyond_vertical_horizon_cannot_change_label(self) -> None:
        labeler = TripleBarrierLabeler(
            price_policy=ExecutablePricePolicy(entry_slippage=0.5, exit_slippage=0.5)
        )
        prior = labeler.label(
            candidate_id="candidate",
            decision_time=NOW,
            entry_state=state(),
            future_bars=tuple(
                future_bar(index, high=103.0, low=98.0) for index in range(5)
            ),
            atr=2.0,
            parameters=parameters(),
        )
        mutated = labeler.label(
            candidate_id="candidate",
            decision_time=NOW,
            entry_state=state(),
            future_bars=(
                *(future_bar(index, high=103.0, low=98.0) for index in range(5)),
                future_bar(6, high=999999.0, low=-999999.0),
            ),
            atr=2.0,
            parameters=parameters(),
        )

        self.assertEqual(prior, mutated)
        self.assertLessEqual(prior.evidence_available_at, NOW + timedelta(minutes=5))


if __name__ == "__main__":
    unittest.main()
