"""Tests for fastapi_loopguard.pytest_plugin module."""

from __future__ import annotations

import ast
import asyncio
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

        assert report["schema_version"] == 2
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
        """A shape change in the plugin that the schema misses fails CI."""
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

        report = json.loads((pytester.path / "loopguard.json").read_text())
        jsonschema.Draft202012Validator(_schema()).validate(report)
        # The generated report exercises both verdicts and a real event
        assert {r["verdict"] for r in report["tests"]} == {"blocked", "clean"}

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


class TestPerTestThreshold:
    """Tests for issue #84: @pytest.mark.no_blocking(threshold_ms=N).

    None of this is implemented yet. `item.get_closest_marker(...)` results
    are only ever tested for `is not None` in pytest_plugin.py (lines 210,
    212) -- marker args and kwargs are never read. Every test below either
    demonstrates that gap (and must fail against the unfixed source) or, for
    the one marked explicitly, documents behavior that is already correct
    today.
    """

    def test_marker_raises_the_bar_above_the_ini_value(
        self, pytester: pytest.Pytester
    ) -> None:
        """A 500ms override should let a 200ms block pass under a 10ms ini.

        Today the marker's kwargs are never read, so the ini threshold (10ms)
        still governs and the block is flagged instead.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            @pytest.mark.no_blocking(threshold_ms=500)
            async def test_bounded_worst_case():
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
        result.assert_outcomes(passed=1)

    def test_marker_lowers_the_bar_below_the_ini_value(
        self, pytester: pytest.Pytester
    ) -> None:
        """A 10ms override should flag a 200ms block even under a 500ms ini.

        Today the marker's kwargs are never read, so the ini threshold
        (500ms) still governs and the block passes uncaught.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            @pytest.mark.no_blocking(threshold_ms=10)
            async def test_tight_override():
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 500
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)

    def test_override_raises_the_bar_under_loopguard_all_async(
        self, pytester: pytest.Pytester
    ) -> None:
        """The marker override still governs when loopguard_all_async is
        also on: the option does not stomp an explicit per-test threshold.

        The marker here is explicit, so `pytest_runtest_call` takes the
        `explicit = True` path regardless of all-async; all-async plays no
        part in whether this test is instrumented. It is enabled anyway to
        prove the override survives that configuration, not to exercise the
        all-async instrumentation path itself.

        Today the marker's kwargs are never read, so the ini threshold
        (10ms) still governs and the block is flagged instead of passing.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            @pytest.mark.no_blocking(threshold_ms=500)
            async def test_bounded_worst_case():
                await asyncio.sleep(0.02)
                time.sleep(0.2)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
            loopguard_all_async = true
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_failure_message_reports_the_effective_threshold(
        self, pytester: pytest.Pytester
    ) -> None:
        """The failure text must name 500 (the override), not 10 (the ini).

        The block (700ms) exceeds both thresholds, so the test fails either
        way; only the number printed in the message distinguishes the two
        code paths. Today it prints the ini value.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            @pytest.mark.no_blocking(threshold_ms=500)
            async def test_still_too_slow():
                await asyncio.sleep(0.02)
                time.sleep(0.7)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)
        out = result.stdout.str()
        assert "threshold: 500" in out
        assert "threshold: 10.0ms" not in out

    def test_zero_is_a_legal_override_not_a_bad_value(
        self, pytester: pytest.Pytester
    ) -> None:
        """threshold_ms=0 is documented as legal (the schema allows it) and
        must not be treated as falsy and silently discarded in favor of the
        ini value.

        Today the marker's kwargs are never read at all, so the generous
        500ms ini threshold governs and the 50ms block passes.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            @pytest.mark.no_blocking(threshold_ms=0)
            async def test_tiniest_block_flags():
                await asyncio.sleep(0.02)
                time.sleep(0.05)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 500
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)

    @pytest.mark.parametrize(
        "literal",
        ["'fast'", "-1", "float('nan')", "float('inf')", "True"],
        ids=["non-numeric", "negative", "nan", "inf", "bool"],
    )
    def test_bad_marker_value_must_fail_loudly_not_fall_back_to_ini(
        self, pytester: pytest.Pytester, literal: str
    ) -> None:
        """A bad threshold_ms must fail that test, never silently use the ini
        value instead.

        Today the marker's kwargs are never read, so a bad value is
        indistinguishable from no override: this clean test passes at the
        generous 500ms ini threshold when it should fail loudly regardless
        of whether the test body blocks.
        """
        pytester.makepyfile(f"""
            import pytest
            import asyncio

            @pytest.mark.no_blocking(threshold_ms={literal})
            async def test_clean_under_bad_marker():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 500
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)

    def test_positional_argument_is_rejected(self, pytester: pytest.Pytester) -> None:
        """`no_blocking(500)` (positional) must be rejected like any other
        bad value, not silently accepted or ignored.

        Today it is ignored: the clean test passes at the ini threshold.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking(500)
            async def test_clean_under_positional_arg():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 500
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)

    def test_unknown_keyword_is_rejected(self, pytester: pytest.Pytester) -> None:
        """`no_blocking(threshold=500)` (typo'd keyword) must be rejected,
        not silently ignored in favor of the ini value.

        Today it is ignored: the clean test passes at the ini threshold.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking(threshold=500)
            async def test_clean_under_unknown_kwarg():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 500
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)

    def test_allow_blocking_with_threshold_ms_warns(
        self, pytester: pytest.Pytester
    ) -> None:
        """`allow_blocking(threshold_ms=500)` means "not instrumented at
        all", so a keyword on it must warn the author to use
        `no_blocking(threshold_ms=...)` instead of believing they got a gate.

        Today no such warning exists.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.allow_blocking(threshold_ms=500)
            async def test_opted_out():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
            loopguard_all_async = true
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1, warnings=1)
        assert "no_blocking(threshold_ms=" in result.stdout.str()

    def test_bad_value_fails_only_that_test_not_the_whole_session(
        self, pytester: pytest.Pytester
    ) -> None:
        """A bad marker value must fail only its own test, not the whole
        session: a healthy test in the same file still runs and passes.

        Today the bad value is silently ignored on both tests, so both pass;
        the desired outcome is exactly one failure and one pass.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking(threshold_ms="fast")
            async def test_bad_marker():
                await asyncio.sleep(0.01)

            @pytest.mark.no_blocking
            async def test_healthy():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 500
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1, passed=1)

    def test_no_blocking_wins_over_allow_blocking_when_both_present(
        self, pytester: pytest.Pytester
    ) -> None:
        """Characterization test, not a gap: already true today and cannot
        be made to fail against the unfixed source.

        `pytest_runtest_call` treats a test as explicit whenever
        `no_blocking` is present, regardless of `allow_blocking` also being
        present, so a test carrying both markers is still instrumented.
        Issue #84 asks for this precedence to be written down, not changed.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            @pytest.mark.no_blocking
            @pytest.mark.allow_blocking
            async def test_both_markers():
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
        assert "Event loop blocking detected" in result.stdout.str()

    def test_report_records_the_effective_threshold_per_test_and_per_event(
        self, pytester: pytest.Pytester
    ) -> None:
        """A blocked test's report record must carry the 500ms override at
        both the per-test and per-event level; the top-level threshold_ms
        must stay the 10ms session default.

        Today testRecord carries no `threshold_ms` key at all, so
        `record["threshold_ms"]` raises KeyError.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio
            import time

            @pytest.mark.no_blocking(threshold_ms=500)
            async def test_bounded_worst_case():
                await asyncio.sleep(0.02)
                time.sleep(0.7)
                await asyncio.sleep(0.02)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v", "--loopguard-report=loopguard.json")
        result.assert_outcomes(failed=1)

        report = json.loads((pytester.path / "loopguard.json").read_text())
        assert report["threshold_ms"] == 10.0

        record = report["tests"][0]
        assert record["threshold_ms"] == 500
        assert record["events"][0]["threshold_ms"] == 500

    def test_report_shows_the_override_on_a_clean_test_via_per_test_threshold(
        self, pytester: pytest.Pytester
    ) -> None:
        """A clean test's `events` list is empty by definition, so
        `threshold_ms` on the testRecord is the only place evidence of a
        moved bar can live.

        Today testRecord carries no `threshold_ms` key at all, so
        `record["threshold_ms"]` raises KeyError.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking(threshold_ms=500)
            async def test_clean_under_override():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest("-v", "--loopguard-report=loopguard.json")
        result.assert_outcomes(passed=1)

        report = json.loads((pytester.path / "loopguard.json").read_text())
        record = report["tests"][0]
        assert record["verdict"] == "clean"
        assert record["events"] == []
        assert record["threshold_ms"] == 500
