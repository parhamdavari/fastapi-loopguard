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

Scoping measurement to part of a test:
    from fastapi_loopguard.pytest_plugin import loopguard_only, loopguard_pause

    async def test_route(client):
        with loopguard_pause():     # slow setup, not a handler stall
            app = create_app()
        resp = await client.get("/x")

    Both managers are synchronous, and complete no-ops in a test the
    plugin is not instrumenting, so a shared helper can use them either
    way.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import json
import logging
import math
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import pytest

from .hints import hint_lines

if TYPE_CHECKING:
    from collections.abc import Iterator

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


def _loop_time() -> float | None:
    """The running loop's own clock, or None when there is no loop.

    Only ever compared against another reading of the same clock, never
    against the real one on its own -- see `_measure_tick`. Returns None
    off the loop, which the scoped-measurement managers can reach: a
    context copy carrying the detector travels into a worker thread
    (`asyncio.to_thread`), and a helper that pauses there has no loop of
    its own to read.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return loop.time()


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
        # Scoped-measurement window state (#85). It lives on the detector
        # rather than in a context variable of its own, so a task spawned
        # by the test -- which gets a copy of the context pointing at this
        # same object -- scopes the same window its parent does.
        self._pause_depth = 0
        self._only_depth = 0
        self._only_opened = False
        self._only_closed = False
        # Real- and loop-clock baselines that a measurement is taken
        # against once a window ends, so the tick straddling that point
        # contributes only its post-window portion. Both clocks, always
        # together: shifting the real baseline alone would leave
        # _measure_tick's drift check reading the whole window as loop
        # clock divergence and reporting the test unmeasured.
        self._watermark_real: float | None = None
        self._watermark_loop: float | None = None

    @property
    def suppressed(self) -> bool:
        """Whether measurement is currently scoped out of the test (#85).

        True inside a `loopguard_pause()` window and after a
        `loopguard_only()` window has closed. A depth counter, not a
        boolean, so a helper that pauses inside its caller's pause does
        not un-pause the caller early.
        """
        return self._pause_depth > 0 or self._only_closed

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
        if self.suppressed:
            # Inside a loopguard_pause(), or after a loopguard_only()
            # window closed: nothing is recorded, and the clock is not
            # judged either. The tick is deliberately left *unconsumed* --
            # leaving the window re-baselines it against a watermark, so
            # its post-window portion is still measured (#85).
            return
        self._tick_consumed = True

        real_start = self._tick_real_start
        loop_start = self._tick_loop_start
        interval = _MONITOR_INTERVAL_SEC
        watermark = self._watermark_real
        if watermark is not None and watermark > real_start:
            # A window ended part-way through this tick: measure only what
            # happened after it, and move BOTH clocks' baselines, or the
            # drift check below reads the window itself as divergence.
            #
            # The expected time moves with the baseline. This tick's sleep
            # started at the tick, not at the watermark, so all that is
            # still owed from the watermark onward is whatever of that
            # sleep is left -- nothing at all once it would already have
            # ended, which is the usual case after a window that blocked
            # for longer than one interval. Crediting the full interval
            # from every watermark drops up to one interval of real lag at
            # each boundary, which invariant 9 does not allow any more
            # than it allows counting one twice.
            interval = max(0.0, real_start + interval - watermark)
            real_start = watermark
            loop_start = self._watermark_loop

        real_elapsed = _REAL_MONOTONIC() - real_start
        lag_ms = (real_elapsed - interval) * 1000

        if lag_ms > self.threshold_ms:
            self.blocking_events.append(lag_ms)
            return

        if time.monotonic is not _REAL_MONOTONIC:
            self._clock_untrusted = True
            return

        if loop_start is not None:
            loop_now = _loop_time()
            if (
                loop_now is not None
                and abs(real_elapsed - (loop_now - loop_start))
                > _CLOCK_DRIFT_TOLERANCE_SEC
            ):
                self._clock_untrusted = True

    def enter_pause(self) -> None:
        """Open a `loopguard_pause()` window.

        Banks the pre-entry portion of the in-flight tick first: blocking
        *before* the window is still the test's problem, and with no
        further await it would otherwise only ever be measured by the tick
        that resumes after the window -- where the suppression would
        swallow it. `poll()` is itself suppressed inside an open window,
        so a nested pause banks nothing.
        """
        self.poll()
        self._pause_depth += 1

    def exit_pause(self) -> None:
        """Close a `loopguard_pause()` window; measurement resumes at zero."""
        self._pause_depth -= 1
        if self._pause_depth == 0:
            self._resume_measurement()

    def enter_only(self) -> None:
        """Open a `loopguard_only()` window: measure this, and nothing else.

        The first enter clears what was recorded before it. That is
        retroactive, and safe because the pass/fail decision is taken after
        the test body returns; a second window reopens without clearing, so
        what the first one found survives.
        """
        if self._only_depth == 0:
            if not self._only_opened:
                self.blocking_events.clear()
                self._only_opened = True
            self._only_closed = False
            self._resume_measurement()
        self._only_depth += 1

    def exit_only(self) -> None:
        """Close a `loopguard_only()` window and suppress the rest of the test.

        Banks the in-window portion of the in-flight tick *before* raising
        the suppression, mirroring `enter_pause()` on the other side. This
        is the only transition into suppression that has something left to
        measure: the enter re-baselined the tick to the window's start, so
        a window that blocks and returns without ever awaiting has nothing
        else that would ever measure it -- `stop()`'s own poll runs after
        the window is closed and is suppressed like any other.
        """
        self._only_depth -= 1
        if self._only_depth == 0:
            self.poll()
            self._only_closed = True

    def _resume_measurement(self) -> None:
        """Re-baseline the in-flight tick to now, as a window ends (#85).

        Two things, both load-bearing. The watermark -- real and loop
        clocks together -- is what makes the tick straddling this point
        contribute only its post-window portion, so the window's own stall
        is not charged by the tick that resumes after it.

        Re-arming `_tick_consumed` is what keeps that tick measurable at
        all. The poll on entering the window consumed it, and a window that
        ends with no further await (an `httpx.ASGITransport` request
        completes without ever yielding to the loop) would leave `stop()`'s
        own poll refusing to measure exactly the region the user asked to
        measure.
        """
        self._watermark_real = _REAL_MONOTONIC()
        self._watermark_loop = _loop_time()
        self._tick_consumed = False

    async def stop(self) -> None:
        """Stop the blocking detector.

        Runs inside test finally blocks, so it must not swallow a
        cancellation aimed at the test itself (e.g. a timeout plugin) --
        and, just as important, a cancellation aimed at *this* coroutine
        must not be able to skip cancelling the monitor task either.
        Capturing and clearing `_task`, flipping `_running`, and calling
        `task.cancel()` therefore all happen synchronously, with no
        `await` ahead of them, mirroring `SentinelMonitor._cancel_and_wait`
        in monitor.py, whose first statement is the cancel for the same
        reason.

        An earlier version of this method opened with
        `await asyncio.sleep(0)` before any of that, reasoning it was a
        call_soon hop and therefore safe to await even under a frozen
        clock. It is safe from the clock, but it is still a cancellation
        point: a cancellation delivered there (e.g. a timeout plugin
        firing while this method is suspended) raised immediately and
        skipped every line after it -- the monitor task was never told to
        stop, orphaning it on the loop, and the exception propagated past
        this method before `pytest_plugin.wrapped()`'s own `finally` could
        append the test's report record, the same defect class already
        fixed for the marker-validation path.

        Measures the in-flight tick before any of that (`poll()`, like
        `SentinelMonitor.poll()`, refuses to measure once `_running` is
        false) -- this is the last chance to catch a tick still in flight,
        since the monitor task is cancelled immediately after and never
        gets a turn of its own to measure it (#83). `poll()` and
        `_measure_tick()` are both synchronous, so this cannot itself be
        interrupted by a cancellation. A test that ends inside a scoped
        window records nothing there: that measurement is suppressed like
        any other (#85).
        """
        if not self._running:
            return

        # Always the last measurement of this tick: the monitor task is
        # cancelled right below and never gets another turn to measure it.
        self.poll()

        self._running = False
        task = self._task
        self._task = None
        if task is None:
            return
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
            # failure with a confusing one. Retrieved unconditionally --
            # including when the task had already finished by raising
            # before we got here -- so asyncio never resurfaces it later
            # as an unattributed "Task exception was never retrieved".
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


# The detector instrumenting the test that is currently running, or None.
# Set by wrapped() immediately before awaiting the test and reset from its
# token in the same finally, so an uninstrumented test -- a sync test, an
# unmarked one with the gate off, an allow_blocking one, or no pytest
# session at all -- never sees one, and both managers below are inert
# there. A task spawned by the test inherits a copy of the context, which
# points at the same detector object.
_ACTIVE_DETECTOR: contextvars.ContextVar[BlockingDetector | None] = (
    contextvars.ContextVar("fastapi_loopguard_active_detector", default=None)
)


@contextmanager
def loopguard_pause() -> Iterator[None]:
    """Stop measuring event loop blocking for the duration of this block.

    For work that is part of the test but not part of what it is testing --
    building an app, loading a fixture, warming a cache -- which the
    deployed service does once at startup rather than per request::

        async def test_route(client):
            with loopguard_pause():
                app = create_app()
            resp = await client.get("/x")   # this is what gets measured

    Blocking before the window is still charged, and blocking after it
    still flags. Nests: a helper that pauses inside a caller's pause
    leaves the caller's window intact. A no-op, raising and warning
    nothing, when the plugin is not instrumenting the test.
    """
    detector = _ACTIVE_DETECTOR.get()
    if detector is None:
        yield
        return

    detector.enter_pause()
    try:
        yield
    finally:
        # try/finally: an exception escaping the window must not leave the
        # rest of the test silently unguarded.
        detector.exit_pause()


@contextmanager
def loopguard_only() -> Iterator[None]:
    """Measure event loop blocking inside this block and nowhere else.

    The inverse of `loopguard_pause()`, for a test whose setup and teardown
    are both out of scope::

        async def test_route(client):
            app = create_app()
            with loopguard_only():
                resp = await client.get("/x")

    The first window clears what was recorded before it and the rest of the
    test after it is suppressed; a second window reopens without clearing,
    so what an earlier one found still fails the test. A no-op, raising and
    warning nothing, when the plugin is not instrumenting the test.

    **Suppressing the rest of the test is the whole point of it, and it
    reaches past the block.** Everything after the window is out of scope
    until another window opens -- not merely the lines below it in the same
    function, but the rest of the test, whichever function it runs in. So a
    shared helper that opens one of these takes its caller's test out of
    scope from the moment the helper returns, and nothing at the call site
    shows that. Prefer `loopguard_pause()` in a helper, which gives back
    exactly what it took; keep `loopguard_only()` in the test body, where a
    reader can see what it covers.
    """
    detector = _ACTIVE_DETECTOR.get()
    if detector is None:
        yield
        return

    detector.enter_only()
    try:
        yield
    finally:
        detector.exit_only()


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

        # Published here, immediately before the test runs, so that
        # loopguard_pause()/loopguard_only() reach this detector -- and
        # only ever from a test this wrapper is actually instrumenting
        # (#85).
        token = _ACTIVE_DETECTOR.set(detector)

        try:
            result = await original_func(*args, **kwargs)
        finally:
            _ACTIVE_DETECTOR.reset(token)
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
