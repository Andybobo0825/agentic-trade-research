from __future__ import annotations

import unittest
from datetime import timedelta

from tmf_research.models.provenance import InnerTrainDataset, InnerTrainRow
from tmf_research.models.training import InteractionRole, Phase4TrainingSpec, train_phase4_model

from tests.unit.test_phase4_training import END, START, inner_train_dataset, training_spec


class LogisticTests(unittest.TestCase):
    def test_rejects_unknown_labels_and_zero_l2_before_training(self) -> None:
        with self.assertRaisesRegex(ValueError, "label"):
            InnerTrainRow(START + timedelta(days=1), {"x": 0.0}, "UNKNOWN")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "L2"):
            Phase4TrainingSpec(primary_features=("x",), required_features=("x",), l2=0.0)

    def test_rejects_formal_feature_role_budget_overflow(self) -> None:
        with self.assertRaisesRegex(ValueError, "30"):
            Phase4TrainingSpec(
                primary_features=tuple(f"primary_{index}" for index in range(31)),
                required_features=tuple(f"primary_{index}" for index in range(31)),
            )
        with self.assertRaisesRegex(ValueError, "10 missing"):
            Phase4TrainingSpec(
                primary_features=tuple(f"primary_{index}" for index in range(11)),
                required_features=(),
            )
        with self.assertRaisesRegex(ValueError, "5"):
            Phase4TrainingSpec(
                primary_features=("x", "y"), required_features=("x", "y"),
                interactions=tuple(
                    InteractionRole(f"interaction_{index}", ("x", "y"), "mechanism", "ablation")
                    for index in range(6)
                ),
            )

    def test_accepts_only_declared_interactions_with_ablation_evidence(self) -> None:
        interaction = InteractionRole(
            "return_x_quote", ("return_1m", "quote"),
            "momentum conditioned on quote", "ablation-report:return_x_quote",
        )
        spec = Phase4TrainingSpec(
            primary_features=("return_1m", "quote"), required_features=("return_1m", "quote"),
            interactions=(interaction,), max_iterations=5,
        )
        dataset = InnerTrainDataset.create(
            fold_id="outer-1/inner-1", dataset_hash="e" * 64, fit_start=START, fit_end=END,
            rows=(
                InnerTrainRow(START + timedelta(days=1), {"return_1m": -1.0, "quote": 1.0, "return_x_quote": -1.0}, "NO_TRADE"),
                InnerTrainRow(START + timedelta(days=2), {"return_1m": -0.5, "quote": 1.0, "return_x_quote": -0.5}, "SHORT"),
                InnerTrainRow(START + timedelta(days=3), {"return_1m": 1.0, "quote": 1.0, "return_x_quote": 1.0}, "LONG"),
            ),
        )

        model = train_phase4_model(dataset, spec).model

        self.assertEqual(model.trade_model.feature_order, spec.raw_feature_order)
        with self.assertRaisesRegex(ValueError, "ablation"):
            InteractionRole("return_x_quote", ("return_1m", "quote"), "defined", "")

    def test_two_stage_training_records_provenance_weights_and_exclusions(self) -> None:
        result = train_phase4_model(inner_train_dataset(), training_spec())
        model = result.model

        self.assertEqual(model.trade_model.record.sample_count, 4)
        self.assertEqual(model.direction_model.record.sample_count, 2)
        self.assertEqual(model.record.excluded_ambiguous, 1)
        self.assertEqual(model.record.excluded_incomplete, 1)
        self.assertEqual(model.trade_model.l2, 0.5)
        self.assertEqual(model.trade_model.class_weights, ((0, 1.0), (1, 2.0)))
        self.assertEqual(model.trade_model.max_iterations, 400)
        self.assertEqual(model.trade_model.tolerance, 1e-8)
        self.assertEqual(model.trade_model.random_seed, 7)
        self.assertEqual(model.trade_model.record.fold_id, inner_train_dataset().fold_id)
        self.assertEqual(model.trade_model.record.train_hash, inner_train_dataset().train_hash)
        self.assertEqual(model.trade_model.record.preprocessor_hash, result.preprocessor.content_hash)
        self.assertEqual(model.trade_model.record.iterations, len(model.trade_model.record.loss_history))
        self.assertEqual(model.direction_model.classes, ("SHORT", "LONG"))
        self.assertAlmostEqual(sum(model.predict((1.5, 0.0, 0.0)).as_tuple()), 1.0)


if __name__ == "__main__":
    unittest.main()
