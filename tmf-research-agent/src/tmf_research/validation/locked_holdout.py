from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from tmf_research.infrastructure.trusted_witness import (
    SqliteTrustedWitness, TrustedWitness, WitnessHead, WitnessMissing, witness_subject,
)


HoldoutStatus = Literal["LOCKED", "FROZEN", "UNLOCKED", "CONSUMED", "EVALUATED", "CONTAMINATED"]
REQUIRED_FREEZE_COMPONENTS = ("model", "features", "labels", "parameters", "thresholds", "rules")
_APPROVAL_SEAL = object()
_EVALUATION_SEAL = object()


class HoldoutAccessError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HoldoutRow:
    row_id: str
    trading_date: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.row_id.strip() or not self.trading_date.strip():
            raise ValueError("holdout rows require id and effective trading date")
        copied = json.loads(json.dumps(dict(self.payload), allow_nan=False))
        if not isinstance(copied, dict):
            raise ValueError("holdout row payload must be a JSON object")
        object.__setattr__(self, "payload", MappingProxyType(copied))

    def to_dict(self) -> dict[str, object]:
        return {"row_id": self.row_id, "trading_date": self.trading_date, "payload": dict(self.payload)}


@dataclass(frozen=True, slots=True)
class HoldoutSelection:
    development: tuple[HoldoutRow, ...]
    holdout: tuple[HoldoutRow, ...]
    required_rows_by_percent: int
    required_effective_days: int
    percentage: float
    status: Literal["READY", "RESEARCH_INSUFFICIENT_DATA"]
    source_hash: str
    holdout_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        combined = self.development + self.holdout
        expected = _selection_payload(combined, self.percentage, self.required_effective_days)
        if (
            self.development != expected["development"]
            or self.holdout != expected["holdout"]
            or self.required_rows_by_percent != expected["percent_count"]
            or self.status != expected["status"]
            or self.source_hash != expected["source_hash"]
            or self.holdout_hash != expected["holdout_hash"]
        ):
            raise ValueError("locked holdout selection is not the canonical final suffix")
        payload = self._payload_without_hash()
        if self.content_hash != _hash(payload):
            raise ValueError("locked holdout selection content hash mismatch")

    def _payload_without_hash(self) -> dict[str, object]:
        return {
            "source_hash": self.source_hash,
            "holdout_hash": self.holdout_hash,
            "development_count": len(self.development),
            "holdout_count": len(self.holdout),
            "required_rows_by_percent": self.required_rows_by_percent,
            "required_effective_days": self.required_effective_days,
            "percentage": self.percentage,
            "status": self.status,
        }

    def to_manifest(self) -> dict[str, object]:
        return {**self._payload_without_hash(), "content_hash": self.content_hash}


def select_locked_holdout(
    rows: Sequence[HoldoutRow],
    *,
    percentage: float = 0.15,
    effective_days: int = 40,
) -> HoldoutSelection:
    expected = _selection_payload(tuple(rows), percentage, effective_days)
    payload = {
        "source_hash": expected["source_hash"],
        "holdout_hash": expected["holdout_hash"],
        "development_count": len(cast(tuple[HoldoutRow, ...], expected["development"])),
        "holdout_count": len(cast(tuple[HoldoutRow, ...], expected["holdout"])),
        "required_rows_by_percent": expected["percent_count"],
        "required_effective_days": effective_days,
        "percentage": percentage,
        "status": expected["status"],
    }
    return HoldoutSelection(
        cast(tuple[HoldoutRow, ...], expected["development"]),
        cast(tuple[HoldoutRow, ...], expected["holdout"]),
        cast(int, expected["percent_count"]),
        effective_days,
        percentage,
        cast(Literal["READY", "RESEARCH_INSUFFICIENT_DATA"], expected["status"]),
        cast(str, expected["source_hash"]),
        cast(str, expected["holdout_hash"]),
        _hash(payload),
    )


@dataclass(frozen=True, slots=True)
class FrozenCandidate:
    hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        if set(self.hashes) != set(REQUIRED_FREEZE_COMPONENTS):
            raise ValueError("freeze requires model/features/labels/parameters/thresholds/rules hashes")
        for name, value in self.hashes.items():
            _sha256(value, name)
        object.__setattr__(self, "hashes", MappingProxyType(dict(sorted(self.hashes.items()))))

    @property
    def content_hash(self) -> str:
        return _hash(dict(self.hashes))


@dataclass(frozen=True, slots=True)
class HoldoutToken:
    token: str
    candidate_hash: str


@dataclass(frozen=True, slots=True)
class HoldoutCostModel:
    entry_fee_points: float
    exit_fee_points: float
    tax_points: float
    slippage_points: float

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0.0
            for value in (self.entry_fee_points, self.exit_fee_points, self.tax_points, self.slippage_points)
        ):
            raise ValueError("complete finite non-negative holdout cost inputs are required")

    @property
    def round_trip_cost_points(self) -> float:
        return self.entry_fee_points + self.exit_fee_points + self.tax_points + self.slippage_points

    @property
    def content_hash(self) -> str:
        return _hash([self.entry_fee_points, self.exit_fee_points, self.tax_points, self.slippage_points])


@dataclass(frozen=True, slots=True)
class HoldoutPrediction:
    row_id: str
    outcome: int
    probability: float
    event_id: str
    regime: str
    target_code: str

    def __post_init__(self) -> None:
        if (
            not self.row_id.strip() or not self.event_id.strip() or not self.regime.strip() or not self.target_code.strip()
            or isinstance(self.outcome, bool) or self.outcome not in (0, 1)
            or not isinstance(self.probability, (int, float)) or isinstance(self.probability, bool)
            or not math.isfinite(self.probability) or not 0.0 <= self.probability <= 1.0
        ):
            raise ValueError("invalid holdout prediction evidence")


@dataclass(frozen=True, slots=True)
class HoldoutTrade:
    row_id: str
    direction: Literal["LONG", "SHORT"]
    gross_points: float
    cost_points: float
    net_points: float
    event_id: str
    regime: str
    target_code: str

    def __post_init__(self) -> None:
        if (
            not self.row_id.strip() or self.direction not in ("LONG", "SHORT")
            or not self.event_id.strip() or not self.regime.strip() or not self.target_code.strip()
            or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in (self.gross_points, self.cost_points, self.net_points))
            or self.cost_points < 0.0
            or not math.isclose(self.net_points, self.gross_points - self.cost_points, rel_tol=1e-9, abs_tol=1e-9)
        ):
            raise ValueError("invalid executable holdout trade/cost evidence")


@dataclass(frozen=True, slots=True, init=False)
class LockedHoldoutEvaluation:
    candidate_hash: str
    evaluation_hash: str
    epoch: int
    status: Literal["PASSED", "FAILED"]
    row_count: int
    trade_count: int
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    net_pnl: float
    net_ev: float
    event_concentration: float
    cost_model_hash: str
    terminal_anchor_hash: str
    reasons: tuple[str, ...]
    authority: Literal["RAW_DERIVED", "TEST_ONLY"]
    _root: Path
    _witness: TrustedWitness
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> LockedHoldoutEvaluation:
        raise TypeError("holdout evaluations must be issued by the durable vault evaluator")

    def __post_init__(self) -> None:
        if self._seal is not _EVALUATION_SEAL or self.status not in ("PASSED", "FAILED"):
            raise TypeError("invalid holdout evaluation authority")
        if self.authority not in ("RAW_DERIVED", "TEST_ONLY"):
            raise TypeError("unknown holdout evaluation derivation authority")
        for value in (self.candidate_hash, self.evaluation_hash, self.cost_model_hash, self.terminal_anchor_hash):
            _sha256(value, "evaluation")
        if any(not math.isfinite(value) for value in (self.brier_score, self.log_loss, self.expected_calibration_error, self.net_pnl, self.net_ev, self.event_concentration)):
            raise ValueError("holdout evaluation metrics must be finite")

    def assert_current(self) -> None:
        if self._seal is not _EVALUATION_SEAL:
            raise HoldoutAccessError("holdout evaluation authority is invalid")
        LockedHoldout(self._root, witness=self._witness)
        state = _read_state(self._root)
        terminal_anchor = _read_holdout_anchors(self._root)[-1]
        path = self._root / f"holdout.evaluation.{self.evaluation_hash}.json"
        if (
            state.get("status") != "EVALUATED"
            or state.get("epoch") != self.epoch
            or state.get("evaluation_hash") != self.evaluation_hash
            or state.get("evaluation_status") != self.status
            or not path.is_file() or _hash(_object(path)) != self.evaluation_hash
            or _approval_state_hash(state) != state.get("approval_state_hash")
            or _hash(terminal_anchor) != self.terminal_anchor_hash
        ):
            raise HoldoutAccessError("holdout evaluation is stale or no longer current")


@dataclass(frozen=True, slots=True, init=False)
class LockedHoldoutApprovalEvidence:
    selection_hash: str
    candidate_hash: str
    model_hash: str
    data_hash: str
    state_hash: str
    evaluation_hash: str
    cost_model_hash: str
    terminal_anchor_hash: str
    candidate_hashes: Mapping[str, str]
    epoch: int
    status: Literal["PASSED"]
    authority: Literal["RAW_DERIVED", "TEST_ONLY"]
    _root: Path
    _witness: TrustedWitness
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> LockedHoldoutApprovalEvidence:
        raise TypeError("holdout approval evidence must be issued by a consumed locked holdout")

    def __post_init__(self) -> None:
        if self._seal is not _APPROVAL_SEAL or self.status != "PASSED":
            raise TypeError("locked holdout approval evidence can only be issued by a verified consumed holdout")
        if self.authority not in ("RAW_DERIVED", "TEST_ONLY"):
            raise TypeError("unknown holdout approval derivation authority")
        for name, value in (
            ("selection", self.selection_hash), ("candidate", self.candidate_hash), ("model", self.model_hash),
            ("data", self.data_hash), ("state", self.state_hash),
            ("evaluation", self.evaluation_hash),
            ("cost_model", self.cost_model_hash),
            ("terminal_anchor", self.terminal_anchor_hash),
        ):
            _sha256(value, name)
        if set(self.candidate_hashes) != set(REQUIRED_FREEZE_COMPONENTS):
            raise ValueError("holdout approval candidate hashes are incomplete")

    def assert_current(self) -> None:
        LockedHoldout(self._root, witness=self._witness)
        state = _read_state(self._root)
        terminal_anchor = _read_holdout_anchors(self._root)[-1]
        if (
            state.get("status") != "EVALUATED" or state.get("evaluation_status") != "PASSED"
            or state.get("epoch") != self.epoch or state.get("evaluation_hash") != self.evaluation_hash
            or _approval_state_hash(state) != self.state_hash or state.get("approval_state_hash") != self.state_hash
            or _hash(terminal_anchor) != self.terminal_anchor_hash
        ):
            raise HoldoutAccessError("locked holdout approval evidence is stale or not current")


class LockedHoldout:
    """Durable fail-closed capability for a canonical, sufficient terminal suffix."""

    __slots__ = ("_root", "_witness")

    def __init__(self, root: Path, *, witness: TrustedWitness | None = None) -> None:
        self._root = root
        self._witness = SqliteTrustedWitness() if witness is None else witness
        _require_external_witness(self._witness, root)
        self._verify_witness()
        self._verify_files(contaminate=True)

    @classmethod
    def create(
        cls,
        root: Path,
        selection: HoldoutSelection,
        *,
        witness: TrustedWitness | None = None,
        lineage_commitment_hash: str | None = None,
    ) -> LockedHoldout:
        if not isinstance(selection, HoldoutSelection):
            raise TypeError("LockedHoldout.create requires a canonical HoldoutSelection")
        if selection.status != "READY" or not selection.development or not selection.holdout:
            raise ValueError("insufficient or empty locked holdout selection cannot be persisted")
        canonical = select_locked_holdout(
            selection.development + selection.holdout,
            percentage=selection.percentage,
            effective_days=selection.required_effective_days,
        )
        if canonical != selection:
            raise ValueError("locked holdout selection must be revalidated before persistence")
        if lineage_commitment_hash is not None:
            _sha256(lineage_commitment_hash, "dataset lineage commitment")
        if root.exists():
            raise FileExistsError(root)
        audit_root = _external_holdout_audit_root(root)
        if audit_root.exists():
            raise FileExistsError(audit_root)
        audit_root.mkdir(parents=True)
        (audit_root / "anchors").mkdir()
        root.mkdir(parents=True)
        data = _canonical([row.to_dict() for row in selection.holdout])
        manifest = selection.to_manifest()
        manifest_hash = _hash(manifest)
        genesis = {
            "version": 2,
            "manifest_hash": manifest_hash,
            "selection_hash": selection.content_hash,
            "data_hash": hashlib.sha256(data).hexdigest(),
            "lineage_commitment_hash": lineage_commitment_hash,
        }
        genesis_hash = _hash(genesis)
        _write_exclusive(root / "holdout.data.json", data)
        _write_exclusive(root / "holdout.manifest.json", _canonical(manifest))
        _write_exclusive(root / f"holdout.genesis.{genesis_hash}.json", _canonical(genesis))
        state: dict[str, object] = {
            "version": 2,
            "status": "LOCKED",
            "genesis_hash": genesis_hash,
            "manifest_hash": manifest_hash,
            "selection_hash": selection.content_hash,
            "data_hash": hashlib.sha256(data).hexdigest(),
            "lineage_commitment_hash": lineage_commitment_hash,
            "row_count": len(selection.holdout),
            "candidate_hash": None,
            "candidate_hashes": None,
            "token_hash": None,
            "unlock_count": 0,
            "read_count": 0,
            "epoch": 0,
            "evaluation_hash": None,
            "evaluation_status": None,
            "evaluation_authority": None,
            "approval_state_hash": None,
            "contamination_reasons": [],
        }
        _write_state(root / "holdout.state.json", state, exclusive=True)
        _append_holdout_anchor(root, state)
        authority = SqliteTrustedWitness() if witness is None else witness
        _require_external_witness(authority, root)
        subject = witness_subject("HOLDOUT", secrets.token_bytes(32), genesis_hash)
        receipt = authority.register(subject, _hash(state))
        _write_exclusive(root / "witness.receipt.json", _canonical(_receipt(receipt)))
        return cls(root, witness=authority)

    @property
    def status(self) -> HoldoutStatus:
        return cast(HoldoutStatus, self._state()["status"])

    @property
    def contaminated(self) -> bool:
        return self.status == "CONTAMINATED"

    @property
    def contamination_reasons(self) -> tuple[str, ...]:
        return tuple(str(value) for value in _list(self._state()["contamination_reasons"]))

    def assert_lineage_commitment(self, lineage_hash: str) -> None:
        _sha256(lineage_hash, "dataset lineage commitment")
        state = self._state()
        genesis = _object(next(iter(self._root.glob("holdout.genesis.*.json"))))
        if (
            state.get("lineage_commitment_hash") != lineage_hash
            or genesis.get("lineage_commitment_hash") != lineage_hash
        ):
            raise HoldoutAccessError("holdout lineage commitment mismatch")

    def freeze(self, candidate: FrozenCandidate) -> None:
        self._verify_files(contaminate=True)
        state = self._state()
        if state["status"] != "LOCKED":
            self._contaminate("INVALID_FREEZE_TRANSITION")
            raise HoldoutAccessError("holdout may be frozen exactly once from LOCKED")
        state["candidate_hash"] = candidate.content_hash
        state["candidate_hashes"] = dict(candidate.hashes)
        state["epoch"] = _integer(state["epoch"]) + 1
        state["status"] = "FROZEN"
        self._save(state)

    def unlock_once(self, candidate: FrozenCandidate) -> HoldoutToken:
        self._verify_files(contaminate=True)
        state = self._state()
        if state["status"] != "FROZEN" or state["candidate_hash"] != candidate.content_hash:
            self._contaminate("UNLOCK_BEFORE_EXACT_FREEZE_OR_RETRY")
            raise HoldoutAccessError("holdout unlock requires the exact frozen candidate and is single-use")
        raw = secrets.token_hex(32)
        state["status"] = "UNLOCKED"
        state["unlock_count"] = _integer(state["unlock_count"]) + 1
        state["token_hash"] = hashlib.sha256(raw.encode("ascii")).hexdigest()
        self._save(state)
        return HoldoutToken(raw, candidate.content_hash)

    def read_once(self, token: HoldoutToken) -> tuple[HoldoutRow, ...]:
        self._verify_files(contaminate=True)
        state = self._state()
        expected_token = hashlib.sha256(token.token.encode("ascii")).hexdigest()
        if (
            state["status"] != "UNLOCKED"
            or state["token_hash"] != expected_token
            or state["candidate_hash"] != token.candidate_hash
        ):
            self._contaminate("HOLDOUT_READ_RETRY_OR_INVALID_TOKEN")
            raise HoldoutAccessError("holdout is unreadable before exact freeze/unlock or after its single read")
        before = (self._root / "holdout.data.json").read_bytes()
        rows = tuple(_row(value) for value in _list(json.loads(before)))
        after = (self._root / "holdout.data.json").read_bytes()
        if before != after or hashlib.sha256(after).hexdigest() != state["data_hash"]:
            self._contaminate("HOLDOUT_DATA_MUTATED_DURING_READ")
            raise HoldoutAccessError("holdout data changed during the single evaluation")
        manifest = self._manifest()
        if _hash([row.to_dict() for row in rows]) != manifest["holdout_hash"]:
            self._contaminate("HOLDOUT_CONTENT_HASH_MISMATCH")
            raise HoldoutAccessError("holdout rows do not match the frozen canonical suffix")
        state["status"] = "CONSUMED"
        state["read_count"] = _integer(state["read_count"]) + 1
        self._save(state)
        self._verify_files(contaminate=True)
        return rows

    def evaluate_once(
        self,
        bundle: object,
        policy: object,
    ) -> LockedHoldoutEvaluation:
        from tmf_research.experiments.registry import phase4_candidate_hashes
        from tmf_research.models.provenance import FrozenDecisionPolicy, canonical_hash
        from tmf_research.models.serialization import ModelBundle

        if not isinstance(bundle, ModelBundle) or not isinstance(policy, FrozenDecisionPolicy):
            raise TypeError("production holdout evaluation requires ModelBundle + FrozenDecisionPolicy")
        state = self._state()
        hashes = phase4_candidate_hashes(bundle)
        candidate = FrozenCandidate(hashes)
        self.assert_candidate_unchanged(candidate)
        if (
            policy.thresholds_hash != hashes["thresholds"]
            or policy.rules_hash != hashes["rules"]
            or policy.calibration_hash != canonical_hash(bundle.calibrator.to_dict())
        ):
            self._contaminate("HOLDOUT_POLICY_OR_MODEL_MISMATCH")
            raise HoldoutAccessError("holdout policy does not match frozen model candidate")
        if state["status"] != "FROZEN":
            self._contaminate("PRODUCTION_HOLDOUT_NOT_EXACTLY_FROZEN")
            raise HoldoutAccessError("production holdout scoring consumes the frozen vault internally")
        before = (self._root / "holdout.data.json").read_bytes()
        if hashlib.sha256(before).hexdigest() != state["data_hash"]:
            self._contaminate("HOLDOUT_DATA_MUTATED_DURING_READ")
            raise HoldoutAccessError("holdout data changed before production scoring")
        state["status"] = "CONSUMED"
        state["unlock_count"] = 1
        state["read_count"] = 1
        self._save(state)
        rows = tuple(_row(value) for value in _list(json.loads(
            before,
        )))
        predictions = []
        trades = []
        cost_hashes: set[str] = set()
        for row in rows:
            source, outcome = _production_payload(row)
            inference = bundle.predict(_feature_mapping(source))
            p_trade = 1.0 - inference.probabilities.p_no_trade
            p_long = (
                inference.probabilities.p_long / p_trade if p_trade > 0.0 else 0.5
            )
            signal = (
                "NO_TRADE" if p_trade < policy.trade_threshold
                else "LONG" if p_long >= policy.direction_threshold else "SHORT"
            )
            label = str(source["label"])
            predictions.append(HoldoutPrediction(
                row.row_id, int(label in ("LONG", "SHORT")), p_trade,
                str(outcome["event_id"]), str(outcome["regime"]),
                str(outcome["target_code"]),
            ))
            cost_hashes.add(str(outcome["cost_policy_hash"]))
            if signal != "NO_TRADE":
                net = _number(outcome[
                    "long_net_points" if signal == "LONG" else "short_net_points"
                ])
                trades.append(HoldoutTrade(
                    row.row_id, cast(Literal["LONG", "SHORT"], signal),
                    net, 0.0, net, str(outcome["event_id"]),
                    str(outcome["regime"]), str(outcome["target_code"]),
                ))
        if len(cost_hashes) != 1:
            self._contaminate("HOLDOUT_COST_POLICY_MISMATCH")
            raise HoldoutAccessError("one exact raw-derived holdout cost policy is required")
        return self._evaluate_values(
            candidate, tuple(predictions), tuple(trades), next(iter(cost_hashes)),
            expected_cost_points=0.0, authority="RAW_DERIVED",
            extra_commitments={
                "model_hash": hashes["model"], "policy_hash": policy.content_hash,
                "lineage_hash": state.get("lineage_commitment_hash"),
            },
        )

    def evaluate_test_only(
        self,
        candidate: FrozenCandidate,
        predictions: Sequence[HoldoutPrediction],
        trades: Sequence[HoldoutTrade],
        cost_model: HoldoutCostModel,
    ) -> LockedHoldoutEvaluation:
        return self._evaluate_values(
            candidate, tuple(predictions), tuple(trades), cost_model.content_hash,
            expected_cost_points=cost_model.round_trip_cost_points,
            authority="TEST_ONLY", extra_commitments={},
        )

    def _evaluate_values(
        self,
        candidate: FrozenCandidate,
        prediction_values: tuple[HoldoutPrediction, ...],
        trade_values: tuple[HoldoutTrade, ...],
        cost_model_hash: str,
        *,
        expected_cost_points: float,
        authority: str,
        extra_commitments: Mapping[str, object],
    ) -> LockedHoldoutEvaluation:
        self.assert_candidate_unchanged(candidate)
        state = self._state()
        if state["status"] != "CONSUMED" or state["evaluation_hash"] is not None:
            self._contaminate("HOLDOUT_EVALUATION_RETRY_OR_INVALID_STATE")
            raise HoldoutAccessError("holdout evaluation is single-use after the exact read")
        rows = tuple(_row(value) for value in _list(json.loads((self._root / "holdout.data.json").read_bytes())))
        row_ids = tuple(row.row_id for row in rows)
        if (
            tuple(value.row_id for value in prediction_values) != row_ids
            or len({value.row_id for value in prediction_values}) != len(prediction_values)
            or len({value.row_id for value in trade_values}) != len(trade_values)
            or any(value.row_id not in set(row_ids) for value in trade_values)
            or any(not math.isclose(value.cost_points, expected_cost_points, rel_tol=1e-9, abs_tol=1e-9) for value in trade_values)
        ):
            self._contaminate("HOLDOUT_EVALUATION_PROVENANCE_MISMATCH")
            raise HoldoutAccessError("holdout predictions/trades/costs do not align with frozen rows")
        epsilon = 1e-15
        brier = sum((value.probability - value.outcome) ** 2 for value in prediction_values) / len(prediction_values)
        log_loss = -sum(
            value.outcome * math.log(max(epsilon, value.probability))
            + (1 - value.outcome) * math.log(max(epsilon, 1.0 - value.probability))
            for value in prediction_values
        ) / len(prediction_values)
        ece = abs(sum(value.probability for value in prediction_values) / len(prediction_values) - sum(value.outcome for value in prediction_values) / len(prediction_values))
        net_pnl = sum(value.net_points for value in trade_values)
        net_ev = net_pnl / len(trade_values) if trade_values else 0.0
        event_pnl: dict[str, float] = {}
        regime_pnl: dict[str, float] = {}
        target_pnl: dict[str, float] = {}
        for value in trade_values:
            event_pnl[value.event_id] = event_pnl.get(value.event_id, 0.0) + value.net_points
            regime_pnl[value.regime] = regime_pnl.get(value.regime, 0.0) + value.net_points
            target_pnl[value.target_code] = target_pnl.get(value.target_code, 0.0) + value.net_points
        event_concentration = max((max(0.0, value) / net_pnl for value in event_pnl.values()), default=1.0) if net_pnl > 0.0 else 1.0
        reasons: list[str] = []
        if len(rows) < 40 or len({row.trading_date for row in rows}) < 40:
            reasons.append("INSUFFICIENT_HOLDOUT_SAMPLE")
        long_count = sum(value.direction == "LONG" for value in trade_values)
        short_count = len(trade_values) - long_count
        if len(trade_values) < 30 or long_count < 10 or short_count < 10:
            reasons.append("INSUFFICIENT_HOLDOUT_TRADES")
        if brier > 0.25 or log_loss > math.log(2.0) or ece > 0.10:
            reasons.append("HOLDOUT_CALIBRATION_FAILED")
        if net_pnl <= 0.0 or net_ev < 0.0:
            reasons.append("HOLDOUT_NET_EV_OR_COST_FAILED")
        if event_concentration > 0.40:
            reasons.append("HOLDOUT_EVENT_CONCENTRATION_FAILED")
        if any(value < 0.0 for value in regime_pnl.values()) or any(value < 0.0 for value in target_pnl.values()):
            reasons.append("HOLDOUT_REGIME_OR_TARGET_STABILITY_FAILED")
        payload = {
            "candidate_hash": candidate.content_hash, "epoch": state["epoch"],
            "row_count": len(rows), "trade_count": len(trade_values),
            "brier_score": brier, "log_loss": log_loss, "expected_calibration_error": ece,
            "net_pnl": net_pnl, "net_ev": net_ev, "event_concentration": event_concentration,
            "cost_model_hash": cost_model_hash, "authority": authority,
            "reasons": reasons, "status": "PASSED" if not reasons else "FAILED",
            "prediction_hash": _hash([_prediction_payload(value) for value in prediction_values]),
            "trade_hash": _hash([_trade_payload(value) for value in trade_values]),
            **dict(extra_commitments),
        }
        evaluation_hash = _hash(payload)
        _write_exclusive(self._root / f"holdout.evaluation.{evaluation_hash}.json", _canonical(payload))
        state["status"] = "EVALUATED"
        state["evaluation_hash"] = evaluation_hash
        state["evaluation_status"] = payload["status"]
        state["evaluation_authority"] = authority
        state["approval_state_hash"] = None
        state["approval_state_hash"] = _approval_state_hash(state)
        self._save(state)
        terminal_anchor_hash = _hash(_read_holdout_anchors(self._root)[-1])
        return _sealed_evaluation(
            self._root, payload, evaluation_hash, terminal_anchor_hash, self._witness,
        )

    def assert_candidate_unchanged(self, candidate: FrozenCandidate) -> None:
        self._verify_files(contaminate=True)
        state = self._state()
        if state["candidate_hash"] != candidate.content_hash or state["candidate_hashes"] != dict(candidate.hashes):
            self._contaminate("POST_HOLDOUT_CANDIDATE_MUTATION")
            raise HoldoutAccessError("candidate model/features/labels/parameters/thresholds/rules changed")

    def mark_rerun_attempt(self) -> None:
        self._contaminate("LOCKED_HOLDOUT_RERUN_ATTEMPT")
        raise HoldoutAccessError("locked holdout cannot be re-run")

    def approval_evidence(self, candidate: FrozenCandidate) -> LockedHoldoutApprovalEvidence:
        self._verify_witness()
        self.assert_candidate_unchanged(candidate)
        self._verify_files(contaminate=True)
        state = self._state()
        if not self._approval_eligible_state(state, candidate):
            raise HoldoutAccessError("locked holdout is not eligible for approval")
        evaluation = _object(self._root / f"holdout.evaluation.{state['evaluation_hash']}.json")
        if evaluation.get("authority") != "RAW_DERIVED":
            raise HoldoutAccessError("TEST_ONLY holdout evaluation cannot mint approval evidence")
        return _sealed_approval(
            selection_hash=str(state["selection_hash"]),
            candidate_hash=candidate.content_hash,
            model_hash=candidate.hashes["model"],
            data_hash=str(state["data_hash"]),
            state_hash=_approval_state_hash(state),
            evaluation_hash=str(state["evaluation_hash"]),
            cost_model_hash=str(evaluation["cost_model_hash"]),
            terminal_anchor_hash=_hash(_read_holdout_anchors(self._root)[-1]),
            candidate_hashes=MappingProxyType(dict(candidate.hashes)),
            epoch=_integer(state["epoch"]),
            authority=str(evaluation["authority"]),
            _root=self._root,
            _witness=self._witness,
        )

    def approval_eligible(self, candidate: FrozenCandidate) -> bool:
        try:
            self.approval_evidence(candidate)
        except (HoldoutAccessError, OSError, ValueError):
            return False
        return True

    def _approval_eligible_state(self, state: Mapping[str, object], candidate: FrozenCandidate) -> bool:
        return (
            state["status"] == "EVALUATED"
            and state["evaluation_status"] == "PASSED"
            and state["candidate_hash"] == candidate.content_hash
            and state["candidate_hashes"] == dict(candidate.hashes)
            and _integer(state["unlock_count"]) == 1
            and _integer(state["read_count"]) == 1
            and _integer(state["row_count"]) > 0
            and not _list(state["contamination_reasons"])
            and state["approval_state_hash"] == _approval_state_hash(state)
            and self._manifest()["status"] == "READY"
        )

    def _verify_files(self, *, contaminate: bool) -> None:
        try:
            state = self._state()
            _verify_holdout_audit(self._root, state)
            genesis_files = tuple(self._root.glob("holdout.genesis.*.json"))
            if len(genesis_files) != 1:
                raise HoldoutAccessError("exactly one immutable holdout genesis is required")
            genesis_file = genesis_files[0]
            genesis = _object(genesis_file)
            genesis_hash = _hash(genesis)
            if genesis_file.name != f"holdout.genesis.{genesis_hash}.json" or state["genesis_hash"] != genesis_hash:
                raise HoldoutAccessError("holdout genesis anchor mismatch")
            manifest = self._manifest()
            manifest_hash = _hash(manifest)
            data = (self._root / "holdout.data.json").read_bytes()
            data_hash = hashlib.sha256(data).hexdigest()
            if (
                genesis["manifest_hash"] != manifest_hash
                or genesis["selection_hash"] != manifest["content_hash"]
                or genesis["data_hash"] != data_hash
                or genesis.get("lineage_commitment_hash")
                != state.get("lineage_commitment_hash")
                or state["manifest_hash"] != manifest_hash
                or state["selection_hash"] != manifest["content_hash"]
                or state["data_hash"] != data_hash
                or manifest["status"] != "READY"
                or _integer(manifest["holdout_count"]) <= 0
                or _integer(manifest["development_count"]) <= 0
            ):
                raise HoldoutAccessError("holdout data/manifest/genesis integrity failure")
            values = tuple(_row(value) for value in _list(json.loads(data)))
            if len(values) != _integer(manifest["holdout_count"]) or _hash([row.to_dict() for row in values]) != manifest["holdout_hash"]:
                raise HoldoutAccessError("holdout data content does not match manifest")
            evaluation_hash = state.get("evaluation_hash")
            evaluation_files = tuple(self._root.glob("holdout.evaluation.*.json"))
            if evaluation_hash is None:
                if evaluation_files:
                    raise HoldoutAccessError("unanchored holdout evaluation file detected")
            elif (
                not isinstance(evaluation_hash, str) or len(evaluation_files) != 1
                or evaluation_files[0].name != f"holdout.evaluation.{evaluation_hash}.json"
                or _hash(_object(evaluation_files[0])) != evaluation_hash
            ):
                raise HoldoutAccessError("holdout evaluation anchor mismatch")
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, HoldoutAccessError) as error:
            if contaminate:
                self._contaminate("HOLDOUT_INTEGRITY_FAILURE")
            if isinstance(error, HoldoutAccessError):
                raise
            raise HoldoutAccessError("holdout integrity verification failed") from error

    def _manifest(self) -> dict[str, object]:
        return _object(self._root / "holdout.manifest.json")

    def _state(self) -> dict[str, object]:
        envelope = _object(self._root / "holdout.state.json")
        if set(envelope) != {"state", "checksum"}:
            raise HoldoutAccessError("holdout state envelope invalid")
        state = envelope["state"]
        if not isinstance(state, dict) or envelope["checksum"] != _hash(state):
            raise HoldoutAccessError("holdout state checksum invalid")
        return cast(dict[str, object], state)

    def _save(self, state: Mapping[str, object]) -> None:
        expected = _witness_receipt(self._root)
        _append_holdout_anchor(self._root, state)
        _write_state(self._root / "holdout.state.json", state, exclusive=False)
        advanced = self._witness.compare_and_swap(expected, _hash(state))
        _replace_receipt(self._root / "witness.receipt.json", advanced)

    def _contaminate(self, reason: str) -> None:
        try:
            state = self._state()
        except (OSError, ValueError, HoldoutAccessError):
            return
        reasons = [str(value) for value in _list(state["contamination_reasons"])]
        try:
            latest = _read_holdout_anchors(self._root)[-1]
            reasons.extend(
                value for value in (str(item) for item in _list(latest["contamination_reasons"]))
                if value not in reasons
            )
            latest_epoch = _integer(latest["epoch"])
        except (OSError, ValueError, HoldoutAccessError):
            latest_epoch = _integer(state.get("epoch", 0))
        if reason not in reasons:
            reasons.append(reason)
        state["contamination_reasons"] = reasons
        state["status"] = "CONTAMINATED"
        state["epoch"] = max(_integer(state.get("epoch", 0)), latest_epoch) + 1
        state["approval_state_hash"] = None
        self._save(state)

    def _verify_witness(self) -> None:
        receipt = _witness_receipt(self._root)
        try:
            current = self._witness.current(receipt.subject)
        except WitnessMissing as error:
            raise HoldoutAccessError("trusted holdout witness is missing") from error
        state = _read_state(self._root)
        local_head = _hash(state)
        if current == receipt and local_head == receipt.head:
            return
        if current.count == receipt.count + 1 and local_head == current.head:
            _replace_receipt(self._root / "witness.receipt.json", current)
            return
        raise HoldoutAccessError("trusted holdout witness rejects local rollback or divergence")


def _selection_payload(rows: tuple[HoldoutRow, ...], percentage: float, effective_days: int) -> dict[str, object]:
    if (
        isinstance(percentage, bool) or not isinstance(percentage, (int, float))
        or not math.isfinite(percentage) or not 0.15 <= percentage < 1.0
        or isinstance(effective_days, bool) or not isinstance(effective_days, int)
        or effective_days < 40
    ):
        raise ValueError("invalid locked holdout sizing")
    if not rows or len({row.row_id for row in rows}) != len(rows):
        raise ValueError("locked holdout requires non-empty unique chronological rows")
    dates = tuple(row.trading_date for row in rows)
    if dates != tuple(sorted(dates)):
        raise ValueError("holdout input must be chronological")
    distinct_dates = tuple(dict.fromkeys(dates))
    percent_count = math.ceil(len(rows) * percentage)
    percent_start = len(rows) - percent_count
    if len(distinct_dates) >= effective_days:
        first_required_date = distinct_dates[-effective_days]
        day_start = next(index for index, row in enumerate(rows) if row.trading_date == first_required_date)
        status: Literal["READY", "RESEARCH_INSUFFICIENT_DATA"] = "READY"
    else:
        day_start = 0
        status = "RESEARCH_INSUFFICIENT_DATA"
    start = min(percent_start, day_start)
    development, holdout = rows[:start], rows[start:]
    if not development or not holdout:
        status = "RESEARCH_INSUFFICIENT_DATA"
    return {
        "development": development,
        "holdout": holdout,
        "percent_count": percent_count,
        "status": status,
        "source_hash": _hash([row.to_dict() for row in rows]),
        "holdout_hash": _hash([row.to_dict() for row in holdout]),
    }


def _sealed_approval(**values: object) -> LockedHoldoutApprovalEvidence:
    instance = object.__new__(LockedHoldoutApprovalEvidence)
    for name, value in (*values.items(), ("status", "PASSED"), ("_seal", _APPROVAL_SEAL)):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _sealed_evaluation(
    root: Path,
    payload: Mapping[str, object],
    evaluation_hash: str,
    terminal_anchor_hash: str,
    witness: TrustedWitness,
) -> LockedHoldoutEvaluation:
    instance = object.__new__(LockedHoldoutEvaluation)
    values: dict[str, object] = {
        "candidate_hash": payload["candidate_hash"], "evaluation_hash": evaluation_hash,
        "epoch": payload["epoch"], "status": payload["status"],
        "row_count": payload["row_count"], "trade_count": payload["trade_count"],
        "brier_score": payload["brier_score"], "log_loss": payload["log_loss"],
        "expected_calibration_error": payload["expected_calibration_error"],
        "net_pnl": payload["net_pnl"], "net_ev": payload["net_ev"],
        "event_concentration": payload["event_concentration"],
        "cost_model_hash": payload["cost_model_hash"],
        "terminal_anchor_hash": terminal_anchor_hash,
        "reasons": tuple(str(value) for value in _list(payload["reasons"])),
        "authority": payload["authority"],
        "_root": root, "_witness": witness, "_seal": _EVALUATION_SEAL,
    }
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _prediction_payload(value: HoldoutPrediction) -> list[object]:
    return [value.row_id, value.outcome, value.probability, value.event_id, value.regime, value.target_code]


def _trade_payload(value: HoldoutTrade) -> list[object]:
    return [
        value.row_id, value.direction, value.gross_points, value.cost_points,
        value.net_points, value.event_id, value.regime, value.target_code,
    ]


def _production_payload(
    row: HoldoutRow,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    from tmf_research.models.provenance import canonical_hash

    source = row.payload.get("source")
    outcome = row.payload.get("outcome")
    if not isinstance(source, Mapping) or not isinstance(outcome, Mapping):
        raise HoldoutAccessError("production holdout row lacks sealed source/outcome")
    if source.get("row_id") != row.row_id or outcome.get("row_id") != row.row_id:
        raise HoldoutAccessError("production holdout row identity mismatch")
    source_hash = canonical_hash(dict(source))
    if outcome.get("source_row_hash") != source_hash:
        raise HoldoutAccessError("production holdout source commitment mismatch")
    body = {key: value for key, value in outcome.items() if key != "content_hash"}
    if outcome.get("content_hash") != canonical_hash(body):
        raise HoldoutAccessError("production executable outcome commitment mismatch")
    for name in (
        "cost_policy_hash", "event_id", "regime", "target_code",
        "long_net_points", "short_net_points",
    ):
        if name not in outcome:
            raise HoldoutAccessError("production executable outcome is incomplete")
    return source, outcome


def _feature_mapping(source: Mapping[str, object]) -> Mapping[str, float | None]:
    values = source.get("features")
    if not isinstance(values, Mapping):
        raise HoldoutAccessError("production holdout source features are invalid")
    result: dict[str, float | None] = {}
    for key, value in values.items():
        if not isinstance(key, str) or (
            value is not None
            and (not isinstance(value, (int, float)) or isinstance(value, bool))
        ):
            raise HoldoutAccessError("production holdout source features are invalid")
        result[key] = None if value is None else float(value)
    return MappingProxyType(result)


def _number(value: object) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise HoldoutAccessError("production executable return is invalid")
    return float(value)


def _approval_state_hash(state: Mapping[str, object]) -> str:
    return _hash({key: value for key, value in state.items() if key != "approval_state_hash"})


def _external_holdout_audit_root(root: Path) -> Path:
    return root.parent / f".{root.name}.phase5-holdout-audit"


def _require_external_witness(witness: TrustedWitness, artifact_root: Path) -> None:
    location = witness.location
    if location is not None and location.resolve().is_relative_to(artifact_root.resolve()):
        raise HoldoutAccessError("trusted witness must live outside the holdout vault")


def _receipt(head: WitnessHead) -> dict[str, object]:
    return {"subject": head.subject, "count": head.count, "head": head.head}


def _witness_receipt(root: Path) -> WitnessHead:
    value = _object(root / "witness.receipt.json")
    if set(value) != {"subject", "count", "head"}:
        raise HoldoutAccessError("holdout witness receipt is invalid")
    return WitnessHead(str(value["subject"]), _integer(value["count"]), str(value["head"]))


def _replace_receipt(path: Path, head: WitnessHead) -> None:
    temporary = path.with_suffix(".tmp")
    if temporary.exists():
        temporary.unlink()
    _write_exclusive(temporary, _canonical(_receipt(head)))
    os.replace(temporary, path)


def _append_holdout_anchor(root: Path, state: Mapping[str, object]) -> str:
    audit_root = _external_holdout_audit_root(root)
    anchor_files = tuple((audit_root / "anchors").glob("*.json"))
    existing = _read_holdout_anchors(root) if anchor_files else ()
    sequence = len(existing)
    if not existing and (state.get("status") != "LOCKED" or state.get("epoch") != 0):
        raise HoldoutAccessError("external holdout audit history cannot be recreated or shortened")
    previous = "0" * 64 if not existing else _hash(existing[-1])
    epoch = _integer(state["epoch"])
    if existing:
        latest = existing[-1]
        if epoch < _integer(latest["epoch"]):
            raise HoldoutAccessError("holdout epoch cannot move backwards")
        if latest["status"] == "CONTAMINATED" and state["status"] != "CONTAMINATED":
            raise HoldoutAccessError("holdout contamination is externally monotonic")
    anchor = {
        "sequence": sequence,
        "previous_anchor_hash": previous,
        "state_hash": _hash(state),
        "epoch": epoch,
        "status": state["status"],
        "evaluation_hash": state.get("evaluation_hash"),
        "contamination_reasons": list(_list(state["contamination_reasons"])),
    }
    anchor_hash = _hash(anchor)
    _write_exclusive(
        audit_root / "anchors" / f"{sequence:08d}-{anchor_hash}.json",
        _canonical(anchor),
    )
    return anchor_hash


def _read_holdout_anchors(root: Path) -> tuple[dict[str, object], ...]:
    files = tuple(sorted((_external_holdout_audit_root(root) / "anchors").glob("*.json")))
    if not files:
        raise HoldoutAccessError("external holdout audit is empty")
    previous = "0" * 64
    contaminated = False
    prior_epoch = -1
    anchors: list[dict[str, object]] = []
    for sequence, path in enumerate(files):
        anchor = _object(path)
        anchor_hash = _hash(anchor)
        epoch = _integer(anchor.get("epoch"))
        status = anchor.get("status")
        if (
            path.name != f"{sequence:08d}-{anchor_hash}.json"
            or _integer(anchor.get("sequence")) != sequence
            or anchor.get("previous_anchor_hash") != previous
            or epoch < prior_epoch
            or not isinstance(status, str)
            or (contaminated and status != "CONTAMINATED")
        ):
            raise HoldoutAccessError("external append-only holdout audit is invalid")
        _sha256(str(anchor.get("state_hash")), "holdout audit state")
        _list(anchor.get("contamination_reasons"))
        contaminated = contaminated or status == "CONTAMINATED"
        prior_epoch = epoch
        previous = anchor_hash
        anchors.append(anchor)
    return tuple(anchors)


def _verify_holdout_audit(root: Path, state: Mapping[str, object]) -> None:
    latest = _read_holdout_anchors(root)[-1]
    if (
        latest["state_hash"] != _hash(state)
        or _integer(latest["epoch"]) != _integer(state["epoch"])
        or latest["status"] != state["status"]
        or latest["evaluation_hash"] != state.get("evaluation_hash")
    ):
        raise HoldoutAccessError("external holdout terminal anchor rejects state rollback")


def _row(value: object) -> HoldoutRow:
    if not isinstance(value, dict) or not isinstance(value.get("payload"), dict):
        raise HoldoutAccessError("holdout row is invalid")
    return HoldoutRow(str(value["row_id"]), str(value["trading_date"]), cast(dict[str, object], value["payload"]))


def _write_state(path: Path, state: Mapping[str, object], *, exclusive: bool) -> None:
    envelope = {"state": dict(state), "checksum": _hash(state)}
    payload = _canonical(envelope)
    if exclusive:
        _write_exclusive(path, payload)
        return
    temporary = path.with_suffix(".tmp")
    if temporary.exists():
        temporary.unlink()
    _write_exclusive(temporary, payload)
    os.replace(temporary, path)


def _read_state(root: Path) -> dict[str, object]:
    envelope = _object(root / "holdout.state.json")
    state = envelope.get("state")
    if set(envelope) != {"state", "checksum"} or not isinstance(state, dict) or envelope["checksum"] != _hash(state):
        raise HoldoutAccessError("holdout durable state is invalid")
    return cast(dict[str, object], state)


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HoldoutAccessError("expected JSON object")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise HoldoutAccessError("expected list")
    return value


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise HoldoutAccessError("expected integer")
    return value


def _sha256(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"invalid {name} SHA-256")
