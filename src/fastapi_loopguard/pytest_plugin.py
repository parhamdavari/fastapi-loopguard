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
from pathlib import Path
from typing import Any

import pytest

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
        """Start the blocking detector."""
        self._running = True
        self._task = asyncio.create_task(self._monitor())

    async def stop(self) -> None:
        """Stop the blocking detector.

        Runs inside test finally blocks, so it must not swallow a
        cancellation aimed at the test itself (e.g. a timeout plugin).
        """
        self._running = False
        task = self._task
        self._task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise

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
