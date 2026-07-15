from __future__ import annotations

import argparse
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
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    args = build_parser().parse_args(argv)
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
