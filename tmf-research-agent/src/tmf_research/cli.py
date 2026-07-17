from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TextIO

from tmf_research.security.readonly_verifier import verify_readonly

if TYPE_CHECKING:
    from tmf_research.collection.backfill import HistoricalTickSource


class GatewayFactory(Protocol):
    def __call__(
        self,
        *,
        api_key: str,
        secret_key: str,
        simulation: bool,
        alias_code: str,
    ) -> HistoricalTickSource: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmf",
        description="Read-only TMF research utilities",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify-readonly",
        help="fail closed on unsafe source or dependency boundaries",
    )
    verify.add_argument(
        "--root",
        type=Path,
        default=None,
        help="sidecar project root or its src directory",
    )
    phase5 = commands.add_parser(
        "phase5-status",
        help="derive the offline Phase 5 lineage status from verified raw data",
    )
    phase5.add_argument("--raw-root", type=Path, required=True)
    phase5.add_argument("--calendar", type=Path, required=True)
    phase5.add_argument("--witness-db", type=Path, required=True)
    backfill = commands.add_parser(
        "backfill",
        help="download historical TMF ticks into the append-only raw store",
    )
    backfill.add_argument("--start", required=True, help="first date, YYYY-MM-DD")
    backfill.add_argument("--end", required=True, help="last date, YYYY-MM-DD")
    backfill.add_argument("--data-root", type=Path, default=Path("data"))
    backfill.add_argument("--dataset-version", default="dataset-v1")
    backfill.add_argument("--alias-code", default="TMFR1")
    backfill.add_argument("--pause-seconds", type=float, default=0.35)
    backfill.add_argument(
        "--simulation",
        action="store_true",
        help="use the Shioaji simulation environment (never for research data)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    gateway_factory: GatewayFactory | None = None,
) -> int:
    output = stdout or sys.stdout
    args = build_parser().parse_args(argv)
    if args.command == "phase5-status":
        return _phase5_status(args.raw_root, args.calendar, args.witness_db, output)
    if args.command == "backfill":
        return _backfill(args, output, gateway_factory)
    if args.command != "verify-readonly":
        raise AssertionError(f"unhandled command: {args.command}")

    root = (
        discover_project_root()
        if args.root is None
        else args.root.resolve()
    )
    source_root = root if root.name == "src" else root / "src"
    report = verify_readonly(source_root)
    if report.ok:
        print(report.render(), file=output)
        return 0

    print(f"READONLY VIOLATION ({len(report.findings)} findings)", file=output)
    print(report.render(), file=output)
    return 1


def _backfill(
    args: argparse.Namespace,
    output: TextIO,
    gateway_factory: GatewayFactory | None,
) -> int:
    root = discover_project_root()
    report = verify_readonly(root / "src")
    if not report.ok:
        print(f"READONLY VIOLATION ({len(report.findings)} findings)", file=output)
        print(report.render(), file=output)
        return 1
    api_key = os.environ.get("SJ_API_KEY", "").strip()
    secret_key = os.environ.get("SJ_SEC_KEY", "").strip()
    if not api_key or not secret_key:
        print(
            "CREDENTIALED_VALIDATION_NOT_RUN: SJ_API_KEY and SJ_SEC_KEY are required",
            file=output,
        )
        return 1

    from tmf_research.collection.backfill import BackfillError, run_backfill
    from tmf_research.infrastructure.raw_store import AppendOnlyRawStore

    if gateway_factory is None:
        from tmf_research.infrastructure.market_session import (
            open_market_data_session,
        )

        gateway_factory = open_market_data_session
    gateway = gateway_factory(
        api_key=api_key,
        secret_key=secret_key,
        simulation=bool(args.simulation),
        alias_code=str(args.alias_code),
    )
    store = AppendOnlyRawStore(
        Path(args.data_root),
        writer_version="backfill-v1",
        dataset_version=str(args.dataset_version),
    )
    pause_seconds = max(0.0, float(args.pause_seconds))
    try:
        summary = run_backfill(
            gateway,
            store,
            start_date=str(args.start),
            end_date=str(args.end),
            pause=(lambda: time.sleep(pause_seconds)) if pause_seconds else None,
        )
    except BackfillError as error:
        print(f"BACKFILL FAILED: {error}", file=output)
        return 1
    for result in summary.results:
        print(
            f"{result.date} {result.status} records={result.record_count}",
            file=output,
        )
    print(
        f"BACKFILL COMPLETE alias={summary.alias_code}"
        f" dataset={summary.dataset_version}"
        f" stored_days={summary.stored_days}"
        f" already_stored_days={summary.already_stored_days}"
        f" no_data_days={summary.no_data_days}"
        f" stored_records={summary.stored_records}",
        file=output,
    )
    return 0


def _phase5_status(raw_root: Path, calendar: Path, witness_db: Path, output: TextIO) -> int:
    status = "REJECTED_INSUFFICIENT_DATA"
    try:
        from tmf_research.features.context_builder import ResearchBuildSpec
        from tmf_research.infrastructure.raw_store import AppendOnlyRawStore, SegmentManifest
        from tmf_research.infrastructure.trusted_witness import SqliteTrustedWitness
        from tmf_research.validation.dataset_lineage import Phase5DatasetIssuer

        records = tuple(
            json.loads(line)
            for line in (raw_root / "manifest.ndjson").read_text(encoding="utf-8").splitlines()
        )
        manifests = tuple(SegmentManifest(**record) for record in records)
        if manifests:
            store = AppendOnlyRawStore(
                raw_root,
                writer_version=manifests[0].writer_version,
                dataset_version=manifests[0].dataset_version,
            )
            evidence = Phase5DatasetIssuer().issue(
                raw_store=store,
                manifests=manifests,
                spec=ResearchBuildSpec(calendar=calendar),
                holdout_root=raw_root.parent / "phase5-holdout",
                witness=SqliteTrustedWitness(witness_db.resolve()),
            )
            status = evidence.status
    except (OSError, ValueError, TypeError, RuntimeError, json.JSONDecodeError):
        status = "REJECTED_INSUFFICIENT_DATA"
    print(json.dumps({"status": status}, separators=(",", ":")), file=output)
    return 0


def discover_project_root(start: Path | None = None) -> Path:
    """Find the checkout at runtime so installed console scripts scan the cwd."""

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "src" / "tmf_research").is_dir()
        ):
            return candidate
    return current


if __name__ == "__main__":
    raise SystemExit(main())
