from __future__ import annotations

import inspect
import hashlib
import json
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

from tmf_research.domain.events import BidAskEvent, Session, TickEvent
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, SegmentManifest
from tmf_research.cli import main
from tmf_research.validation.locked_holdout import LockedHoldout
from tests.support.trusted_witness import MemoryTrustedWitness


class Phase5DatasetLineageTests(unittest.TestCase):
    def test_production_evaluation_owns_every_promotion_affecting_artifact(self) -> None:
        from tmf_research.validation.fold_evaluation import ProductionEvaluation

        required = {
            "folds", "reports", "gaps", "dimensions", "ablations",
            "coefficients", "sensitivities", "calibrations",
            "dataset_build", "content_hash",
        }
        self.assertTrue(
            required.issubset(ProductionEvaluation.__annotations__),
            required - set(ProductionEvaluation.__annotations__),
        )

    def test_live_collected_segments_reach_the_pipeline_with_their_underlying(self) -> None:
        """`tmf collect` writes live-tick/live-bidask, not the tick/bidask of backfill.

        Decoding only the unprefixed names silently dropped every live segment,
        so the basis group — the whole reason live collection exists, since
        historical ticks carry no spot index — was null on every derived row.
        """

        from tmf_research.collection.live_calendar import synthetic_near_term_calendar
        from tmf_research.processing.session_resolver import SessionResolver
        from tmf_research.validation.dataset_lineage import _live_batches

        # The synthetic calendar runs on Taipei wall-clock, so a UTC 09:00 here
        # would resolve to the night session and be rejected as a mismatch.
        when = datetime(2026, 1, 1, 9, 0, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = AppendOnlyRawStore(root / "raw", writer_version="collect-v1")
            tick = store.append_segment("live-tick", (TickEvent(
                event_id="live-tick-1", received_at=when, exchange_datetime=when,
                alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                code="TMF202607", close=23_000.0, volume=3, simtrade=False,
                trading_date="2026-01-01", session="DAY", raw_payload={},
                tick_type=1, underlying_price=22_950.0,
            ),), segment_id="live-tick-TMFR1-2026-01-01-DAY-000000", created_at=when)
            quote = store.append_segment("live-bidask", (BidAskEvent(
                event_id="live-quote-1", received_at=when, exchange_datetime=when,
                alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                code="TMF202607", bid_prices=(22_999.0,), bid_volumes=(4,),
                ask_prices=(23_001.0,), ask_volumes=(4,), simtrade=False,
                trading_date="2026-01-01", session="DAY", raw_payload={},
                underlying_price=22_950.0,
            ),), segment_id="live-bidask-TMFR1-2026-01-01-DAY-000000", created_at=when)

            calendar = synthetic_near_term_calendar(when.date())
            batches = _live_batches(
                store, (tick, quote), SessionResolver(calendar), set(),
            )

        self.assertEqual(len(batches), 1, "live segments produced no session batch")
        batch = batches[0]
        self.assertEqual(len(batch.ticks), 1)
        self.assertEqual(len(batch.quotes), 1)
        self.assertEqual(batch.ticks[0].underlying_price, 22_950.0)

    def test_already_stored_empty_book_and_out_of_session_rows_do_not_sink_a_build(
        self,
    ) -> None:
        """Two artifacts the collector wrote before it knew to filter them.

        Every session opened with one all-zero book snapshot, and pre-open
        capture is stored deliberately with an empty trading date. Neither is
        usable evidence, but the store is immutable, so the build has to drop
        them: the empty book without poisoning the build's rejection reasons,
        and the out-of-session row without raising out of the decoder.
        """

        from tmf_research.collection.live_calendar import synthetic_near_term_calendar
        from tmf_research.processing.session_resolver import SessionResolver
        from tmf_research.validation.dataset_lineage import _live_batches

        taipei = timezone(timedelta(hours=8))
        when = datetime(2026, 1, 1, 9, 0, tzinfo=taipei)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = AppendOnlyRawStore(root / "raw", writer_version="collect-v1")
            common = {
                "received_at": when, "exchange_datetime": when, "alias_code": "TMFR1",
                "target_code": "TMF202607", "delivery_month": "202607",
                "code": "TMF202607", "simtrade": False, "raw_payload": {},
                "underlying_price": 22_950.0,
            }
            tick = store.append_segment("live-tick", (TickEvent(
                event_id="tick-1", close=23_000.0, volume=3, tick_type=1,
                trading_date="2026-01-01", session="DAY", **common,
            ),), segment_id="live-tick-TMFR1-2026-01-01-DAY-000000", created_at=when)
            quotes = store.append_segment("live-bidask", (
                BidAskEvent(
                    event_id="open-snapshot",
                    bid_prices=(0.0,) * 5, bid_volumes=(0,) * 5,
                    ask_prices=(0.0,) * 5, ask_volumes=(0,) * 5,
                    trading_date="2026-01-01", session="DAY", **common,
                ),
                BidAskEvent(
                    event_id="real-quote",
                    bid_prices=(22_999.0,), bid_volumes=(4,),
                    ask_prices=(23_001.0,), ask_volumes=(4,),
                    trading_date="2026-01-01", session="DAY", **common,
                ),
            ), segment_id="live-bidask-TMFR1-2026-01-01-DAY-000000", created_at=when)
            preopen = store.append_segment("live-bidask", (BidAskEvent(
                event_id="pre-open",
                bid_prices=(22_999.0,), bid_volumes=(4,),
                ask_prices=(23_001.0,), ask_volumes=(4,),
                trading_date="", session="CLOSED", **common,
            ),), segment_id="live-bidask-TMFR1-unresolved-CLOSED-000000", created_at=when)

            reasons: set[str] = set()
            batches = _live_batches(
                store, (tick, quotes, preopen),
                SessionResolver(synthetic_near_term_calendar(when.date())), reasons,
            )

        self.assertEqual(reasons, set(), "usable rows were rejected over dropped ones")
        self.assertEqual(len(batches), 1)
        self.assertEqual(
            [quote.event_id for quote in batches[0].quotes], ["real-quote"],
        )

    def test_a_session_collected_live_is_not_also_taken_from_the_backfill(self) -> None:
        """The weekly backfill always overlaps the days live collection covers.

        Both streams then yield a batch for the same session, so every
        candidate is derived twice — once from live evidence carrying the spot
        index, once from historical evidence that structurally cannot. Live is
        the copy worth keeping: basis exists only there.
        """

        from tmf_research.collection.backfill import HistoricalTickRecord
        from tmf_research.collection.live_calendar import synthetic_near_term_calendar
        from tmf_research.processing.session_resolver import SessionResolver
        from tmf_research.validation.dataset_lineage import _session_batches

        taipei = timezone(timedelta(hours=8))
        when = datetime(2026, 1, 1, 9, 0, tzinfo=taipei)
        day = when.date().isoformat()
        with tempfile.TemporaryDirectory() as directory:
            store = AppendOnlyRawStore(Path(directory) / "raw", writer_version="mixed-v1")
            common = {
                "received_at": when, "exchange_datetime": when, "alias_code": "TMFR1",
                "target_code": "TMF202607", "delivery_month": "202607",
                "code": "TMF202607", "simtrade": False, "raw_payload": {},
                "trading_date": day, "session": "DAY",
            }
            live_tick = store.append_segment("live-tick", (TickEvent(
                event_id="live-tick-1", close=23_000.0, volume=3, tick_type=1,
                underlying_price=22_950.0, **common,
            ),), segment_id=f"live-tick-TMFR1-{day}-DAY-000000", created_at=when)
            live_quote = store.append_segment("live-bidask", (BidAskEvent(
                event_id="live-quote-1",
                bid_prices=(22_999.0,), bid_volumes=(4,),
                ask_prices=(23_001.0,), ask_volumes=(4,),
                underlying_price=22_950.0, **common,
            ),), segment_id=f"live-bidask-TMFR1-{day}-DAY-000000", created_at=when)
            backfill = store.append_segment("historical-tick", (HistoricalTickRecord(
                schema_version="1.1.0",
                event_id=f"hist-tick-TMFR1-{day}-000000",
                exchange_datetime=when,
                received_at=when,
                source="SHIOAJI_HISTORICAL_TICKS_CONTINUOUS_NEAR",
                alias_code="TMFR1",
                derived_target_code="TMF202607",
                derived_delivery_date="2026-01-21",
                target_derivation="taifex-third-wednesday-v1",
                fields={
                    "close": 23_000.0, "volume": 3, "bid_price": 22_999.0,
                    "bid_volume": 4, "ask_price": 23_001.0, "ask_volume": 4,
                    "tick_type": 1,
                },
            ),), segment_id=f"backfill-tick-TMFR1-{day}", created_at=when)

            calendar = synthetic_near_term_calendar(when.date())
            batches = list(_session_batches(
                store, (live_tick, live_quote, backfill),
                calendar, SessionResolver(calendar), set(),
            ))

        sessions = [(batch.trading_date, batch.session) for batch in batches]
        self.assertEqual(
            sessions, sorted(set(sessions)), f"session derived twice: {sessions}",
        )
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].ticks[0].underlying_price, 22_950.0)

    def test_quote_only_verified_input_fails_closed_without_indexing_ticks(self) -> None:
        from tmf_research.features.context_builder import ResearchBuildSpec
        from tmf_research.validation.dataset_lineage import Phase5DatasetIssuer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_calendar(calendar, days=1, minutes=1)
            when = datetime(2026, 1, 1, 8, 45, tzinfo=UTC)
            store = AppendOnlyRawStore(root / "raw", writer_version="phase1-v1")
            manifest = store.append_segment("bidask", (BidAskEvent(
                event_id="quote-only", received_at=when, exchange_datetime=when,
                alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                code="TMF202607", bid_prices=(22_999.5,), bid_volumes=(1,),
                ask_prices=(23_000.5,), ask_volumes=(1,), simtrade=False,
                trading_date="2026-01-01", session="DAY", raw_payload={},
            ),), segment_id="quotes", created_at=when)

            result = Phase5DatasetIssuer().issue(
                raw_store=store, manifests=(manifest,),
                spec=ResearchBuildSpec(calendar=calendar),
                holdout_root=root / "holdout", witness=MemoryTrustedWitness(),
            )

            self.assertEqual(result.status, "REJECTED_INSUFFICIENT_DATA")
            self.assertFalse((root / "holdout").exists())

    def test_phase5_status_reopens_the_same_ready_lineage_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_calendar(calendar, days=55, minutes=25)
            _raw_market(root / "raw", days=55, minutes=25)
            argv = [
                "phase5-status", "--raw-root", str(root / "raw"),
                "--calendar", str(calendar),
                "--witness-db", str(root / "witness" / "heads.sqlite3"),
            ]
            first = StringIO()
            second = StringIO()

            self.assertEqual(main(argv, stdout=first), 0)
            self.assertEqual(main(argv, stdout=second), 0)

        payload = json.loads(first.getvalue())
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["outer_folds"], 5)
        self.assertEqual(second.getvalue(), first.getvalue())

    def test_phase4_train_reports_per_fold_and_summary_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_calendar(calendar, days=55, minutes=25)
            _raw_market(root / "raw", days=55, minutes=25)
            stdout = StringIO()

            self.assertEqual(main([
                "phase4-train", "--raw-root", str(root / "raw"),
                "--calendar", str(calendar),
                "--witness-db", str(root / "witness" / "heads.sqlite3"),
                "--sample-cache", str(root / "sample-cache"),
                "--max-iterations", "2",
            ], stdout=stdout), 0)

            lines = stdout.getvalue().splitlines()
            summary = json.loads(lines[-1])
            self.assertEqual(summary["status"], "TRAINED")
            self.assertGreaterEqual(summary["outer_folds"], 1)
            self.assertEqual(
                summary["outer_folds"] + len(summary["skipped_folds"]), 5,
            )
            self.assertEqual(
                [
                    json.loads(line)["fold"]
                    for line in lines[:-1]
                    if json.loads(line)["event"] == "fold"
                ],
                [row["fold"] for row in summary["folds"]],
            )
            for row in summary["folds"]:
                for name in ("test_ev", "baseline_net_ev", "net_pnl", "test_brier"):
                    self.assertIsInstance(row[name], float)

    def test_sample_cache_round_trips_and_rejects_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_calendar(calendar, days=55, minutes=25)
            _raw_market(root / "raw", days=55, minutes=25)
            argv = [
                "phase5-status", "--raw-root", str(root / "raw"),
                "--calendar", str(calendar),
                "--witness-db", str(root / "witness" / "heads.sqlite3"),
                "--sample-cache", str(root / "sample-cache"),
            ]
            first = StringIO()
            second = StringIO()

            self.assertEqual(main(argv, stdout=first), 0)
            cache_files = sorted((root / "sample-cache").glob("samples-*.ndjson.gz"))
            self.assertEqual(len(cache_files), 1)
            self.assertEqual(main(argv, stdout=second), 0)

            payload = json.loads(first.getvalue())
            self.assertEqual(payload["status"], "READY")
            self.assertEqual(second.getvalue(), first.getvalue())

            import gzip

            lines = gzip.decompress(cache_files[0].read_bytes()).splitlines()
            tampered = json.loads(lines[1])
            tampered["outcome"]["long_gross_points"] += 1.0
            lines[1] = json.dumps(
                tampered, sort_keys=True, separators=(",", ":"),
            ).encode()
            cache_files[0].write_bytes(gzip.compress(b"\n".join(lines) + b"\n"))
            corrupted = StringIO()

            self.assertEqual(main(argv, stdout=corrupted), 0)

            rejected = json.loads(corrupted.getvalue())
            self.assertEqual(rejected["status"], "REJECTED_INSUFFICIENT_DATA")
            self.assertTrue(
                any("SAMPLE_CACHE_INVALID" in reason for reason in rejected["reasons"]),
                rejected["reasons"],
            )

    def test_existing_lineage_version_mismatch_fails_closed_without_overwrite(self) -> None:
        from tmf_research.features.context_builder import ResearchBuildSpec
        from tmf_research.validation.dataset_lineage import DatasetValidationError, Phase5DatasetIssuer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_calendar(calendar, days=55, minutes=25)
            store, manifests = _raw_market(root / "raw", days=55, minutes=25)
            witness = MemoryTrustedWitness()
            issuer = Phase5DatasetIssuer()
            issuer.issue(
                raw_store=store, manifests=manifests,
                spec=ResearchBuildSpec(calendar=calendar),
                holdout_root=root / "holdout", witness=witness,
            )
            receipt = (root / "holdout" / "dataset.lineage.json").read_bytes()
            state = (root / "holdout" / "holdout.state.json").read_bytes()

            with self.assertRaisesRegex(DatasetValidationError, "MISMATCH"):
                issuer.issue(
                    raw_store=store, manifests=manifests,
                    spec=ResearchBuildSpec(calendar=calendar, feature_version="features-v2"),
                    holdout_root=root / "holdout", witness=witness,
                )

            self.assertEqual((root / "holdout" / "dataset.lineage.json").read_bytes(), receipt)
            self.assertEqual((root / "holdout" / "holdout.state.json").read_bytes(), state)

    def test_strict_market_semantics_reject_every_invalid_price_volume_book_and_session(self) -> None:
        from tmf_research.processing.raw_decoder import validate_research_event

        when = datetime(2026, 1, 2, 8, 45, tzinfo=UTC)
        tick = TickEvent(
            event_id="tick", received_at=when, exchange_datetime=when,
            alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
            code="TMF202607", close=23_000.0, volume=1, simtrade=False,
            trading_date="2026-01-02", session="DAY", raw_payload={},
        )
        quote = BidAskEvent(
            event_id="quote", received_at=when, exchange_datetime=when,
            alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
            code="TMF202607", bid_prices=(22_999.5,), bid_volumes=(1,),
            ask_prices=(23_000.5,), ask_volumes=(1,), simtrade=False,
            trading_date="2026-01-02", session="DAY", raw_payload={},
        )
        invalid = (
            replace(tick, close=0.0),
            replace(tick, volume=-1),
            replace(tick, simtrade=True),
            replace(tick, session="CLOSED"),
            replace(quote, bid_prices=(23_001.0,), ask_prices=(23_000.0,)),
            replace(quote, bid_prices=(0.0,)),
            replace(quote, bid_volumes=(-1,)),
            replace(quote, target_code="TMF209912"),
        )

        for event in invalid:
            with self.subTest(event=event.event_id, value=event):
                self.assertTrue(validate_research_event(event))

    def test_one_inconsistent_record_revokes_an_otherwise_sufficient_build(self) -> None:
        from tmf_research.features.context_builder import ResearchBuildSpec
        from tmf_research.validation.dataset_lineage import Phase5DatasetIssuer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_day_night_calendar(calendar, days=55, minutes=25)
            store, manifests = _raw_day_night_market(
                root / "raw", days=55, minutes=25,
                false_night_dates=False, one_mismatched_record=True,
                one_simtrade_record=True,
            )
            result = Phase5DatasetIssuer().issue(
                raw_store=store, manifests=manifests,
                spec=ResearchBuildSpec(calendar=calendar),
                holdout_root=root / "holdout", witness=MemoryTrustedWitness(),
            )

            self.assertEqual(result.status, "REJECTED_INSUFFICIENT_DATA")
            self.assertIn("RAW_SESSION_OR_EFFECTIVE_DATE_MISMATCH", result.rejection_reasons)
            self.assertIn("SIMTRADE", result.rejection_reasons)
            self.assertFalse((root / "holdout").exists())

    def test_raw_declared_dates_cannot_inflate_resolved_effective_trading_days(self) -> None:
        from tmf_research.features.context_builder import ResearchBuildSpec
        from tmf_research.validation.dataset_lineage import Phase5DatasetIssuer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_day_night_calendar(calendar, days=30, minutes=25)
            store, manifests = _raw_day_night_market(
                root / "raw", days=30, minutes=25, false_night_dates=True,
            )
            evidence = Phase5DatasetIssuer().issue(
                raw_store=store,
                manifests=manifests,
                spec=ResearchBuildSpec(
                    calendar=calendar,
                    entry_fee_points=0.0,
                    exit_fee_points=0.0,
                    tax_points=0.0,
                ),
                holdout_root=root / "holdout",
                witness=MemoryTrustedWitness(),
            )

            self.assertEqual(evidence.status, "REJECTED_INSUFFICIENT_DATA")
            self.assertFalse((root / "holdout").exists())

    def test_correct_day_and_night_records_share_the_resolved_effective_date(self) -> None:
        from tmf_research.features.context_builder import ResearchBuildSpec
        from tmf_research.validation.dataset_lineage import Phase5DatasetIssuer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_day_night_calendar(calendar, days=55, minutes=25)
            store, manifests = _raw_day_night_market(
                root / "raw", days=55, minutes=25, false_night_dates=False,
            )
            evidence = Phase5DatasetIssuer().issue(
                raw_store=store,
                manifests=manifests,
                spec=ResearchBuildSpec(calendar=calendar),
                holdout_root=root / "holdout",
                witness=MemoryTrustedWitness(),
            )

            self.assertEqual(evidence.status, "READY")
            self.assertGreaterEqual(len(evidence.fold_manifests), 5)

    def test_issuer_has_no_public_fabricated_dataset_or_return_inputs(self) -> None:
        from tmf_research.validation.dataset_lineage import DatasetBuildResult, Phase5DatasetIssuer

        parameters = inspect.signature(Phase5DatasetIssuer.issue).parameters
        forbidden = {"rows", "folds", "returns", "net_returns", "callback", "builder"}
        self.assertTrue(forbidden.isdisjoint(parameters))
        with self.assertRaises(TypeError):
            DatasetBuildResult()

    def test_verified_raw_suffix_reaches_a_lineage_bound_locked_holdout(self) -> None:
        from tmf_research.features.context_builder import ResearchBuildSpec
        from tmf_research.validation.dataset_lineage import Phase5DatasetIssuer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_calendar(calendar, days=55, minutes=25)
            store, manifests = _raw_market(root / "raw", days=55, minutes=25)
            witness = MemoryTrustedWitness()
            evidence = Phase5DatasetIssuer().issue(
                raw_store=store,
                manifests=manifests,
                spec=ResearchBuildSpec(
                    calendar=calendar,
                    entry_fee_points=0.0,
                    exit_fee_points=0.0,
                    tax_points=0.0,
                ),
                holdout_root=root / "holdout",
                witness=witness,
            )

            self.assertEqual(evidence.status, "READY")
            self.assertEqual(evidence.raw_dataset_hash, store.phase5_provenance(manifests).dataset_hash)
            self.assertGreaterEqual(len(evidence.fold_manifests), 5)
            self.assertEqual(
                evidence.fold_manifest_hashes,
                tuple(value.content_hash for value in evidence.fold_manifests),
            )
            self.assertGreater(evidence.holdout_row_count, 0)
            self.assertEqual(LockedHoldout(root / "holdout", witness=witness).status, "LOCKED")
            evidence.assert_current()
            self.assertEqual(
                tuple(value.manifest for value in evidence.fold_capabilities),
                evidence.fold_manifests,
            )
            development_ids = {value.source.row_id for value in evidence.development_samples}
            self.assertTrue(development_ids)
            regime_families = (
                {"DAY", "NIGHT"},
                {"HIGH_VOLATILITY", "MEDIUM_VOLATILITY", "LOW_VOLATILITY"},
                {"TRENDING", "RANGING"},
                {"EXPIRY_WEEK", "NON_EXPIRY_WEEK"},
                {"OPENING_30M", "INTRADAY", "CLOSING_30M"},
            )
            for outcome in evidence.development_outcomes:
                self.assertTrue(outcome.cost_complete)
                self.assertTrue(all(
                    len(set(outcome.regime_tags) & family) == 1
                    for family in regime_families
                ))
                self.assertAlmostEqual(
                    outcome.long_gross_points - outcome.round_trip_cost_points,
                    outcome.long_net_points,
                )
                self.assertAlmostEqual(
                    outcome.short_gross_points - outcome.round_trip_cost_points,
                    outcome.short_net_points,
                )
            self.assertTrue(all(
                row_id in development_ids
                for capability in evidence.fold_capabilities
                for role in (capability.manifest.inner_train, capability.manifest.inner_validation, capability.manifest.outer_test)
                for row_id, _row_hash in role.row_hashes
            ))
            self.assertTrue(development_ids.isdisjoint(evidence.lineage.holdout_row_ids))
            from tmf_research.models.calibration import fit_two_stage_calibrators
            from tmf_research.models.training import Phase4TrainingSpec, train_phase4_model
            from tmf_research.models.provenance import canonical_hash, freeze_decision_policy
            from tmf_research.validation.fold_evaluation import evaluate_outer_fold

            capability = evidence.fold_capabilities[0]
            feature_order = tuple(capability.inner_train.rows[0].features)
            required = tuple(
                name for name in feature_order
                if all(
                    row.features[name] is not None
                    for row in (*capability.inner_train.rows, *capability.inner_validation.rows)
                )
            )
            self.assertLessEqual(len(feature_order) - len(required), 10)
            trained = train_phase4_model(
                capability.inner_train,
                Phase4TrainingSpec(
                    primary_features=feature_order,
                    required_features=required,
                    max_iterations=1,
                ),
            )
            predictions = trained.predict_inner_validation(capability.inner_validation)
            calibration = fit_two_stage_calibrators(predictions)
            self.assertEqual(
                calibration.calibrator.provenance.manifest,
                capability.manifest,
            )
            policy = freeze_decision_policy(
                calibration,
                thresholds_hash=canonical_hash({
                    "trade_probability": 0.5, "direction_probability": 0.5,
                }),
                rules_hash="a" * 64,
            )
            outer_predictions = trained.predict_outer_test(
                capability.outer_test, calibration, policy,
            )
            self.assertEqual(
                tuple(value.source_row_id for value in outer_predictions.rows),
                tuple(value.row_id for value in capability.outer_test.rows),
            )
            self.assertTrue(all(
                not hasattr(value, "trade_outcome") and not hasattr(value, "net_return")
                for value in outer_predictions.rows
            ))
            fold_evaluation = evaluate_outer_fold(
                evidence, capability, trained, calibration, policy,
            )
            self.assertEqual(fold_evaluation.evidence.authority, "RAW_DERIVED")
            self.assertAlmostEqual(
                fold_evaluation.evidence.net_pnl,
                sum(value[-1] for value in fold_evaluation.contribution_rows),
            )
            baseline_rate = sum(
                row.label in ("LONG", "SHORT") for row in capability.inner_train.rows
            ) / len(capability.inner_train.rows)
            self.assertAlmostEqual(
                fold_evaluation.evidence.baseline_brier,
                sum(
                    (baseline_rate - int(row.label in ("LONG", "SHORT"))) ** 2
                    for row in capability.outer_test.rows
                ) / len(capability.outer_test.rows),
            )
            epsilon = 1e-15
            self.assertAlmostEqual(
                fold_evaluation.evidence.baseline_log_loss,
                -sum(
                    int(row.label in ("LONG", "SHORT"))
                    * math.log(max(epsilon, baseline_rate))
                    + int(row.label not in ("LONG", "SHORT"))
                    * math.log(max(epsilon, 1.0 - baseline_rate))
                    for row in capability.outer_test.rows
                ) / len(capability.outer_test.rows),
            )
            from tmf_research.experiments.comparison import (
                ComparisonContext,
                canonical_fold_periods,
            )
            from tmf_research.experiments.registry import ExperimentRegistry
            from tmf_research.validation.fold_evaluation import (
                _candidate_refit_contract_hash,
                _diagnostic_plan_hash,
                evaluate_complete_outer_fold,
            )
            from tests.overfitting.test_experiment_registry import attempt, definition

            thresholds_hash = canonical_hash({
                "trade_probability": 0.5, "direction_probability": 0.5,
            })
            rules_hash = "a" * 64
            candidate_hashes = {
                name: "0" * 64
                for name in (
                    "model", "features", "labels", "parameters",
                    "thresholds", "rules",
                )
            }
            candidate_hashes.update({
                "thresholds": thresholds_hash, "rules": rules_hash,
            })
            base_definition = definition(candidate_hashes=candidate_hashes)
            train_period, evaluation_period = canonical_fold_periods(
                tuple(value.manifest for value in evidence.fold_capabilities),
            )
            fold_plan_hash = hashlib.sha256(json.dumps(
                [value.manifest.content_hash for value in evidence.fold_capabilities],
                separators=(",", ":"),
            ).encode()).hexdigest()
            experiment = ExperimentRegistry.preregister(
                root / "experiment",
                replace(
                    base_definition,
                    train_period=train_period,
                    comparison=ComparisonContext(
                        store.phase5_provenance(manifests).dataset_version,
                        fold_plan_hash,
                        evidence.development_outcomes[0].cost_policy_hash,
                        base_definition.label_version,
                        evaluation_period,
                    ),
                ),
                witness=witness,
            )
            complete_policy = freeze_decision_policy(
                calibration,
                thresholds_hash=thresholds_hash,
                rules_hash=rules_hash,
            )
            complete_spec = Phase4TrainingSpec(
                primary_features=feature_order,
                required_features=required,
                max_iterations=1,
            )
            experiment.append_attempt(attempt("unbound-raw-fold"))
            with self.assertRaisesRegex(ValueError, "exact run"):
                evaluate_complete_outer_fold(
                    evidence, capability, trained, complete_spec,
                    calibration, complete_policy, experiment.evidence(),
                )
            experiment.append_attempt(replace(
                attempt("complete-raw-fold"),
                result={
                    "dataset_build_hash": evidence.content_hash,
                    "fold_manifest_hash": capability.manifest.content_hash,
                    "training_spec_hash": trained.specification_hash,
                    "model_hash": trained.model.content_hash,
                    "calibration_hash": canonical_hash(calibration.calibrator.to_dict()),
                    "policy_hash": complete_policy.content_hash,
                    "diagnostic_plan_hash": _diagnostic_plan_hash(
                        complete_spec, complete_policy,
                    ),
                    "candidate_refit_contract_hash": _candidate_refit_contract_hash(
                        evidence, complete_spec, experiment.evidence(),
                    ),
                },
            ))
            complete = evaluate_complete_outer_fold(
                evidence, capability, trained, complete_spec,
                calibration, complete_policy, experiment.evidence(),
            )
            self.assertEqual(
                tuple(name for name, _value in complete.ablation_results),
                (
                    "FULL", "PRICE", "VWAP", "ORDER_FLOW", "ORDER_BOOK",
                    "BASIS", "VOLATILITY", "MARKET_STRUCTURE", "TIME",
                ),
            )
            self.assertEqual(len(complete.sensitivity_results), 7)
            self.assertEqual(
                len(complete.coefficient_observations),
                len(trained.model.trade_model.coefficients)
                + len(trained.model.direction_model.coefficients),
            )
            self.assertEqual(
                len(complete.feature_removal_evidence),
                len(complete.coefficient_observations),
            )
            with self.assertRaisesRegex(ValueError, "inner-train capability"):
                train_phase4_model(
                    capability.outer_test,  # type: ignore[arg-type]
                    Phase4TrainingSpec(
                        primary_features=feature_order,
                        required_features=required,
                        max_iterations=1,
                    ),
                )

    def test_raw_mutation_revokes_previously_issued_lineage(self) -> None:
        from tmf_research.features.context_builder import ResearchBuildSpec
        from tmf_research.infrastructure.raw_store import RawIntegrityError
        from tmf_research.validation.dataset_lineage import Phase5DatasetIssuer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_calendar(calendar, days=45, minutes=1)
            store, manifests = _raw_ticks(root / "raw", days=45)
            evidence = Phase5DatasetIssuer().issue(
                raw_store=store,
                manifests=manifests,
                spec=ResearchBuildSpec(calendar=calendar),
                holdout_root=root / "holdout",
                witness=MemoryTrustedWitness(),
            )
            segment = root / "raw" / manifests[0].relative_path
            segment.chmod(0o644)
            segment.write_bytes(segment.read_bytes() + b"{}\n")

            with self.assertRaises(RawIntegrityError):
                evidence.assert_current()

    def test_insufficient_verified_raw_is_rejected_without_creating_a_vault(self) -> None:
        from tmf_research.features.context_builder import ResearchBuildSpec
        from tmf_research.validation.dataset_lineage import Phase5DatasetIssuer

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calendar = root / "calendar.json"
            _write_calendar(calendar, days=39, minutes=1)
            store, manifests = _raw_ticks(root / "raw", days=39)
            evidence = Phase5DatasetIssuer().issue(
                raw_store=store,
                manifests=manifests,
                spec=ResearchBuildSpec(calendar=calendar),
                holdout_root=root / "holdout",
                witness=MemoryTrustedWitness(),
            )

            self.assertEqual(evidence.status, "REJECTED_INSUFFICIENT_DATA")
            self.assertEqual(evidence.holdout_row_count, 0)
            self.assertFalse((root / "holdout").exists())


def _raw_ticks(root: Path, *, days: int) -> tuple[AppendOnlyRawStore, tuple[SegmentManifest, ...]]:
    store = AppendOnlyRawStore(root, writer_version="phase1-v1", dataset_version="dataset-v1")
    manifests = []
    start = datetime(2026, 1, 1, 8, 45, tzinfo=UTC)
    for index in range(days):
        when = start + timedelta(days=index)
        event = TickEvent(
            event_id=f"tick-{index}", received_at=when, exchange_datetime=when,
            alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
            code="TMF202607", close=23_000.0 + index, volume=1, simtrade=False,
            trading_date=when.date().isoformat(), session="DAY", raw_payload={},
        )
        manifests.append(store.append_segment(
            "tick", (event,), segment_id=f"tick-{index}", created_at=when,
        ))
    return store, tuple(manifests)


def _raw_market(
    root: Path, *, days: int, minutes: int,
) -> tuple[AppendOnlyRawStore, tuple[SegmentManifest, ...]]:
    store = AppendOnlyRawStore(root, writer_version="phase1-v1", dataset_version="dataset-v1")
    ticks = []
    quotes = []
    start = datetime(2026, 1, 1, 8, 45, tzinfo=UTC)
    for day in range(days):
        day_start = start + timedelta(days=day)
        for minute in range(minutes):
            when = day_start + timedelta(minutes=minute, seconds=59)
            price = 23_000.0 + day + (minute % 5)
            ticks.append(TickEvent(
                event_id=f"tick-{day}-{minute}", received_at=when, exchange_datetime=when,
                alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                code="TMF202607", close=price, volume=minute + 1, simtrade=False,
                trading_date=when.date().isoformat(), session="DAY", raw_payload={},
                tick_type=1 if minute % 2 == 0 else 2, underlying_price=price - 10.0 - (minute % 3),
            ))
            quotes.append(BidAskEvent(
                event_id=f"quote-{day}-{minute}", received_at=when, exchange_datetime=when,
                alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                code="TMF202607", bid_prices=(price - 0.5,), bid_volumes=(5,),
                ask_prices=(price + 0.5,), ask_volumes=(5,), simtrade=False,
                trading_date=when.date().isoformat(), session="DAY", raw_payload={},
                underlying_price=price - 10.0 - (minute % 3),
            ))
    created = start + timedelta(days=days)
    tick_manifest = store.append_segment("tick", ticks, segment_id="ticks", created_at=created)
    quote_manifest = store.append_segment("bidask", quotes, segment_id="quotes", created_at=created)
    return store, (tick_manifest, quote_manifest)


def _write_calendar(path: Path, *, days: int, minutes: int) -> None:
    start = datetime(2026, 1, 1, 8, 45, tzinfo=UTC)
    values = []
    for index in range(days):
        current = start + timedelta(days=index)
        close = current + timedelta(minutes=minutes)
        values.append({
            "trading_date": current.date().isoformat(),
            "day_open": current.time().replace(tzinfo=None).isoformat(timespec="minutes"),
            "day_close": close.time().replace(tzinfo=None).isoformat(timespec="minutes"),
        })
    path.write_text(json.dumps({
        "version": "calendar-v1", "timezone": "UTC", "days": values,
    }), encoding="utf-8")


def _write_day_night_calendar(path: Path, *, days: int, minutes: int) -> None:
    first_effective = datetime(2026, 1, 2, 8, 45, tzinfo=UTC)
    values = []
    for index in range(days):
        day = first_effective + timedelta(days=index)
        night = day - timedelta(hours=17, minutes=45)
        values.append({
            "trading_date": day.date().isoformat(),
            "day_open": day.time().replace(tzinfo=None).isoformat(timespec="minutes"),
            "day_close": (day + timedelta(minutes=minutes)).time().replace(tzinfo=None).isoformat(timespec="minutes"),
            "night_open": night.isoformat(),
            "night_close": (night + timedelta(minutes=minutes)).isoformat(),
        })
    path.write_text(json.dumps({
        "version": "calendar-day-night-v1", "timezone": "UTC", "days": values,
    }), encoding="utf-8")


def _raw_day_night_market(
    root: Path,
    *,
    days: int,
    minutes: int,
    false_night_dates: bool,
    one_mismatched_record: bool = False,
    one_simtrade_record: bool = False,
) -> tuple[AppendOnlyRawStore, tuple[SegmentManifest, ...]]:
    store = AppendOnlyRawStore(root, writer_version="phase1-v1", dataset_version="dataset-v1")
    ticks = []
    quotes = []
    first_effective = datetime(2026, 1, 2, 8, 45, tzinfo=UTC)
    for day_index in range(days):
        day_start = first_effective + timedelta(days=day_index)
        night_start = day_start - timedelta(hours=17, minutes=45)
        effective = day_start.date().isoformat()
        claimed_night = f"2099-{1 + day_index // 28:02d}-{1 + day_index % 28:02d}" if false_night_dates else effective
        session_values: tuple[tuple[Session, datetime, str], ...] = (
            ("NIGHT", night_start, claimed_night),
            ("DAY", day_start, effective),
        )
        for session, session_start, declared_date in session_values:
            for minute in range(minutes):
                when = session_start + timedelta(minutes=minute, seconds=59)
                price = 23_000.0 + day_index + (minute % 5)
                suffix = f"{day_index}-{session.lower()}-{minute}"
                record_date = (
                    "2098-12-31"
                    if one_mismatched_record and day_index == 0 and session == "NIGHT" and minute == 0
                    else declared_date
                )
                ticks.append(TickEvent(
                    event_id=f"tick-{suffix}", received_at=when, exchange_datetime=when,
                    alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                    code="TMF202607", close=price, volume=minute + 1,
                    simtrade=one_simtrade_record and day_index == 0 and session == "NIGHT" and minute == 0,
                    trading_date=record_date, session=session, raw_payload={},
                    tick_type=1 if minute % 2 == 0 else 2, underlying_price=price - 10.0,
                ))
                quotes.append(BidAskEvent(
                    event_id=f"quote-{suffix}", received_at=when, exchange_datetime=when,
                    alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                    code="TMF202607", bid_prices=(price - 0.5,), bid_volumes=(5,),
                    ask_prices=(price + 0.5,), ask_volumes=(5,), simtrade=False,
                    trading_date=declared_date, session=session, raw_payload={},
                    underlying_price=price - 10.0,
                ))
    created = first_effective + timedelta(days=days)
    return store, (
        store.append_segment("tick", ticks, segment_id="ticks", created_at=created),
        store.append_segment("bidask", quotes, segment_id="quotes", created_at=created),
    )
