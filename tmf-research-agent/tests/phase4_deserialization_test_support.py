from __future__ import annotations

from collections.abc import Mapping

from tmf_research.models.calibration import TwoStageCalibrator
from tmf_research.models.provenance import _CHECKSUM_VALIDATED_DESERIALIZATION
from tmf_research.models.scaler import FoldPreprocessor


def deserialize_calibrator_for_test(payload: Mapping[str, object]) -> TwoStageCalibrator:
    return TwoStageCalibrator._from_dict(
        payload,
        deserialization_authority=_CHECKSUM_VALIDATED_DESERIALIZATION,
    )


def deserialize_preprocessor_for_test(payload: Mapping[str, object]) -> FoldPreprocessor:
    return FoldPreprocessor._from_dict(
        payload,
        deserialization_authority=_CHECKSUM_VALIDATED_DESERIALIZATION,
    )
