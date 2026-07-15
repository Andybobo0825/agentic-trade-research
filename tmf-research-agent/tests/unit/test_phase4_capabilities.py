from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import cast
import unittest

import tmf_research.models.provenance as provenance_module
from tmf_research.models.provenance import (
    InnerTrainDataset,
    InnerValidationDataset,
    InnerValidationPredictions,
    NestedFoldManifest,
    Phase4FoldCapabilities,
    Phase4SourceRow,
    SplitRole,
    TrainingProvenance,
)
from tmf_research.models.training import train_phase4_model

from tests.phase4_test_support import TestPhase4FoldPlanner
from tests.unit.test_phase4_training import (
    END,
    START,
    default_train_rows,
    default_validation_rows,
    fold_materialization,
    training_spec,
)


class Phase4CapabilityTests(unittest.TestCase):
    def test_production_models_expose_no_fold_issuer_or_provenance_reconstructor(self) -> None:
        self.assertFalse(hasattr(provenance_module, "Phase4FoldMaterializer"))
        self.assertFalse(hasattr(Phase4FoldCapabilities, "materialize"))
        self.assertFalse(hasattr(TrainingProvenance, "from_dict"))

    def test_authority_objects_have_no_public_constructor(self) -> None:
        for authority in (
            NestedFoldManifest,
            InnerTrainDataset,
            InnerValidationPredictions,
        ):
            with self.subTest(authority=authority.__name__), self.assertRaisesRegex(
                TypeError,
                "cannot be constructed directly",
            ):
                authority()

    def test_issuer_precommits_source_plan_and_exact_role_rows(self) -> None:
        materialized = fold_materialization()
        manifest = materialized.manifest

        self.assertEqual(materialized.source_dataset_hash, manifest.source_dataset_hash)
        self.assertEqual(
            materialized.source_version,
            f"phase4-source-{materialized.source_dataset_hash[:16]}",
        )
        self.assertEqual(manifest.inner_train.count, len(materialized.inner_train.rows))
        self.assertEqual(manifest.inner_validation.count, len(materialized.inner_validation.rows))
        self.assertEqual(manifest.outer_test.count, len(materialized.outer_test.rows))
        self.assertEqual(manifest.inner_train.rows_hash, materialized.inner_train.train_hash)
        self.assertEqual(
            manifest.inner_validation.rows_hash,
            materialized.inner_validation.validation_dataset_hash,
        )
        self.assertEqual(manifest.outer_test.rows_hash, materialized.outer_test.outer_test_hash)
        self.assertEqual(len(manifest.plan_hash), 64)
        self.assertFalse(hasattr(NestedFoldManifest, "plan"))
        self.assertFalse(hasattr(NestedFoldManifest, "from_dict"))
        self.assertFalse(hasattr(InnerTrainDataset, "create"))
        self.assertFalse(hasattr(InnerValidationDataset, "create"))

    def test_manifest_and_capabilities_cannot_relabel_outer_test_as_train(self) -> None:
        materialized = fold_materialization()
        manifest = materialized.manifest

        with self.assertRaises((TypeError, ValueError)):
            replace(
                manifest.inner_train,
                start=manifest.outer_test.start,
                end=manifest.outer_test.end,
                row_hashes=manifest.outer_test.row_hashes,
                row_ids_hash=manifest.outer_test.row_ids_hash,
                rows_hash=manifest.outer_test.rows_hash,
                count=manifest.outer_test.count,
            )
        with self.assertRaises((TypeError, ValueError)):
            replace(manifest, inner_train=manifest.outer_test)
        with self.assertRaises((TypeError, ValueError)):
            replace(materialized.inner_train, rows=materialized.outer_test.rows)
        with self.assertRaisesRegex(ValueError, "inner-train capability"):
            train_phase4_model(
                cast(InnerTrainDataset, materialized.outer_test),
                training_spec(),
            )

    def test_fold_identity_role_is_authenticated(self) -> None:
        fold = fold_materialization().inner_train.fold
        self.assertEqual(fold.role, SplitRole.INNER_TRAIN)

        with self.assertRaises((TypeError, ValueError)):
            replace(fold, role=SplitRole.OUTER_TEST)

    def test_probabilities_cannot_be_fabricated_or_reordered(self) -> None:
        materialized = fold_materialization()
        training = train_phase4_model(materialized.inner_train, training_spec())
        generated = training.predict_inner_validation(materialized.inner_validation)

        self.assertEqual(generated.model_hash, training.model.content_hash)
        self.assertEqual(
            generated.validation_hash,
            training.predict_inner_validation(materialized.inner_validation).validation_hash,
        )
        with self.assertRaises((TypeError, ValueError)):
            replace(generated.rows[0], p_trade=0.99)
        with self.assertRaises((TypeError, ValueError)):
            replace(generated, rows=tuple(reversed(generated.rows)))

    def test_validation_labels_and_returns_cannot_contradict_committed_rows(self) -> None:
        materialized = fold_materialization()
        first = materialized.inner_validation.rows[0]
        contradictory = replace(first, label="LONG", net_return=123.0)

        with self.assertRaises((TypeError, ValueError)):
            replace(
                materialized.inner_validation,
                rows=(contradictory, *materialized.inner_validation.rows[1:]),
            )

    def test_validation_capability_is_bound_to_exact_parent_manifest(self) -> None:
        materialized = fold_materialization()
        training = train_phase4_model(materialized.inner_train, training_spec())
        validation_rows = default_validation_rows()
        other = fold_materialization(
            validation_rows=(
                replace(validation_rows[0], net_return=-2.0),
                *validation_rows[1:],
            ),
        )

        with self.assertRaisesRegex(ValueError, "parent training provenance"):
            training.predict_inner_validation(other.inner_validation)

    def test_registry_rejects_reissuing_same_source_and_fold_with_outer_as_train(self) -> None:
        planner = TestPhase4FoldPlanner()
        template = {"return_1m": 0.0, "basis": 0.0}
        original_outer = (
            Phase4SourceRow("outer-1", END + timedelta(hours=2, minutes=1), template, "NO_TRADE", -1.0),
            Phase4SourceRow("outer-2", END + timedelta(hours=2, minutes=2), template, "LONG", 1.0),
        )
        later_validation = (
            Phase4SourceRow("later-validation-1", END + timedelta(hours=4, minutes=1), template, "NO_TRADE", -1.0),
            Phase4SourceRow("later-validation-2", END + timedelta(hours=4, minutes=2), template, "LONG", 1.0),
        )
        later_outer = (
            Phase4SourceRow("later-outer-1", END + timedelta(hours=6, minutes=1), template, "NO_TRADE", -1.0),
            Phase4SourceRow("later-outer-2", END + timedelta(hours=6, minutes=2), template, "LONG", 1.0),
        )
        source_rows = (
            *default_train_rows(),
            *default_validation_rows(),
            *original_outer,
            *later_validation,
            *later_outer,
        )
        issued = planner.issue(
            source_rows=source_rows,
            outer_fold_id="outer-1",
            inner_fold_id="inner-1",
            train_start=START,
            train_end=END,
            validation_start=END + timedelta(minutes=1),
            validation_end=END + timedelta(hours=1),
            outer_test_start=END + timedelta(hours=2),
            outer_test_end=END + timedelta(hours=3),
        )
        self.assertEqual(
            tuple(row.row_id for row in issued.outer_test.rows),
            ("outer-1", "outer-2"),
        )

        with self.assertRaisesRegex(ValueError, "canonical fold plan"):
            planner.issue(
                source_rows=source_rows,
                outer_fold_id="outer-1",
                inner_fold_id="inner-1",
                train_start=END + timedelta(hours=2),
                train_end=END + timedelta(hours=3),
                validation_start=END + timedelta(hours=4),
                validation_end=END + timedelta(hours=5),
                outer_test_start=END + timedelta(hours=6),
                outer_test_end=END + timedelta(hours=7),
            )

    def test_outer_test_capability_cannot_enter_validation_composition(self) -> None:
        materialized = fold_materialization()
        training = train_phase4_model(materialized.inner_train, training_spec())

        with self.assertRaisesRegex(ValueError, "inner-validation"):
            training.predict_inner_validation(
                cast(InnerValidationDataset, materialized.outer_test),
            )


if __name__ == "__main__":
    unittest.main()
