from __future__ import annotations

from dataclasses import replace
import unittest

from tmf_research.validation.metrics import TradeResult, classification_metrics, trading_metrics
from tmf_research.validation.report import FoldReport, build_phase5_report, summarize
from tests.overfitting.test_model_selection import decision_for
from tests.phase5_test_support import complete_fold_evidence


class ReportTests(unittest.TestCase):
    def test_classification_and_trading_metrics_are_finite_and_complete(self) -> None:
        classification = classification_metrics((0, 0, 1, 1), (0.1, 0.4, 0.6, 0.9), minimum_bin_size=1)
        self.assertEqual(classification.confusion_matrix, ((2, 0), (0, 2)))
        trades = (
            TradeResult("LONG", 2.0, 2.5, 5.0, "2026-01-01"),
            TradeResult("SHORT", -1.0, -0.5, 7.0, "2026-01-01"),
        )
        trading = trading_metrics(trades, candidate_count=100, total_available_minutes=1000)
        self.assertEqual((trading.trade_count, trading.long_count, trading.short_count), (2, 1, 1))
        with self.assertRaises(ValueError):
            classification_metrics((0, 1), (0.2, float("nan")))
        with self.assertRaises(ValueError):
            TradeResult("LONG", float("inf"), 1.0, 1.0, "2026-01-01")

    def test_report_cross_validates_fold_gap_ids_and_builds_every_summary(self) -> None:
        values = complete_fold_evidence()
        decision = decision_for().decision
        report = build_phase5_report(values[1], values[2], values[3], decision)
        self.assertEqual(len(report.folds), 6)
        self.assertIn("log_loss", report.summaries)
        self.assertIn("fold_profit_concentration", report.summaries)
        with self.assertRaisesRegex(ValueError, "identical"):
            build_phase5_report(values[1], (replace(values[2][0], fold_id="wrong"), *values[2][1:]), values[3], decision)

    def test_strings_nan_and_incomplete_report_metrics_are_rejected(self) -> None:
        report = complete_fold_evidence()[1][0]
        bad_classification = dict(report.classification)
        bad_classification["log_loss"] = "0.5"
        with self.assertRaisesRegex(ValueError, "finite"):
            FoldReport(report.fold_id, report.manifest_hash, report.split_regions, bad_classification, report.trading, report.stability)
        bad_stability = dict(report.stability)
        bad_stability["train_test_gap"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            FoldReport(report.fold_id, report.manifest_hash, report.split_regions, report.classification, report.trading, bad_stability)
        with self.assertRaises(ValueError):
            summarize((1.0, float("nan")))
        with self.assertRaises(TypeError):
            report.stability["positive_fold_ratio"] = 0.0  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
