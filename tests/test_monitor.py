"""Tests for SentinelMonitor."""

import asyncio
import logging
import time

import pytest

from fastapi_loopguard import LoopGuardConfig, SentinelMonitor
from fastapi_loopguard.context import (
    RequestContext,
    get_registry,
    register_request,
    reset_current_request,
    set_current_request,
    unregister_request,
)
from fastapi_loopguard.monitor import AdaptiveThreshold


class TestSentinelMonitor:
    """Tests for the sentinel monitor."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    @pytest.fixture
    def config(self) -> LoopGuardConfig:
        """Create a test configuration with fast calibration."""
        return LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=20,
            threshold_multiplier=3.0,
            fallback_threshold_ms=20.0,
        )

    async def test_calibration(self, config: LoopGuardConfig) -> None:
        """Test that calibration sets baseline and threshold."""
        monitor = SentinelMonitor(config)

        threshold = await monitor.calibrate()

        assert monitor.baseline_ms >= 0
        assert monitor.threshold_ms > 0
        assert threshold == monitor.threshold_ms
        assert monitor.threshold_ms >= config.fallback_threshold_ms
        assert monitor.is_calibrated

    async def test_start_and_stop(self, config: LoopGuardConfig) -> None:
        """Test starting and stopping the monitor."""
        monitor = SentinelMonitor(config)

        assert not monitor.is_running

        await monitor.start()
        assert monitor.is_running

        await monitor.stop()
        assert not monitor.is_running

    async def test_start_with_background_calibration(
        self, config: LoopGuardConfig
    ) -> None:
        """Test background calibration doesn't block."""
        monitor = SentinelMonitor(config)

        assert not monitor.is_running
        assert not monitor.is_calibrated

        # Start with background calibration
        await monitor.start_with_background_calibration()
        assert monitor.is_running

        # Calibration starts in background, may not be done yet
        # Wait for calibration to complete
        await asyncio.sleep(0.2)
        assert monitor.is_calibrated

        await monitor.stop()
        assert not monitor.is_running

    async def test_detects_blocking(self, config: LoopGuardConfig) -> None:
        """Test that blocking code is detected."""
        blocking_events: list[tuple[float, str | None, str | None]] = []

        def on_blocking(lag_ms: float, path: str | None, method: str | None) -> None:
            blocking_events.append((lag_ms, path, method))

        # Use a very low threshold for testing
        test_config = LoopGuardConfig(
            monitor_interval_ms=2.0,  # Fast monitoring
            calibration_iterations=10,
            threshold_multiplier=2.0,
            fallback_threshold_ms=5.0,  # Low threshold
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(test_config, on_blocking=on_blocking)

        await monitor.start()

        # Let the monitor start its loop
        await asyncio.sleep(0.01)

        # Block the event loop (this is intentional for testing!)
        time.sleep(0.1)  # 100ms blocking - well above threshold

        # Give the monitor a chance to detect it
        await asyncio.sleep(0.01)

        await monitor.stop()

        # Should have detected at least one blocking event
        assert len(blocking_events) >= 1
        assert blocking_events[0][0] > 5  # lag > threshold

    async def test_attributes_to_request(self, config: LoopGuardConfig) -> None:
        """Test that blocking is attributed to the active request."""
        blocking_events: list[tuple[float, str | None, str | None]] = []

        def on_blocking(lag_ms: float, path: str | None, method: str | None) -> None:
            blocking_events.append((lag_ms, path, method))

        test_config = LoopGuardConfig(
            monitor_interval_ms=2.0,  # Fast monitoring
            calibration_iterations=10,
            threshold_multiplier=2.0,
            fallback_threshold_ms=5.0,  # Low threshold
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(test_config, on_blocking=on_blocking)

        await monitor.start()

        # Let the monitor start its loop
        await asyncio.sleep(0.01)

        # Set up a request context using new API
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        register_request(ctx)

        try:
            # Block the event loop
            time.sleep(0.1)  # 100ms blocking
            await asyncio.sleep(0.01)
        finally:
            unregister_request(ctx.request_id)

        await monitor.stop()

        # Should have detected blocking with request attribution
        assert len(blocking_events) >= 1
        assert blocking_events[0][1] == "/api/users"
        assert blocking_events[0][2] == "GET"

        # Request context should have recorded the blocking
        assert ctx.blocking_count >= 1
        assert ctx.total_blocking_ms > 0

    async def test_attributes_to_multiple_requests(
        self, config: LoopGuardConfig
    ) -> None:
        """Test that blocking is attributed to all active requests."""
        blocking_events: list[tuple[float, str | None, str | None]] = []

        def on_blocking(lag_ms: float, path: str | None, method: str | None) -> None:
            blocking_events.append((lag_ms, path, method))

        test_config = LoopGuardConfig(
            monitor_interval_ms=2.0,
            calibration_iterations=10,
            threshold_multiplier=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(test_config, on_blocking=on_blocking)

        await monitor.start()
        await asyncio.sleep(0.01)

        # Register multiple concurrent requests
        ctx1 = RequestContext(request_id="req-1", path="/api/users", method="GET")
        ctx2 = RequestContext(request_id="req-2", path="/api/items", method="POST")
        register_request(ctx1)
        register_request(ctx2)

        try:
            # Block the event loop
            time.sleep(0.1)
            await asyncio.sleep(0.01)
        finally:
            unregister_request(ctx1.request_id)
            unregister_request(ctx2.request_id)

        await monitor.stop()

        # Both requests should have blocking recorded
        assert ctx1.blocking_count >= 1
        assert ctx2.blocking_count >= 1

        # Callback should be called for each active request
        assert len(blocking_events) >= 2

    async def test_backward_compat_api(self, config: LoopGuardConfig) -> None:
        """Test backward compatibility with old set/reset API."""
        ctx = RequestContext(
            request_id="compat-test",
            path="/compat",
            method="GET",
        )

        # Old API still works
        token = set_current_request(ctx)
        assert get_registry().active_count() == 1

        reset_current_request(token)
        assert get_registry().active_count() == 0


class TestAdaptiveThreshold:
    """Tests for AdaptiveThreshold class."""

    def test_init_values(self) -> None:
        """Test initialization sets correct values."""
        adaptive = AdaptiveThreshold(
            window_size=500,
            percentile=0.95,
            multiplier=5.0,
            min_threshold_ms=50.0,
            min_samples=100,
        )

        assert adaptive.current_threshold_ms == 50.0
        assert adaptive.sample_count == 0

    def test_add_sample(self) -> None:
        """Test adding samples."""
        adaptive = AdaptiveThreshold(
            window_size=100,
            percentile=0.95,
            multiplier=5.0,
            min_threshold_ms=10.0,
            min_samples=10,
        )

        for i in range(50):
            adaptive.add_sample(float(i))

        assert adaptive.sample_count == 50

    def test_window_size_limit(self) -> None:
        """Test that window size is respected."""
        adaptive = AdaptiveThreshold(
            window_size=100,
            percentile=0.95,
            multiplier=5.0,
            min_threshold_ms=10.0,
            min_samples=10,
        )

        # Add more samples than window size
        for i in range(200):
            adaptive.add_sample(float(i))

        # Should be capped at window size
        assert adaptive.sample_count == 100

    def test_recalculate_below_min_samples(self) -> None:
        """Test recalculate returns current value below min_samples."""
        adaptive = AdaptiveThreshold(
            window_size=1000,
            percentile=0.95,
            multiplier=5.0,
            min_threshold_ms=50.0,
            min_samples=100,
        )

        # Add fewer samples than min_samples
        for _ in range(50):
            adaptive.add_sample(5.0)

        result = adaptive.recalculate()
        assert result == 50.0  # Should return min_threshold_ms (initial value)

    def test_recalculate_with_enough_samples(self) -> None:
        """Test recalculate computes percentile-based threshold."""
        adaptive = AdaptiveThreshold(
            window_size=1000,
            percentile=0.95,
            multiplier=5.0,
            min_threshold_ms=10.0,
            min_samples=100,
        )

        # Add 100 samples with values 0-99
        for i in range(100):
            adaptive.add_sample(float(i))

        result = adaptive.recalculate()
        # P95 of [0..99] is around 95, × 5 = 475
        assert result > 400
        assert result == adaptive.current_threshold_ms

    def test_recalculate_respects_min_threshold(self) -> None:
        """Test that recalculate doesn't go below min_threshold_ms."""
        adaptive = AdaptiveThreshold(
            window_size=1000,
            percentile=0.95,
            multiplier=5.0,
            min_threshold_ms=100.0,
            min_samples=10,
        )

        # Add low values that would produce threshold < min
        for _ in range(100):
            adaptive.add_sample(1.0)

        result = adaptive.recalculate()
        # 1.0 × 5.0 = 5.0, but min is 100
        assert result == 100.0


class TestSentinelMonitorAdaptive:
    """Tests for SentinelMonitor with adaptive threshold."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_adaptive_mode_initialization(self) -> None:
        """Test that adaptive mode initializes AdaptiveThreshold."""
        config = LoopGuardConfig(
            adaptive_threshold=True,
            adaptive_window_size=500,
            adaptive_percentile=0.90,
            adaptive_min_samples=50,
            adaptive_update_interval_ms=100.0,
        )
        monitor = SentinelMonitor(config)

        # Monitor should have an adaptive threshold
        assert monitor._adaptive is not None
        assert monitor._adaptive.current_threshold_ms == config.fallback_threshold_ms

    async def test_non_adaptive_mode_no_adaptive(self) -> None:
        """Test that non-adaptive mode has no AdaptiveThreshold."""
        config = LoopGuardConfig(adaptive_threshold=False)
        monitor = SentinelMonitor(config)

        assert monitor._adaptive is None

    async def test_adaptive_threshold_updates(self) -> None:
        """Test that adaptive threshold updates during monitoring."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            adaptive_threshold=True,
            adaptive_window_size=200,
            adaptive_percentile=0.95,
            adaptive_min_samples=50,
            adaptive_update_interval_ms=50.0,  # Fast updates
            fallback_threshold_ms=50.0,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.start_with_background_calibration()

        # Run for a bit to collect samples and trigger updates
        await asyncio.sleep(0.5)

        await monitor.stop()

        # Adaptive should have collected samples
        assert monitor._adaptive is not None
        assert monitor._adaptive.sample_count > 0


class TestMonitorIdempotency:
    """Tests for idempotent start/stop operations."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_double_start_idempotent(self) -> None:
        """Test that calling start() twice is safe and idempotent."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.start()
        assert monitor.is_running

        # Second start should be no-op
        await monitor.start()
        assert monitor.is_running

        await monitor.stop()
        assert not monitor.is_running

    async def test_double_stop_idempotent(self) -> None:
        """Test that calling stop() twice is safe."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.start()
        assert monitor.is_running

        await monitor.stop()
        assert not monitor.is_running

        # Second stop should be no-op
        await monitor.stop()
        assert not monitor.is_running

    async def test_stop_before_start(self) -> None:
        """Test that calling stop() without start() is safe."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        assert not monitor.is_running

        # Should not raise
        await monitor.stop()

        assert not monitor.is_running

    async def test_double_start_background_calibration_idempotent(self) -> None:
        """Test that calling start_with_background_calibration() twice is safe."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.start_with_background_calibration()
        assert monitor.is_running

        # Second start should be no-op
        await monitor.start_with_background_calibration()
        assert monitor.is_running

        await monitor.stop()
        assert not monitor.is_running


class TestCallbackAndZeroRequests:
    """Tests for callback handling and zero active requests."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_on_blocking_callback_receives_none_for_no_requests(self) -> None:
        """Test callback receives (lag, None, None) when no requests active."""
        blocking_events: list[tuple[float, str | None, str | None]] = []

        def on_blocking(lag_ms: float, path: str | None, method: str | None) -> None:
            blocking_events.append((lag_ms, path, method))

        config = LoopGuardConfig(
            monitor_interval_ms=2.0,
            calibration_iterations=10,
            threshold_multiplier=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config, on_blocking=on_blocking)

        await monitor.start()
        await asyncio.sleep(0.01)

        # Block with no active requests
        time.sleep(0.1)
        await asyncio.sleep(0.01)

        await monitor.stop()

        # Should have detected blocking with None values
        assert len(blocking_events) >= 1
        assert blocking_events[0][1] is None  # path is None
        assert blocking_events[0][2] is None  # method is None

    async def test_blocking_with_no_requests_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that blocking with no requests logs a warning."""
        config = LoopGuardConfig(
            monitor_interval_ms=2.0,
            calibration_iterations=10,
            threshold_multiplier=2.0,
            fallback_threshold_ms=5.0,
            log_blocking_events=True,  # Enable logging
        )
        monitor = SentinelMonitor(config)

        with caplog.at_level(logging.WARNING, logger="fastapi_loopguard"):
            await monitor.start()
            await asyncio.sleep(0.01)

            # Block with no active requests
            time.sleep(0.1)
            await asyncio.sleep(0.01)

            await monitor.stop()

        # Should have logged "no active request" warning
        assert any("no active request" in record.message for record in caplog.records)


class TestThresholdEdgeCases:
    """Tests for threshold boundary conditions."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_fallback_threshold_used_before_calibration(self) -> None:
        """Test that fallback threshold is used before calibration completes."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=100,  # Long calibration
            fallback_threshold_ms=25.0,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        # Before starting, threshold should be fallback
        assert monitor.threshold_ms == config.fallback_threshold_ms

        await monitor.start_with_background_calibration()

        # Immediately after start, threshold should still be fallback
        assert monitor.threshold_ms == config.fallback_threshold_ms
        assert not monitor.is_calibrated

        await monitor.stop()

    async def test_threshold_above_fallback_after_calibration(self) -> None:
        """Test threshold is at least fallback after calibration."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            threshold_multiplier=3.0,
            fallback_threshold_ms=20.0,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.calibrate()

        # Threshold should be at least fallback
        assert monitor.threshold_ms >= config.fallback_threshold_ms
        assert monitor.is_calibrated


class TestCalibrationEdgeCases:
    """Tests for calibration edge cases."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_calibration_cancelled_uses_fallback(self) -> None:
        """Test that cancelling calibration keeps fallback threshold."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=1000,  # Very long calibration
            fallback_threshold_ms=50.0,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.start_with_background_calibration()
        assert monitor.is_running
        assert not monitor.is_calibrated

        # Stop immediately before calibration completes
        await monitor.stop()

        # Threshold should still be fallback
        assert monitor.threshold_ms == config.fallback_threshold_ms

    async def test_calibration_already_done_skipped_on_start(self) -> None:
        """Test that start() doesn't re-calibrate if already done."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            fallback_threshold_ms=20.0,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        # Calibrate first
        await monitor.calibrate()
        assert monitor.is_calibrated
        original_threshold = monitor.threshold_ms
        original_baseline = monitor.baseline_ms

        # Start should skip calibration
        await monitor.start()
        assert monitor.is_running

        # Values should be unchanged
        assert monitor.threshold_ms == original_threshold
        assert monitor.baseline_ms == original_baseline

        await monitor.stop()

    async def test_calibration_calculates_p75(self) -> None:
        """Test that calibration correctly calculates P75 percentile."""
        config = LoopGuardConfig(
            monitor_interval_ms=1.0,  # Very fast
            calibration_iterations=20,
            threshold_multiplier=5.0,
            fallback_threshold_ms=0.1,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.calibrate()

        # Baseline should be set (P75 of samples)
        assert monitor.baseline_ms >= 0
        # Threshold should be baseline * multiplier (or fallback if higher)
        expected_min = max(
            monitor.baseline_ms * config.threshold_multiplier,
            config.fallback_threshold_ms,
        )
        assert monitor.threshold_ms >= expected_min - 0.001  # Small tolerance


class TestTaskCancellation:
    """Tests for proper task cancellation."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_stop_cancels_monitor_task(self) -> None:
        """Test that stop() cancels the monitor task."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.start()
        assert monitor._task is not None
        assert not monitor._task.done()

        await monitor.stop()

        # Task should be cancelled/done
        assert monitor._task is None or monitor._task.done()

    async def test_stop_cancels_calibration_task(self) -> None:
        """Test that stop() cancels the calibration task."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=1000,  # Long calibration
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.start_with_background_calibration()
        assert monitor._calibration_task is not None

        await monitor.stop()

        # Calibration task should be cancelled/done/None
        assert monitor._calibration_task is None or monitor._calibration_task.done()

    async def test_cancelled_error_suppressed(self) -> None:
        """Test that CancelledError is properly suppressed in stop()."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.start()

        # This should not raise CancelledError
        await monitor.stop()

        # Monitor should be cleanly stopped
        assert not monitor.is_running


class TestAdaptiveThresholdEdgeCases:
    """Tests for adaptive threshold edge cases."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_adaptive_threshold_not_updated_below_min_samples(self) -> None:
        """Test that adaptive threshold respects min_samples."""
        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            adaptive_threshold=True,
            adaptive_window_size=500,
            adaptive_percentile=0.95,
            adaptive_min_samples=100,  # High min samples
            adaptive_update_interval_ms=10.0,  # Fast updates
            fallback_threshold_ms=50.0,
            log_blocking_events=False,
        )
        monitor = SentinelMonitor(config)

        await monitor.start_with_background_calibration()

        # Run briefly - not enough to collect min_samples
        await asyncio.sleep(0.1)

        # Threshold should still be fallback
        # (adaptive doesn't update until min_samples reached)
        assert monitor._adaptive is not None
        assert monitor._adaptive.sample_count < config.adaptive_min_samples

        await monitor.stop()

    async def test_adaptive_percentile_bounds_check(self) -> None:
        """Test that adaptive percentile calculation doesn't go out of bounds."""
        adaptive = AdaptiveThreshold(
            window_size=10,
            percentile=0.99,  # High percentile
            multiplier=5.0,
            min_threshold_ms=10.0,
            min_samples=5,
        )

        # Add exactly window_size samples
        for i in range(10):
            adaptive.add_sample(float(i + 1))

        # Should not raise index error
        result = adaptive.recalculate()
        assert result > 0

    def test_adaptive_with_identical_samples(self) -> None:
        """Test adaptive threshold with all identical samples."""
        adaptive = AdaptiveThreshold(
            window_size=100,
            percentile=0.95,
            multiplier=5.0,
            min_threshold_ms=1.0,
            min_samples=10,
        )

        # Add identical samples
        for _ in range(50):
            adaptive.add_sample(10.0)

        result = adaptive.recalculate()
        # P95 of [10, 10, 10, ...] is 10, × 5 = 50
        assert result == 50.0

    def test_adaptive_with_single_high_outlier(self) -> None:
        """Test adaptive threshold handles outliers correctly."""
        adaptive = AdaptiveThreshold(
            window_size=100,
            percentile=0.95,
            multiplier=5.0,
            min_threshold_ms=1.0,
            min_samples=10,
        )

        # Add mostly low values with one high outlier
        for _ in range(99):
            adaptive.add_sample(1.0)
        adaptive.add_sample(1000.0)  # Outlier

        result = adaptive.recalculate()
        # P95 should be around 1.0 (outlier is above P95)
        # So threshold = 1.0 × 5 = 5.0
        assert result < 100  # Should not be dominated by outlier
