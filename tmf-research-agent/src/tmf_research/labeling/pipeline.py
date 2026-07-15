from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from tmf_research.labeling.triple_barrier import LabelParameters, LabelRecord
from tmf_research.processing.bars import Bar


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate_id: str
    target_code: str
    decision_time: datetime
    horizon_minutes: int


@dataclass(frozen=True, slots=True)
class LabelManifest:
    version: str
    horizons_minutes: tuple[int, ...]
    primary_horizon_minutes: int
    parameter_versions: tuple[str, ...]
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.horizons_minutes != (5, 15, 60):
            raise ValueError("label manifest requires separate 5m, 15m, and 60m datasets")
        if self.primary_horizon_minutes != 15:
            raise ValueError("the Phase 3 primary horizon must be 15m")
        payload = {
            "version": self.version,
            "horizons_minutes": list(self.horizons_minutes),
            "primary_horizon_minutes": self.primary_horizon_minutes,
            "parameter_versions": list(self.parameter_versions),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        object.__setattr__(self, "content_hash", hashlib.sha256(encoded).hexdigest())

    @classmethod
    def from_parameters(
        cls,
        version: str,
        parameters: tuple[LabelParameters, ...],
    ) -> LabelManifest:
        by_horizon = {item.horizon_minutes: item.version for item in parameters}
        if set(by_horizon) != {5, 15, 60}:
            raise ValueError("one train/inner parameter set is required per horizon")
        return cls(
            version=version,
            horizons_minutes=(5, 15, 60),
            primary_horizon_minutes=15,
            parameter_versions=tuple(by_horizon[horizon] for horizon in (5, 15, 60)),
        )


class LabelPipeline:
    def candidates(
        self,
        bars: tuple[Bar, ...],
        *,
        horizons: tuple[int, ...] = (5, 15, 60),
    ) -> tuple[CandidateDecision, ...]:
        if set(horizons) - {5, 15, 60}:
            raise ValueError("horizons must be 5, 15, or 60")
        complete = tuple(
            sorted(
                (
                    bar
                    for bar in bars
                    if bar.is_complete
                    and bar.target_code is not None
                    and bar.bar_end - bar.bar_start == timedelta(minutes=1)
                ),
                key=lambda item: (item.bar_end, item.target_code or ""),
            )
        )
        seen: set[tuple[str, datetime, int]] = set()
        result: list[CandidateDecision] = []
        for bar in complete:
            assert bar.target_code is not None
            for horizon in horizons:
                key = (bar.target_code, bar.bar_end, horizon)
                if key in seen:
                    continue
                seen.add(key)
                encoded = f"{bar.target_code}|{bar.bar_end.isoformat()}|{horizon}".encode("utf-8")
                result.append(
                    CandidateDecision(
                        candidate_id=hashlib.sha256(encoded).hexdigest(),
                        target_code=bar.target_code,
                        decision_time=bar.bar_end,
                        horizon_minutes=horizon,
                    )
                )
        return tuple(result)

    def training_records(self, records: tuple[LabelRecord, ...]) -> tuple[LabelRecord, ...]:
        return tuple(record for record in records if record.training_eligible)

