from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    """One immutable observation of the SPEC 35 step 1-6 preconditions."""

    connection_ok: bool
    target_code: str
    rollover_in_progress: bool
    tick_age_ms: int
    bidask_age_ms: int
    data_quality_valid: bool

    def __post_init__(self) -> None:
        if not self.target_code.strip():
            raise ValueError("target_code is required")
        for name, value in (
            ("tick_age_ms", self.tick_age_ms),
            ("bidask_age_ms", self.bidask_age_ms),
        ):
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be non-negative")


def health_failure(
    health: RuntimeHealth,
    *,
    expected_target_code: str,
    tick_age_limit_ms: int,
    bidask_age_limit_ms: int,
) -> str | None:
    """Return the first SPEC 35 step 1-6 failure, in fixed fail-closed order."""

    if not health.connection_ok:
        return "CONNECTION_INVALID"
    if health.target_code != expected_target_code:
        return "TARGET_CODE_MISMATCH"
    if health.rollover_in_progress:
        return "ROLLOVER_UNCONFIRMED"
    if health.tick_age_ms > tick_age_limit_ms:
        return "TICK_STALE"
    if health.bidask_age_ms > bidask_age_limit_ms:
        return "BIDASK_STALE"
    if not health.data_quality_valid:
        return "DATA_QUALITY_INVALID"
    return None
