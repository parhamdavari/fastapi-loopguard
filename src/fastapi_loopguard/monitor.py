"""Sentinel monitor for detecting event loop blocking."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING

from .context import get_active_requests

if TYPE_CHECKING:
    from .config import LoopGuardConfig

logger = logging.getLogger("fastapi_loopguard")


class AdaptiveThreshold:
    """Adaptive threshold based on sliding window of recent lag samples.

    Uses percentile-based calculation to automatically adjust the blocking
    threshold based on observed latency patterns. This reduces false positives
    in high-concurrency environments.
    """

    __slots__ = (
        "_samples",
        "_window_size",
        "_percentile",
        "_multiplier",
        "_min_threshold_ms",
        "_min_samples",
        "_current_threshold_ms",
    )

    def __init__(
        self,
        window_size: int,
        percentile: float,
        multiplier: float,
        min_threshold_ms: float,
        min_samples: int,
    ) -> None:
        """Initialize the adaptive threshold.

        Args:
            window_size: Maximum samples in sliding window.
            percentile: Percentile (0.0-1.0) for baseline calculation.
            multiplier: Threshold = baseline × multiplier.
            min_threshold_ms: Minimum threshold value.
            min_samples: Minimum samples before adapting.
        """
        self._samples: deque[float] = deque(maxlen=window_size)
        self._window_size = window_size
        self._percentile = percentile
        self._multiplier = multiplier
        self._min_threshold_ms = min_threshold_ms
        self._min_samples = min_samples
        self._current_threshold_ms = min_threshold_ms

    @property
    def current_threshold_ms(self) -> float:
        """Current calculated threshold in milliseconds."""
        return self._current_threshold_ms

    @property
    def sample_count(self) -> int:
        """Number of samples currently in the window."""
        return len(self._samples)

    def add_sample(self, lag_ms: float) -> None:
        """Add a new lag sample to the sliding window.

        Args:
            lag_ms: The lag value in milliseconds.
        """
        self._samples.append(lag_ms)

    def recalculate(self) -> float:
        """Recalculate the threshold based on current samples.

        Returns:
            The new threshold in milliseconds.
        """
        if len(self._samples) < self._min_samples:
            return self._current_threshold_ms

        sorted_samples = sorted(self._samples)
        idx = int(len(sorted_samples) * self._percentile)
        idx = min(idx, len(sorted_samples) - 1)  # Bounds check
        baseline = sorted_samples[idx]

        self._current_threshold_ms = max(
            baseline * self._multiplier,
            self._min_threshold_ms,
        )
        return self._current_threshold_ms


class SentinelMonitor:
    """Background task that monitors event loop health.

    The sentinel works by scheduling short sleeps and measuring how long
    they actually take. If the actual time significantly exceeds the
    expected time, it indicates the event loop was blocked.

    When blocking is detected, the monitor iterates ALL active requests
    and attributes the lag to each of them, since we cannot determine
    which specific request caused the blocking.

    Improvements in v0.2.0:
    - Background calibration: First request is not blocked
    - Multi-context attribution: All active requests are notified
    - Named tasks: Easier debugging
    - Clean shutdown: Proper task cancellation
    """

    __slots__ = (
        "_config",
        "_on_blocking",
        "_task",
        "_calibration_task",
        "_running",
        "_baseline_ms",
        "_threshold_ms",
        "_calibrated",
        "_adaptive",
        "_last_adapt_time",
        "_lag_history",
    )

    def __init__(
        self,
        config: LoopGuardConfig,
        on_blocking: Callable[[float, str | None, str | None], None] | None = None,
    ) -> None:
        """Initialize the sentinel monitor.

        Args:
            config: The LoopGuard configuration.
            on_blocking: Optional callback called when blocking is detected.
                         Receives (lag_ms, path, method).
        """
        self._config = config
        self._on_blocking = on_blocking
        self._task: asyncio.Task[None] | None = None
        self._calibration_task: asyncio.Task[None] | None = None
        self._running = False
        self._baseline_ms: float = 0.0
        self._threshold_ms: float = config.fallback_threshold_ms
        self._calibrated = False

        # Initialize adaptive threshold if enabled
        if config.adaptive_threshold:
            self._adaptive: AdaptiveThreshold | None = AdaptiveThreshold(
                window_size=config.adaptive_window_size,
                percentile=config.adaptive_percentile,
                multiplier=config.threshold_multiplier,
                min_threshold_ms=config.fallback_threshold_ms,
                min_samples=config.adaptive_min_samples,
            )
        else:
            self._adaptive = None
        self._last_adapt_time: float = 0.0
        self._lag_history: deque[tuple[float, float]] = deque()

    @property
    def is_running(self) -> bool:
        """Whether the monitor is currently running."""
        return self._running

    @property
    def is_calibrated(self) -> bool:
        """Whether calibration has completed."""
        return self._calibrated

    @property
    def threshold_ms(self) -> float:
        """Current blocking threshold in milliseconds."""
        return self._threshold_ms

    @property
    def baseline_ms(self) -> float:
        """Calibrated baseline latency in milliseconds."""
        return self._baseline_ms

    async def calibrate(self) -> float:
        """Calibrate the baseline event loop latency.

        Runs a series of sleep calls to measure the typical latency
        of yielding to the event loop under normal conditions.

        Returns:
            The calibrated threshold in milliseconds.
        """
        loop = asyncio.get_running_loop()
        interval_sec = self._config.monitor_interval_ms / 1000.0
        samples: list[float] = []

        for _ in range(self._config.calibration_iterations):
            start = loop.time()
            await asyncio.sleep(interval_sec)
            elapsed = loop.time() - start
            lag_ms = (elapsed - interval_sec) * 1000.0
            samples.append(lag_ms)

        # Use P75 as baseline to be robust against outliers
        samples.sort()
        p75_index = int(len(samples) * 0.75)
        self._baseline_ms = samples[p75_index]

        # Calculate threshold
        self._threshold_ms = max(
            self._baseline_ms * self._config.threshold_multiplier,
            self._config.fallback_threshold_ms,
        )
        self._calibrated = True

        logger.info(
            "LoopGuard calibrated: baseline=%.2fms, threshold=%.2fms",
            self._baseline_ms,
            self._threshold_ms,
        )

        return self._threshold_ms

    async def _background_calibrate(self) -> None:
        """Run calibration in background without blocking requests."""
        try:
            await self.calibrate()
        except asyncio.CancelledError:
            logger.debug("LoopGuard calibration cancelled during shutdown")
        except Exception:
            logger.exception(
                "LoopGuard calibration failed, using fallback threshold=%.2fms",
                self._threshold_ms,
            )

    async def _monitor_loop(self) -> None:
        """The main monitoring loop."""
        loop = asyncio.get_running_loop()
        interval_sec = self._config.monitor_interval_ms / 1000.0
        adapt_interval_sec = self._config.adaptive_update_interval_ms / 1000.0

        while self._running:
            try:
                start = loop.time()
                await asyncio.sleep(interval_sec)
                elapsed = loop.time() - start

                lag_ms = (elapsed - interval_sec) * 1000.0

                # Adaptive threshold processing
                if self._adaptive:
                    self._adaptive.add_sample(lag_ms)
                    now = loop.time()
                    if now - self._last_adapt_time >= adapt_interval_sec:
                        old_threshold = self._threshold_ms
                        new_threshold = self._adaptive.recalculate()
                        if new_threshold != old_threshold:
                            self._threshold_ms = new_threshold
                            logger.debug(
                                "Adaptive threshold updated: %.2fms -> %.2fms",
                                old_threshold,
                                new_threshold,
                            )
                        self._last_adapt_time = now

                triggered = False
                if lag_ms > self._threshold_ms:
                    self._handle_blocking(lag_ms)
                    triggered = True

                # Cumulative blocking detection
                if self._config.cumulative_blocking_enabled:
                    now = loop.time()
                    self._lag_history.append((now, lag_ms))

                    # Prune old samples
                    window_start = now - (self._config.cumulative_window_ms / 1000.0)
                    while self._lag_history and self._lag_history[0][0] < window_start:
                        self._lag_history.popleft()

                    # Calculate total lag in window
                    cumulative_lag = sum(lag for _, lag in self._lag_history)

                    if (
                        cumulative_lag > self._config.cumulative_blocking_threshold_ms
                        and not triggered
                    ):
                        self._handle_blocking(cumulative_lag, is_cumulative=True)
                        # Clear history to avoid repeated triggering for the same window
                        self._lag_history.clear()
            except Exception:
                logger.exception("Error in LoopGuard monitor loop")
                # Wait a bit before retrying to avoid tight loop on persistent error
                await asyncio.sleep(1.0)

    def _handle_blocking(self, lag_ms: float, is_cumulative: bool = False) -> None:
        """Handle a detected blocking event.

        Attributes blocking to ALL currently active requests, since we
        cannot determine which specific request caused the blocking.
        """
        # Get all active request contexts
        active_contexts = list(get_active_requests())

        msg_type = (
            "Cumulative event loop blocking" if is_cumulative else "Event loop blocked"
        )

        if not active_contexts:
            # No active requests - log as background blocking
            if self._config.log_blocking_events:
                logger.warning(
                    "%s for %.2fms (no active request)",
                    msg_type,
                    lag_ms,
                )
            if self._on_blocking:
                self._on_blocking(lag_ms, None, None)
            return

        # Attribute to all active requests
        for ctx in active_contexts:
            ctx.record_blocking(lag_ms)

            if self._config.log_blocking_events:
                logger.warning(
                    "%s for %.2fms during %s %s (request_id=%s)",
                    msg_type,
                    lag_ms,
                    ctx.method,
                    ctx.path,
                    ctx.request_id,
                )

            if self._on_blocking:
                self._on_blocking(lag_ms, ctx.path, ctx.method)

    async def start_with_background_calibration(self) -> None:
        """Start monitoring immediately with background calibration.

        Uses fallback threshold initially, calibrates in background.
        First request is not blocked waiting for calibration.
        """
        if self._running:
            return

        self._running = True

        # Start monitoring immediately with fallback threshold
        self._task = asyncio.create_task(
            self._monitor_loop(),
            name="loopguard-monitor",
        )

        # Calibrate in background
        self._calibration_task = asyncio.create_task(
            self._background_calibrate(),
            name="loopguard-calibrate",
        )

        logger.info(
            "LoopGuard started with fallback threshold=%.2fms, "
            "calibrating in background",
            self._threshold_ms,
        )

    async def start(self) -> None:
        """Start the sentinel monitor.

        Performs calibration first (blocking), then starts the monitoring loop.
        For non-blocking startup, use start_with_background_calibration().
        """
        if self._running:
            return

        if not self._calibrated:
            await self.calibrate()

        self._running = True
        self._task = asyncio.create_task(
            self._monitor_loop(),
            name="loopguard-monitor",
        )
        logger.info("LoopGuard sentinel started")

    async def stop(self) -> None:
        """Stop the sentinel monitor gracefully."""
        if not self._running:
            return

        self._running = False

        # Cancel calibration if still running
        if self._calibration_task and not self._calibration_task.done():
            self._calibration_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._calibration_task
            self._calibration_task = None

        # Cancel monitoring task
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        logger.info("LoopGuard sentinel stopped")
