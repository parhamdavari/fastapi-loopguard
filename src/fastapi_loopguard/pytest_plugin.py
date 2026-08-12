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
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest

# Marker for tests that should fail on blocking
MARKER_NAME = "no_blocking"


def pytest_configure(config: pytest.Config) -> None:
    """Register the no_blocking marker."""
    config.addinivalue_line(
        "markers",
        f"{MARKER_NAME}: fail test if event loop blocking is detected",
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add loopguard options to pytest."""
    parser.addini(
        "loopguard_threshold_ms",
        "Blocking detection threshold in milliseconds",
        type="string",
        default="50",
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


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item: pytest.Item) -> None:
    """Check for blocking after test execution."""
    marker = item.get_closest_marker(MARKER_NAME)
    if marker is None:
        return

    # Only works with Function items (which have obj attribute)
    if not isinstance(item, pytest.Function):
        return

    # Store the original test function
    original_func = item.obj

    if not inspect.iscoroutinefunction(original_func):
        # A sync test never runs on the event loop; silently passing would
        # let the author believe blocking was checked
        item.warn(
            pytest.PytestWarning(
                f"@pytest.mark.{MARKER_NAME} has no effect on synchronous "
                f"test {item.nodeid}: there is no event loop to monitor"
            )
        )
        return

    # Wrap async test with blocking detection
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        threshold_str = item.config.getini("loopguard_threshold_ms")
        threshold = float(threshold_str) if threshold_str else 50.0

        detector = BlockingDetector(threshold_ms=threshold)
        await detector.start()

        try:
            result = await original_func(*args, **kwargs)
        finally:
            await detector.stop()

        if detector.blocking_events:
            max_lag = max(detector.blocking_events)
            pytest.fail(
                f"Event loop blocking detected! "
                f"{len(detector.blocking_events)} blocking event(s), "
                f"max lag: {max_lag:.2f}ms (threshold: {threshold}ms)"
            )

        return result

    item.obj = wrapped
