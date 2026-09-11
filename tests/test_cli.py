"""Tests for fastapi_loopguard.cli — the `loopguard` console script.

The exit-code contract is the point of the module: 0 clean, 1 blocking
detected, 2 the report could not be read. Tests call `main([...])`
directly and read the return value plus captured output, so nothing here
depends on the console script being on PATH.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# Enable pytester fixture for the end-to-end plugin-to-CLI test
pytest_plugins = ["pytester"]

import fastapi_loopguard.cli  # noqa: E402
from fastapi_loopguard.cli import (  # noqa: E402
    EXIT_BLOCKED,
    EXIT_CLEAN,
    EXIT_ERROR,
    main,
)

_BLOCKED_REPORT: dict[str, Any] = {
    "schema_version": 2,
    "status": "blocked",
    "threshold_ms": 50.0,
    "totals": {"tests": 3, "flagged": 2},
    "tests": [
        {
            "nodeid": "tests/test_api.py::test_upload",
            "verdict": "blocked",
            "events": [
                {"lag_ms": 61.5, "threshold_ms": 50.0},
                {"lag_ms": 180.24, "threshold_ms": 50.0},
            ],
            "hints": ["time.sleep(n) -> await asyncio.sleep(n)"],
        },
        {
            "nodeid": "tests/test_api.py::test_render",
            "verdict": "blocked",
            "events": [{"lag_ms": 95.0, "threshold_ms": 50.0}],
            "hints": [],
        },
        {
            "nodeid": "tests/test_api.py::test_list",
            "verdict": "clean",
            "events": [],
            "hints": [],
        },
    ],
}

_CLEAN_REPORT: dict[str, Any] = {
    "schema_version": 2,
    "status": "clean",
    "threshold_ms": 50.0,
    "totals": {"tests": 3, "flagged": 0},
    "tests": [
        {
            "nodeid": "tests/test_api.py::test_list",
            "verdict": "clean",
            "events": [],
            "hints": [],
        }
    ],
}


def _write(tmp_path: Path, payload: Any, name: str = "loopguard.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return str(path)


class TestCleanReport:
    """A clean report exits 0 and says so in one greppable line."""

    def test_exit_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["report", _write(tmp_path, _CLEAN_REPORT)]) == EXIT_CLEAN

        out = capsys.readouterr().out
        assert out.splitlines() == [
            "loopguard: clean  tests=3  flagged=0  threshold=50.0ms"
        ]

    def test_zero_tests_is_clean_in_the_report_contract(self, tmp_path: Path) -> None:
        """The report itself says clean; --allow-empty accepts it as exit 0.

        Without --allow-empty the CLI treats this as a setup failure — see
        TestEmptyRun below.
        """
        report = {
            "schema_version": 2,
            "status": "clean",
            "threshold_ms": 50.0,
            "totals": {"tests": 0, "flagged": 0},
            "tests": [],
        }
        path = _write(tmp_path, report)
        assert main(["report", path, "--allow-empty"]) == EXIT_CLEAN


class TestEmptyRun:
    """A clean verdict from a run that instrumented zero tests is not
    evidence the suite is clean — the gate must fail closed by default."""

    _ZERO_TESTS_REPORT: dict[str, Any] = {
        "schema_version": 2,
        "status": "clean",
        "threshold_ms": 50.0,
        "totals": {"tests": 0, "flagged": 0},
        "tests": [],
    }

    def test_zero_tests_clean_exits_two_by_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(tmp_path, self._ZERO_TESTS_REPORT)
        assert main(["report", path]) == EXIT_ERROR

        captured = capsys.readouterr()
        assert "loopguard: clean  tests=0  flagged=0" in captured.out
        assert "0 tests" in captured.err
        assert "--allow-empty" in captured.err

    def test_zero_tests_clean_with_allow_empty_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(tmp_path, self._ZERO_TESTS_REPORT)
        assert main(["report", path, "--allow-empty"]) == EXIT_CLEAN

        captured = capsys.readouterr()
        assert "loopguard: clean  tests=0  flagged=0" in captured.out
        assert captured.err == ""

    def test_zero_tests_but_flagged_is_still_blocked(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A pathological report (flagged > 0, tests == 0) is a verdict,
        not an empty run — it must not fall into the --allow-empty path."""
        report = {
            "status": "blocked",
            "threshold_ms": 50.0,
            "totals": {"tests": 0, "flagged": 1},
            "tests": [],
        }
        path = _write(tmp_path, report)
        assert main(["report", path]) == EXIT_BLOCKED
        assert capsys.readouterr().err == ""

    def test_quiet_still_warns_on_stderr_for_an_empty_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--quiet silences stdout, not the setup-failure warning."""
        path = _write(tmp_path, self._ZERO_TESTS_REPORT)
        assert main(["report", path, "--quiet"]) == EXIT_ERROR

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "--allow-empty" in captured.err

    def test_no_totals_at_all_is_not_treated_as_an_empty_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A `status`-only report has no `totals.tests` to be zero, so the
        empty-run gate must not fire — the count is unknown, not zero."""
        path = _write(tmp_path, {"status": "clean"})
        assert main(["report", path]) == EXIT_CLEAN

        captured = capsys.readouterr()
        assert "loopguard: clean  tests=unknown  flagged=unknown" in captured.out
        assert captured.err == ""

    def test_v1_totals_without_a_tests_key_is_not_an_empty_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A schema_version 1 report can carry `totals` without a `tests`
        key; that is also an unknown count, not a zero one."""
        report = {"schema_version": 1, "totals": {"flagged": 0}}
        path = _write(tmp_path, report)
        assert main(["report", path]) == EXIT_CLEAN

        captured = capsys.readouterr()
        assert "loopguard: clean  tests=unknown  flagged=0" in captured.out
        assert captured.err == ""


class TestBlockedReport:
    """A blocked report exits 1 and names every flagged test."""

    def test_exit_one_with_per_test_lines(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["report", _write(tmp_path, _BLOCKED_REPORT)]) == EXIT_BLOCKED

        assert capsys.readouterr().out.splitlines() == [
            "loopguard: blocked  tests=3  flagged=2  threshold=50.0ms",
            "  blocked tests/test_api.py::test_upload  worst_lag=180.24ms",
            "  blocked tests/test_api.py::test_render  worst_lag=95.0ms",
        ]

    def test_worst_lag_is_the_maximum_not_the_first(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["report", _write(tmp_path, _BLOCKED_REPORT)])
        out = capsys.readouterr().out
        assert "worst_lag=180.24ms" in out
        assert "worst_lag=61.5ms" not in out

    def test_blocked_test_without_events(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A flagged verdict with no measured event still gets a line."""
        report = {
            "status": "blocked",
            "threshold_ms": 50.0,
            "totals": {"tests": 1, "flagged": 1},
            "tests": [
                {"nodeid": "t.py::test_x", "verdict": "blocked", "events": []},
            ],
        }
        assert main(["report", _write(tmp_path, report)]) == EXIT_BLOCKED
        assert "  blocked t.py::test_x  worst_lag=unknown" in capsys.readouterr().out


class TestPartialReport:
    """Keys the verdict does not depend on degrade, they do not error."""

    def test_status_only_report_prints_unknown_counts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A verdict is enough to gate; missing totals and tests are not fatal."""
        assert main(["report", _write(tmp_path, {"status": "blocked"})]) == EXIT_BLOCKED

        assert capsys.readouterr().out.splitlines() == [
            "loopguard: blocked  tests=unknown  flagged=unknown  threshold=unknown"
        ]


class TestSchemaV1Fallback:
    """A report without `status` falls back to totals.flagged > 0."""

    def test_v1_blocked(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        report = {
            "schema_version": 1,
            "threshold_ms": 50.0,
            "totals": {"tests": 2, "flagged": 1},
            "tests": [
                {
                    "nodeid": "t.py::test_blocks",
                    "verdict": "blocked",
                    "events": [{"lag_ms": 120.0, "threshold_ms": 50.0}],
                    "hints": [],
                }
            ],
        }
        assert main(["report", _write(tmp_path, report)]) == EXIT_BLOCKED
        assert "loopguard: blocked" in capsys.readouterr().out

    def test_v1_clean(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        report = {
            "schema_version": 1,
            "threshold_ms": 50.0,
            "totals": {"tests": 2, "flagged": 0},
            "tests": [],
        }
        assert main(["report", _write(tmp_path, report)]) == EXIT_CLEAN
        assert "loopguard: clean" in capsys.readouterr().out


class TestMalformed:
    """Every unusable report is exit 2 with one line on stderr."""

    def _assert_error(self, capsys: pytest.CaptureFixture[str]) -> str:
        captured = capsys.readouterr()
        assert captured.out == ""
        assert len(captured.err.splitlines()) == 1
        assert captured.err.startswith("loopguard: ")
        return captured.err

    def test_missing_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["report", str(tmp_path / "absent.json")]) == EXIT_ERROR
        assert "no such file" in self._assert_error(capsys)

    def test_unreadable_path_is_a_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["report", str(tmp_path)]) == EXIT_ERROR
        self._assert_error(capsys)

    def test_invalid_json(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "loopguard.json"
        path.write_text("{not json")
        assert main(["report", str(path)]) == EXIT_ERROR
        assert "invalid JSON" in self._assert_error(capsys)

    def test_empty_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "loopguard.json"
        path.write_text("")
        assert main(["report", str(path)]) == EXIT_ERROR
        assert "invalid JSON" in self._assert_error(capsys)

    def test_json_that_is_not_an_object(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["report", _write(tmp_path, ["blocked"])]) == EXIT_ERROR
        assert "expected a JSON object" in self._assert_error(capsys)

    def test_neither_status_nor_totals(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {"schema_version": 2, "threshold_ms": 50.0, "tests": []}
        assert main(["report", _write(tmp_path, payload)]) == EXIT_ERROR
        assert "neither 'status' nor 'totals'" in self._assert_error(capsys)

    def test_totals_without_flagged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {"schema_version": 1, "totals": {"tests": 3}}
        assert main(["report", _write(tmp_path, payload)]) == EXIT_ERROR
        assert "totals.flagged" in self._assert_error(capsys)

    def test_unknown_status_value(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {"status": "probably-fine", "totals": {"tests": 1, "flagged": 0}}
        assert main(["report", _write(tmp_path, payload)]) == EXIT_ERROR
        assert "unknown status 'probably-fine'" in self._assert_error(capsys)

    def test_unknown_status_wins_over_the_totals_fallback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A present-but-invalid status is an error, never silently ignored."""
        payload = {"status": True, "totals": {"tests": 1, "flagged": 0}}
        assert main(["report", _write(tmp_path, payload)]) == EXIT_ERROR
        self._assert_error(capsys)


class TestQuiet:
    """--quiet keeps the exit code and drops the output."""

    def test_quiet_blocked(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(tmp_path, _BLOCKED_REPORT)
        assert main(["report", path, "--quiet"]) == EXIT_BLOCKED
        assert capsys.readouterr() == ("", "")

    def test_quiet_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["report", _write(tmp_path, _CLEAN_REPORT), "-q"]) == EXIT_CLEAN
        assert capsys.readouterr() == ("", "")

    def test_quiet_still_reports_a_malformed_file_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A missing report is a tool failure, not a verdict to silence."""
        argv = ["report", str(tmp_path / "absent.json"), "--quiet"]
        assert main(argv) == EXIT_ERROR
        assert capsys.readouterr().err != ""


class TestUsage:
    """argparse behaviour the exit-code convention relies on."""

    def test_no_subcommand_prints_help_and_exits_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([]) == EXIT_CLEAN
        assert "usage: loopguard" in capsys.readouterr().out

    def test_help_exits_zero_and_documents_the_exit_codes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["--help"])
        assert excinfo.value.code == EXIT_CLEAN

        out = capsys.readouterr().out
        assert "exit codes:" in out
        assert "0  clean" in out
        assert "1  blocking detected" in out
        assert "2  the report is missing, unreadable, or malformed" in out

    def test_report_help_documents_the_exit_codes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["report", "--help"])
        assert excinfo.value.code == EXIT_CLEAN

        out = capsys.readouterr().out
        assert "exit codes:" in out
        assert "--allow-empty" in out

    def test_unknown_subcommand_exits_two(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["inspect"])
        assert excinfo.value.code == EXIT_ERROR

    def test_missing_path_argument_exits_two(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["report"])
        assert excinfo.value.code == EXIT_ERROR


class TestNoPytestImport:
    """pytest is a dev dependency; the console script must not need it."""

    def test_importing_cli_does_not_import_pytest(self) -> None:
        # A subprocess is the only honest check: this test process has
        # already imported pytest, so an in-process assertion proves nothing.
        code = (
            "import sys\n"
            "import fastapi_loopguard.cli\n"
            "assert 'pytest' not in sys.modules, 'cli pulled in pytest'\n"
            "assert 'fastapi_loopguard.pytest_plugin' not in sys.modules, (\n"
            "    'cli pulled in pytest_plugin'\n"
            ")\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    def test_cli_imports_only_the_standard_library(self) -> None:
        """Read the imports off the AST, so a docstring cannot fool it."""
        source = Path(fastapi_loopguard.cli.__file__).read_text()
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        assert imported <= {
            "__future__",
            "argparse",
            "json",
            "sys",
            "pathlib",
            "typing",
        }


class TestEndToEnd:
    """A real plugin-written report, fed to the CLI."""

    def test_generated_blocked_report_exits_one(
        self, pytester: pytest.Pytester, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            @pytest.mark.no_blocking
            async def test_blocks():
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)

            @pytest.mark.no_blocking
            async def test_clean():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("--loopguard-report=loopguard.json")
        result.assert_outcomes(failed=1, passed=1)

        report_path = pytester.path / "loopguard.json"
        capsys.readouterr()  # drop whatever the inner pytest run printed
        assert main(["report", str(report_path)]) == EXIT_BLOCKED

        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "loopguard: blocked  tests=2  flagged=1  threshold=10.0ms"
        assert len(lines) == 2
        assert "test_blocks" in lines[1]
        assert "worst_lag=" in lines[1]

    def test_generated_clean_report_exits_zero(
        self, pytester: pytest.Pytester, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking
            async def test_clean():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 50
        """)

        result = pytester.runpytest("--loopguard-report=loopguard.json")
        result.assert_outcomes(passed=1)

        report_path = pytester.path / "loopguard.json"
        assert main(["report", str(report_path)]) == EXIT_CLEAN
        assert "loopguard: clean" in capsys.readouterr().out
