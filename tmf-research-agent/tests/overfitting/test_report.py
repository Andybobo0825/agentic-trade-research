from __future__ import annotations

import unittest

from tmf_research.validation.metrics import TradeResult, classification_metrics, trading_metrics
from tmf_research.validation.overfitting import generalization_gap
from tmf_research.validation.report import FoldReport, build_phase5_report
from tests.overfitting.test_model_selection import dimensions, fold, gates
from tmf_research.validation.overfitting import decide_model_status


CLASSIFICATION: dict[str, object] = {
    "log_loss": 0.5, "brier_score": 0.2, "roc_auc": 0.6,
    "precision": 0.5, "recall": 0.5, "f1": 0.5,
    "confusion_matrix": ((1, 1), (1, 1)),
    "expected_calibration_error": 0.1, "calibration_table": (),
}
TRADING: dict[str, object] = {
    "trade_count": 30.0, "long_count": 15.0, "short_count": 15.0,
    "win_rate": 0.5, "average_win": 1.0, "average_loss": -1.0,
    "average_net_points": 0.1, "gross_pnl": 5.0, "net_pnl": 3.0,
    "profit_factor": 1.2, "maximum_drawdown": 2.0,
    "longest_losing_streak": 3.0, "expected_value_per_trade": 0.1,
    "expected_value_per_day": 0.3, "average_holding_time": 5.0,
    "exposure_ratio": 0.1, "turnover": 3.0,
}


class ReportTests(unittest.TestCase):
    def test_classification_and_trading_metrics_are_complete(self) -> None:
        classification = classification_metrics((0, 0, 1, 1), (0.1, 0.4, 0.6, 0.9), minimum_bin_size=1)
        self.assertEqual(classification.confusion_matrix, ((2, 0), (0, 2)))
        trades = (
            TradeResult("LONG", 2.0, 2.5, 5.0, "2026-01-01"),
            TradeResult("SHORT", -1.0, -0.5, 7.0, "2026-01-01"),
        )
        trading = trading_metrics(trades, candidate_count=100, total_available_minutes=1000)
        self.assertEqual((trading.trade_count, trading.long_count, trading.short_count), (2, 1, 1))
        self.assertEqual(trading.net_pnl, 1.0)

    def test_report_shows_each_fold_all_summaries_gaps_and_regions(self) -> None:
        evidence = tuple(fold(index) for index in range(5))
        decision = decide_model_status(evidence, dimensions(), gates(), data_provenance="REAL_READONLY_MARKET_DATA")
        fold_reports = tuple(
            FoldReport(
                item.fold_id,
                {"TRAIN": "a", "INNER_VALIDATION": "b", "OUTER_TEST": "c", "LOCKED_HOLDOUT": "d"},
                {**CLASSIFICATION, "log_loss": 0.5 + index * 0.01},
                TRADING,
                {
                    "positive_fold_ratio": 1.0, "baseline_outperformance_ratio": 1.0,
                    "coefficient_sign_stability": 1.0, "feature_rank_stability": 1.0,
                    "parameter_sensitivity": 1.0, "monthly_contribution_concentration": 0.1,
                    "directional_contribution_concentration": 0.5,
                    "fold_profit_concentration": 0.2, "train_test_gap": 0.05,
                },
            )
            for index, item in enumerate(evidence)
        )
        report = build_phase5_report(fold_reports, tuple(generalization_gap(item) for item in evidence), dimensions(), decision)
        summary = report.summaries["log_loss"]
        self.assertEqual(len(summary.all_values), 5)
        self.assertLessEqual(summary.best, summary.worst)
        self.assertGreaterEqual(summary.standard_deviation, 0.0)
        self.assertGreaterEqual(summary.interquartile_range, 0.0)


if __name__ == "__main__":
    unittest.main()
