from __future__ import annotations

from dataclasses import replace
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tmf_research.models.calibration import fit_two_stage_calibrators
from tmf_research.models.serialization import (
    ExpectedModelContract,
    ModelBundle,
    ModelMetadata,
    _bundle_checksum,
    load_approved_model_bundle,
    load_model_bundle,
    save_model_bundle,
)
from tmf_research.models.training import train_phase4_model

from tests.unit.test_calibration import validation_predictions
from tests.unit.test_phase4_training import END, START, inner_train_dataset, training_spec


def bundle() -> ModelBundle:
    dataset = inner_train_dataset()
    training = train_phase4_model(dataset, training_spec())
    calibration = fit_two_stage_calibrators(
        validation_predictions(),
        bin_count=4,
        minimum_bin_size=2,
    ).calibrator
    metadata = ModelMetadata(
        model_id="model-1", model_version="v1", created_at=END,
        training_start=START, training_end=END, instrument="TMF", session="DAY", horizon="15m",
        feature_version="phase3-features-v1", label_version="labels-v1", schema_version="model-bundle-v1",
        code_commit="abc123", random_seed=7, training_data_hash=dataset.train_hash,
        experiment_id="experiment-1", outer_fold_count=0, locked_holdout_status="NOT_RUN",
        model_status="DRAFT_PHASE4",
    )
    return ModelBundle(
        metadata,
        training.preprocessor.feature_order,
        {"version": "phase3-features-v1"},
        training.preprocessor,
        training.model,
        calibration,
    )


class ModelSerializationTests(unittest.TestCase):
    def test_round_trip_preserves_research_probabilities_but_forces_no_trade(self) -> None:
        original = bundle()
        with TemporaryDirectory() as directory:
            root = Path(directory) / "model"
            checksum = save_model_bundle(original, root)
            loaded = load_model_bundle(root, ExpectedModelContract.from_bundle(original, model_checksum=checksum))
            files = {path.name for path in root.iterdir()}

        self.assertIsNotNone(loaded.bundle)
        assert loaded.bundle is not None
        row = {"return_1m": 1.5, "basis": 25.0}
        before = original.predict(row)
        after = loaded.bundle.predict(row)
        self.assertEqual(before, after)
        self.assertEqual(after.signal, "NO_TRADE")
        self.assertEqual(after.reasons, ("PHASE4_RESEARCH_ONLY_DRAFT",))
        self.assertAlmostEqual(sum(after.probabilities.as_tuple()), 1.0)
        required = {"metadata.json", "feature_names.json", "feature_manifest.json", "scaler.json", "imputer.json", "trade_model.json", "direction_model.json", "calibrator.json", "fold_metrics.json", "stability_report.json", "ablation_report.json", "overfitting_report.json", "checksum.sha256"}
        self.assertTrue(required.issubset(files))

    def test_every_runtime_contract_mismatch_is_rejected(self) -> None:
        original = bundle()
        cases = (
            ({"feature_version": "wrong"}, "FEATURE_VERSION_MISMATCH"),
            ({"feature_order": ("wrong",)}, "FEATURE_ORDER_MISMATCH"),
            ({"instrument": "TXF"}, "INSTRUMENT_MISMATCH"),
            ({"session": "NIGHT"}, "SESSION_MISMATCH"),
            ({"horizon": "60m"}, "HORIZON_MISMATCH"),
            ({"schema_version": "wrong"}, "SCHEMA_VERSION_MISMATCH"),
            ({"scaler_dimension": 999}, "SCALER_DIMENSION_MISMATCH"),
            ({"imputer_dimension": 999}, "IMPUTER_DIMENSION_MISMATCH"),
            ({"model_checksum": "0" * 64}, "EXPECTED_MODEL_CHECKSUM_MISMATCH"),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory) / "model"
            save_model_bundle(original, root)
            for overrides, reason in cases:
                with self.subTest(reason=reason):
                    result = load_model_bundle(root, ExpectedModelContract.from_bundle(original, **overrides))
                    self.assertEqual(result.signal, "NO_TRADE")
                    self.assertIn(reason, result.reasons)

    def test_checksum_corruption_and_rehashed_invalid_state_fail_closed(self) -> None:
        original = bundle()
        corruptions = (
            ("calibrator.json", {"trade": {"method": "ISOTONIC", "upper_bounds": [], "values": []}}),
            ("trade_model.json", "ZERO_L2"),
        )
        with TemporaryDirectory() as directory:
            tampered_root = Path(directory) / "tampered"
            save_model_bundle(original, tampered_root)
            (tampered_root / "trade_model.json").write_text("{}", encoding="utf-8")
            tampered = load_model_bundle(tampered_root, ExpectedModelContract.from_bundle(original))
            self.assertEqual(tampered.reasons, ("MODEL_CHECKSUM_MISMATCH",))
        for filename, corruption in corruptions:
            with self.subTest(filename=filename), TemporaryDirectory() as directory:
                root = Path(directory) / "model"
                save_model_bundle(original, root)
                payload = json.loads((root / filename).read_text(encoding="utf-8"))
                if corruption == "ZERO_L2":
                    payload["model"]["l2"] = 0.0
                else:
                    payload.update(corruption)
                (root / filename).write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
                (root / "checksum.sha256").write_text(_bundle_checksum(root) + "\n", encoding="ascii")
                result = load_model_bundle(root, ExpectedModelContract.from_bundle(original))
                self.assertEqual(result.reasons, ("MODEL_BUNDLE_INVALID",))

    def test_publish_is_exclusive_and_load_io_errors_are_stable(self) -> None:
        original = bundle()
        with TemporaryDirectory() as directory:
            root = Path(directory) / "model"
            save_model_bundle(original, root)
            with self.assertRaises(FileExistsError):
                save_model_bundle(original, root)
            with patch.object(Path, "read_bytes", side_effect=OSError("transient")):
                result = load_model_bundle(root, ExpectedModelContract.from_bundle(original))
        self.assertEqual(result.reasons, ("MODEL_BUNDLE_IO_ERROR",))

    def test_nonfinite_runtime_feature_and_approved_loader_fail_closed(self) -> None:
        original = bundle()
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                prediction = original.predict({"return_1m": value, "basis": 1.0})
                self.assertEqual(prediction.signal, "NO_TRADE")
                self.assertEqual(prediction.probabilities.as_tuple(), (1.0, 0.0, 0.0))
                self.assertEqual(prediction.reasons, ("NONFINITE_FEATURE:return_1m",))
        approved = load_approved_model_bundle(Path("unused"), ExpectedModelContract.from_bundle(original))
        self.assertEqual(approved.reasons, ("PHASE6_APPROVED_LOADER_NOT_IMPLEMENTED",))

    def test_bundle_rejects_manifest_or_calibration_provenance_disagreement(self) -> None:
        original = bundle()
        with self.assertRaisesRegex(ValueError, "manifest"):
            ModelBundle(original.metadata, original.feature_names, {"version": "wrong"}, original.preprocessor, original.model, original.calibrator)

    def test_bundle_rejects_metadata_training_provenance_disagreement(self) -> None:
        original = bundle()
        cases = (
            (replace(original.metadata, training_data_hash="0" * 64), "training data"),
            (replace(original.metadata, training_start=START.replace(year=2025)), "training interval"),
            (replace(original.metadata, random_seed=999), "random seed"),
        )
        for metadata, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                ModelBundle(
                    metadata,
                    original.feature_names,
                    original.feature_manifest,
                    original.preprocessor,
                    original.model,
                    original.calibrator,
                )


if __name__ == "__main__":
    unittest.main()
