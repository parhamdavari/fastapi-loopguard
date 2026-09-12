"""Tests for fastapi_loopguard.pytest_plugin module."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import re
import time
from pathlib import Path
from typing import Any

import jsonschema
import pytest

# Enable pytester fixture for plugin integration tests
pytest_plugins = ["pytester"]

from fastapi_loopguard import pytest_plugin  # noqa: E402
from fastapi_loopguard.hints import hint_lines  # noqa: E402
from fastapi_loopguard.pytest_plugin import (  # noqa: E402
    REPORT_SCHEMA_VERSION,
    BlockingDetector,
)


def _wrapper_source_lines() -> list[str]:
    """The body of pytest_plugin's `wrapped`, as a traceback would print it.

    Read from the module rather than hard-coded so the traceback-hiding test
    keeps matching the wrapper when the wrapper changes.
    """
    source = Path(pytest_plugin.__file__).read_text()
    tree = ast.parse(source)
    wrapped = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "wrapped"
    )
    segment = ast.get_source_segment(source, wrapped) or ""
    # Short lines ("try:", ")") are too generic to prove anything.
    return [line.strip() for line in segment.splitlines() if len(line.strip()) > 25]


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC_PATH = _REPO_ROOT / "docs" / "AI-HARNESS.md"
_SCHEMA_PATH = _REPO_ROOT / "docs" / "loopguard-report.schema.json"


class TestBlockingDetector:
    """Tests for BlockingDetector class."""

    async def test_start_and_stop(self) -> None:
        """Test detector starts and stops cleanly."""
        detector = BlockingDetector(threshold_ms=50.0)

        await detector.start()
        assert detector._running is True
        assert detector._task is not None

        await detector.stop()
        assert detector._running is False

    async def test_detects_blocking_above_threshold(self) -> None:
        """Test detector detects blocking above threshold."""
        detector = BlockingDetector(threshold_ms=20.0)

        await detector.start()

        # Give detector time to start monitoring
        await asyncio.sleep(0.02)

        # Block the event loop
        time.sleep(0.1)  # 100ms blocking - well above 20ms threshold

        # Give detector time to detect (needs at least one monitor cycle after block)
        await asyncio.sleep(0.05)

        await detector.stop()

        assert len(detector.blocking_events) > 0
        assert max(detector.blocking_events) > 20.0

    async def test_no_false_positive_async_sleep(self) -> None:
        """Test async sleep does NOT trigger detection."""
        detector = BlockingDetector(threshold_ms=30.0)

        await detector.start()

        # Async sleep should NOT block
        await asyncio.sleep(0.05)

        await detector.stop()

        # Should have no or very few blocking events
        # (occasional small spikes may occur due to system load)
        if detector.blocking_events:
            # Any detected events should be small (< 30ms)
            assert all(lag < 30.0 for lag in detector.blocking_events)

    async def test_records_multiple_events(self) -> None:
        """Test detector records multiple blocking events."""
        detector = BlockingDetector(threshold_ms=15.0)

        await detector.start()

        # Give detector time to start
        await asyncio.sleep(0.02)

        # Multiple blocks with longer delays to ensure detection
        time.sleep(0.05)  # 50ms - first block
        await asyncio.sleep(0.03)  # Let detector catch up
        time.sleep(0.05)  # 50ms - second block
        await asyncio.sleep(0.03)  # Let detector catch up

        await detector.stop()

        # Should have recorded at least 1 blocking event
        # (may be 1 or 2 depending on timing - just verify detection works)
        assert len(detector.blocking_events) >= 1
        assert all(lag > 15.0 for lag in detector.blocking_events)

    async def test_threshold_initialization(self) -> None:
        """Test threshold is properly initialized."""
        detector = BlockingDetector(threshold_ms=100.0)
        assert detector.threshold_ms == 100.0

    async def test_events_list_starts_empty(self) -> None:
        """Test blocking_events list starts empty."""
        detector = BlockingDetector()
        assert detector.blocking_events == []

    async def test_stop_without_start(self) -> None:
        """Test stop works even if never started."""
        detector = BlockingDetector()
        await detector.stop()  # Should not raise

    async def test_cancel_handles_cleanly(self) -> None:
        """Test detector handles cancellation gracefully."""
        detector = BlockingDetector()
        await detector.start()

        # Immediately stop (cancel the task)
        await detector.stop()

        # Should not raise and should be stopped
        assert detector._running is False

    async def test_stop_returns_promptly_under_frozen_clock(self) -> None:
        """stop() must not hang when time.monotonic is frozen (#83).

        asyncio.BaseEventLoop.time() resolves to time.monotonic() at call
        time, so freezing it also freezes the deadline of stop()'s own
        `asyncio.wait_for`. Bounded on real time here by counting
        call_soon-based turns (`asyncio.sleep(0)`) instead of a wall-clock
        or asyncio timeout: either of those would depend on the very clock
        this test freezes, and could hang this test itself.
        """
        detector = BlockingDetector(threshold_ms=50.0)
        await detector.start()

        real_monotonic = time.monotonic
        frozen = real_monotonic()
        time.monotonic = lambda: frozen
        stop_task = asyncio.create_task(detector.stop())
        try:
            for _ in range(200):
                await asyncio.sleep(0)
                if stop_task.done():
                    break
            completed = stop_task.done()
        finally:
            time.monotonic = real_monotonic
            if not stop_task.done():
                stop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_task

        assert completed, "detector.stop() did not return within 200 no-op turns"

    async def test_poll_records_the_in_flight_tick(self) -> None:
        """poll() measures a stall in progress instead of waiting for the
        monitor's own sleep to resume.

        Mirrors SentinelMonitor.poll() in monitor.py (invariant 9): a test
        that blocks and returns without ever awaiting again would otherwise
        leave the monitor's pending sleep expired and unrecorded.
        """
        detector = BlockingDetector(threshold_ms=10.0)
        await detector.start()
        await asyncio.sleep(0.02)  # let the monitor arm its first tick

        time.sleep(0.05)  # block for 50ms, then never await again

        detector.poll()

        await detector.stop()

        assert detector.blocking_events
        assert max(detector.blocking_events) > 10.0


class TestPytestPluginIntegration:
    """Integration tests for pytest plugin using pytester."""

    def test_marker_registered(self, pytester: pytest.Pytester) -> None:
        """Test that @pytest.mark.no_blocking marker is registered."""
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
        """)
        pytester.makepyfile("""
            import pytest

            @pytest.mark.no_blocking
            async def test_with_marker():
                pass
        """)

        # Should not warn about unknown marker
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)
        assert "PytestUnknownMarkWarning" not in result.stdout.str()

    def test_no_blocking_marker_fails_blocking_test(
        self, pytester: pytest.Pytester
    ) -> None:
        """Test that @pytest.mark.no_blocking fails blocking tests."""
        pytester.makepyfile("""
            import pytest
            import time
            import asyncio

            @pytest.mark.no_blocking
            async def test_blocks():
                # Give detector time to start
                await asyncio.sleep(0.02)
                # Block for 200ms - well above 10ms threshold
                time.sleep(0.2)
                # Give detector time to detect
                await asyncio.sleep(0.02)
        """)

        # Configure a very low threshold for reliable detection
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()

    def test_no_blocking_marker_fails_block_without_trailing_await(
        self, pytester: pytest.Pytester
    ) -> None:
        """A test that blocks and returns with no trailing await still fails.

        This is the common shape of blocking test code. The monitor's pending
        sleep expires during the block but never resumes, so a stop() that
        cancels instead of draining discards the sample and scores it clean.
        """
        pytester.makepyfile("""
            import pytest
            import time

            @pytest.mark.no_blocking
            async def test_blocks_then_returns():
                # No await anywhere: the monitor gets no turn of its own
                time.sleep(0.2)
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()

    def test_no_blocking_marker_passes_clean_test(
        self, pytester: pytest.Pytester
    ) -> None:
        """Test that @pytest.mark.no_blocking passes clean async tests."""
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking
            async def test_no_blocks():
                await asyncio.sleep(0.01)  # Async sleep - no blocking
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 50
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_unmarked_test_ignores_blocking(self, pytester: pytest.Pytester) -> None:
        """Test that unmarked tests ignore blocking (no failure)."""
        pytester.makepyfile("""
            import pytest
            import time

            async def test_blocks_but_unmarked():
                time.sleep(0.1)  # Would block but no marker
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 20
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_sync_test_with_marker_passes(self, pytester: pytest.Pytester) -> None:
        """Test sync tests with marker are not affected (only async works)."""
        pytester.makepyfile("""
            import pytest
            import time

            @pytest.mark.no_blocking
            def test_sync_with_marker():
                time.sleep(0.1)  # Sync test, marker ignored
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 20
        """)

        result = pytester.runpytest("-v")
        # Sync test passes because marker only wraps async functions
        result.assert_outcomes(passed=1)

    def test_custom_threshold_from_ini(self, pytester: pytest.Pytester) -> None:
        """Test custom threshold is read from pytest.ini."""
        pytester.makepyfile("""
            import pytest
            import time

            @pytest.mark.no_blocking
            async def test_short_block():
                time.sleep(0.03)  # 30ms - under 100ms threshold
        """)

        # High threshold - 30ms should not trigger
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 100
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_failure_message_format(self, pytester: pytest.Pytester) -> None:
        """Test failure message contains expected information."""
        pytester.makepyfile("""
            import pytest
            import time
            import asyncio

            @pytest.mark.no_blocking
            async def test_block_for_message():
                # Give detector time to start
                await asyncio.sleep(0.02)
                # Block for 200ms - well above threshold
                time.sleep(0.2)
                # Give detector time to detect
                await asyncio.sleep(0.02)
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)

        stdout = result.stdout.str()
        assert "blocking event(s)" in stdout
        assert "max lag:" in stdout
        assert "threshold:" in stdout

    def test_failure_does_not_print_the_plugin_source(
        self, pytester: pytest.Pytester
    ) -> None:
        """The verdict, not ~25 lines of the plugin's own wrapper.

        docs/AI-HARNESS.md tells agents to react to "Event loop blocking
        detected"; it has to be what the reader sees, not the last line
        under the wrapper's body.
        """
        pytester.makepyfile("""
            import pytest
            import time
            import asyncio

            @pytest.mark.no_blocking
            async def test_block_for_traceback():
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)

        stdout = result.stdout.str()
        assert "Event loop blocking detected!" in stdout
        plugin_lines = _wrapper_source_lines()
        assert plugin_lines  # the helper actually found the wrapper
        for line in plugin_lines:
            assert line not in stdout, line


class TestPluginHygiene:
    """Plugin behavior as an always-installed pytest11 entry point."""

    def test_no_deprecation_warnings_under_error_filter(
        self, pytester: pytest.Pytester
    ) -> None:
        """The plugin must survive a downstream -W error suite.

        asyncio.iscoroutinefunction is deprecated on 3.14 and scheduled for
        removal; the plugin auto-loads into every project that installs the
        package, so its hooks may not emit deprecation warnings.
        """
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
            filterwarnings =
                error::DeprecationWarning
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_sync_test_with_marker_warns(self, pytester: pytest.Pytester) -> None:
        """The marker on a sync test warns instead of silently no-opping."""
        pytester.makepyfile("""
            import pytest
            import time

            @pytest.mark.no_blocking
            def test_sync_blocking():
                time.sleep(0.05)
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=1)
        assert "has no effect on synchronous test" in result.stdout.str()

    def test_loopguard_detector_fixture_removed(
        self, pytester: pytest.Pytester
    ) -> None:
        """The never-started detector fixture is gone.

        It yielded a detector that was never started, so asserting on its
        (always empty) blocking_events passed unconditionally.
        """
        pytester.makepyfile("""
            def test_uses_fixture(loopguard_detector):
                pass
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(errors=1)
        assert "loopguard_detector" in result.stdout.str()

    def test_marked_test_that_raises_reports_original_error(
        self, pytester: pytest.Pytester
    ) -> None:
        """A failing marked test fails with its own error, detector stopped."""
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking
            async def test_raises():
                await asyncio.sleep(0.01)
                raise RuntimeError("the test itself is broken")
        """)

        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 50
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)
        assert "the test itself is broken" in result.stdout.str()
        assert "Event loop blocking detected" not in result.stdout.str()


class TestAllAsyncMode:
    """loopguard_all_async: the harness switch for unannotated test suites."""

    def _make_suite(self, pytester: pytest.Pytester) -> None:
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            async def test_blocks():
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)

            async def test_clean():
                await asyncio.sleep(0.01)

            @pytest.mark.allow_blocking
            async def test_opted_out():
                time.sleep(0.2)
        """)

    def test_ini_flags_unmarked_blocking_test(self, pytester: pytest.Pytester) -> None:
        self._make_suite(pytester)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
            loopguard_all_async = true
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1, passed=2)
        assert "Event loop blocking detected" in result.stdout.str()

    def test_cli_flag_equivalent(self, pytester: pytest.Pytester) -> None:
        self._make_suite(pytester)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v", "--loopguard-all-async")
        result.assert_outcomes(failed=1, passed=2)

    def test_off_by_default(self, pytester: pytest.Pytester) -> None:
        self._make_suite(pytester)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=3)

    def test_sync_tests_out_of_scope_without_warning(
        self, pytester: pytest.Pytester
    ) -> None:
        """All-async mode skips sync tests silently (no marker, no warning)."""
        pytester.makepyfile("""
            import time

            def test_sync_blocks():
                time.sleep(0.05)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
            loopguard_all_async = true
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=0)


class TestJsonReport:
    """--loopguard-report: the machine-readable verdict file."""

    def test_report_written_with_verdicts_and_hints(
        self, pytester: pytest.Pytester
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

        result = pytester.runpytest("-v", "--loopguard-report=loopguard.json")
        result.assert_outcomes(failed=1, passed=1)

        report_file = pytester.path / "loopguard.json"
        assert report_file.exists()
        report = json.loads(report_file.read_text())

        assert report["schema_version"] == 3
        assert report["status"] == "blocked"
        assert report["threshold_ms"] == 10.0
        assert report["totals"] == {"tests": 2, "flagged": 1}

        by_verdict = {r["verdict"]: r for r in report["tests"]}
        blocked = by_verdict["blocked"]
        assert "test_blocks" in blocked["nodeid"]
        assert blocked["events"][0]["lag_ms"] > 10.0
        assert blocked["hints"] == hint_lines()
        assert any("time.sleep" in hint for hint in blocked["hints"])

        clean = by_verdict["clean"]
        assert clean["events"] == []
        assert clean["hints"] == []

    def test_ini_report_path(self, pytester: pytest.Pytester) -> None:
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
            loopguard_report = from-ini.json
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)
        assert (pytester.path / "from-ini.json").exists()

    def test_no_report_without_option(self, pytester: pytest.Pytester) -> None:
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
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)
        assert not list(pytester.path.glob("*.json"))


class TestReportStatus:
    """The top-level pass/fail verdict a consuming agent reads."""

    _INI = """
        [pytest]
        asyncio_mode = auto
        loopguard_threshold_ms = 10
    """

    def _report(self, pytester: pytest.Pytester) -> dict[str, Any]:
        report_file = pytester.path / "loopguard.json"
        assert report_file.exists()
        parsed: dict[str, Any] = json.loads(report_file.read_text())
        return parsed

    def test_status_blocked_when_a_test_is_flagged(
        self, pytester: pytest.Pytester
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
        """)
        pytester.makeini(self._INI)

        result = pytester.runpytest("--loopguard-report=loopguard.json")
        result.assert_outcomes(failed=1)

        report = self._report(pytester)
        assert report["schema_version"] == REPORT_SCHEMA_VERSION
        assert report["status"] == "blocked"
        # Additive: the derived field existing consumers read still agrees
        assert report["totals"]["flagged"] == 1

    def test_status_clean_when_nothing_is_flagged(
        self, pytester: pytest.Pytester
    ) -> None:
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking
            async def test_clean():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini(self._INI)

        result = pytester.runpytest("--loopguard-report=loopguard.json")
        result.assert_outcomes(passed=1)

        report = self._report(pytester)
        assert report["status"] == "clean"
        assert report["totals"] == {"tests": 1, "flagged": 0}

    def test_status_clean_when_no_test_was_instrumented(
        self, pytester: pytest.Pytester
    ) -> None:
        """Zero instrumented tests is "clean" with totals.tests == 0.

        Nothing blocked because nothing was watched. The documented contract
        is that a gate which must also insist the suite was checked reads
        totals.tests > 0 alongside status.
        """
        pytester.makepyfile("""
            import time

            def test_sync_blocks():
                time.sleep(0.05)
        """)
        pytester.makeini(self._INI)

        result = pytester.runpytest("--loopguard-report=loopguard.json")
        result.assert_outcomes(passed=1)

        report = self._report(pytester)
        assert report["status"] == "clean"
        assert report["totals"] == {"tests": 0, "flagged": 0}
        assert report["tests"] == []


def _schema() -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text())
    return parsed


def _doc_example_report() -> dict[str, Any]:
    """The one report payload in docs/AI-HARNESS.md, parsed."""
    blocks = re.findall(r"```json\n(.*?)```", _DOC_PATH.read_text(), re.DOTALL)
    reports = [
        parsed
        for parsed in (json.loads(block) for block in blocks)
        if isinstance(parsed, dict) and "schema_version" in parsed
    ]
    assert len(reports) == 1, (
        f"expected exactly one report payload in {_DOC_PATH.name}, found {len(reports)}"
    )
    example: dict[str, Any] = reports[0]
    return example


class TestReportSchema:
    """docs/loopguard-report.schema.json is the contract; keep it honest."""

    def test_schema_is_a_valid_draft_2020_12_schema(self) -> None:
        schema = _schema()
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_schema_id_and_version_track_the_plugin(self) -> None:
        """The described version, the $id, and the plugin must agree."""
        schema = _schema()
        assert schema["properties"]["schema_version"]["const"] == REPORT_SCHEMA_VERSION
        assert schema["$id"].endswith(f"/v{REPORT_SCHEMA_VERSION}.json")

    def test_schema_validates_the_documented_example(self) -> None:
        """The doc payload and the schema cannot drift apart."""
        jsonschema.Draft202012Validator(_schema()).validate(_doc_example_report())

    def test_documented_example_matches_the_plugin_version(self) -> None:
        assert _doc_example_report()["schema_version"] == REPORT_SCHEMA_VERSION

    def test_schema_validates_a_freshly_generated_report(
        self, pytester: pytest.Pytester
    ) -> None:
        """A shape change in the plugin that the schema misses fails CI.

        Uses runpytest_subprocess with a timeout: the clock-tampering test
        below hangs pytest_plugin's unfixed BlockingDetector.stop(), and an
        in-process runpytest would wedge this repo's own suite on that
        regression instead of failing it (see TestClockTampering).
        """
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

            @pytest.mark.no_blocking
            async def test_tampers_with_the_clock(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest_subprocess(
            "--loopguard-report=loopguard.json", timeout=30
        )
        assert result.ret == 0

        report = json.loads((pytester.path / "loopguard.json").read_text())
        jsonschema.Draft202012Validator(_schema()).validate(report)
        # The generated report exercises all three verdicts
        assert {r["verdict"] for r in report["tests"]} == {
            "blocked",
            "clean",
            "unmeasured",
        }

    def test_schema_accepts_an_unmeasured_record(self) -> None:
        """schema_version 3 adds the unmeasured verdict; the schema must
        allow it, plus its optional `reason` and the new totals fields."""
        report = _doc_example_report()
        report["schema_version"] = 3
        report["totals"]["unmeasured"] = 1
        report["totals"]["measured"] = len(report["tests"])
        report["tests"].append(
            {
                "nodeid": "tests/test_x.py::test_tampered_clock",
                "verdict": "unmeasured",
                "events": [],
                "hints": [],
                "reason": "event loop clock did not advance during this test",
            }
        )

        jsonschema.Draft202012Validator(_schema()).validate(report)

    def test_schema_requires_the_top_level_status(self) -> None:
        """The schema has teeth: a pre-status report no longer validates."""
        report = _doc_example_report()
        del report["status"]

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(_schema()).validate(report)

    def test_schema_tolerates_unknown_keys(self) -> None:
        """The contract is additive, so validators must not reject new keys."""
        report = _doc_example_report()
        report["some_future_key"] = {"nested": True}
        report["tests"][0]["some_future_key"] = 1

        jsonschema.Draft202012Validator(_schema()).validate(report)


class TestDetectorArmedBeforeTestBody:
    """The sentinel must be armed before the test body runs."""

    def test_block_before_first_await_is_detected(
        self, pytester: pytest.Pytester
    ) -> None:
        """A test that blocks immediately (no prior yield) must still fail.

        An ASGI request dispatch can reach blocking code without ever
        returning to the scheduler; if start() does not yield, the monitor
        task never arms and the block is invisible.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            @pytest.mark.no_blocking
            async def test_blocks_immediately():
                time.sleep(0.2)  # no await before the block
                await asyncio.sleep(0.02)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)
        assert "Event loop blocking detected" in result.stdout.str()


class TestClockTampering:
    """#83: a test that replaces time.monotonic must not wedge the suite.

    asyncio.BaseEventLoop.time() is `return time.monotonic()`, resolved on
    the `time` module at call time. A test anywhere that does
    `monkeypatch.setattr(time, "monotonic", ...)` freezes every asyncio
    timer for as long as the patch is active, including the deadline of
    BlockingDetector.stop()'s own `asyncio.wait_for` — an await that
    cannot finish, bounded by a timeout that cannot fire either.

    Every test in this class that lets a frozen clock reach stop() uses
    `runpytest_subprocess` with an explicit `timeout`, never the in-process
    `runpytest` used elsewhere in this file: in-process, the unfixed defect
    hangs the *outer* suite forever instead of failing one test.
    """

    def test_frozen_clock_suite_does_not_hang(self, pytester: pytest.Pytester) -> None:
        """The single most important test in this file.

        A suite containing one test that freezes time.monotonic must run to
        completion. Against the unfixed source this test does not fail in
        the ordinary sense — it hangs, and `runpytest_subprocess(timeout=...)`
        is what turns that hang into a bounded, reportable failure
        (`Pytester.TimeoutExpired`) instead of wedging this repo's own CI.
        """
        pytester.makepyfile("""
            import time
            import pytest

            @pytest.mark.no_blocking
            async def test_tampers_with_the_clock(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
        """)

        result = pytester.runpytest_subprocess(timeout=60)
        assert result.ret == 0

    def test_frozen_clock_test_reports_unmeasured_with_reason_and_totals(
        self, pytester: pytest.Pytester
    ) -> None:
        """The tampered test is reported unmeasured, never silently clean."""
        pytester.makepyfile("""
            import time
            import pytest

            @pytest.mark.no_blocking
            async def test_tampers_with_the_clock(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
        """)

        result = pytester.runpytest_subprocess(
            "--loopguard-report=loopguard.json", timeout=30
        )
        assert result.ret == 0

        report = json.loads((pytester.path / "loopguard.json").read_text())
        assert report["status"] == "clean"
        assert report["totals"]["unmeasured"] == 1
        assert report["totals"]["measured"] == 0
        [record] = report["tests"]
        assert record["verdict"] == "unmeasured"
        assert record["reason"]

    def test_frozen_clock_under_all_async_passes_with_warning(
        self, pytester: pytest.Pytester
    ) -> None:
        """loopguard_all_async: an unmeasured test still just warns."""
        pytester.makepyfile("""
            import time

            async def test_tampers_with_the_clock(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_all_async = true
        """)

        result = pytester.runpytest_subprocess(timeout=30)
        result.assert_outcomes(passed=1, warnings=1)

    def test_frozen_clock_under_explicit_marker_passes_with_warning(
        self, pytester: pytest.Pytester
    ) -> None:
        """@pytest.mark.no_blocking: an unmeasured test is not a new failure.

        Deliberate product decision: the plugin cannot prove the test is
        clean, but it must not punish the test for that with a failure it
        would not otherwise have had.
        """
        pytester.makepyfile("""
            import time
            import pytest

            @pytest.mark.no_blocking
            async def test_tampers_with_the_clock(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
        """)

        result = pytester.runpytest_subprocess(timeout=30)
        result.assert_outcomes(passed=1, warnings=1)

    def test_clock_frozen_then_restored_is_still_unmeasured(
        self, pytester: pytest.Pytester
    ) -> None:
        """Drift, not identity, is what must catch this.

        The clock is back to normal by the time the plugin could inspect
        `time.monotonic`, so an identity check (`time.monotonic is
        original`) would wrongly call this trustworthy. 30ms of real time
        passes while the loop's clock cannot see it, which a drift check
        (real elapsed vs. the loop's own elapsed) catches regardless. The
        threshold is generous (200ms) so this stays unmeasured, not
        blocked — that distinction is TestClockTampering's other case.
        """
        pytester.makepyfile("""
            import time
            import asyncio
            import pytest

            @pytest.mark.no_blocking
            async def test_tampers_then_restores(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)
                time.sleep(0.03)  # real time the frozen loop clock can't see
                monkeypatch.undo()
                await asyncio.sleep(0.02)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 200
        """)

        result = pytester.runpytest_subprocess(
            "--loopguard-report=loopguard.json", timeout=30
        )
        assert result.ret == 0

        report = json.loads((pytester.path / "loopguard.json").read_text())
        [record] = report["tests"]
        assert record["verdict"] == "unmeasured"

    def test_frozen_clock_and_real_blocking_is_blocked_not_unmeasured(
        self, pytester: pytest.Pytester
    ) -> None:
        """Observed blocking beats a missing measurement (issue #83).

        The clock stays frozen for the rest of the test (never restored),
        so this only completes at all once the fix measures against a
        clock immune to the tampering — the same mechanism the first test
        in this class depends on. That real 200ms block must still win a
        "blocked" verdict over "unmeasured".
        """
        pytester.makepyfile("""
            import time
            import pytest

            @pytest.mark.no_blocking
            async def test_tampers_and_blocks(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)
                time.sleep(0.2)  # 200ms real block, clock stays frozen
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 50
        """)

        result = pytester.runpytest_subprocess(
            "--loopguard-report=loopguard.json", timeout=30
        )
        assert result.ret == 0

        report = json.loads((pytester.path / "loopguard.json").read_text())
        [record] = report["tests"]
        assert record["verdict"] == "blocked"

    def test_terminal_summary_names_the_unmeasured_count(
        self, pytester: pytest.Pytester
    ) -> None:
        """pytest_terminal_summary must name how many tests were unmeasured."""
        pytester.makepyfile("""
            import time
            import pytest

            @pytest.mark.no_blocking
            async def test_tampers_with_the_clock(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
        """)

        result = pytester.runpytest_subprocess(timeout=30)
        assert result.ret == 0
        assert "1 unmeasured" in result.stdout.str()
