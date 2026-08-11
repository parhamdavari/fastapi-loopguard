import asyncio
import time

import pytest

from fastapi_loopguard.config import LoopGuardConfig
from fastapi_loopguard.context import (
    RequestContext,
    register_request,
    unregister_request,
)
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
async def test_single_block_reported_once() -> None:
    # A single long block must produce exactly one event. The sample that
    # fired the single-shot detection must not be re-counted by the
    # cumulative window as a second event.
    config = LoopGuardConfig(
        monitor_interval_ms=10.0,
        calibration_iterations=10,
        fallback_threshold_ms=50.0,
        cumulative_blocking_enabled=True,
        cumulative_blocking_threshold_ms=200.0,
        cumulative_window_ms=1000.0,
        log_blocking_events=False,
    )
    detected: list[float] = []

    def on_blocking(lag_ms: float, path: str | None, method: str | None) -> None:
        detected.append(lag_ms)

    monitor = SentinelMonitor(config, on_blocking=on_blocking)
    ctx = RequestContext(request_id="req-1", path="/x", method="GET")

    await monitor.start()
    await asyncio.sleep(0.05)  # Let the monitor loop start ticking
    register_request(ctx)
    try:
        time.sleep(0.3)  # ONE 300ms block, above both thresholds
        await asyncio.sleep(0.1)  # Several monitor iterations observe the aftermath
    finally:
        unregister_request(ctx.request_id)
        await monitor.stop()

    assert len(detected) == 1, f"expected exactly one event, got {detected}"
    assert 250.0 <= detected[0] <= 450.0
    assert ctx.blocking_count == 1
    assert 250.0 <= ctx.total_blocking_ms <= 450.0


def test_cumulative_events_tracked_separately() -> None:
    # Cumulative window sums must not be mixed into the individual-lag list;
    # they carry different semantics (sum vs sample).
    ctx = RequestContext(request_id="r1", path="/", method="GET")
    ctx.record_blocking(30.0)
    ctx.record_blocking(120.0, cumulative=True)

    assert [lag for lag, _ in ctx.blocking_events] == [30.0]
    assert [lag for lag, _ in ctx.cumulative_events] == [120.0]
    assert ctx.blocking_count == 2
    assert ctx.total_blocking_ms == 150.0


@pytest.mark.asyncio
async def test_cumulative_blocking_enabled_by_default() -> None:
    # Verify cumulative blocking is enabled by default
    config = LoopGuardConfig(
        enabled=True,
        monitor_interval_ms=10.0,
        fallback_threshold_ms=50.0,
    )

    assert config.cumulative_blocking_enabled is True


@pytest.mark.asyncio
async def test_cumulative_blocking_can_be_disabled() -> None:
    # Verify it doesn't trigger when explicitly disabled
    config = LoopGuardConfig(
        enabled=True,
        monitor_interval_ms=10.0,
        fallback_threshold_ms=50.0,
        cumulative_blocking_enabled=False,
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
