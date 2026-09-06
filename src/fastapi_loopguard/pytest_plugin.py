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
from pathlib import Path
from typing import Any

import pytest

logger = logging.getLogger("fastapi_loopguard")

# How long stop() waits for the monitor to record its pending sample. The
# monitor's own interval is 5ms, so this is slack, not a budget.
_DRAIN_TIMEOUT_SEC = 0.1

# Marker for tests that should fail on blocking
MARKER_NAME = "no_blocking"
# Opt-out marker for loopguard_all_async mode
ALLOW_MARKER_NAME = "allow_blocking"

# Per-session records for the machine-readable report
_REPORT_KEY: pytest.StashKey[list[dict[str, Any]]] = pytest.StashKey()

# Suggested rewrites included with every "blocked" verdict so an agent
# consuming the report can act without extra context
_FIX_HINTS = [
    "time.sleep(n) -> await asyncio.sleep(n)",
    "requests.get(url) -> await httpx.AsyncClient().get(url)",
    "open(f).read() -> await aiofiles.open(f)",
    "subprocess.run(...) -> await asyncio.create_subprocess_exec(...)",
    "CPU-bound work -> await asyncio.to_thread(func)",
]


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
        "Blocking detection threshold in milliseconds",
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
    """Detects event loop blocking during test execution."""

    def __init__(self, threshold_ms: float = 50.0) -> None:
        self.threshold_ms = threshold_ms
        self.blocking_events: list[float] = []
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the blocking detector.

        Yields once so the monitor task reaches its first sleep before the
        caller continues: without this, a test that blocks before its first
        real await (an ASGI request dispatch does exactly that) blocks an
        unarmed sentinel and is never measured.
        """
        self._running = True
        self._task = asyncio.create_task(self._monitor())
        await asyncio.sleep(0)

    async def stop(self) -> None:
        """Stop the blocking detector.

        Runs inside test finally blocks, so it must not swallow a
        cancellation aimed at the test itself (e.g. a timeout plugin).

        Adds up to one monitor interval (5ms) per instrumented test, which
        is visible as wall clock on a large suite under loopguard_all_async.

        Drains the monitor instead of cancelling it: a test that blocks and
        then returns without awaiting leaves the monitor holding an expired
        sleep and an unrecorded lag. Cancelling straight away discards that
        sample and scores the test clean, which is the common shape of
        blocking test code. Clearing _running first makes the monitor exit
        after one more iteration, so this waits at most one interval.
        """
        self._running = False
        task = self._task
        self._task = None
        if task:
            try:
                # Bounded: _running is already False, so the monitor exits
                # after at most one interval. The timeout is only there so a
                # wedged loop cannot hang every test's teardown.
                await asyncio.wait_for(task, timeout=_DRAIN_TIMEOUT_SEC)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            except Exception:
                # This runs in the finally of every instrumented test. An
                # exception from the monitor must not replace the test's own
                # failure with a confusing one.
                logger.warning("LoopGuard blocking detector failed", exc_info=True)
            finally:
                if not task.done():
                    task.cancel()

    async def _monitor(self) -> None:
        """Monitor for blocking."""
        loop = asyncio.get_running_loop()
        interval = 0.005  # 5ms

        while self._running:
            start = loop.time()
            await asyncio.sleep(interval)
            elapsed = loop.time() - start
            lag_ms = (elapsed - interval) * 1000

            if lag_ms > self.threshold_ms:
                self.blocking_events.append(lag_ms)


def _threshold_ms(config: pytest.Config) -> float:
    threshold_str = config.getini("loopguard_threshold_ms")
    return float(threshold_str) if threshold_str else 50.0


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
    if not explicit:
        if item.get_closest_marker(ALLOW_MARKER_NAME) is not None:
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
        threshold = _threshold_ms(item.config)

        detector = BlockingDetector(threshold_ms=threshold)
        await detector.start()

        try:
            result = await original_func(*args, **kwargs)
        finally:
            # Record in the finally so a test that both blocks AND fails
            # functionally still lands its "blocked" verdict in the report
            await detector.stop()
            events = list(detector.blocking_events)
            records = item.config.stash.setdefault(_REPORT_KEY, [])
            records.append(
                {
                    "nodeid": item.nodeid,
                    "verdict": "blocked" if events else "clean",
                    "events": [
                        {"lag_ms": round(lag, 2), "threshold_ms": threshold}
                        for lag in events
                    ],
                    "hints": _FIX_HINTS if events else [],
                }
            )

        if events:
            max_lag = max(events)
            pytest.fail(
                f"Event loop blocking detected! "
                f"{len(events)} blocking event(s), "
                f"max lag: {max_lag:.2f}ms (threshold: {threshold}ms)"
            )

        return result

    item.obj = wrapped


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write the machine-readable report if a path was configured."""
    config = session.config
    path = _report_path(config)
    if not path:
        return

    records = config.stash.get(_REPORT_KEY, [])
    report = {
        "schema_version": 1,
        "threshold_ms": _threshold_ms(config),
        "totals": {
            "tests": len(records),
            "flagged": sum(1 for r in records if r["verdict"] == "blocked"),
        },
        "tests": records,
    }
    Path(path).write_text(json.dumps(report, indent=2))
