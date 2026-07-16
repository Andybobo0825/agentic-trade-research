from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tmf_research.domain.events import BidAskEvent, TickEvent
from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, SegmentManifest
from tmf_research.validation.locked_holdout import LockedHoldout
from tests.support.trusted_witness import MemoryTrustedWitness


class Phase5DatasetLineageTests(unittest.TestCase):
    def test_issuer_has_no_public_fabricated_dataset_or_return_inputs(self) -> None:
        from tmf_research.validation.dataset_lineage import Phase5DatasetIssuer

        parameters = inspect.signature(Phase5DatasetIssuer.issue).parameters
        forbidden = {"rows", "folds", "returns", "net_returns", "callback", "builder"}
        self.assertTrue(forbidden.isdisjoint(parameters))

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
                spec=ResearchBuildSpec(calendar=calendar),
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
            when = day_start + timedelta(minutes=minute)
            price = 23_000.0 + day + (minute % 5)
            ticks.append(TickEvent(
                event_id=f"tick-{day}-{minute}", received_at=when, exchange_datetime=when,
                alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                code="TMF202607", close=price, volume=minute + 1, simtrade=False,
                trading_date=when.date().isoformat(), session="DAY", raw_payload={},
            ))
            quotes.append(BidAskEvent(
                event_id=f"quote-{day}-{minute}", received_at=when, exchange_datetime=when,
                alias_code="TMFR1", target_code="TMF202607", delivery_month="202607",
                code="TMF202607", bid_prices=(price - 0.5,), bid_volumes=(5,),
                ask_prices=(price + 0.5,), ask_volumes=(5,), simtrade=False,
                trading_date=when.date().isoformat(), session="DAY", raw_payload={},
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
