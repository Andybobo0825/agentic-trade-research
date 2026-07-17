from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from tmf_research.domain.paper_trades import (
    PaperCostConfig,
    PaperExit,
    PaperIntent,
    PaperQuote,
)
from tmf_research.domain.predictions import (
    InstrumentBlock,
    MarketBlock,
    ModelBlock,
    PaperPlanBlock,
    PredictionRecord,
    ProbabilityBlock,
    QualityBlock,
    SessionBlock,
    Signal,
    TraceBlock,
)
from tmf_research.experiments.registry import phase4_candidate_hashes
from tmf_research.models.inference import ClassProbabilities, combine_probabilities
from tmf_research.models.provenance import FrozenDecisionPolicy
from tmf_research.models.serialization import ExpectedModelContract, ModelBundle
from tmf_research.paper.broker import PaperBroker
from tmf_research.paper.fill_model import PaperFillModel
from tmf_research.paper.risk import (
    EntryConditions,
    ExitObservation,
    evaluate_entry,
    evaluate_exit,
)
from tmf_research.runtime.feature_state import BarCloseGate, RuntimeFeatureVector
from tmf_research.runtime.health import RuntimeHealth, health_failure
from tmf_research.validation.approval import ApprovalCapability


_RUNTIME_SEAL = object()
RuntimeAuthority = Literal["APPROVED_FOR_PAPER", "TEST_ONLY"]
TEST_ONLY_WARNING = "TEST_ONLY_RUNTIME_EVIDENCE"


class RuntimeConfigurationError(ValueError):
    """Raised when a live runtime cannot be frozen from its inputs."""


@dataclass(frozen=True, slots=True, init=False)
class FrozenLiveRuntime:
    """Immutable Phase 6 runtime; nothing about the model can be adjusted."""

    bundle: ModelBundle
    contract: ExpectedModelContract
    policy: FrozenDecisionPolicy
    approval: ApprovalCapability | None
    authority: RuntimeAuthority
    alias_code: str
    target_code: str
    delivery_month: str
    delivery_date: str
    raw_checksum: str
    dataset_version: str
    stop_points: float
    target_points: float
    maximum_holding_minutes: int
    tick_age_limit_ms: int
    bidask_age_limit_ms: int
    spread_limit_points: float
    fill_model: PaperFillModel
    cost_config: PaperCostConfig
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _RUNTIME_SEAL:
            raise TypeError(
                "live runtimes are frozen only by freeze_live_runtime"
            )
        for name, value in (
            ("alias_code", self.alias_code), ("target_code", self.target_code),
            ("delivery_month", self.delivery_month),
            ("delivery_date", self.delivery_date),
            ("dataset_version", self.dataset_version),
        ):
            if not value.strip():
                raise RuntimeConfigurationError(f"{name} is required")
        if len(self.raw_checksum) != 64 or any(
            character not in "0123456789abcdef" for character in self.raw_checksum
        ):
            raise RuntimeConfigurationError("raw checksum must be SHA-256 hex")
        for name, number in (
            ("stop_points", self.stop_points),
            ("target_points", self.target_points),
            ("spread_limit_points", self.spread_limit_points),
        ):
            if not math.isfinite(number) or number <= 0.0:
                raise RuntimeConfigurationError(f"{name} must be finite and positive")
        for name, count in (
            ("maximum_holding_minutes", self.maximum_holding_minutes),
            ("tick_age_limit_ms", self.tick_age_limit_ms),
            ("bidask_age_limit_ms", self.bidask_age_limit_ms),
        ):
            if isinstance(count, bool) or count <= 0:
                raise RuntimeConfigurationError(f"{name} must be positive")
        if self.contract.feature_order != self.bundle.feature_names:
            raise RuntimeConfigurationError(
                "contract feature order must match the frozen bundle"
            )
        if self.authority == "APPROVED_FOR_PAPER":
            if not isinstance(self.approval, ApprovalCapability):
                raise TypeError(
                    "approved runtimes require the sealed Phase 5 capability"
                )
            if dict(phase4_candidate_hashes(self.bundle)) != dict(
                self.approval.candidate_hashes
            ):
                raise RuntimeConfigurationError(
                    "approval capability does not bind this exact candidate bundle"
                )
            if (
                self.policy.thresholds_hash
                != self.approval.candidate_hashes["thresholds"]
                or self.policy.rules_hash != self.approval.candidate_hashes["rules"]
            ):
                raise RuntimeConfigurationError(
                    "decision policy does not match the approved candidate"
                )
        elif self.authority == "TEST_ONLY":
            if self.approval is not None:
                raise RuntimeConfigurationError(
                    "test-only runtimes cannot carry approval capabilities"
                )
        else:
            raise RuntimeConfigurationError("unknown runtime authority")


def _build_runtime(
    *,
    bundle: ModelBundle,
    contract: ExpectedModelContract,
    policy: FrozenDecisionPolicy,
    approval: ApprovalCapability | None,
    authority: RuntimeAuthority,
    alias_code: str,
    target_code: str,
    delivery_month: str,
    delivery_date: str,
    raw_checksum: str,
    dataset_version: str,
    stop_points: float,
    target_points: float,
    maximum_holding_minutes: int,
    tick_age_limit_ms: int,
    bidask_age_limit_ms: int,
    spread_limit_points: float,
    entry_slippage_points: float,
    exit_slippage_points: float,
    cost_config: PaperCostConfig,
) -> FrozenLiveRuntime:
    if not isinstance(bundle, ModelBundle):
        raise TypeError("runtime requires a checksum-validated model bundle")
    if not isinstance(policy, FrozenDecisionPolicy):
        raise TypeError("runtime requires a sealed frozen decision policy")
    if not isinstance(cost_config, PaperCostConfig):
        raise TypeError("runtime requires a declared paper cost configuration")
    instance = object.__new__(FrozenLiveRuntime)
    for name, value in (
        ("bundle", bundle), ("contract", contract), ("policy", policy),
        ("approval", approval), ("authority", authority),
        ("alias_code", alias_code), ("target_code", target_code),
        ("delivery_month", delivery_month), ("delivery_date", delivery_date),
        ("raw_checksum", raw_checksum), ("dataset_version", dataset_version),
        ("stop_points", stop_points), ("target_points", target_points),
        ("maximum_holding_minutes", maximum_holding_minutes),
        ("tick_age_limit_ms", tick_age_limit_ms),
        ("bidask_age_limit_ms", bidask_age_limit_ms),
        ("spread_limit_points", spread_limit_points),
        (
            "fill_model",
            PaperFillModel(
                entry_slippage_points=entry_slippage_points,
                exit_slippage_points=exit_slippage_points,
            ),
        ),
        ("cost_config", cost_config),
        ("_seal", _RUNTIME_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def freeze_live_runtime(
    *,
    bundle: ModelBundle,
    contract: ExpectedModelContract,
    policy: FrozenDecisionPolicy,
    approval: ApprovalCapability,
    alias_code: str,
    target_code: str,
    delivery_month: str,
    delivery_date: str,
    raw_checksum: str,
    dataset_version: str,
    stop_points: float,
    target_points: float,
    maximum_holding_minutes: int,
    tick_age_limit_ms: int,
    bidask_age_limit_ms: int,
    spread_limit_points: float,
    entry_slippage_points: float,
    exit_slippage_points: float,
    cost_config: PaperCostConfig,
) -> FrozenLiveRuntime:
    """Freeze the production runtime; only APPROVED_FOR_PAPER can enable plans."""

    if not isinstance(approval, ApprovalCapability):
        raise TypeError("approved runtimes require the sealed Phase 5 capability")
    return _build_runtime(
        bundle=bundle, contract=contract, policy=policy, approval=approval,
        authority="APPROVED_FOR_PAPER", alias_code=alias_code,
        target_code=target_code, delivery_month=delivery_month,
        delivery_date=delivery_date, raw_checksum=raw_checksum,
        dataset_version=dataset_version, stop_points=stop_points,
        target_points=target_points,
        maximum_holding_minutes=maximum_holding_minutes,
        tick_age_limit_ms=tick_age_limit_ms,
        bidask_age_limit_ms=bidask_age_limit_ms,
        spread_limit_points=spread_limit_points,
        entry_slippage_points=entry_slippage_points,
        exit_slippage_points=exit_slippage_points,
        cost_config=cost_config,
    )


def _issue_test_only_runtime(
    *,
    bundle: ModelBundle,
    contract: ExpectedModelContract,
    policy: FrozenDecisionPolicy,
    alias_code: str,
    target_code: str,
    delivery_month: str,
    delivery_date: str,
    raw_checksum: str,
    dataset_version: str,
    stop_points: float,
    target_points: float,
    maximum_holding_minutes: int,
    tick_age_limit_ms: int,
    bidask_age_limit_ms: int,
    spread_limit_points: float,
    entry_slippage_points: float,
    exit_slippage_points: float,
    cost_config: PaperCostConfig,
) -> FrozenLiveRuntime:
    """Issue a TEST_ONLY runtime that proves mechanics, never research claims."""

    return _build_runtime(
        bundle=bundle, contract=contract, policy=policy, approval=None,
        authority="TEST_ONLY", alias_code=alias_code, target_code=target_code,
        delivery_month=delivery_month, delivery_date=delivery_date,
        raw_checksum=raw_checksum, dataset_version=dataset_version,
        stop_points=stop_points, target_points=target_points,
        maximum_holding_minutes=maximum_holding_minutes,
        tick_age_limit_ms=tick_age_limit_ms,
        bidask_age_limit_ms=bidask_age_limit_ms,
        spread_limit_points=spread_limit_points,
        entry_slippage_points=entry_slippage_points,
        exit_slippage_points=exit_slippage_points,
        cost_config=cost_config,
    )


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    """Everything one completed bar contributes besides its features."""

    health: RuntimeHealth
    quote: PaperQuote | None
    bar_high: float
    bar_low: float
    last_price: float
    session_type: Literal["DAY", "NIGHT"]
    trading_date: str
    minutes_from_open: int
    minutes_to_close: int
    session_end_time: datetime
    underlying_price: float | None
    basis_points: float | None
    session_vwap: float
    atr_15m: float

    def __post_init__(self) -> None:
        if self.session_type not in ("DAY", "NIGHT"):
            raise ValueError("session_type must be DAY or NIGHT")
        if not self.trading_date.strip():
            raise ValueError("trading_date is required")
        for name, value in (
            ("bar_high", self.bar_high), ("bar_low", self.bar_low),
            ("last_price", self.last_price),
            ("session_vwap", self.session_vwap), ("atr_15m", self.atr_15m),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        for name, optional in (
            ("underlying_price", self.underlying_price),
            ("basis_points", self.basis_points),
        ):
            if optional is not None and not math.isfinite(optional):
                raise ValueError(f"{name} must be finite")
        if self.bar_high < self.bar_low:
            raise ValueError("bar range is inverted")
        for name, count in (
            ("minutes_from_open", self.minutes_from_open),
            ("minutes_to_close", self.minutes_to_close),
        ):
            if isinstance(count, bool) or count < 0:
                raise ValueError(f"{name} must be non-negative")
        if (
            self.session_end_time.tzinfo is None
            or self.session_end_time.utcoffset() is None
        ):
            raise ValueError("session_end_time must be timezone-aware")


class PredictionLog:
    """Append-only persistence for every runtime prediction."""

    __slots__ = ("_records",)

    def __init__(self) -> None:
        self._records: dict[str, PredictionRecord] = {}

    @property
    def records(self) -> tuple[PredictionRecord, ...]:
        return tuple(self._records.values())

    def append(self, record: PredictionRecord) -> PredictionRecord:
        if record.prediction_id in self._records:
            raise ValueError(
                f"prediction {record.prediction_id} is already persisted"
            )
        self._records[record.prediction_id] = record
        return record


class LiveResearchRunner:
    """Runs the SPEC 35 fourteen-step loop; every failure persists NO_TRADE."""

    __slots__ = ("runtime", "loaded_checksum", "broker", "gate", "log")

    def __init__(
        self,
        *,
        runtime: FrozenLiveRuntime,
        loaded_checksum: str,
        broker: PaperBroker,
        gate: BarCloseGate,
        log: PredictionLog,
    ) -> None:
        if not isinstance(runtime, FrozenLiveRuntime):
            raise TypeError("runner requires a frozen live runtime")
        if not isinstance(broker, PaperBroker):
            raise TypeError("runner requires the paper broker boundary")
        self.runtime = runtime
        self.loaded_checksum = loaded_checksum
        self.broker = broker
        self.gate = gate
        self.log = log

    def process_bar(
        self,
        vector: RuntimeFeatureVector,
        observation: RuntimeObservation,
    ) -> PredictionRecord:
        self.gate.admit(vector)
        ledger_row_id = self._settle_open_position(vector, observation)
        failure = health_failure(
            observation.health,
            expected_target_code=self.runtime.target_code,
            tick_age_limit_ms=self.runtime.tick_age_limit_ms,
            bidask_age_limit_ms=self.runtime.bidask_age_limit_ms,
        )
        if failure is not None:
            return self._persist_no_trade(
                vector, observation, (failure,), (), ledger_row_id,
                complete_features=False,
            )
        transformed = self.runtime.bundle.preprocessor.transform(vector.values)
        if not transformed.is_eligible:
            missing = tuple(
                reason.partition(":")[2]
                for reason in transformed.reasons
                if reason.startswith("REQUIRED_FEATURE_MISSING:")
            )
            return self._persist_no_trade(
                vector, observation, ("FEATURES_MISSING",), missing,
                ledger_row_id, complete_features=False,
            )
        if vector.feature_version != self.runtime.bundle.metadata.feature_version:
            return self._persist_no_trade(
                vector, observation, ("FEATURE_VERSION_MISMATCH",), (),
                ledger_row_id, complete_features=True,
            )
        if self.loaded_checksum != self.runtime.contract.model_checksum:
            return self._persist_no_trade(
                vector, observation, ("MODEL_CHECKSUM_MISMATCH",), (),
                ledger_row_id, complete_features=True,
            )
        try:
            p_trade, p_long = self.runtime.bundle.calibrator.calibrate(
                self.runtime.bundle.model.trade_model.predict_probability(
                    transformed.values,
                ),
                self.runtime.bundle.model.direction_model.predict_probability(
                    transformed.values,
                ),
            )
            probabilities = combine_probabilities(
                p_trade=p_trade, p_long_given_trade=p_long,
            )
        except (ArithmeticError, ValueError):
            return self._persist_no_trade(
                vector, observation, ("NONFINITE_MODEL_INFERENCE",), (),
                ledger_row_id, complete_features=True,
            )
        signal: Signal = (
            "NO_TRADE" if p_trade < self.runtime.policy.trade_threshold
            else "LONG" if p_long >= self.runtime.policy.direction_threshold
            else "SHORT"
        )
        reasons: tuple[str, ...] = ()
        plan = _disabled_plan()
        allow_paper = False
        if signal != "NO_TRADE":
            rejections = evaluate_entry(EntryConditions(
                quote=observation.quote,
                quote_age_limit_ms=self.runtime.bidask_age_limit_ms,
                spread_limit_points=self.runtime.spread_limit_points,
                data_quality_valid=observation.health.data_quality_valid,
                model_compatible=True,
                features_complete=True,
                position_open=self.broker.position is not None,
                rollover_in_progress=observation.health.rollover_in_progress,
                session_ending=(
                    observation.minutes_to_close
                    < self.runtime.maximum_holding_minutes
                ),
                cost_config=self.runtime.cost_config,
            ))
            if rejections:
                reasons = rejections
            else:
                plan, allow_paper = self._enter_paper_position(
                    signal, vector, observation,
                )
        record = self._record(
            vector, observation, probabilities, signal, plan, reasons, (),
            ledger_row_id, complete_features=True, allow_paper=allow_paper,
        )
        return self.log.append(record)

    def _settle_open_position(
        self,
        vector: RuntimeFeatureVector,
        observation: RuntimeObservation,
    ) -> str | None:
        position = self.broker.position
        if position is None:
            return None
        exit_reason = evaluate_exit(position, ExitObservation(
            observed_at=vector.bar_close_time,
            bar_high=observation.bar_high,
            bar_low=observation.bar_low,
            quote=observation.quote,
            quote_age_limit_ms=self.runtime.bidask_age_limit_ms,
            rollover_in_progress=observation.health.rollover_in_progress,
        ))
        if exit_reason is None:
            return None
        if exit_reason == "STOP_LOSS":
            reference = position.stop_price
        elif exit_reason == "PROFIT_TARGET":
            reference = position.target_price
        elif observation.quote is not None:
            reference = (
                observation.quote.bid_price_1
                if position.direction == "LONG"
                else observation.quote.ask_price_1
            )
        else:
            reference = observation.last_price
        fill = self.runtime.fill_model.exit_fill(
            position.direction, reference, vector.bar_close_time,
        )
        row = self.broker.close_position(
            PaperExit(
                reason=exit_reason,
                price=fill.price,
                exited_at=vector.bar_close_time,
            ),
            self.runtime.cost_config,
        )
        return row.row_id

    def _enter_paper_position(
        self,
        signal: Signal,
        vector: RuntimeFeatureVector,
        observation: RuntimeObservation,
    ) -> tuple[PaperPlanBlock, bool]:
        assert signal in ("LONG", "SHORT")
        assert observation.quote is not None
        direction: Literal["LONG", "SHORT"] = (
            "LONG" if signal == "LONG" else "SHORT"
        )
        entry = self.runtime.fill_model.entry_fill(
            direction, observation.quote, vector.bar_close_time,
        )
        if direction == "LONG":
            stop_price = entry.price - self.runtime.stop_points
            target_price = entry.price + self.runtime.target_points
        else:
            stop_price = entry.price + self.runtime.stop_points
            target_price = entry.price - self.runtime.target_points
        vertical_deadline = min(
            vector.bar_close_time
            + timedelta(minutes=self.runtime.maximum_holding_minutes),
            observation.session_end_time,
        )
        intent = PaperIntent(
            intent_id=_deterministic_id("paper", vector, self.runtime.target_code),
            direction=direction,
            quantity=1,
            created_at=vector.bar_close_time,
        )
        self.broker.open_position(
            intent,
            entry,
            stop_price=stop_price,
            target_price=target_price,
            vertical_deadline=vertical_deadline,
            session_end=observation.session_end_time,
        )
        plan = PaperPlanBlock(
            enabled=True,
            direction=direction,
            quantity=1,
            entry_price=entry.price,
            stop_price=stop_price,
            target_price=target_price,
            maximum_holding_minutes=self.runtime.maximum_holding_minutes,
        )
        return plan, True

    def _persist_no_trade(
        self,
        vector: RuntimeFeatureVector,
        observation: RuntimeObservation,
        reasons: tuple[str, ...],
        missing_features: tuple[str, ...],
        ledger_row_id: str | None,
        *,
        complete_features: bool,
    ) -> PredictionRecord:
        record = self._record(
            vector, observation, ClassProbabilities(1.0, 0.0, 0.0), "NO_TRADE",
            _disabled_plan(), reasons, missing_features, ledger_row_id,
            complete_features=complete_features, allow_paper=False,
        )
        return self.log.append(record)

    def _record(
        self,
        vector: RuntimeFeatureVector,
        observation: RuntimeObservation,
        probabilities: ClassProbabilities,
        signal: Signal,
        plan: PaperPlanBlock,
        reasons: tuple[str, ...],
        missing_features: tuple[str, ...],
        ledger_row_id: str | None,
        *,
        complete_features: bool,
        allow_paper: bool,
    ) -> PredictionRecord:
        runtime = self.runtime
        metadata = runtime.bundle.metadata
        quote = observation.quote
        data_stale = (
            quote is None
            or quote.age_ms > runtime.bidask_age_limit_ms
            or observation.health.tick_age_ms > runtime.tick_age_limit_ms
        )
        warnings: tuple[str, ...] = (
            (TEST_ONLY_WARNING,) if runtime.authority == "TEST_ONLY" else ()
        )
        return PredictionRecord(
            prediction_id=_deterministic_id("pred", vector, runtime.target_code),
            decision_time=vector.bar_close_time,
            evidence_available_at=vector.evidence_available_at,
            instrument=InstrumentBlock(
                category="TMF",
                alias_code=runtime.alias_code,
                target_code=runtime.target_code,
                delivery_month=runtime.delivery_month,
                delivery_date=runtime.delivery_date,
            ),
            session=SessionBlock(
                type=observation.session_type,
                trading_date=observation.trading_date,
                minutes_from_open=observation.minutes_from_open,
                minutes_to_close=observation.minutes_to_close,
            ),
            market=MarketBlock(
                last_price=observation.last_price,
                bid_price_1=(
                    quote.bid_price_1 if quote is not None
                    else observation.last_price
                ),
                ask_price_1=(
                    quote.ask_price_1 if quote is not None
                    else observation.last_price
                ),
                spread_points=(
                    quote.spread_points if quote is not None else 0.0
                ),
                underlying_price=observation.underlying_price,
                basis_points=observation.basis_points,
                session_vwap=observation.session_vwap,
                atr_15m=observation.atr_15m,
            ),
            probability=ProbabilityBlock(
                long=probabilities.p_long,
                short=probabilities.p_short,
                no_trade=probabilities.p_no_trade,
            ),
            signal=signal,
            paper_plan=plan,
            quality=QualityBlock(
                tick_age_ms=observation.health.tick_age_ms,
                bidask_age_ms=observation.health.bidask_age_ms,
                data_stale=data_stale,
                rollover=observation.health.rollover_in_progress,
                complete_features=complete_features,
                allow_paper_trade=allow_paper,
            ),
            model=ModelBlock(
                model_id=metadata.model_id,
                model_version=metadata.model_version,
                feature_version=metadata.feature_version,
                label_version=metadata.label_version,
                training_end=metadata.training_end.isoformat(),
                calibration_method=(
                    runtime.bundle.calibrator.trade_calibrator.method
                ),
            ),
            reasons=reasons,
            missing_features=missing_features,
            warnings=warnings,
            trace=TraceBlock(
                raw_checksum=runtime.raw_checksum,
                dataset_version=runtime.dataset_version,
                experiment_id=metadata.experiment_id,
                code_commit=metadata.code_commit,
                ledger_row_id=ledger_row_id,
            ),
        )


def _disabled_plan() -> PaperPlanBlock:
    return PaperPlanBlock(
        enabled=False, direction=None, quantity=0,
        entry_price=None, stop_price=None, target_price=None,
        maximum_holding_minutes=0,
    )


def _deterministic_id(
    prefix: str,
    vector: RuntimeFeatureVector,
    target_code: str,
) -> str:
    stamp = vector.bar_close_time.strftime("%Y%m%dT%H%M%S%z")
    return f"{prefix}-{stamp}-{target_code}"
