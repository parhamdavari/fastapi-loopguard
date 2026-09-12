"""Pytest plugin for detecting event loop blocking in tests.

Usage:
    # pytest.ini
    [pytest]
    loopguard_threshold_ms = 50

    # In test files
    import pytest

    @pytest.mark.no_blocking
    async def test_my_endpoint():
        # If this test blocks the event loop, it will fail
        ...

Harness mode (for CI gates over AI-generated or unfamiliar code):
    # pytest.ini
    [pytest]
    loopguard_all_async = true          # every async test is checked
    loopguard_report = loopguard.json   # machine-readable results

    Opt a test out with @pytest.mark.allow_blocking. Both options also
    exist as CLI flags: --loopguard-all-async, --loopguard-report=PATH.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, NoReturn

import pytest

from .hints import hint_lines

logger = logging.getLogger("fastapi_loopguard")

# asyncio.BaseEventLoop.time() is `return time.monotonic()`, resolved on the
# `time` module at call time (#83): a test that does
# `monkeypatch.setattr(time, "monotonic", ...)` freezes every asyncio timer
# for as long as the patch holds, including a `wait_for` deadline. Every
# measurement BlockingDetector makes uses this pinned reference instead of
# `loop.time()`, so it keeps working (and stop() keeps returning promptly)
# no matter what a test under it does to the `time` module.
_REAL_MONOTONIC = time.monotonic

# The monitor's own sampling interval.
_MONITOR_INTERVAL_SEC = 0.005

# How far a pending tick's real-clock elapsed time may diverge from what
# the loop's own clock reports for the same tick before that clock is no
# longer trusted -- e.g. a custom loop clock, or time.monotonic still
# replaced when this is checked. One monitor interval (#83). Deliberately
# not applied to a tick's lag on its own: see _measure_tick's docstring for
# why that produced false positives on a legitimate long block, and why a
# freeze fully undone before this runs cannot be caught by any timing-only
# check regardless of the tolerance chosen (CLAUDE.md invariant 9,
# FINDINGS.md).
_CLOCK_DRIFT_TOLERANCE_SEC = _MONITOR_INTERVAL_SEC

_CLOCK_UNTRUSTED_REASON = (
    "the event loop clock could not be trusted during this test (it may "
    "still be replaced or frozen, or the loop's own clock diverged from "
    "the real one) -- any blocking may have gone unmeasured"
)

# Version of the JSON report contract. Bump on any shape change; the
# schema that describes it is docs/loopguard-report.schema.json. Changes
# must stay additive — consumers reading older keys keep working.
REPORT_SCHEMA_VERSION = 3

# Marker for tests that should fail on blocking
MARKER_NAME = "no_blocking"
# Opt-out marker for loopguard_all_async mode
ALLOW_MARKER_NAME = "allow_blocking"

# Per-session records for the machine-readable report
_REPORT_KEY: pytest.StashKey[list[dict[str, Any]]] = pytest.StashKey()


def pytest_configure(config: pytest.Config) -> None:
    """Register the markers."""
    config.addinivalue_line(
        "markers",
        f"{MARKER_NAME}: fail test if event loop blocking is detected",
    )
    config.addinivalue_line(
        "markers",
        f"{ALLOW_MARKER_NAME}: exempt this test from loopguard_all_async mode",
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add loopguard options to pytest."""
    parser.addini(
        "loopguard_threshold_ms",
        # pytest ini values have no float type, so this is registered as a
        # string and converted in _threshold_ms; the help text has to say so.
        "Blocking detection threshold in milliseconds, parsed as a float "
        "(pytest ini has no float type); a value float() cannot parse fails "
        "every instrumented test",
        type="string",
        default="50",
    )
    parser.addini(
        "loopguard_all_async",
        "Treat every async test as @pytest.mark.no_blocking",
        type="bool",
        default=False,
    )
    parser.addini(
        "loopguard_report",
        "Path to write a JSON report of blocking verdicts",
        type="string",
        default="",
    )
    group = parser.getgroup("loopguard")
    group.addoption(
        "--loopguard-all-async",
        action="store_true",
        default=False,
        dest="loopguard_all_async",
        help="Treat every async test as @pytest.mark.no_blocking",
    )
    group.addoption(
        "--loopguard-report",
        action="store",
        default="",
        dest="loopguard_report",
        help="Path to write a JSON report of blocking verdicts",
    )


class BlockingDetector:
    """Detects event loop blocking during test execution.

    Every measurement uses `_REAL_MONOTONIC`, never `loop.time()`: the
    suite under test can replace `time.monotonic`, which is also what
    `loop.time()` resolves to, so a detector built on that clock cannot be
    trusted to notice the replacement (#83). When the clock cannot be
    trusted, `clock_untrusted` is set and the test is reported `unmeasured`
    rather than `clean` -- positive evidence of blocking still wins, since
    that stands on its own regardless of the clock.
    """

    def __init__(self, threshold_ms: float = 50.0) -> None:
        self.threshold_ms = threshold_ms
        self.blocking_events: list[float] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None
        # Set at the top of every tick in _monitor(); None until the loop
        # runs or after a tick has been measured, which is what makes
        # poll() a no-op outside an in-flight tick.
        self._tick_real_start: float | None = None
        self._tick_loop_start: float | None = None
        self._tick_consumed = False
        self._clock_untrusted = False

    @property
    def clock_untrusted(self) -> bool:
        """Whether this test's event loop clock could not be trusted.

        True once a measurement observed `time.monotonic` still replaced,
        or the loop's own clock diverging from the real one by more than
        one monitor interval while a tick was pending. Deliberately not
        based on a tick's lag alone: a freeze fully undone before this
        detector next runs is indistinguishable from a slow but healthy
        tick (see CLAUDE.md and FINDINGS.md) -- and `poll()` measures every
        tick against the pinned real clock regardless, so a block behind
        such a freeze is still caught as lag, not lost.
        """
        return self._clock_untrusted

    async def start(self) -> None:
        """Start the blocking detector.

        Yields once so the monitor task reaches its first sleep before the
        caller continues: without this, a test that blocks before its first
        real await (an ASGI request dispatch does exactly that) blocks an
        unarmed sentinel and is never measured.
        """
        if self._running:
            return
        self._running = True
        # Cheap fast path: the clock was already replaced before this
        # test's own monitoring even began. Tampering that starts or ends
        # mid-test is caught in poll()/stop() instead -- this check cannot
        # see anything that happens after it runs.
        if time.monotonic is not _REAL_MONOTONIC:
            self._clock_untrusted = True
        self._task = asyncio.create_task(self._monitor())
        await asyncio.sleep(0)

    def poll(self) -> None:
        """Measure the current tick now instead of waiting for it to finish.

        Mirrors SentinelMonitor.poll() in monitor.py (invariant 9): a test
        that blocks and returns without ever awaiting again would otherwise
        leave the monitor's pending sleep expired and unrecorded. Measured
        with the pinned real clock, so it keeps working when a test has
        replaced time.monotonic (#83).
        """
        if not self._running or self._tick_real_start is None or self._tick_consumed:
            return
        # A cancelled or finished monitor leaves _tick_real_start pointing
        # at a tick that will never complete; measuring against it invents
        # a stall that grows with wall-clock time.
        if self._task is None or self._task.done():
            self._tick_real_start = None
            return
        self._measure_tick()

    def _measure_tick(self) -> None:
        """Measure the in-flight tick and record it exactly once.

        Blocking (lag over threshold) wins outright, since it is positive
        evidence that stands on its own -- measured against the pinned real
        clock, so it stands regardless of what `time.monotonic` says or
        said. Short of that, an untrustworthy clock -- still replaced, or
        diverged from the real one while this tick was pending -- marks the
        test `unmeasured` rather than `clean`: the sentinel cannot prove
        nothing blocked when it cannot prove it was watching reliably.

        Deliberately does not treat a tick's own lag, on its own, as
        evidence of an untrustworthy clock: a freeze that is fully undone
        before this method runs looks identical, in every measurement
        available afterwards, to a slow but healthy tick -- see CLAUDE.md's
        invariant 9 and FINDINGS.md. Trying to catch that case anyway
        produced real false positives on a long, deliberate block under a
        raised per-test `@pytest.mark.no_blocking(threshold_ms=...)` --
        exactly the legitimate, documented use this detector must not
        punish.
        """
        assert self._tick_real_start is not None
        self._tick_consumed = True

        interval = _MONITOR_INTERVAL_SEC
        real_elapsed = _REAL_MONOTONIC() - self._tick_real_start
        lag_ms = (real_elapsed - interval) * 1000

        if lag_ms > self.threshold_ms:
            self.blocking_events.append(lag_ms)
            return

        if time.monotonic is not _REAL_MONOTONIC:
            self._clock_untrusted = True
            return

        if self._tick_loop_start is not None:
            loop_elapsed = asyncio.get_running_loop().time() - self._tick_loop_start
            if abs(real_elapsed - loop_elapsed) > _CLOCK_DRIFT_TOLERANCE_SEC:
                self._clock_untrusted = True

    async def stop(self) -> None:
        """Stop the blocking detector.

        Runs inside test finally blocks, so it must not swallow a
        cancellation aimed at the test itself (e.g. a timeout plugin).

        Measures the in-flight tick, then cancels the monitor task instead
        of draining it (#83): the drain's own `asyncio.wait_for` deadline is
        scheduled on the same loop clock a tampered test can freeze, so it
        can wait forever behind a timeout that can never fire either.
        Cancelling a task suspended in `asyncio.sleep` resolves through
        `call_soon`, not the timer heap, so it completes even when
        `time.monotonic` is frozen.
        """
        if not self._running:
            return

        # A call_soon hop, never a timer -- safe to await even when every
        # asyncio timer is frozen (#83).
        await asyncio.sleep(0)

        # Measure the in-flight tick before flipping _running: poll() (like
        # SentinelMonitor.poll()) refuses to measure once the monitor is no
        # longer running, since a stopped monitor's tick marker belongs to a
        # tick that will never complete.
        self.poll()
        self._running = False

        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            except Exception:
                # This runs in the finally of every instrumented test. An
                # exception from the monitor must not replace the test's own
                # failure with a confusing one.
                logger.warning("LoopGuard blocking detector failed", exc_info=True)

    async def _monitor(self) -> None:
        """Monitor for blocking."""
        loop = asyncio.get_running_loop()
        interval = _MONITOR_INTERVAL_SEC

        while self._running:
            self._tick_real_start = _REAL_MONOTONIC()
            self._tick_loop_start = loop.time()
            self._tick_consumed = False
            await asyncio.sleep(interval)
            if not self._tick_consumed:
                self._measure_tick()
        self._tick_real_start = None


def _threshold_ms(config: pytest.Config) -> float:
    threshold_str = config.getini("loopguard_threshold_ms")
    return float(threshold_str) if threshold_str else 50.0


def _fail_bad_threshold(value: object) -> NoReturn:
    pytest.fail(
        f"@pytest.mark.{MARKER_NAME}(threshold_ms=...) must be a "
        f"non-negative, finite number; got {value!r}",
        pytrace=False,
    )


def _validate_threshold_ms(value: object) -> float:
    """Parse and validate a threshold_ms override, failing the test on
    anything else.

    bool is checked before the numeric check because isinstance(True, int)
    is True in Python. Numeric strings go through float(), matching how
    the ini value is parsed.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        _fail_bad_threshold(value)

    try:
        parsed = float(value)
    except ValueError:
        _fail_bad_threshold(value)

    if math.isnan(parsed) or math.isinf(parsed) or parsed < 0:
        _fail_bad_threshold(value)

    return parsed


def _effective_threshold_ms(item: pytest.Function, marker: pytest.Mark | None) -> float:
    """The threshold to use for this test.

    A bare `@pytest.mark.no_blocking` (marker with no threshold_ms kwarg)
    keeps the session default (the ini value). A `threshold_ms=...` kwarg
    overrides it, in either direction. Anything else on the marker -- a
    positional argument, an unknown keyword, or a bad threshold_ms value --
    fails this one test via pytest.fail(pytrace=False) rather than silently
    falling back to the ini default, which would hide a typo behind a
    threshold the test's author does not believe is in effect.
    """
    default = _threshold_ms(item.config)
    if marker is None:
        return default

    if marker.args:
        pytest.fail(
            f"@pytest.mark.{MARKER_NAME}(...) does not take positional "
            f"arguments; got {marker.args!r}. Use threshold_ms=<value> "
            f"instead.",
            pytrace=False,
        )

    unknown = set(marker.kwargs) - {"threshold_ms"}
    if unknown:
        pytest.fail(
            f"@pytest.mark.{MARKER_NAME}(...) received unknown keyword "
            f"argument(s) {sorted(unknown)!r}; only threshold_ms is "
            f"supported.",
            pytrace=False,
        )

    if "threshold_ms" not in marker.kwargs:
        return default

    return _validate_threshold_ms(marker.kwargs["threshold_ms"])


def _all_async_enabled(config: pytest.Config) -> bool:
    return bool(
        config.getoption("loopguard_all_async") or config.getini("loopguard_all_async")
    )


def _report_path(config: pytest.Config) -> str:
    return str(
        config.getoption("loopguard_report") or config.getini("loopguard_report")
    )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item: pytest.Item) -> None:
    """Instrument marked (or, in all-async mode, every async) test."""
    # Only works with Function items (which have obj attribute)
    if not isinstance(item, pytest.Function):
        return

    explicit = item.get_closest_marker(MARKER_NAME) is not None
    allow_marker = item.get_closest_marker(ALLOW_MARKER_NAME)
    if allow_marker is not None and (allow_marker.args or allow_marker.kwargs):
        # allow_blocking means "not instrumented at all" -- there is no
        # measurement for an argument on it to set a bar for. Emitted
        # before the early return below, so it fires even when that
        # return is the only thing that happens to this test.
        item.warn(
            pytest.PytestWarning(
                f"@pytest.mark.{ALLOW_MARKER_NAME} takes no arguments; it "
                f"exempts a test from instrumentation entirely, so there is "
                f"no measurement to set a threshold for. Use "
                f"@pytest.mark.{MARKER_NAME}(threshold_ms=...) to raise the "
                f"bar instead of removing the check."
            )
        )
    if not explicit:
        if allow_marker is not None:
            return
        if not _all_async_enabled(item.config):
            return

    # Store the original test function
    original_func = item.obj

    if not inspect.iscoroutinefunction(original_func):
        # A sync test never runs on the event loop. In all-async mode it is
        # silently out of scope; with an explicit marker, silently passing
        # would let the author believe blocking was checked
        if explicit:
            item.warn(
                pytest.PytestWarning(
                    f"@pytest.mark.{MARKER_NAME} has no effect on synchronous "
                    f"test {item.nodeid}: there is no event loop to monitor"
                )
            )
        return

    # Wrap async test with blocking detection
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        # Keep this frame out of the failure traceback. Without it pytest
        # prints ~25 lines of this function's own source and the blocking
        # verdict lands underneath it, the last thing the reader sees --
        # while docs/AI-HARNESS.md tells agents to react to that verdict,
        # so it has to come first. An exception raised by the test itself
        # is unaffected: only this frame is hidden, the user's own frames
        # still show.
        __tracebackhide__ = True
        marker = item.get_closest_marker(MARKER_NAME)
        try:
            threshold = _effective_threshold_ms(item, marker)
        except pytest.fail.Exception as exc:
            # #83 (comment): pytest.fail() above raises before the
            # try/finally below ever runs, so this test used to vanish from
            # the report entirely -- totals.tests undercounted and the
            # top-level verdict could read "clean" while a test loudly
            # failed. Give it an unmeasured record naming the problem
            # instead, and still fail exactly as before.
            records = item.config.stash.setdefault(_REPORT_KEY, [])
            records.append(
                {
                    "nodeid": item.nodeid,
                    "verdict": "unmeasured",
                    "threshold_ms": _threshold_ms(item.config),
                    "events": [],
                    "hints": [],
                    "reason": str(exc),
                }
            )
            raise

        detector = BlockingDetector(threshold_ms=threshold)
        await detector.start()

        try:
            result = await original_func(*args, **kwargs)
        finally:
            # Record in the finally so a test that both blocks AND fails
            # functionally still lands its "blocked" verdict in the report
            await detector.stop()
            events = list(detector.blocking_events)
            if events:
                verdict = "blocked"
            elif detector.clock_untrusted:
                verdict = "unmeasured"
            else:
                verdict = "clean"
            record: dict[str, Any] = {
                "nodeid": item.nodeid,
                "verdict": verdict,
                "threshold_ms": threshold,
                "events": [
                    {"lag_ms": round(lag, 2), "threshold_ms": threshold}
                    for lag in events
                ],
                "hints": hint_lines() if events else [],
            }
            if verdict == "unmeasured":
                record["reason"] = _CLOCK_UNTRUSTED_REASON
            records = item.config.stash.setdefault(_REPORT_KEY, [])
            records.append(record)

        if events:
            max_lag = max(events)
            pytest.fail(
                f"Event loop blocking detected! "
                f"{len(events)} blocking event(s), "
                f"max lag: {max_lag:.2f}ms (threshold: {threshold}ms)"
            )
        elif detector.clock_untrusted:
            # Loud, but never a new failure (#83): the plugin cannot prove
            # the test is clean when it cannot prove it was watching the
            # loop reliably, but it must not punish the test for that with
            # a failure it would not otherwise have had.
            item.warn(pytest.PytestWarning(_CLOCK_UNTRUSTED_REASON))

        return result

    item.obj = wrapped


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write the machine-readable report if a path was configured."""
    config = session.config
    path = _report_path(config)
    if not path:
        return

    records = config.stash.get(_REPORT_KEY, [])
    flagged = sum(1 for r in records if r["verdict"] == "blocked")
    unmeasured = sum(1 for r in records if r["verdict"] == "unmeasured")
    totals: dict[str, int] = {
        "tests": len(records),
        "flagged": flagged,
    }
    if unmeasured:
        totals["unmeasured"] = unmeasured
        totals["measured"] = len(records) - unmeasured
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        # One top-level verdict so a consumer does not have to derive it.
        # A run that instrumented nothing is "clean": the report states what
        # was observed, and nothing blocked because nothing was watched. A
        # gate that must also insist the suite was actually checked reads
        # totals.tests > 0 alongside it. An unmeasured-only run is also
        # "clean": no blocking was observed, even though it could not be
        # ruled out either -- see totals.unmeasured for that distinction.
        "status": "blocked" if flagged else "clean",
        "threshold_ms": _threshold_ms(config),
        "totals": totals,
        "tests": records,
    }
    Path(path).write_text(json.dumps(report, indent=2))


def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: pytest.Config
) -> None:
    """Name how many tests had an untrustworthy clock, if any did (#83)."""
    records = config.stash.get(_REPORT_KEY, [])
    unmeasured = sum(1 for r in records if r["verdict"] == "unmeasured")
    if not unmeasured:
        return
    terminalreporter.write_line(
        f"loopguard: {unmeasured} unmeasured test(s) -- the event loop "
        "clock could not be trusted, so blocking may have gone undetected"
    )
