"""Tests for fastapi_loopguard.pytest_plugin module."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
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
        stop_task: asyncio.Task[None] | None = None
        try:
            # Everything that touches the frozen clock, including the
            # assignment itself, lives inside this try: if anything here
            # raises, the finally below still restores the real
            # time.monotonic before the exception can reach the rest of
            # this repo's own suite.
            time.monotonic = lambda: frozen
            stop_task = asyncio.create_task(detector.stop())
            for _ in range(200):
                await asyncio.sleep(0)
                if stop_task.done():
                    break
            completed = stop_task.done()
        finally:
            time.monotonic = real_monotonic
            if stop_task is not None and not stop_task.done():
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

    async def test_stop_cancelled_at_its_own_await_does_not_leak_the_monitor(
        self,
    ) -> None:
        """A cancellation delivered while stop() is suspended must not be
        able to skip cancelling the monitor task.

        Reproduces a real defect: an earlier stop() opened with
        `await asyncio.sleep(0)` before ever calling `task.cancel()`. A
        cancellation delivered right there raised immediately and skipped
        every line after it -- the monitor task was never told to stop,
        orphaning it on the loop, and (in the real wrapped() path) the
        exception would propagate past stop() before the test's report
        record could be appended. The fix moves capturing the task,
        clearing `_task`, flipping `_running`, and cancelling all before
        any `await`, so cancelling stop() at its own (now only) await
        point must still find the monitor task already told to stop.
        """
        detector = BlockingDetector(threshold_ms=50.0)
        await detector.start()
        monitor_task = detector._task
        assert monitor_task is not None

        stop_task = asyncio.create_task(detector.stop())
        await asyncio.sleep(0)  # let stop() run up to its own first await
        assert not stop_task.done(), "stop() finished before it could be cancelled"

        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_task

        # Bounded, not a fixed sleep: give the already-cancelled monitor
        # task the turns it needs to actually finish unwinding.
        for _ in range(50):
            if monitor_task.done():
                break
            await asyncio.sleep(0)

        assert monitor_task.done(), "monitor task leaked: still pending"
        assert monitor_task.cancelled()
        assert detector._running is False

    async def test_stop_retrieves_the_monitor_exception_even_if_already_done(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """stop() must retrieve (and log) the monitor task's exception even
        when that task already finished by raising before stop() runs.

        The cancel-and-await block used to be guarded by
        `if task is not None and not task.done()`, so an already-finished,
        already-raised monitor task skipped the block entirely and its
        exception was never retrieved -- asyncio surfaces that later as an
        unattributed "Task exception was never retrieved" instead of the
        warning this module logs.
        """

        async def _boom(self: BlockingDetector) -> None:
            raise RuntimeError("monitor exploded")

        monkeypatch.setattr(BlockingDetector, "_monitor", _boom)

        detector = BlockingDetector(threshold_ms=50.0)
        await detector.start()

        # Let the patched monitor task run to completion -- it raises
        # immediately, with nothing to await.
        assert detector._task is not None
        for _ in range(50):
            if detector._task.done():
                break
            await asyncio.sleep(0)
        assert detector._task.done(), "monitor task never finished raising"

        with caplog.at_level(logging.WARNING, logger="fastapi_loopguard"):
            await detector.stop()

        assert any(
            "LoopGuard blocking detector failed" in record.message
            for record in caplog.records
        )

    async def test_clock_untrusted_and_blocking_events_can_both_be_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The state the precedence rule in `wrapped()` exists to handle --
        a genuine block *and* an untrusted clock, both true at once -- is
        directly reachable, closing a gap `TestClockTampering`'s end-to-end
        equivalent cannot: a verdict of "blocked" there cannot by itself
        prove `clock_untrusted` was also True, since blocking_events alone
        already decides that verdict.

        Every clock-tampering scenario elsewhere in this file patches
        `time.monotonic` from inside the running test, always after
        `start()`'s own fast-path identity check has already run with the
        clock still genuine -- and `_measure_tick` never reaches its own
        identity check on an over-threshold tick either, since it returns
        as soon as it appends to `blocking_events`. So for a tick that
        blocks past its threshold, `start()`'s fast path is the *only*
        place `clock_untrusted` can become True: tamper before `start()`
        runs, as this test does, or it never does. Deleting that fast
        path leaves every other test in this file green (verified: it
        does) but turns this assertion false.
        """
        real_monotonic = time.monotonic
        frozen = real_monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: frozen)

        detector = BlockingDetector(threshold_ms=10.0)
        await detector.start()  # the clock is already tampered when this runs

        time.sleep(0.05)  # genuine block, well past the 10ms threshold

        await detector.stop()

        assert detector.blocking_events, "the genuine block was not measured"
        assert detector.clock_untrusted, (
            "start()'s fast-path identity check did not see the already-tampered clock"
        )

    def test_drift_check_catches_a_custom_loop_clock(self) -> None:
        """The drift check (loop.time() vs. the pinned real clock) has no
        test of its own elsewhere: every clock-tampering scenario in this
        file patches `time.monotonic` itself, which the (cheaper) identity
        check in `_measure_tick` catches first -- the drift branch right
        below it never runs for any of them. Zeroing
        `_CLOCK_DRIFT_TOLERANCE_SEC` does not turn any of those red.

        This is deliberately the one case an identity check on
        `time.monotonic` cannot catch at all: a custom event loop whose own
        `time()` disagrees with the real clock without `time.monotonic`
        ever being touched (issue #83 names this alongside monkeypatch,
        freezegun, and a C-level patcher). I could not find a way to reach
        this branch other than actually constructing one -- a loop whose
        `time()` is wrong is the thing the branch exists to catch, so nothing
        short of one exercises it. `asyncio.new_event_loop()` returns a
        plain-Python `SelectorEventLoop` with no `__slots__`, so replacing
        the *instance's* `time` is enough; no subclass needed.

        `await asyncio.sleep(interval)` inside `_monitor()` schedules its
        wakeup via this same broken `time()` (through `call_later`), so it
        never fires -- the tick armed at `start()` is still the pending one
        when `stop()` runs. That does not matter here: `poll()` measures it
        synchronously against the pinned real clock regardless, exactly as
        it does under a frozen `time.monotonic`.
        """
        loop = asyncio.new_event_loop()
        frozen_loop_time = loop.time()
        loop.time = lambda: frozen_loop_time  # type: ignore[method-assign]

        async def scenario() -> BlockingDetector:
            detector = BlockingDetector(threshold_ms=50.0)
            await detector.start()
            # Real time the loop's own (frozen) clock cannot see -- large
            # enough to clear the 5ms drift tolerance, well under the 50ms
            # blocking threshold so this does not also trip that check.
            time.sleep(0.015)
            await detector.stop()
            return detector

        try:
            detector = loop.run_until_complete(scenario())
        finally:
            loop.close()

        assert not detector.blocking_events, "the block should stay under threshold"
        assert detector.clock_untrusted, "the loop-clock divergence was not caught"


class _FakeClock:
    """A monotonic clock a test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class TestScopedWindowInternals:
    """Unit cover for corners of the #85 window state.

    All of these are driven end to end in test_scoped_measurement.py too;
    these reach the states a pytester run does not naturally produce, or
    assert on a mechanism an end-to-end verdict cannot distinguish from
    its own absence.
    """

    def test_loop_time_is_none_off_the_event_loop(self) -> None:
        """The drift check's second clock is optional, not assumed.

        A context copy carrying the detector can travel into a worker
        thread (`asyncio.to_thread`), where a helper that scopes its own
        setup has no loop of its own to read -- and reading one must not
        raise into that helper.
        """
        assert pytest_plugin._loop_time() is None

    def test_nested_only_window_stays_open_until_the_outer_one_closes(self) -> None:
        """A depth counter, not a boolean, on the `loopguard_only()` side too.

        Driven directly rather than through pytester: only the outermost
        enter may clear, and only the outermost exit may suppress the rest
        of the test.
        """
        detector = BlockingDetector(threshold_ms=10.0)
        detector.blocking_events.append(99.0)

        detector.enter_only()
        assert detector.blocking_events == [], "the first enter did not clear"
        assert not detector.suppressed

        detector.blocking_events.append(42.0)
        detector.enter_only()
        assert detector.blocking_events == [42.0], "a nested enter cleared again"

        detector.exit_only()
        assert not detector.suppressed, "the inner exit closed the outer window"

        detector.exit_only()
        assert detector.suppressed, "the outer exit did not suppress the rest"

    def test_loop_clock_watermark_keeps_the_drift_check_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_resume_measurement()` must move the loop clock's baseline too.

        `_measure_tick`'s drift check is guarded by
        `if loop_start is not None`, so a watermark that moves only the
        real clock does not misfire -- it silently stops checking, for
        every measurement after the first window in the test. Both halves
        below then read `clean`, and the whole suite stays green.

        So the proof that the check still runs has to be a divergence it
        still catches (second half). The first half is the other half of
        the same claim: under clocks that agree, a window boundary is not
        itself read as divergence -- which is what a watermark that moved
        only one clock, or neither, would do.
        """
        real = _FakeClock()
        monkeypatch.setattr(pytest_plugin, "_REAL_MONOTONIC", real)
        # The identity check sits above the drift check and returns as
        # soon as it sees a replaced time.monotonic, so the fake has to be
        # the real clock too or the drift branch is unreachable.
        monkeypatch.setattr(time, "monotonic", real)

        loop_clock = _FakeClock()
        monkeypatch.setattr(pytest_plugin, "_loop_time", loop_clock)

        def measure_after_a_window(*, loop_reads_at_the_end: float) -> BlockingDetector:
            """One tick: a 200ms pause window, then 50ms measured after it."""
            detector = BlockingDetector(threshold_ms=1000.0)
            detector._running = True
            detector._tick_real_start = 0.0
            detector._tick_loop_start = 0.0
            # As the enter-poll would have left it; with the tick already
            # consumed that poll is a no-op, so this needs no monitor task.
            detector._tick_consumed = True

            real.now = loop_clock.now = 0.2
            detector.enter_pause()
            real.now = loop_clock.now = 0.4
            detector.exit_pause()

            real.now = 0.45
            loop_clock.now = loop_reads_at_the_end
            detector._measure_tick()
            return detector

        agreeing = measure_after_a_window(loop_reads_at_the_end=0.45)
        # 50ms of lag against a 1000ms threshold: under the bar, so the
        # measurement reaches the clock checks instead of returning at the
        # blocking branch above them.
        assert agreeing.blocking_events == []
        assert not agreeing.clock_untrusted, (
            "the window itself was read as loop-clock divergence"
        )

        # The loop's own clock stops advancing after the window closes:
        # 50ms of real time it cannot see, ten times the drift tolerance.
        diverging = measure_after_a_window(loop_reads_at_the_end=0.4)
        assert diverging.clock_untrusted, (
            "the drift check stopped running after the window closed"
        )

    async def test_leaving_a_pause_re_arms_the_consumed_tick(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_resume_measurement()` must re-arm `_tick_consumed` (#85).

        Entering the window polls, and that poll consumes the in-flight
        tick. If leaving does not re-arm it, `stop()`'s final poll refuses
        to measure that same tick -- and a test that blocks after the
        window and then returns without ever awaiting (an
        `httpx.ASGITransport` request does exactly that) has nothing else
        that would ever measure it. The stall is simply not seen.

        That is invisible to an end-to-end verdict: "nothing was measured"
        and "a clean measurement" are both a passing test with no
        warnings, which is why this is asserted here on the mechanism
        rather than through pytester.

        Driven on a hand-moved clock for the same reason
        `TestWatermarkArithmetic` is: the numbers are exact and wall-clock
        timing cannot pin them. Patching `_REAL_MONOTONIC` alone leaves
        `_measure_tick`'s identity check seeing a replaced clock and
        marking this detector untrusted -- irrelevant here, since the only
        assertion is about what got measured.
        """
        clock = _FakeClock()
        monkeypatch.setattr(pytest_plugin, "_REAL_MONOTONIC", clock)

        detector = BlockingDetector(threshold_ms=10.0)
        detector._running = True
        # poll() refuses to measure a tick no live task owns, so the
        # detector needs one. Nothing ever runs in it.
        detector._task = asyncio.create_task(asyncio.sleep(3600))
        try:
            detector._tick_real_start = 0.0
            detector._tick_loop_start = None
            detector._tick_consumed = False

            clock.now = 0.001  # 1ms into a 5ms tick: nothing to charge yet
            detector.enter_pause()
            assert detector._tick_consumed, "the enter-poll did not consume the tick"
            assert detector.blocking_events == []

            clock.now = 0.201  # 200ms inside the window, deliberately unmeasured
            detector.exit_pause()

            clock.now = 0.401  # 200ms after it, with no await in between
            detector.poll()

            assert detector.blocking_events == [pytest.approx(200.0)], (
                "the tick straddling the window exit was never re-armed, so the "
                "200ms stall after the window went unmeasured"
            )
        finally:
            detector._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await detector._task


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
        sleep expires during the block but never resumes on its own, so
        stop() measures the in-flight tick itself (poll(), mirroring
        SentinelMonitor.poll()) before cancelling the task -- a stop() that
        cancelled first, with no measurement, would discard the sample and
        score this test clean.
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

    def test_terminal_summary_silent_for_a_suite_that_never_opts_in(
        self, pytester: pytest.Pytester
    ) -> None:
        """pytest_terminal_summary must print nothing for an un-instrumented
        suite.

        The hook runs in every project that installs this package (it is a
        pytest11 entry point), not only ones that use
        @pytest.mark.no_blocking or loopguard_all_async. Nothing previously
        pinned that a suite which never opts into either stays silent.
        """
        pytester.makepyfile("""
            def test_plain():
                assert 1 == 1
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)
        stdout = result.stdout.str()
        assert "unmeasured" not in stdout
        assert not any(line.startswith("loopguard:") for line in stdout.splitlines())

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

        The inner suite is expected to have exactly one failing test:
        test_blocks genuinely blocks past its threshold, and a "blocked"
        verdict fails by design (that is the entire point of
        @pytest.mark.no_blocking). Asserting the inner run's outcomes
        directly, rather than decoding a bare exit code, keeps that
        expectation visible to the next reader.
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
        # test_blocks fails (blocked verdict, by design); test_clean and the
        # clock-tampering test both pass, the latter with one warning.
        result.assert_outcomes(failed=1, passed=2, warnings=1)

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

    def test_block_behind_a_freeze_then_restore_is_still_caught(
        self, pytester: pytest.Pytester
    ) -> None:
        """A block that happens behind a freeze-and-restore is still
        caught at all -- not lost along with the (undetectable) tamper.

        This class used to assert this scenario was "unmeasured", on the
        theory that a real-vs-loop drift check could catch a freeze even
        after it was undone. It cannot: while the clock is frozen the loop
        never runs, so nothing here executes to observe it, and once
        restored every start-to-stop comparison reads the same source
        again -- "tampered, then fully restored" and "slow but healthy"
        produce identical measurements, by construction (see CLAUDE.md's
        invariant 9 and FINDINGS.md). Chasing that distinction anyway is
        what produced real false positives on this project's own
        bounded-worst-case test pattern, documented elsewhere in this file.

        This test does *not* exercise the pinned clock's own value, despite
        its former name claiming otherwise: by the time `poll()` measures,
        `monkeypatch.undo()` has already restored `time.monotonic`, so the
        real clock and the loop's clock agree again -- measuring against
        `loop.time()` instead of the pinned `_REAL_MONOTONIC` passes this
        test exactly the same way (verified: swapping the two in
        `_measure_tick` does not fail it). What it actually protects is
        narrower and still worth having: a block is not silently dropped
        just because it happened while the clock was tampered with, even
        after the tamper itself becomes unprovable. The sibling case where
        the pinned clock is load-bearing -- the clock is *still* frozen when
        `poll()` runs -- is
        `test_frozen_clock_and_real_blocking_is_blocked_not_unmeasured`
        above; swapping the two clocks there does fail it. The block and
        threshold are both generous (200ms over 10ms) because this asserts
        detection, not absence of it.
        """
        pytester.makepyfile("""
            import time
            import pytest

            @pytest.mark.no_blocking
            async def test_tampers_then_restores_but_still_blocks(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)
                time.sleep(0.2)  # real block behind the freeze
                monkeypatch.undo()
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest_subprocess(
            "--loopguard-report=loopguard.json", timeout=30
        )
        # The block clears the threshold by a wide margin, so it fails --
        # a "blocked" verdict fails by design, same as any other blocked
        # test in this file.
        result.assert_outcomes(failed=1)

        report = json.loads((pytester.path / "loopguard.json").read_text())
        [record] = report["tests"]
        assert record["verdict"] == "blocked"

    def test_frozen_clock_and_real_blocking_is_blocked_not_unmeasured(
        self, pytester: pytest.Pytester
    ) -> None:
        """Observed blocking beats a missing measurement (issue #83).

        The clock stays frozen for the rest of the test (never restored),
        so this only completes at all once the fix measures against a
        clock immune to the tampering — the same mechanism the first test
        in this class depends on. That real 200ms block must still win a
        "blocked" verdict over "unmeasured".

        The inner test is expected to fail: a "blocked" verdict fails by
        design (@pytest.mark.no_blocking's whole point), and a tampered
        clock must not become a way to dodge that gate.
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
        # The single inner test genuinely blocks past its threshold, so it
        # fails -- that is not a regression, it is the blocking gate doing
        # its job even under a tampered clock.
        result.assert_outcomes(failed=1)

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

    def test_clock_already_tampered_when_start_runs_still_reports_blocked(
        self, pytester: pytest.Pytester
    ) -> None:
        """The precedence rule -- positive evidence beats an untrusted
        clock -- must hold even when the clock was untrusted from the
        very first measurement `start()` ever takes.

        Every other test in this class patches `time.monotonic` *inside*
        the test body, which only ever runs after `detector.start()` has
        already returned -- so none of them reach `start()`'s own cheap
        identity check (`if time.monotonic is not _REAL_MONOTONIC` at the
        top of `start()`) with the patch already live. A fixture used by
        the test patches it during setup, before `wrapped()` ever calls
        `start()`, so this is the one test where `clock_untrusted` is
        already `True` before a single tick has been measured. A genuine
        block past the threshold must still win `"blocked"`: a sample that
        never ran is not evidence of absence, but an observed stall is
        evidence of presence, regardless of how little the clock can be
        trusted otherwise.

        Deleting the identity check from `start()` entirely, or inverting
        the precedence in `wrapped()` so an untrusted clock beats an
        observed block, both leave every other test in this file green --
        this is the one that goes red for either mutation.
        """
        pytester.makepyfile("""
            import time
            import pytest

            @pytest.fixture
            def clock_already_tampered(monkeypatch):
                frozen = time.monotonic()
                monkeypatch.setattr(time, "monotonic", lambda: frozen)

            @pytest.mark.no_blocking
            async def test_tampered_before_start_but_blocks(clock_already_tampered):
                time.sleep(0.2)  # genuine block, clock already tampered
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 10
        """)

        result = pytester.runpytest_subprocess(
            "--loopguard-report=loopguard.json", timeout=30
        )
        # A blocked verdict fails by design, same as any other blocked test.
        result.assert_outcomes(failed=1)

        report = json.loads((pytester.path / "loopguard.json").read_text())
        [record] = report["tests"]
        assert record["verdict"] == "blocked"


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
        ("literal", "expected_repr"),
        [
            ("'fast'", repr("fast")),
            ("-1", repr(-1)),
            ("float('nan')", repr(float("nan"))),
            ("float('inf')", repr(float("inf"))),
            ("True", repr(True)),
        ],
        ids=["non-numeric", "negative", "nan", "inf", "bool"],
    )
    def test_bad_marker_value_must_fail_loudly_not_fall_back_to_ini(
        self, pytester: pytest.Pytester, literal: str, expected_repr: str
    ) -> None:
        """A bad threshold_ms must fail that test, never silently use the ini
        value instead.

        Today the marker's kwargs are never read, so a bad value is
        indistinguishable from no override: this clean test passes at the
        generous 500ms ini threshold when it should fail loudly regardless
        of whether the test body blocks.

        Asserting failed=1 alone is not enough for the `bool` case: with the
        isinstance(value, bool) guard removed, float(True) == 1.0, and a
        1.0ms threshold is thin enough that ordinary scheduler jitter often
        gets flagged as blocking too -- the outcome alone cannot tell a real
        rejection from a coincidental blocking detection. Asserting on the
        rejection message (the marker name and the rejected value's repr)
        pins the actual validation path for every case here.
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

        out = result.stdout.str()
        assert "no_blocking(threshold_ms=" in out
        assert f"got {expected_repr}" in out

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

    def test_bad_value_never_starts_the_monitor(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Validation must run before `detector.start()`.

        Issue #84 requires validating the marker at the top of `wrapped`,
        before the detector starts, precisely so a rejected value fails
        without ever creating a background monitor task. If validation were
        moved to after `await detector.start()` instead, `pytest.fail`
        would raise before the `try/finally` that calls `detector.stop()`,
        leaking that task -- exactly what CLAUDE.md's lifecycle invariant
        (idempotent, race-free start/stop) exists to prevent.

        `result.assert_outcomes(failed=1)` alone cannot tell these two
        orderings apart: the test fails either way. This instruments the
        actual `BlockingDetector.start` the plugin calls (patched on the
        class object the already-imported `pytest_plugin` module holds, so
        the patch also covers the in-process pytester run below) and
        asserts it was never invoked for a test whose marker value was
        rejected.

        Verified to fail (red) when `wrapped`'s validation call is moved to
        after `await detector.start()`.
        """
        starts: list[None] = []
        original_start = pytest_plugin.BlockingDetector.start

        async def counting_start(self: pytest_plugin.BlockingDetector) -> None:
            starts.append(None)
            await original_start(self)

        monkeypatch.setattr(pytest_plugin.BlockingDetector, "start", counting_start)

        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking(threshold_ms="fast")
            async def test_bad_marker():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
            loopguard_threshold_ms = 500
        """)

        result = pytester.runpytest("-v")
        result.assert_outcomes(failed=1)

        assert starts == [], (
            "BlockingDetector.start() was called for a test whose marker "
            "value was rejected -- validation must happen before "
            "detector.start() so no monitor task is ever created for it"
        )

    def test_bad_marker_value_still_produces_an_unmeasured_report_record(
        self, pytester: pytest.Pytester
    ) -> None:
        """#83 (comment): a test that fails marker validation must not
        vanish from the report.

        pytest.fail() in _effective_threshold_ms raises before the test's
        own try/finally ever appends a record, so before this fix the test
        disappeared from loopguard.json entirely: totals.tests undercounted
        and the top-level verdict could read "clean" while a test loudly
        failed. It must now get an unmeasured record naming the marker
        problem, and still fail in pytest exactly as before.
        """
        pytester.makepyfile("""
            import pytest
            import asyncio

            @pytest.mark.no_blocking(threshold_ms="oops")
            async def test_bad_marker():
                await asyncio.sleep(0.01)
        """)
        pytester.makeini("""
            [pytest]
            asyncio_mode = auto
        """)

        result = pytester.runpytest("-v", "--loopguard-report=loopguard.json")
        result.assert_outcomes(failed=1)

        report = json.loads((pytester.path / "loopguard.json").read_text())
        assert report["totals"]["tests"] == 1
        assert report["totals"]["unmeasured"] == 1
        assert report["totals"]["measured"] == 0
        [record] = report["tests"]
        assert record["verdict"] == "unmeasured"
        assert "threshold_ms" in record["reason"]

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
