import asyncio
import time

import pytest

from fastapi_loopguard.config import LoopGuardConfig
from fastapi_loopguard.monitor import SentinelMonitor


@pytest.mark.asyncio
async def test_cumulative_blocking_detection() -> None:
    # Setup: Enable cumulative blocking detection
    config = LoopGuardConfig(
        enabled=True,
        monitor_interval_ms=10.0,
        fallback_threshold_ms=50.0,  # High single threshold
        cumulative_blocking_enabled=True,
        cumulative_blocking_threshold_ms=100.0,  # Lower cumulative threshold
        cumulative_window_ms=1000.0,
    )

    detected_events: list[float] = []

    def on_blocking(lag_ms: float, path: str | None, method: str | None) -> None:
        detected_events.append(lag_ms)

    monitor = SentinelMonitor(config, on_blocking=on_blocking)

    # Start monitor with background calibration to avoid startup block
    await monitor.start_with_background_calibration()

    # Wait for calibration to likely finish or at least monitor to be running
    await asyncio.sleep(0.2)

    try:
        # Simulate frequent small blocking calls
        # Each block is 20ms.
        # Single threshold is 50ms, so individual blocks shouldn't trigger.
        # Cumulative threshold is 100ms.
        # We need ~6 iterations to exceed 100ms (6 * 20 = 120ms).

        for _ in range(10):
            time.sleep(0.02)  # 20ms synchronous block
            await asyncio.sleep(0.01)  # Yield to event loop to let monitor run

        # Allow monitor time to process
        await asyncio.sleep(0.2)

        # Assertions
        assert len(detected_events) > 0, "Should have detected cumulative blocking"

        # Verify that we detected cumulative blocking (value should be > 100)
        # Note: The first detection might clear the history,
        # so subsequent ones might be smaller or larger depending on timing.
        # But we expect at least one event where lag > 100.

        # Filter for events that exceed the cumulative threshold
        cumulative_detections = [lag for lag in detected_events if lag > 100.0]
        assert len(cumulative_detections) > 0, (
            f"Detected events {detected_events} "
            "did not exceed cumulative threshold 100ms"
        )

    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_cumulative_blocking_disabled_by_default() -> None:
    # Verify it doesn't trigger when disabled
    config = LoopGuardConfig(
        enabled=True,
        monitor_interval_ms=10.0,
        fallback_threshold_ms=50.0,
        # Default is cumulative_blocking_enabled=False
    )

    assert config.cumulative_blocking_enabled is False

    detected_events: list[float] = []

    def on_blocking_lambda(x: float, y: str | None, z: str | None) -> None:
        detected_events.append(x)

    monitor = SentinelMonitor(config, on_blocking=on_blocking_lambda)
    await monitor.start_with_background_calibration()
    await asyncio.sleep(0.2)

    try:
        for _ in range(10):
            time.sleep(0.02)
            await asyncio.sleep(0.01)

        await asyncio.sleep(0.2)
        assert len(detected_events) == 0, (
            "Should NOT detect blocking when cumulative detection is disabled"
        )
    finally:
        await monitor.stop()
