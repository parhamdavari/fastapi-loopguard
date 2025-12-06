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
import contextlib
from collections.abc import Generator
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
        """Stop the blocking detector."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

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


@pytest.fixture
def loopguard_detector(
    request: pytest.FixtureRequest,
) -> Generator[BlockingDetector, None, None]:
    """Fixture that provides a blocking detector for tests."""
    threshold_str = request.config.getini("loopguard_threshold_ms")
    threshold = float(threshold_str) if threshold_str else 50.0

    detector = BlockingDetector(threshold_ms=threshold)
    yield detector


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

    if asyncio.iscoroutinefunction(original_func):
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
