from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from tmf_research.domain.events import BidAskEvent, TickEvent
from tmf_research.features.context_builder import ResearchBuildSpec, build_feature_context
from tmf_research.features.definitions import default_feature_manifest
from tmf_research.features.pipeline import FeaturePipeline
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, SegmentManifest
from tmf_research.infrastructure.trusted_witness import TrustedWitness
from tmf_research.labeling.executable_prices import ExecutablePricePolicy
from tmf_research.labeling.pipeline import LabelPipeline
from tmf_research.labeling.triple_barrier import LabelParameters, TripleBarrierLabeler
from tmf_research.models.provenance import (
    NestedFoldManifest,
    Phase4FoldCapabilities,
    Phase4SourceRow,
    canonical_hash,
)
from tmf_research.processing.pipeline import ProcessingPipeline
from tmf_research.processing.bars import Bar
from tmf_research.processing.one_second import OneSecondState
from tmf_research.processing.quote_joiner import QuoteJoiner
from tmf_research.processing.raw_decoder import decode_bidask, decode_tick, validate_research_event
from tmf_research.processing.session_resolver import SessionResolver
from tmf_research.validation.data_provenance import DataProvenanceEvidence
from tmf_research.validation.folds import Phase5FoldPlanner, TemporalSample
from tmf_research.validation.locked_holdout import HoldoutRow, HoldoutSelection, LockedHoldout, select_locked_holdout


_LINEAGE_SEAL = object()
_BUILD_RESULT_SEAL = object()
LineageStatus = Literal["READY", "REJECTED_INSUFFICIENT_DATA"]


class DatasetValidationError(ValueError):
    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(sorted(set(reasons)))
        super().__init__(",".join(self.reasons))


@dataclass(frozen=True, slots=True, init=False)
class DatasetLineageEvidence:
    status: LineageStatus
    raw_dataset_hash: str
    segment_manifest_hashes: tuple[str, ...]
    build_spec_hash: str
    all_rows_hash: str
    development_rows_hash: str
    holdout_rows_hash: str
    temporal_sample_hashes: tuple[tuple[str, str], ...]
    development_row_ids: tuple[str, ...]
    holdout_row_ids: tuple[str, ...]
    fold_manifests: tuple[NestedFoldManifest, ...]
    fold_manifest_hashes: tuple[str, ...]
    holdout_selection_hash: str | None
    holdout_data_hash: str | None
    holdout_row_count: int
    content_hash: str
    _provenance: DataProvenanceEvidence
    _spec: ResearchBuildSpec
    _holdout_root: Path | None
    _witness: TrustedWitness
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> DatasetLineageEvidence:
        raise TypeError("dataset lineage must be issued from verified raw storage")

    def __post_init__(self) -> None:
        if self._seal is not _LINEAGE_SEAL:
            raise TypeError("invalid dataset lineage authority")
        for value in (
            self.raw_dataset_hash, self.build_spec_hash, self.all_rows_hash,
            self.development_rows_hash, self.holdout_rows_hash, self.content_hash,
            *self.segment_manifest_hashes, *self.fold_manifest_hashes,
        ):
            _sha256(value)
        if self.fold_manifest_hashes != tuple(value.content_hash for value in self.fold_manifests):
            raise ValueError("fold manifest hashes are not exact lineage commitments")
        if set(self.development_row_ids).intersection(self.holdout_row_ids):
            raise ValueError("development and locked holdout lineage must not overlap")
        committed = dict(self.temporal_sample_hashes)
        if len(committed) != len(self.temporal_sample_hashes):
            raise ValueError("temporal sample lineage requires unique row ids")
        if any(row_id not in self.development_row_ids for manifest in self.fold_manifests for role in (
            manifest.inner_train, manifest.inner_validation, manifest.outer_test,
        ) for row_id, _row_hash in role.row_hashes):
            raise ValueError("fold manifests may only commit development-prefix rows")
        for optional_hash in (self.holdout_selection_hash, self.holdout_data_hash):
            if optional_hash is not None:
                _sha256(optional_hash)

    def assert_current(self) -> None:
        self._provenance.assert_current()
        if self._spec.content_hash != self.build_spec_hash:
            raise ValueError("Phase 5 build context changed after lineage issuance")
        if self.status == "READY":
            if self._holdout_root is None:
                raise ValueError("ready lineage lost its locked holdout")
            LockedHoldout(self._holdout_root, witness=self._witness)
            if hashlib.sha256((self._holdout_root / "holdout.data.json").read_bytes()).hexdigest() != self.holdout_data_hash:
                raise ValueError("locked holdout no longer matches dataset lineage")

    def binds(
        self,
        folds: Sequence[object],
        *,
        selection_hash: str,
        data_hash: str,
    ) -> bool:
        self.assert_current()
        manifests = tuple(getattr(value, "manifest", None) for value in folds)
        return (
            self.status == "READY"
            and tuple(value.content_hash for value in manifests if isinstance(value, NestedFoldManifest))
            == self.fold_manifest_hashes
            and len(manifests) == len(self.fold_manifest_hashes)
            and selection_hash == self.holdout_selection_hash
            and data_hash == self.holdout_data_hash
        )


@dataclass(frozen=True, slots=True, init=False)
class DatasetBuildResult:
    lineage: DatasetLineageEvidence
    development_samples: tuple[TemporalSample, ...]
    fold_capabilities: tuple[Phase4FoldCapabilities, ...]
    rejection_reasons: tuple[str, ...]
    content_hash: str
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> DatasetBuildResult:
        raise TypeError("dataset build results must be issued from verified raw storage")

    def __post_init__(self) -> None:
        if self._seal is not _BUILD_RESULT_SEAL:
            raise TypeError("invalid dataset build result authority")
        if tuple(value.manifest for value in self.fold_capabilities) != self.lineage.fold_manifests:
            raise ValueError("build capabilities do not match sealed lineage fold manifests")
        development_ids = {value.source.row_id for value in self.development_samples}
        if any(
            row_id not in development_ids
            for capability in self.fold_capabilities
            for role in (
                capability.manifest.inner_train,
                capability.manifest.inner_validation,
                capability.manifest.outer_test,
            )
            for row_id, _row_hash in role.row_hashes
        ):
            raise ValueError("fold capabilities escape the development sample prefix")
        expected = canonical_hash({
            "lineage": self.lineage.content_hash,
            "development": [_sample_payload(value) for value in self.development_samples],
            "folds": [value.manifest.content_hash for value in self.fold_capabilities],
            "rejection_reasons": self.rejection_reasons,
        })
        if self.content_hash != expected:
            raise ValueError("dataset build result content hash mismatch")

    @property
    def status(self) -> LineageStatus:
        return self.lineage.status

    @property
    def raw_dataset_hash(self) -> str:
        return self.lineage.raw_dataset_hash

    @property
    def fold_manifests(self) -> tuple[NestedFoldManifest, ...]:
        return self.lineage.fold_manifests

    @property
    def fold_manifest_hashes(self) -> tuple[str, ...]:
        return self.lineage.fold_manifest_hashes

    @property
    def holdout_row_count(self) -> int:
        return self.lineage.holdout_row_count

    def assert_current(self) -> None:
        self.lineage.assert_current()


class Phase5DatasetIssuer:
    """Only production issuer for raw→processed→features→labels→folds→holdout."""

    def issue(
        self,
        *,
        raw_store: AppendOnlyRawStore,
        manifests: Sequence[SegmentManifest],
        spec: ResearchBuildSpec,
        holdout_root: Path,
        witness: TrustedWitness,
    ) -> DatasetBuildResult:
        provenance = raw_store.phase5_provenance(manifests)
        ticks: list[TickEvent] = []
        quotes: list[BidAskEvent] = []
        for manifest in manifests:
            records = raw_store.read_verified(manifest)
            if manifest.event_type == "tick":
                ticks.extend(decode_tick(record) for record in records)
            elif manifest.event_type == "bidask":
                quotes.extend(decode_bidask(record) for record in records)
        try:
            samples = _derive_samples(tuple(ticks), tuple(quotes), tuple(manifests), spec)
        except DatasetValidationError as error:
            lineage = _issue_evidence(
                provenance, spec, (), (), None, holdout_root, witness,
            )
            return _build_result(lineage, (), (), error.reasons)
        holdout_rows = tuple(
            HoldoutRow(sample.source.row_id, sample.trading_date, sample.source.payload())
            for sample in samples
        )
        selection = select_locked_holdout(holdout_rows) if holdout_rows else None
        if selection is None or selection.status != "READY" or not selection.development:
            lineage = _issue_evidence(provenance, spec, samples, (), None, holdout_root, witness)
            return _build_result(
                lineage, (), (), ("FEWER_THAN_40_EFFECTIVE_TRADING_DAYS",),
            )
        development_ids = {row.row_id for row in selection.development}
        development = tuple(sample for sample in samples if sample.source.row_id in development_ids)
        capabilities = _plan_development_folds(development, spec.requested_outer_folds)
        folds = tuple(value.manifest for value in capabilities)
        if len(capabilities) < spec.requested_outer_folds:
            lineage = _issue_evidence(provenance, spec, samples, folds, None, holdout_root, witness)
            return _build_result(
                lineage, development, capabilities, ("FEWER_THAN_FIVE_OUTER_FOLDS",),
            )
        if holdout_root.exists():
            LockedHoldout(holdout_root, witness=witness)
            lineage = _issue_evidence(
                provenance, spec, samples, folds, selection, holdout_root, witness,
            )
            if _read_lineage_receipt(holdout_root) != _lineage_receipt(lineage):
                raise DatasetValidationError(("EXISTING_LINEAGE_INPUT_MISMATCH",))
            return _build_result(lineage, development, capabilities, ())
        LockedHoldout.create(holdout_root, selection, witness=witness)
        lineage = _issue_evidence(
            provenance, spec, samples, folds, selection, holdout_root, witness,
        )
        _write_lineage_receipt(holdout_root, lineage)
        return _build_result(lineage, development, capabilities, ())


def _derive_samples(ticks: tuple[TickEvent, ...], quotes: tuple[BidAskEvent, ...], manifests: tuple[SegmentManifest, ...], spec: ResearchBuildSpec) -> tuple[TemporalSample, ...]:
    result: list[TemporalSample] = []
    feature_manifest = replace(default_feature_manifest(), version=spec.feature_version)
    feature_pipeline = FeaturePipeline(feature_manifest)
    label_pipeline = LabelPipeline()
    price_policy = ExecutablePricePolicy(entry_slippage=0.0, exit_slippage=spec.cost_points)
    labeler = TripleBarrierLabeler(price_policy=price_policy)
    resolver = SessionResolver(spec.trading_calendar())
    events: tuple[TickEvent | BidAskEvent, ...] = (*ticks, *quotes)
    semantic_reasons = tuple(
        reason
        for event in events
        for reason in validate_research_event(event)
    )
    mismatch = any(
        not _event_matches_resolution(event, resolver.resolve(event.exchange_datetime))
        for event in events
    )
    if semantic_reasons or mismatch:
        raise DatasetValidationError((
            *semantic_reasons,
            *(("RAW_SESSION_OR_EFFECTIVE_DATE_MISMATCH",) if mismatch else ()),
        ))
    resolved_ticks = tuple(
        (value, resolution)
        for value in ticks
        if _event_matches_resolution(value, resolution := resolver.resolve(value.exchange_datetime))
    )
    resolved_quotes = tuple(
        (value, resolution)
        for value in quotes
        if _event_matches_resolution(value, resolution := resolver.resolve(value.exchange_datetime))
    )
    resolutions = {
        (resolution.trading_date.isoformat(), resolution.session): resolution
        for _value, resolution in (*resolved_ticks, *resolved_quotes)
        if resolution.trading_date is not None
    }
    prior_bars: list[Bar] = []
    prior_states: list[OneSecondState] = []
    ordered_keys = tuple(sorted(
        resolutions,
        key=lambda key: _required_session_start(resolutions[key]),
    ))
    for trading_date, session in ordered_keys:
        resolution = resolutions[(trading_date, session)]
        day_ticks = tuple(
            value for value, resolved in resolved_ticks
            if resolved.trading_date is not None
            and resolved.trading_date.isoformat() == trading_date
            and resolved.session == session
        )
        day_quotes = tuple(
            value for value, resolved in resolved_quotes
            if resolved.trading_date is not None
            and resolved.trading_date.isoformat() == trading_date
            and resolved.session == session
        )
        if not day_ticks or not day_quotes:
            continue
        if (
            len({value.target_code for value in day_ticks}) != 1
            or {value.target_code for value in day_ticks}
            != {value.target_code for value in day_quotes}
        ):
            raise DatasetValidationError(("TARGET_MISMATCH",))
        start = min(value.exchange_datetime for value in day_ticks).replace(second=0, microsecond=0)
        if resolution.session == "CLOSED" or resolution.session_start is None or resolution.session_end is None:
            continue
        end = resolution.session_end
        processed = ProcessingPipeline(quote_joiner=QuoteJoiner(max_quote_age=timedelta(minutes=2))).process(
            ticks=day_ticks, bidasks=day_quotes, resolution=resolution,
            start_second=start, end_second=end - timedelta(seconds=1),
            source_manifests=manifests, intervals=(1,),
        )
        bars = processed.bar_sets[0].bars
        candidates = tuple(value for value in label_pipeline.candidates(bars, horizons=(15,)))
        context = build_feature_context(
            resolution,
            prior_bars=tuple(prior_bars),
            prior_states=tuple(prior_states),
        )
        parameters = LabelParameters(
            version=spec.label_version, fit_start=start - timedelta(days=2),
            fit_end=start - timedelta(seconds=1), target_atr_multiplier=1.0,
            stop_atr_multiplier=1.0, minimum_target_points=1.0,
            minimum_stop_points=1.0, horizon_minutes=15,
        )
        for candidate in candidates:
            future = tuple(bar for bar in bars if candidate.decision_time <= bar.bar_start)
            if len(future) < 15:
                continue
            try:
                feature = feature_pipeline.compute(
                    bars=tuple(bar for bar in bars if bar.bar_end <= candidate.decision_time),
                    states=tuple(state for state in processed.states if state.second < candidate.decision_time),
                    decision_time=candidate.decision_time, context=context,
                )
                entry = max(
                    (state for state in processed.states if state.second < candidate.decision_time),
                    key=lambda state: state.second,
                )
                atr_value = feature.values.get("atr_5m")
                atr = float(atr_value) if isinstance(atr_value, (int, float)) and atr_value > 0 else 1.0
                label = labeler.label(
                    candidate_id=candidate.candidate_id, decision_time=candidate.decision_time,
                    entry_state=entry, future_bars=future, atr=atr, parameters=parameters,
                )
            except ValueError:
                continue
            net_return = 0.0
            if label.label == "LONG":
                outcome_state = max(
                    (state for state in processed.states if state.second < label.outcome_time),
                    key=lambda state: state.second,
                )
                exit_quote = price_policy.snapshot(outcome_state)
                net_return = exit_quote.bid - label.entry_ask - price_policy.estimated_round_trip_cost
            elif label.label == "SHORT":
                outcome_state = max(
                    (state for state in processed.states if state.second < label.outcome_time),
                    key=lambda state: state.second,
                )
                exit_quote = price_policy.snapshot(outcome_state)
                net_return = label.entry_bid - exit_quote.ask - price_policy.estimated_round_trip_cost
            features = {
                name: feature.values[name]
                for name in feature_manifest.formal_features
            }
            source = Phase4SourceRow(
                candidate.candidate_id, candidate.decision_time, features,
                label.label, net_return, label.training_eligible,
            )
            result.append(TemporalSample(source, candidate.decision_time, label.outcome_time, trading_date))
        prior_bars[:] = bars
        prior_states.extend(processed.states)
    return tuple(sorted(result, key=lambda value: (value.decision_time, value.source.row_id)))


def _event_matches_resolution(
    value: TickEvent | BidAskEvent,
    resolution: object,
) -> bool:
    from tmf_research.domain.sessions import SessionResolution

    return (
        isinstance(resolution, SessionResolution)
        and resolution.session in ("DAY", "NIGHT")
        and resolution.trading_date is not None
        and value.session == resolution.session
        and value.trading_date == resolution.trading_date.isoformat()
    )


def _required_session_start(resolution: object) -> datetime:
    from tmf_research.domain.sessions import SessionResolution

    if not isinstance(resolution, SessionResolution) or resolution.session_start is None:
        raise DatasetValidationError(("RESOLVED_SESSION_BOUNDARY_MISSING",))
    return resolution.session_start


def _plan_development_folds(
    rows: tuple[TemporalSample, ...], requested: int,
) -> tuple[Phase4FoldCapabilities, ...]:
    if len(rows) < requested * 3 + 3:
        return ()
    test_size = max(1, len(rows) // (requested + 3))
    validation_size = max(1, test_size // 2)
    minimum_train = len(rows) - requested * test_size
    planned = Phase5FoldPlanner().plan(
        rows, outer_test_size=test_size, inner_validation_size=validation_size,
        minimum_outer_train_size=minimum_train, step_size=test_size,
    )
    return tuple(value.capabilities for value in planned[:requested])


def _issue_evidence(
    provenance: DataProvenanceEvidence,
    spec: ResearchBuildSpec,
    samples: tuple[TemporalSample, ...],
    folds: tuple[NestedFoldManifest, ...],
    selection: HoldoutSelection | None,
    holdout_root: Path,
    witness: TrustedWitness,
) -> DatasetLineageEvidence:
    ready = selection is not None
    development = selection.development if selection is not None else ()
    holdout = selection.holdout if selection is not None else ()
    data_hash = hashlib.sha256((holdout_root / "holdout.data.json").read_bytes()).hexdigest() if ready else None
    payload = {
        "status": "READY" if ready else "REJECTED_INSUFFICIENT_DATA",
        "raw_dataset_hash": provenance.dataset_hash,
        "segment_manifest_hashes": provenance.segment_manifest_hashes,
        "build_spec_hash": spec.content_hash,
        "all_rows_hash": canonical_hash([_sample_payload(value) for value in samples]),
        "development_rows_hash": canonical_hash([
            _sample_payload(value) for value in samples if value.source.row_id in {row.row_id for row in development}
        ]),
        "holdout_rows_hash": canonical_hash([
            _sample_payload(value) for value in samples if value.source.row_id in {row.row_id for row in holdout}
        ]),
        "temporal_sample_hashes": tuple(
            (value.source.row_id, canonical_hash(_sample_payload(value))) for value in samples
        ),
        "development_row_ids": tuple(row.row_id for row in development),
        "holdout_row_ids": tuple(row.row_id for row in holdout),
        "fold_manifest_hashes": tuple(value.content_hash for value in folds),
        "holdout_selection_hash": selection.content_hash if selection is not None else None,
        "holdout_data_hash": data_hash,
        "holdout_row_count": len(holdout),
    }
    instance = object.__new__(DatasetLineageEvidence)
    values: dict[str, object] = {
        **payload, "fold_manifests": folds, "content_hash": canonical_hash(payload),
        "_provenance": provenance, "_spec": spec,
        "_holdout_root": holdout_root.resolve() if ready else None,
        "_witness": witness, "_seal": _LINEAGE_SEAL,
    }
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _sample_payload(value: TemporalSample) -> dict[str, object]:
    return {
        "source": value.source.payload(),
        "decision_time": value.decision_time.isoformat(),
        "outcome_time": value.outcome_time.isoformat(),
        "trading_date": value.trading_date,
    }


def _build_result(
    lineage: DatasetLineageEvidence,
    development: tuple[TemporalSample, ...],
    capabilities: tuple[Phase4FoldCapabilities, ...],
    rejection_reasons: tuple[str, ...],
) -> DatasetBuildResult:
    payload = {
        "lineage": lineage.content_hash,
        "development": [_sample_payload(value) for value in development],
        "folds": [value.manifest.content_hash for value in capabilities],
        "rejection_reasons": rejection_reasons,
    }
    instance = object.__new__(DatasetBuildResult)
    for name, value in (
        ("lineage", lineage),
        ("development_samples", development),
        ("fold_capabilities", capabilities),
        ("rejection_reasons", rejection_reasons),
        ("content_hash", canonical_hash(payload)),
        ("_seal", _BUILD_RESULT_SEAL),
    ):
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _lineage_receipt(lineage: DatasetLineageEvidence) -> dict[str, object]:
    return {
        "status": lineage.status,
        "content_hash": lineage.content_hash,
        "raw_dataset_hash": lineage.raw_dataset_hash,
        "build_spec_hash": lineage.build_spec_hash,
        "fold_manifest_hashes": list(lineage.fold_manifest_hashes),
        "holdout_selection_hash": lineage.holdout_selection_hash,
        "holdout_data_hash": lineage.holdout_data_hash,
    }


def _read_lineage_receipt(root: Path) -> dict[str, object]:
    value = json.loads((root / "dataset.lineage.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DatasetValidationError(("EXISTING_LINEAGE_RECEIPT_INVALID",))
    return value


def _write_lineage_receipt(root: Path, lineage: DatasetLineageEvidence) -> None:
    path = root / "dataset.lineage.json"
    encoded = (json.dumps(
        _lineage_receipt(lineage), sort_keys=True, separators=(",", ":"), allow_nan=False,
    ) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)


def _sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("invalid lineage SHA-256")
