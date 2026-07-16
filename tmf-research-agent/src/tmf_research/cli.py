from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from tmf_research.security.readonly_verifier import verify_readonly


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
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    args = build_parser().parse_args(argv)
    if args.command == "phase5-status":
        return _phase5_status(args.raw_root, args.calendar, args.witness_db, output)
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
