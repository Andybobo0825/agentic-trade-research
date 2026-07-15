from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tmf_research.models.calibration import IdentityCalibrator
from tmf_research.models.logistic import ModelTrainingSample, fit_two_stage_logistic
from tmf_research.models.scaler import FoldPreprocessor
from tmf_research.models.serialization import ExpectedModelContract, ModelBundle, ModelMetadata, load_model_bundle, save_model_bundle


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 2, 1, tzinfo=timezone.utc)


def bundle() -> ModelBundle:
    rows = ({"return_1m": -2.0}, {"return_1m": -1.0}, {"return_1m": 1.0}, {"return_1m": 2.0})
    preprocessor = FoldPreprocessor.fit(rows, feature_order=("return_1m",), required_features=("return_1m",), fit_start=START, fit_end=END)
    model = fit_two_stage_logistic(
        (ModelTrainingSample((-2.0,), "NO_TRADE"), ModelTrainingSample((-1.0,), "NO_TRADE"), ModelTrainingSample((1.0,), "LONG"), ModelTrainingSample((2.0,), "SHORT")),
        feature_order=("return_1m",),
    )
    metadata = ModelMetadata(
        model_id="model-1", model_version="v1", created_at=END, training_start=START, training_end=END,
        instrument="TMF", session="DAY", horizon="15m", feature_version="phase3-features-v1",
        label_version="labels-v1", schema_version="model-bundle-v1", code_commit="abc123", random_seed=0,
        training_data_hash="datahash", experiment_id="experiment-1", outer_fold_count=0, locked_holdout_status="NOT_RUN",
    )
    return ModelBundle(metadata, ("return_1m",), {"version": "phase3-features-v1"}, preprocessor, model, IdentityCalibrator())


class ModelSerializationTests(unittest.TestCase):
    def test_canonical_round_trip_preserves_probability_and_registry_files(self) -> None:
        original = bundle()
        expected = ExpectedModelContract.from_bundle(original)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            checksum = save_model_bundle(original, root)
            loaded = load_model_bundle(root, expected)
            files = {path.name for path in root.iterdir()}

        self.assertEqual(len(checksum), 64)
        self.assertIsNotNone(loaded.bundle)
        assert loaded.bundle is not None
        self.assertEqual(original.predict({"return_1m": 1.5}), loaded.bundle.predict({"return_1m": 1.5}))
        required = {"metadata.json", "feature_names.json", "feature_manifest.json", "scaler.json", "imputer.json", "trade_model.json", "direction_model.json", "calibrator.json", "fold_metrics.json", "stability_report.json", "ablation_report.json", "overfitting_report.json", "checksum.sha256"}
        self.assertTrue(required.issubset(files))

    def test_any_contract_or_checksum_mismatch_fails_closed(self) -> None:
        original = bundle()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            save_model_bundle(original, root)
            rejected = load_model_bundle(root, ExpectedModelContract.from_bundle(original, instrument="TXF"))
            (root / "trade_model.json").write_text("{}", encoding="utf-8")
            tampered = load_model_bundle(root, ExpectedModelContract.from_bundle(original))

        self.assertEqual(rejected.signal, "NO_TRADE")
        self.assertIn("INSTRUMENT_MISMATCH", rejected.reasons)
        self.assertIn("MODEL_CHECKSUM_MISMATCH", tampered.reasons)

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
            root = Path(directory)
            save_model_bundle(original, root)
            for overrides, reason in cases:
                with self.subTest(reason=reason):
                    result = load_model_bundle(root, ExpectedModelContract.from_bundle(original, **overrides))
                    self.assertEqual(result.signal, "NO_TRADE")
                    self.assertIn(reason, result.reasons)

    def test_bundle_rejects_manifest_version_disagreement(self) -> None:
        original = bundle()
        with self.assertRaisesRegex(ValueError, "manifest"):
            ModelBundle(
                original.metadata,
                original.feature_names,
                {"version": "wrong"},
                original.preprocessor,
                original.model,
                original.calibrator,
            )


if __name__ == "__main__":
    unittest.main()
