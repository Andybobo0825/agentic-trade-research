from __future__ import annotations

import gzip
import hashlib
import heapq
import json
import math
import os
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from tmf_research.domain.events import BidAskEvent, TickEvent
from tmf_research.domain.sessions import SessionResolution, TradingCalendar
from tmf_research.features.context_builder import ResearchBuildSpec, build_feature_context
from tmf_research.features.definitions import (
    FeatureManifest,
    default_feature_manifest,
    historical_l1_feature_manifest,
    historical_l1_reduced_feature_manifest,
)
from tmf_research.features.pipeline import FeaturePipeline
from tmf_research.processing.historical_adapter import decode_historical_day
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
_OUTCOME_SEAL = object()
LineageStatus = Literal["READY", "REJECTED_INSUFFICIENT_DATA"]


class DatasetValidationError(ValueError):
    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(sorted(set(reasons)))
        super().__init__(",".join(self.reasons))


@dataclass(frozen=True, slots=True, init=False)
class ExecutableOutcome:
    row_id: str
    source_row_hash: str
    long_gross_points: float
    short_gross_points: float
    long_net_points: float
    short_net_points: float
    round_trip_cost_points: float
    cost_components: tuple[tuple[str, float | None], ...]
    cost_complete: bool
    cost_policy_hash: str
    decision_time: datetime
    outcome_time: datetime
    event_id: str
    regime_tags: tuple[str, ...]
    target_code: str
    atr_sensitivity: tuple[tuple[float, str, float, float], ...]
    content_hash: str
    _seal: object

    def __new__(cls, *_args: object, **_kwargs: object) -> ExecutableOutcome:
        raise TypeError("executable outcomes must be issued from verified raw market data")

    def __post_init__(self) -> None:
        if self._seal is not _OUTCOME_SEAL:
            raise TypeError("invalid executable outcome authority")
        if (
            not self.row_id.strip()
            or not self.event_id.strip()
            or len(self.regime_tags) != 5
            or any(not value.strip() for value in self.regime_tags)
            or not self.target_code.strip()
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in (
                    self.long_gross_points, self.short_gross_points,
                    self.long_net_points, self.short_net_points,
                    self.round_trip_cost_points,
                )
            )
            or self.round_trip_cost_points < 0.0
            or tuple(name for name, _value in self.cost_components)
            != ("SLIPPAGE", "ENTRY_FEE", "EXIT_FEE", "TAX")
            or any(
                value is not None and (not math.isfinite(value) or value < 0.0)
                for _name, value in self.cost_components
            )
            or self.cost_complete
            != all(value is not None for _name, value in self.cost_components)
            or not math.isclose(
                self.long_net_points,
                self.long_gross_points - self.round_trip_cost_points,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or not math.isclose(
                self.short_net_points,
                self.short_gross_points - self.round_trip_cost_points,
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
            or self.decision_time.tzinfo is None
            or self.decision_time.utcoffset() is None
            or self.outcome_time.tzinfo is None
            or self.outcome_time.utcoffset() is None
            or self.outcome_time < self.decision_time
            or tuple(value[0] for value in self.atr_sensitivity) != (0.75, 1.0, 1.25)
            or any(
                label not in ("NO_TRADE", "LONG", "SHORT", "AMBIGUOUS")
                or not math.isfinite(long_value)
                or not math.isfinite(short_value)
                for _multiplier, label, long_value, short_value in self.atr_sensitivity
            )
        ):
            raise ValueError("invalid executable outcome semantics")
        for value in (self.source_row_hash, self.cost_policy_hash, self.content_hash):
            _sha256(value)
        if canonical_hash(_outcome_payload(self, include_hash=False)) != self.content_hash:
            raise ValueError("executable outcome content hash mismatch")


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
    executable_outcome_hashes: tuple[tuple[str, str], ...]
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
        outcome_committed = dict(self.executable_outcome_hashes)
        if (
            len(outcome_committed) != len(self.executable_outcome_hashes)
            or set(outcome_committed) != set(committed)
        ):
            raise ValueError("executable outcome lineage must cover every exact sample")
        for value in outcome_committed.values():
            _sha256(value)
        development_ids = set(self.development_row_ids)
        if any(row_id not in development_ids for manifest in self.fold_manifests for role in (
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
            holdout = LockedHoldout(self._holdout_root, witness=self._witness)
            holdout.assert_lineage_commitment(self.content_hash)
            if hashlib.sha256((self._holdout_root / "holdout.data.json").read_bytes()).hexdigest() != self.holdout_data_hash:
                raise ValueError("locked holdout no longer matches dataset lineage")
            if _read_lineage_receipt(self._holdout_root) != _lineage_receipt(self):
                raise ValueError("dataset lineage receipt no longer matches issued evidence")

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
    development_outcomes: tuple[ExecutableOutcome, ...]
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
        if tuple(value.row_id for value in self.development_outcomes) != tuple(
            value.source.row_id for value in self.development_samples
        ):
            raise ValueError("development outcomes do not match exact development samples")
        if any(
            outcome.source_row_hash != sample.source.content_hash
            for sample, outcome in zip(
                self.development_samples, self.development_outcomes, strict=True,
            )
        ):
            raise ValueError("development outcome source commitments do not match")
        if len({value.cost_policy_hash for value in self.development_outcomes}) > 1:
            raise ValueError("one exact executable cost policy is required per build")
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
            "outcomes": [value.content_hash for value in self.development_outcomes],
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
        sample_cache: Path | None = None,
    ) -> DatasetBuildResult:
        provenance = raw_store.phase5_provenance(manifests)
        cache_path = (
            _sample_cache_path(sample_cache, provenance, spec)
            if sample_cache is not None else None
        )
        try:
            cached = (
                _load_cached_samples(cache_path, provenance, spec)
                if cache_path is not None else None
            )
            if cached is None:
                samples, outcomes = _derive_samples(raw_store, tuple(manifests), spec)
                if cache_path is not None:
                    _write_cached_samples(cache_path, provenance, spec, samples, outcomes)
            else:
                samples, outcomes = cached
        except DatasetValidationError as error:
            lineage = _issue_evidence(
                provenance, spec, (), (), (), None, holdout_root, witness,
            )
            return _build_result(lineage, (), (), (), error.reasons)
        outcomes_by_id = {value.row_id: value for value in outcomes}
        holdout_rows = tuple(
            HoldoutRow(sample.source.row_id, sample.trading_date, {
                "source": sample.source.payload(),
                "outcome": _outcome_payload(outcomes_by_id[sample.source.row_id]),
            })
            for sample in samples
        )
        selection = select_locked_holdout(holdout_rows) if holdout_rows else None
        if selection is None or selection.status != "READY" or not selection.development:
            lineage = _issue_evidence(
                provenance, spec, samples, outcomes, (), None, holdout_root, witness,
            )
            return _build_result(
                lineage, (), (), (), ("FEWER_THAN_40_EFFECTIVE_TRADING_DAYS",),
            )
        development_ids = {row.row_id for row in selection.development}
        development = tuple(sample for sample in samples if sample.source.row_id in development_ids)
        development_outcomes = tuple(outcomes_by_id[value.source.row_id] for value in development)
        capabilities = _plan_development_folds(development, spec.requested_outer_folds)
        folds = tuple(value.manifest for value in capabilities)
        if len(capabilities) < spec.requested_outer_folds:
            lineage = _issue_evidence(
                provenance, spec, samples, outcomes, folds, None, holdout_root, witness,
            )
            return _build_result(
                lineage, development, development_outcomes, capabilities,
                ("FEWER_THAN_FIVE_OUTER_FOLDS",),
            )
        if holdout_root.exists():
            LockedHoldout(holdout_root, witness=witness)
            lineage = _issue_evidence(
                provenance, spec, samples, outcomes, folds, selection,
                holdout_root, witness,
            )
            if _read_lineage_receipt(holdout_root) != _lineage_receipt(lineage):
                raise DatasetValidationError(("EXISTING_LINEAGE_INPUT_MISMATCH",))
            return _build_result(
                lineage, development, development_outcomes, capabilities, (),
            )
        lineage = _issue_evidence(
            provenance, spec, samples, outcomes, folds, selection,
            holdout_root, witness,
        )
        LockedHoldout.create(
            holdout_root, selection, witness=witness,
            lineage_commitment_hash=lineage.content_hash,
        )
        _write_lineage_receipt(holdout_root, lineage)
        return _build_result(lineage, development, development_outcomes, capabilities, ())


@dataclass(frozen=True, slots=True)
class _SessionBatch:
    """One complete resolved trading session's events, emitted in start order."""

    order_key: datetime
    resolution: SessionResolution
    trading_date: str
    session: str
    ticks: tuple[TickEvent, ...]
    quotes: tuple[BidAskEvent, ...]


_Bucket = tuple[list[TickEvent], list[BidAskEvent], SessionResolution]


def _ingest_events(
    ticks: Sequence[TickEvent],
    quotes: Sequence[BidAskEvent],
    resolver: SessionResolver,
    reasons: set[str],
    buckets: dict[tuple[str, str], _Bucket],
) -> None:
    events: tuple[TickEvent | BidAskEvent, ...] = (*ticks, *quotes)
    for event in events:
        reasons.update(validate_research_event(event))
        resolution = resolver.resolve(event.exchange_datetime)
        if not _event_matches_resolution(event, resolution):
            reasons.add("RAW_SESSION_OR_EFFECTIVE_DATE_MISMATCH")
            continue
        key = (event.trading_date, event.session)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = buckets[key] = ([], [], resolution)
        if isinstance(event, TickEvent):
            bucket[0].append(event)
        else:
            bucket[1].append(event)


def _batch_from_bucket(
    key: tuple[str, str],
    bucket: _Bucket,
    reasons: set[str],
) -> _SessionBatch:
    ticks, quotes, resolution = bucket
    if resolution.session_start is None:
        reasons.add("RESOLVED_SESSION_BOUNDARY_MISSING")
        events: tuple[TickEvent | BidAskEvent, ...] = (*ticks, *quotes)
        order_key = min(event.exchange_datetime for event in events)
    else:
        order_key = resolution.session_start
    return _SessionBatch(
        order_key, resolution, key[0], key[1], tuple(ticks), tuple(quotes),
    )


def _drain_buckets(
    buckets: dict[tuple[str, str], _Bucket],
    keys: Sequence[tuple[str, str]],
    reasons: set[str],
) -> list[_SessionBatch]:
    return sorted(
        (_batch_from_bucket(key, buckets.pop(key), reasons) for key in keys),
        key=lambda batch: batch.order_key,
    )


def _historical_batches(
    raw_store: AppendOnlyRawStore,
    manifests: Sequence[SegmentManifest],
    calendar: TradingCalendar,
    resolver: SessionResolver,
    reasons: set[str],
) -> Iterator[_SessionBatch]:
    """Decode one stored day at a time; a session flushes once a later day arrives.

    A backfill day file covers [previous trading day 15:00, day 13:46), so every
    (trading date, session) is complete within one file; the watermark only has
    to hold the current day's buckets, keeping memory at a single day of events.
    """

    buckets: dict[tuple[str, str], _Bucket] = {}
    ordered = sorted(
        manifests, key=lambda manifest: manifest.segment_id.rpartition("TMFR1-")[2],
    )
    for manifest in ordered:
        day = manifest.segment_id.rpartition("TMFR1-")[2]
        records = raw_store.read_verified(manifest)
        day_ticks, day_quotes = decode_historical_day(day, records, calendar=calendar)
        del records
        _ingest_events(day_ticks, day_quotes, resolver, reasons, buckets)
        del day_ticks, day_quotes
        ready = tuple(key for key in buckets if key[0] < day)
        yield from _drain_buckets(buckets, ready, reasons)
    yield from _drain_buckets(buckets, tuple(buckets), reasons)


def _live_batches(
    raw_store: AppendOnlyRawStore,
    manifests: Sequence[SegmentManifest],
    resolver: SessionResolver,
    reasons: set[str],
) -> list[_SessionBatch]:
    ticks: list[TickEvent] = []
    quotes: list[BidAskEvent] = []
    for manifest in manifests:
        records = raw_store.read_verified(manifest)
        if manifest.event_type == "tick":
            ticks.extend(decode_tick(record) for record in records)
        elif manifest.event_type == "bidask":
            quotes.extend(decode_bidask(record) for record in records)
    buckets: dict[tuple[str, str], _Bucket] = {}
    _ingest_events(ticks, quotes, resolver, reasons, buckets)
    return _drain_buckets(buckets, tuple(buckets), reasons)


def _session_batches(
    raw_store: AppendOnlyRawStore,
    manifests: Sequence[SegmentManifest],
    calendar: TradingCalendar,
    resolver: SessionResolver,
    reasons: set[str],
) -> Iterator[_SessionBatch]:
    live = tuple(
        manifest for manifest in manifests
        if manifest.event_type != "historical-tick"
    )
    historical = tuple(
        manifest for manifest in manifests
        if manifest.event_type == "historical-tick"
    )
    yield from heapq.merge(
        _live_batches(raw_store, live, resolver, reasons),
        _historical_batches(raw_store, historical, calendar, resolver, reasons),
        key=lambda batch: batch.order_key,
    )


def _derive_samples(
    raw_store: AppendOnlyRawStore,
    manifests: tuple[SegmentManifest, ...],
    spec: ResearchBuildSpec,
) -> tuple[tuple[TemporalSample, ...], tuple[ExecutableOutcome, ...]]:
    result: list[TemporalSample] = []
    outcomes: list[ExecutableOutcome] = []
    feature_manifest = _feature_manifest_for(spec)
    feature_pipeline = FeaturePipeline(feature_manifest)
    label_pipeline = LabelPipeline()
    price_policy = ExecutablePricePolicy(entry_slippage=0.0, exit_slippage=spec.cost_points)
    cost_components = (
        ("SLIPPAGE", spec.cost_points),
        ("ENTRY_FEE", spec.entry_fee_points),
        ("EXIT_FEE", spec.exit_fee_points),
        ("TAX", spec.tax_points),
    )
    cost_complete = all(value is not None for _name, value in cost_components)
    total_cost_points = sum(
        0.0 if value is None else value for _name, value in cost_components
    )
    labeler = TripleBarrierLabeler(price_policy=price_policy)
    calendar = spec.trading_calendar()
    resolver = SessionResolver(calendar)
    reasons: set[str] = set()
    prior_bars: list[Bar] = []
    prior_volume_counts: Counter[int] = Counter()
    for batch in _session_batches(raw_store, manifests, calendar, resolver, reasons):
        if reasons:
            continue  # keep draining so validation still covers every stored day
        trading_date, session = batch.trading_date, batch.session
        resolution = batch.resolution
        day_ticks, day_quotes = batch.ticks, batch.quotes
        if not day_ticks or not day_quotes:
            continue
        if (
            len({value.target_code for value in day_ticks}) != 1
            or {value.target_code for value in day_ticks}
            != {value.target_code for value in day_quotes}
        ):
            reasons.add("TARGET_MISMATCH")
            continue
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
        states = processed.states
        # The pipeline emits states second-by-second and bars in start order,
        # so time-prefix and time-suffix slices can use binary search.
        state_seconds = [state.second for state in states]
        bar_starts = [bar.bar_start for bar in bars]
        bar_ends = [bar.bar_end for bar in bars]
        candidates = tuple(value for value in label_pipeline.candidates(bars, horizons=(15,)))
        context = build_feature_context(
            resolution,
            prior_bars=tuple(prior_bars),
            prior_volume_counts=prior_volume_counts,
        )
        parameters = LabelParameters(
            version=spec.label_version, fit_start=start - timedelta(days=2),
            fit_end=start - timedelta(seconds=1), target_atr_multiplier=1.0,
            stop_atr_multiplier=1.0, minimum_target_points=1.0,
            minimum_stop_points=1.0, horizon_minutes=15,
        )
        for candidate in candidates:
            future = bars[bisect_left(bar_starts, candidate.decision_time):]
            if len(future) < 15:
                continue
            try:
                feature = feature_pipeline.compute(
                    bars=bars[:bisect_right(bar_ends, candidate.decision_time)],
                    states=states[:bisect_left(state_seconds, candidate.decision_time)],
                    decision_time=candidate.decision_time, context=context,
                )
                entry = _last_state_before(
                    states, state_seconds, candidate.decision_time,
                )
                atr_value = feature.values.get("atr_5m")
                atr = float(atr_value) if isinstance(atr_value, (int, float)) and atr_value > 0 else 1.0
                label = labeler.label(
                    candidate_id=candidate.candidate_id, decision_time=candidate.decision_time,
                    entry_state=entry, future_bars=future, atr=atr, parameters=parameters,
                )
                outcome_state = _last_state_before(
                    states, state_seconds, label.outcome_time,
                )
                exit_quote = price_policy.snapshot(outcome_state)
                atr_sensitivity = _atr_sensitivity_outcomes(
                    labeler=labeler, candidate_id=candidate.candidate_id,
                    decision_time=candidate.decision_time, entry_state=entry,
                    future_bars=future, atr=atr, parameters=parameters,
                    states=states, state_seconds=state_seconds,
                    price_policy=price_policy,
                    total_cost_points=total_cost_points,
                )
            except ValueError:
                continue
            long_gross = exit_quote.bid - label.entry_ask
            short_gross = label.entry_bid - exit_quote.ask
            long_net = long_gross - total_cost_points
            short_net = short_gross - total_cost_points
            net_return = (
                long_net if label.label == "LONG"
                else short_net if label.label == "SHORT"
                else 0.0
            )
            features = {
                name: feature.values[name]
                for name in feature_manifest.formal_features
            }
            source = Phase4SourceRow(
                candidate.candidate_id, candidate.decision_time, features,
                label.label, net_return, label.training_eligible,
            )
            result.append(TemporalSample(source, candidate.decision_time, label.outcome_time, trading_date))
            outcomes.append(_issue_outcome(
                source=source,
                long_gross_points=long_gross,
                short_gross_points=short_gross,
                long_net_points=long_net,
                short_net_points=short_net,
                round_trip_cost_points=total_cost_points,
                cost_components=cost_components,
                cost_complete=cost_complete,
                decision_time=candidate.decision_time,
                outcome_time=label.outcome_time,
                event_id=candidate.candidate_id,
                regime_tags=_regime_tags(feature.values, str(session)),
                target_code=candidate.target_code,
                atr_sensitivity=atr_sensitivity,
            ))
        prior_bars[:] = bars
        prior_volume_counts.update(
            state.volume for state in processed.states if state.volume > 0
        )
    if reasons:
        raise DatasetValidationError(tuple(reasons))
    paired = tuple(sorted(
        zip(result, outcomes, strict=True),
        key=lambda value: (value[0].decision_time, value[0].source.row_id),
    ))
    return tuple(value[0] for value in paired), tuple(value[1] for value in paired)


def _last_state_before(
    states: tuple[OneSecondState, ...],
    state_seconds: Sequence[datetime],
    moment: datetime,
) -> OneSecondState:
    index = bisect_left(state_seconds, moment)
    if index == 0:
        raise ValueError("no state precedes the requested moment")
    return states[index - 1]


def _feature_manifest_for(spec: ResearchBuildSpec) -> FeatureManifest:
    if spec.feature_version == "phase3-features-hist-l1-v1":
        return historical_l1_feature_manifest()
    if spec.feature_version == "phase3-features-hist-l1-v2":
        return historical_l1_reduced_feature_manifest()
    return replace(default_feature_manifest(), version=spec.feature_version)


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
    outcomes: tuple[ExecutableOutcome, ...],
    folds: tuple[NestedFoldManifest, ...],
    selection: HoldoutSelection | None,
    holdout_root: Path,
    witness: TrustedWitness,
) -> DatasetLineageEvidence:
    if len({value.cost_policy_hash for value in outcomes}) > 1:
        raise DatasetValidationError(("MULTIPLE_EXECUTABLE_COST_POLICIES",))
    ready = selection is not None
    development = selection.development if selection is not None else ()
    holdout = selection.holdout if selection is not None else ()
    development_ids = {row.row_id for row in development}
    holdout_ids = {row.row_id for row in holdout}
    data_hash = None
    if ready:
        data_path = holdout_root / "holdout.data.json"
        data = (
            data_path.read_bytes() if data_path.is_file()
            else _canonical_bytes([row.to_dict() for row in holdout])
        )
        data_hash = hashlib.sha256(data).hexdigest()
    payload = {
        "status": "READY" if ready else "REJECTED_INSUFFICIENT_DATA",
        "raw_dataset_hash": provenance.dataset_hash,
        "segment_manifest_hashes": provenance.segment_manifest_hashes,
        "build_spec_hash": spec.content_hash,
        "all_rows_hash": canonical_hash([_sample_payload(value) for value in samples]),
        "development_rows_hash": canonical_hash([
            _sample_payload(value) for value in samples if value.source.row_id in development_ids
        ]),
        "holdout_rows_hash": canonical_hash([
            _sample_payload(value) for value in samples if value.source.row_id in holdout_ids
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
        "executable_outcome_hashes": tuple(
            (value.row_id, value.content_hash) for value in outcomes
        ),
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


def _sample_cache_path(
    cache_root: Path,
    provenance: DataProvenanceEvidence,
    spec: ResearchBuildSpec,
) -> Path:
    key = canonical_hash({
        "raw_dataset_hash": provenance.dataset_hash,
        "build_spec_hash": spec.content_hash,
    })
    return cache_root / f"samples-{key[:16]}.ndjson.gz"


def _cache_header(
    provenance: DataProvenanceEvidence,
    spec: ResearchBuildSpec,
) -> dict[str, object]:
    return {
        "raw_dataset_hash": provenance.dataset_hash,
        "build_spec_hash": spec.content_hash,
    }


def _write_cached_samples(
    path: Path,
    provenance: DataProvenanceEvidence,
    spec: ResearchBuildSpec,
    samples: tuple[TemporalSample, ...],
    outcomes: tuple[ExecutableOutcome, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmp")
    with gzip.open(staging, "wt", encoding="utf-8") as stream:
        stream.write(json.dumps(
            _cache_header(provenance, spec),
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ) + "\n")
        for sample, outcome in zip(samples, outcomes, strict=True):
            stream.write(json.dumps(
                {"sample": _sample_payload(sample), "outcome": _outcome_payload(outcome)},
                sort_keys=True, separators=(",", ":"), allow_nan=False,
            ) + "\n")
    os.replace(staging, path)


def _load_cached_samples(
    path: Path,
    provenance: DataProvenanceEvidence,
    spec: ResearchBuildSpec,
) -> tuple[tuple[TemporalSample, ...], tuple[ExecutableOutcome, ...]] | None:
    """Rebuild sealed samples from the cache, re-verifying every commitment.

    Every row passes back through the sealed constructors, so semantic and
    content-hash validation runs exactly as in a fresh derivation; a stale
    header (different raw data or build spec) just misses the cache, while a
    corrupted row fails the build closed.
    """

    if path is None or not path.is_file():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            header = json.loads(stream.readline())
            if header != _cache_header(provenance, spec):
                return None
            formal_order = _feature_manifest_for(spec).formal_features
            samples: list[TemporalSample] = []
            outcomes: list[ExecutableOutcome] = []
            for line in stream:
                record = json.loads(line)
                sample = _sample_from_payload(record["sample"], formal_order)
                outcome = _outcome_from_payload(record["outcome"], sample.source)
                samples.append(sample)
                outcomes.append(outcome)
    except (OSError, EOFError, KeyError, TypeError, ValueError) as error:
        raise DatasetValidationError((f"SAMPLE_CACHE_INVALID:{type(error).__name__}",)) from error
    return tuple(samples), tuple(outcomes)


def _sample_from_payload(
    payload: Mapping[str, object],
    formal_order: tuple[str, ...],
) -> TemporalSample:
    source_payload = payload["source"]
    if not isinstance(source_payload, Mapping):
        raise ValueError("cached sample source must be an object")
    features = source_payload["features"]
    if not isinstance(features, Mapping):
        raise ValueError("cached sample features must be an object")
    if set(features) != set(formal_order):
        raise ValueError("cached sample features do not match the build's formal feature set")
    # payload()'s features are alphabetically sorted for canonical hashing; the
    # sealed row must carry them in the manifest's declared formal order, since
    # training checks tuple(row.features) against that exact order.
    source = Phase4SourceRow(
        str(source_payload["row_id"]),
        datetime.fromisoformat(str(source_payload["available_at"])),
        {name: features[name] for name in formal_order},
        source_payload["label"],
        float(source_payload["net_return"]),
        bool(source_payload["is_complete"]),
    )
    if source.content_hash != source_payload.get("content_hash", source.content_hash):
        raise ValueError("cached source row hash mismatch")
    return TemporalSample(
        source,
        datetime.fromisoformat(str(payload["decision_time"])),
        datetime.fromisoformat(str(payload["outcome_time"])),
        str(payload["trading_date"]),
    )


def _outcome_from_payload(
    payload: Mapping[str, object],
    source: Phase4SourceRow,
) -> ExecutableOutcome:
    outcome = _issue_outcome(
        source=source,
        long_gross_points=float(payload["long_gross_points"]),
        short_gross_points=float(payload["short_gross_points"]),
        long_net_points=float(payload["long_net_points"]),
        short_net_points=float(payload["short_net_points"]),
        round_trip_cost_points=float(payload["round_trip_cost_points"]),
        cost_components=tuple(
            (str(name), None if value is None else float(value))
            for name, value in payload["cost_components"]
        ),
        cost_complete=bool(payload["cost_complete"]),
        decision_time=datetime.fromisoformat(str(payload["decision_time"])),
        outcome_time=datetime.fromisoformat(str(payload["outcome_time"])),
        event_id=str(payload["event_id"]),
        regime_tags=tuple(str(tag) for tag in payload["regime_tags"]),
        target_code=str(payload["target_code"]),
        atr_sensitivity=tuple(
            (float(multiplier), str(label), float(long_net), float(short_net))
            for multiplier, label, long_net, short_net in payload["atr_sensitivity"]
        ),
    )
    if outcome.content_hash != payload["content_hash"]:
        raise ValueError("cached executable outcome hash mismatch")
    return outcome


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
    outcomes: tuple[ExecutableOutcome, ...],
    capabilities: tuple[Phase4FoldCapabilities, ...],
    rejection_reasons: tuple[str, ...],
) -> DatasetBuildResult:
    payload = {
        "lineage": lineage.content_hash,
        "development": [_sample_payload(value) for value in development],
        "outcomes": [value.content_hash for value in outcomes],
        "folds": [value.manifest.content_hash for value in capabilities],
        "rejection_reasons": rejection_reasons,
    }
    instance = object.__new__(DatasetBuildResult)
    for name, value in (
        ("lineage", lineage),
        ("development_samples", development),
        ("development_outcomes", outcomes),
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
        "executable_outcome_hashes": [list(value) for value in lineage.executable_outcome_hashes],
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


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def _issue_outcome(
    *,
    source: Phase4SourceRow,
    long_gross_points: float,
    short_gross_points: float,
    long_net_points: float,
    short_net_points: float,
    round_trip_cost_points: float,
    cost_components: tuple[tuple[str, float | None], ...],
    cost_complete: bool,
    decision_time: datetime,
    outcome_time: datetime,
    event_id: str,
    regime_tags: tuple[str, ...],
    target_code: str,
    atr_sensitivity: tuple[tuple[float, str, float, float], ...],
) -> ExecutableOutcome:
    payload = {
        "row_id": source.row_id,
        "source_row_hash": source.content_hash,
        "long_gross_points": long_gross_points,
        "short_gross_points": short_gross_points,
        "long_net_points": long_net_points,
        "short_net_points": short_net_points,
        "round_trip_cost_points": round_trip_cost_points,
        "cost_components": [list(value) for value in cost_components],
        "cost_complete": cost_complete,
        "cost_policy_hash": canonical_hash({
            "version": "phase5-fixed-executable-cost-v1",
            "components": [list(value) for value in cost_components],
            "complete": cost_complete,
        }),
        "decision_time": decision_time.isoformat(),
        "outcome_time": outcome_time.isoformat(),
        "event_id": event_id,
        "regime_tags": list(regime_tags),
        "target_code": target_code,
        "atr_sensitivity": [list(value) for value in atr_sensitivity],
    }
    instance = object.__new__(ExecutableOutcome)
    values: tuple[tuple[str, object], ...] = (
        ("row_id", source.row_id),
        ("source_row_hash", source.content_hash),
        ("long_gross_points", long_gross_points),
        ("short_gross_points", short_gross_points),
        ("long_net_points", long_net_points),
        ("short_net_points", short_net_points),
        ("round_trip_cost_points", round_trip_cost_points),
        ("cost_components", cost_components),
        ("cost_complete", cost_complete),
        ("cost_policy_hash", payload["cost_policy_hash"]),
        ("decision_time", decision_time),
        ("outcome_time", outcome_time),
        ("event_id", event_id),
        ("regime_tags", regime_tags),
        ("target_code", target_code),
        ("atr_sensitivity", atr_sensitivity),
        ("content_hash", canonical_hash(payload)),
        ("_seal", _OUTCOME_SEAL),
    )
    for name, value in values:
        object.__setattr__(instance, name, value)
    instance.__post_init__()
    return instance


def _outcome_payload(
    value: ExecutableOutcome,
    *,
    include_hash: bool = True,
) -> dict[str, object]:
    payload = {
        "row_id": value.row_id,
        "source_row_hash": value.source_row_hash,
        "long_gross_points": value.long_gross_points,
        "short_gross_points": value.short_gross_points,
        "long_net_points": value.long_net_points,
        "short_net_points": value.short_net_points,
        "round_trip_cost_points": value.round_trip_cost_points,
        "cost_components": [list(item) for item in value.cost_components],
        "cost_complete": value.cost_complete,
        "cost_policy_hash": value.cost_policy_hash,
        "decision_time": value.decision_time.isoformat(),
        "outcome_time": value.outcome_time.isoformat(),
        "event_id": value.event_id,
        "regime_tags": list(value.regime_tags),
        "target_code": value.target_code,
        "atr_sensitivity": [list(item) for item in value.atr_sensitivity],
    }
    return {**payload, "content_hash": value.content_hash} if include_hash else payload


def _regime_tags(
    values: Mapping[str, float | None],
    session: str,
) -> tuple[str, ...]:
    realized = values.get("realized_vol_5m")
    volatility = (
        "HIGH_VOLATILITY" if isinstance(realized, (int, float)) and realized > 0.002
        else "MEDIUM_VOLATILITY"
        if isinstance(realized, (int, float)) and realized > 0.0005
        else "LOW_VOLATILITY"
    )
    return_5m = values.get("return_5m")
    structure = (
        "TRENDING"
        if isinstance(return_5m, (int, float)) and abs(return_5m) > 0.001
        else "RANGING"
    )
    days = values.get("days_to_expiry")
    expiry = (
        "EXPIRY_WEEK"
        if isinstance(days, (int, float)) and days <= 7.0
        else "NON_EXPIRY_WEEK"
    )
    from_open = values.get("minutes_from_session_open")
    to_close = values.get("minutes_to_session_close")
    period = (
        "OPENING_30M"
        if isinstance(from_open, (int, float)) and from_open <= 30.0
        else "CLOSING_30M"
        if isinstance(to_close, (int, float)) and to_close <= 30.0
        else "INTRADAY"
    )
    return (session, volatility, structure, expiry, period)


def _atr_sensitivity_outcomes(
    *,
    labeler: TripleBarrierLabeler,
    candidate_id: str,
    decision_time: datetime,
    entry_state: OneSecondState,
    future_bars: tuple[Bar, ...],
    atr: float,
    parameters: LabelParameters,
    states: tuple[OneSecondState, ...],
    state_seconds: Sequence[datetime],
    price_policy: ExecutablePricePolicy,
    total_cost_points: float,
) -> tuple[tuple[float, str, float, float], ...]:
    values = []
    for multiplier in (0.75, 1.0, 1.25):
        label = labeler.label(
            candidate_id=candidate_id,
            decision_time=decision_time,
            entry_state=entry_state,
            future_bars=future_bars,
            atr=atr,
            parameters=replace(
                parameters,
                target_atr_multiplier=multiplier,
                stop_atr_multiplier=multiplier,
            ),
        )
        outcome_state = _last_state_before(states, state_seconds, label.outcome_time)
        exit_quote = price_policy.snapshot(outcome_state)
        values.append((
            multiplier,
            label.label,
            exit_quote.bid - label.entry_ask - total_cost_points,
            label.entry_bid - exit_quote.ask - total_cost_points,
        ))
    return tuple(values)
