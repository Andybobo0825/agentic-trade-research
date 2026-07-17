from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from tmf_research.runtime.live_research import RuntimeObservation
from tmf_research.runtime.feature_state import RuntimeFeatureVector
from tmf_research.domain.paper_trades import PaperQuote

from tests.phase6_test_support import (
    feature_vector,
    healthy,
    observation,
    runner_for,
    test_only_runtime,
)
from tests.replay.replay_support import entering_return


Scenario = tuple[tuple[RuntimeFeatureVector, RuntimeObservation], ...]


def run_scenario(
    root: Path,
    scenario: Scenario,
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], tuple[str, ...]]:
    runtime, checksum = test_only_runtime(root)
    runner = runner_for(runtime, checksum)
    outcomes = tuple(
        (record.signal, record.reasons)
        for record in (
            runner.process_bar(vector, observed)
            for vector, observed in scenario
        )
    )
    exits = tuple(row.exit_reason for row in runner.broker.ledger.rows)
    return outcomes, exits


def fault_scenario() -> Scenario:
    return (
        (
            feature_vector(1),
            observation(1, health=replace(healthy(), connection_ok=False)),
        ),
        (
            feature_vector(2),
            observation(2, health=replace(healthy(), data_quality_valid=False)),
        ),
        (
            feature_vector(3),
            observation(3, health=replace(healthy(), tick_age_ms=60_000)),
        ),
        (
            feature_vector(4),
            observation(4, health=replace(healthy(), rollover_in_progress=True)),
        ),
        (
            feature_vector(5),
            observation(5, quote=None, health=replace(healthy(), bidask_age_ms=60_000)),
        ),
    )


class FaultEquivalenceTests(unittest.TestCase):
    def test_faults_reproduce_identical_no_trade_outcomes_across_runs(self) -> None:
        with TemporaryDirectory() as first_root, TemporaryDirectory() as second_root:
            live = run_scenario(Path(first_root), fault_scenario())
            replayed = run_scenario(Path(second_root), fault_scenario())

        self.assertEqual(live, replayed)
        outcomes, exits = live
        self.assertEqual(exits, ())
        self.assertEqual(
            tuple(reasons for _signal, reasons in outcomes),
            (
                ("CONNECTION_INVALID",),
                ("DATA_QUALITY_INVALID",),
                ("TICK_STALE",),
                ("ROLLOVER_UNCONFIRMED",),
                ("BIDASK_STALE",),
            ),
        )
        for signal, _reasons in outcomes:
            self.assertEqual(signal, "NO_TRADE")

    def test_position_faults_force_identical_exits_across_runs(self) -> None:
        with TemporaryDirectory() as probe_root:
            probe_runtime, probe_checksum = test_only_runtime(Path(probe_root))
            probe_runner = runner_for(probe_runtime, probe_checksum)
            entry_value = entering_return(probe_runner)
        if entry_value is None:
            self.skipTest("fixture model declines every entry; exit faults not reachable")

        def exit_scenario(fault_minute_quote: PaperQuote | None) -> Scenario:
            return (
                (feature_vector(1, return_1m=entry_value), observation(1)),
                (feature_vector(2), observation(2, quote=fault_minute_quote)),
            )

        with TemporaryDirectory() as first_root, TemporaryDirectory() as second_root:
            live = run_scenario(Path(first_root), exit_scenario(None))
            replayed = run_scenario(Path(second_root), exit_scenario(None))

        self.assertEqual(live, replayed)
        _outcomes, exits = live
        self.assertEqual(exits, ("DATA_STALE",))


if __name__ == "__main__":
    unittest.main()
