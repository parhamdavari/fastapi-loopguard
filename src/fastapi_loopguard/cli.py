"""Standalone command-line entry point: read a report, exit 0/1/2.

Installed as the `loopguard` console script. It exists so an agent or a CI
step can enforce the blocking gate without running inside pytest:

    pytest --loopguard-all-async --loopguard-report=loopguard.json
    loopguard report loopguard.json

This module is a leaf. It imports nothing from the detection path and,
deliberately, nothing from `fastapi_loopguard.pytest_plugin` — that module
imports `pytest`, which is a dev dependency, so pulling it in here would
make the console script unusable in a production install. The report
contract is consumed as data (`docs/loopguard-report.schema.json`), not by
importing the writer.

The schema is not validated at runtime either: that needs `jsonschema`,
also dev-only. Only the two keys the verdict depends on are checked.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TypeGuard

# Exit codes follow the ruff/pyright convention: 0 clean, 1 findings,
# 2 the tool could not do its job.
EXIT_CLEAN = 0
EXIT_BLOCKED = 1
EXIT_ERROR = 2

_EXIT_CODES = """\
exit codes:
  0  clean - no blocking detected in the report
  1  blocking detected
  2  the report is missing, unreadable, or malformed
"""

_VALID_STATUS = ("blocked", "clean")


class ReportError(Exception):
    """The report could not be read or does not carry a verdict (exit 2)."""


def _load_report(path: Path) -> dict[str, Any]:
    """Read and parse the report, or raise ReportError."""
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise ReportError(f"{path}: no such file") from exc
    except OSError as exc:
        raise ReportError(f"{path}: cannot read ({exc.strerror or exc})") from exc

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReportError(
            f"{path}: invalid JSON ({exc.msg} at line {exc.lineno})"
        ) from exc

    if not isinstance(parsed, dict):
        raise ReportError(
            f"{path}: expected a JSON object, got {type(parsed).__name__}"
        )

    report: dict[str, Any] = parsed
    return report


def _is_blocked(report: dict[str, Any], path: Path) -> bool:
    """The run's verdict: True when blocking was detected.

    `status` (schema_version 2) is the verdict. A report without it is a
    schema_version 1 report, and falls back to `totals.flagged > 0` so an
    older report still gates.
    """
    status = report.get("status")
    if status is not None:
        if status not in _VALID_STATUS:
            raise ReportError(f"{path}: unknown status {status!r}")
        return bool(status == "blocked")

    totals = report.get("totals")
    if not isinstance(totals, dict):
        raise ReportError(f"{path}: report has neither 'status' nor 'totals'")

    flagged = totals.get("flagged")
    if _is_number(flagged):
        return flagged > 0
    raise ReportError(f"{path}: totals.flagged is missing or not a number")


def _is_number(value: Any) -> TypeGuard[int | float]:
    """True for a real JSON number (bool is an int in Python; reject it)."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _count(value: Any) -> str:
    return str(value) if _is_number(value) else "unknown"


def _summary_line(report: dict[str, Any], blocked: bool) -> str:
    totals = report.get("totals")
    totals = totals if isinstance(totals, dict) else {}
    threshold = report.get("threshold_ms")
    threshold_text = f"{threshold}ms" if _is_number(threshold) else "unknown"
    return (
        f"loopguard: {'blocked' if blocked else 'clean'}"
        f"  tests={_count(totals.get('tests'))}"
        f"  flagged={_count(totals.get('flagged'))}"
        f"  threshold={threshold_text}"
    )


def _flagged_lines(report: dict[str, Any]) -> list[str]:
    """One line per flagged test: its node id and its worst measured lag."""
    records = report.get("tests")
    if not isinstance(records, list):
        return []

    lines = []
    for record in records:
        if not isinstance(record, dict) or record.get("verdict") != "blocked":
            continue
        events = record.get("events")
        lags = [
            event["lag_ms"]
            for event in (events if isinstance(events, list) else [])
            if isinstance(event, dict) and _is_number(event.get("lag_ms"))
        ]
        worst = f"{max(lags)}ms" if lags else "unknown"
        lines.append(f"  blocked {record.get('nodeid', 'unknown')}  worst_lag={worst}")
    return lines


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loopguard",
        description=(
            "Enforce the LoopGuard blocking gate outside pytest. Run the suite "
            "with --loopguard-report=PATH first, then read the report here."
        ),
        epilog=_EXIT_CODES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    report = subparsers.add_parser(
        "report",
        help="summarize a loopguard.json report and exit 0 (clean) or 1 (blocked)",
        description=(
            "Read an existing loopguard.json, print a short summary, and exit "
            "0 if clean, 1 if blocking was detected, 2 if the report is "
            "missing or malformed."
        ),
        epilog=_EXIT_CODES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    report.add_argument("path", help="path to the JSON report written by pytest")
    report.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="print nothing; communicate through the exit code only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_CLEAN

    path = Path(args.path)
    try:
        report = _load_report(path)
        blocked = _is_blocked(report, path)
    except ReportError as exc:
        print(f"loopguard: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not args.quiet:
        print(_summary_line(report, blocked))
        for line in _flagged_lines(report):
            print(line)

    return EXIT_BLOCKED if blocked else EXIT_CLEAN


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
