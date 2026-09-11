"""Sentinel monitor for detecting event loop blocking."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

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
        "_max_threshold_ms",
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
        max_threshold_ms: float,
    ) -> None:
        """Initialize the adaptive threshold.

        Args:
            window_size: Maximum samples in sliding window.
            percentile: Percentile (0.0-1.0) for baseline calculation.
            multiplier: Threshold = baseline × multiplier.
            min_threshold_ms: Minimum threshold value.
            min_samples: Minimum samples before adapting.
            max_threshold_ms: Hard ceiling; adaptation may never raise the
                threshold above it. Without a ceiling the censor gate widens
                with every raise and the threshold ratchets upward unboundedly.
        """
        self._samples: deque[float] = deque(maxlen=window_size)
        self._window_size = window_size
        self._percentile = percentile
        self._multiplier = multiplier
        self._min_threshold_ms = min_threshold_ms
        self._max_threshold_ms = max_threshold_ms
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

    def set_min_threshold(self, min_threshold_ms: float) -> None:
        """Update the floor, e.g. after calibration tightens the threshold.

        Until enough samples are collected, the current threshold follows the
        floor so a stale initial value cannot overwrite a calibrated one.
        """
        self._min_threshold_ms = min_threshold_ms
        if len(self._samples) < self._min_samples:
            self._current_threshold_ms = min_threshold_ms

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

        # Clamp to [floor, ceiling]: the ceiling stops the feedback loop where
        # a raised threshold widens the censor gate, which admits larger
        # samples, which raises the threshold again (measured compounding
        # 50 -> 241 -> 573ms on merely-noisy traffic without it)
        self._current_threshold_ms = min(
            max(
                baseline * self._multiplier,
                self._min_threshold_ms,
            ),
            self._max_threshold_ms,
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
        "_tick_start",
        "_tick_consumed",
        "_tick_reported_ms",
        "_metrics",
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
        # Set by _monitor_loop at the top of every tick; None until the loop
        # runs, which is what makes poll() a no-op on a monitor that has not
        # started or has been stopped
        self._tick_start: float | None = None
        self._tick_consumed = False
        self._tick_reported_ms = 0.0

        # Initialize adaptive threshold if enabled
        if config.adaptive_threshold:
            self._adaptive: AdaptiveThreshold | None = AdaptiveThreshold(
                window_size=config.adaptive_window_size,
                percentile=config.adaptive_percentile,
                multiplier=config.threshold_multiplier,
                min_threshold_ms=config.fallback_threshold_ms,
                min_samples=config.adaptive_min_samples,
                max_threshold_ms=config.fallback_threshold_ms,
            )
        else:
            self._adaptive = None
        self._last_adapt_time: float = 0.0
        # Safety cap: twice the ticks a full window can hold, so a stalled
        # prune (or a huge configured window) cannot grow the deque unboundedly
        history_cap = max(
            2, int(config.cumulative_window_ms / config.monitor_interval_ms) * 2
        )
        self._lag_history: deque[tuple[float, float]] = deque(maxlen=history_cap)

        # Optional Prometheus export. Imported lazily so metrics.py stays off
        # the import path of every app that does not ask for it.
        self._metrics: Any = None
        if config.prometheus_enabled:
            from fastapi_loopguard.metrics import create_metrics

            try:
                self._metrics = create_metrics()
            except Exception:
                # An explicitly enabled flag that cannot work must say so, but
                # a monitoring extra must never take the host app down. This
                # covers the missing extra and a duplicate registration on the
                # process-wide registry, which would otherwise fail startup.
                logger.exception(
                    "prometheus_enabled=True but metrics could not be set up; "
                    "metrics are disabled. Install the extra with: "
                    "pip install fastapi-loopguard[prometheus]"
                )
            else:
                self._metrics.set_threshold(self._threshold_ms / 1000.0)

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

        Runs a series of sleep calls and takes the MINIMUM observed lag as
        the baseline: it estimates the idle floor and is the sample least
        affected by concurrent traffic. The resulting threshold may tighten
        the fallback but never exceed it, so calibration running alongside a
        blocking app cannot raise the threshold and blind later detection.

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

        # Idle floor: the minimum lag is the least contaminated sample.
        # Clamped at 0: a timer may fire up to clock_resolution early, which
        # would otherwise report a (meaningless) negative baseline.
        self._baseline_ms = max(0.0, min(samples))

        # Floor at the sampling interval (lag below it cannot be resolved),
        # ceiling at the fallback (calibration may only ever lower it)
        self._threshold_ms = min(
            max(
                self._baseline_ms * self._config.threshold_multiplier,
                self._config.monitor_interval_ms,
            ),
            self._config.fallback_threshold_ms,
        )
        self._calibrated = True

        # Adaptive mode floors at the calibrated threshold, not the fallback;
        # otherwise its first update would undo the calibration
        if self._adaptive:
            self._adaptive.set_min_threshold(self._threshold_ms)

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
        # Start the adaptive clock now; a 0.0 start would fire the first
        # update on the very first iteration
        self._last_adapt_time = loop.time()

        while self._running:
            try:
                start = loop.time()
                # Published so poll() can measure this tick from the response
                # path before the sleep below ever resumes
                self._tick_start = start
                self._tick_consumed = False
                self._tick_reported_ms = 0.0
                await asyncio.sleep(interval_sec)
                elapsed = loop.time() - start

                lag_ms = (elapsed - interval_sec) * 1000.0

                # A tick poll() already reported is a blocking tick, not a
                # baseline sample, and its reported portion is spoken for
                reported_ms = self._tick_reported_ms if self._tick_consumed else 0.0
                residual_ms = max(0.0, lag_ms - reported_ms)

                # Adaptive threshold processing
                if self._adaptive:
                    # Censor the window: only sub-threshold samples inform
                    # the baseline. Admitting detected blocking makes the
                    # threshold chase the blocking upward until detection
                    # stops ("the worse the app gets, the less it reports").
                    # A tick poll() reported is blocking, not baseline.
                    if not self._tick_consumed and lag_ms < self._threshold_ms:
                        self._adaptive.add_sample(lag_ms)
                    now = loop.time()
                    if now - self._last_adapt_time >= adapt_interval_sec:
                        old_threshold = self._threshold_ms
                        new_threshold = self._adaptive.recalculate()
                        if new_threshold != old_threshold:
                            self._threshold_ms = new_threshold
                            if self._metrics is not None:
                                self._metrics.set_threshold(new_threshold / 1000.0)
                            logger.debug(
                                "Adaptive threshold updated: %.2fms -> %.2fms",
                                old_threshold,
                                new_threshold,
                            )
                        self._last_adapt_time = now

                # Report only the part of the tick poll() has not already
                # attributed. The two portions are disjoint, so no lag is
                # counted twice and no lag is dropped: a stall that began
                # before a response went out and continued after it is
                # reported as the polled portion plus this residual.
                triggered = False
                if residual_ms > self._threshold_ms:
                    self._handle_blocking(residual_ms)
                    triggered = True

                if self._config.cumulative_blocking_enabled:
                    self._check_cumulative(loop.time(), residual_ms, triggered)
            except Exception:
                logger.exception("Error in LoopGuard monitor loop")
                # Drop the tick marker before yielding: it points at a tick
                # that will never complete, and a poll() measuring against it
                # would report a stall that never happened
                self._tick_start = None
                # Wait a bit before retrying to avoid tight loop on persistent error
                try:
                    await asyncio.sleep(1.0)
                except RuntimeError:
                    # The event loop is closing; nothing left to monitor. Bail
                    # out instead of dying with an unretrieved exception.
                    return
            finally:
                if not self._running:
                    self._tick_start = None

    def _check_cumulative(self, now: float, lag_ms: float, triggered: bool) -> None:
        """Track baseline-corrected lag and fire once per saturated window.

        Only lag in excess of the calibrated baseline is admitted: raw lag
        includes platform timer jitter, and at defaults (~100 ticks per
        window) a ~2ms per-tick floor alone would sum past the cumulative
        threshold on a completely idle loop.
        """
        # A sample consumed by the single-shot detection is not re-counted
        # toward the cumulative window
        if not triggered:
            excess_ms = max(0.0, lag_ms - self._baseline_ms)
            self._lag_history.append((now, excess_ms))

        # Prune samples older than the window
        window_start = now - (self._config.cumulative_window_ms / 1000.0)
        while self._lag_history and self._lag_history[0][0] < window_start:
            self._lag_history.popleft()

        if triggered:
            return

        cumulative_lag = sum(lag for _, lag in self._lag_history)
        if cumulative_lag > self._config.cumulative_blocking_threshold_ms:
            self._handle_blocking(cumulative_lag, is_cumulative=True)
            # Clear history so one window reports at most once
            self._lag_history.clear()

    def poll(self) -> None:
        """Measure the current tick now instead of waiting for it to finish.

        A handler that blocks and then returns without awaiting leaves the
        monitor suspended in a sleep that has already expired: the lag is
        real, but nothing has resumed to measure it, so the response goes out
        reporting zero blocking. Callers on the response path invoke this
        while the request context is still registered.

        Synchronous on purpose — awaiting here would hand control to the
        monitor task and reintroduce the ordering dependency this removes.
        Reports at most once per tick; _monitor_loop skips a consumed tick.
        """
        if not self._running or self._tick_start is None or self._tick_consumed:
            return
        # A cancelled or finished monitor leaves _tick_start pointing at a
        # tick that will never complete. Measuring against it invents a stall
        # that grows with wall-clock time, which in strict mode is a 503 for
        # requests that did nothing wrong.
        if self._task is None or self._task.done():
            self._tick_start = None
            return

        interval_sec = self._config.monitor_interval_ms / 1000.0
        elapsed = asyncio.get_running_loop().time() - self._tick_start
        lag_ms = (elapsed - interval_sec) * 1000.0

        if lag_ms > self._threshold_ms:
            self._tick_consumed = True
            self._tick_reported_ms = lag_ms
            self._handle_blocking(lag_ms)

    def record_request(self, route: str, method: str) -> None:
        """Count a monitored request in Prometheus. No-op without the extra.

        Takes the matched route template, never the raw request path: the
        path is client-controlled, and an unbounded metric label is remote
        memory exhaustion.
        """
        if self._metrics is not None:
            self._metrics.record_request(route, method)

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

        if self._metrics is not None:
            # One observation per event, like the log line below: per-context
            # metric work is O(N) on the loop thread right after a stall
            self._metrics.record_blocking(
                lag_ms / 1000.0,
                "cumulative" if is_cumulative else "single",
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
            ctx.record_blocking(lag_ms, cumulative=is_cumulative)

            if self._on_blocking:
                self._on_blocking(lag_ms, ctx.path, ctx.method)

        # One summary line per event, not one per context: this runs on the
        # loop thread right after a stall, and O(N) log formatting under
        # concurrency would pile more work onto an already-late loop
        if self._config.log_blocking_events:
            logger.warning(
                "%s for %.2fms across %d in-flight request(s): %s",
                msg_type,
                lag_ms,
                len(active_contexts),
                ",".join(ctx.request_id for ctx in active_contexts),
            )

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

        # Mark running before the (blocking) calibration so a stop() issued
        # while calibration runs is observed and vetoes the loop start
        self._running = True
        try:
            if not self._calibrated:
                await self.calibrate()
        except BaseException:
            self._running = False
            raise

        if not self._running:
            # stop() ran during calibration
            return

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
        # Drop the tick marker so a later poll() cannot measure against a
        # timestamp from before this stop
        self._tick_start = None

        # Cancel calibration if still running
        calibration_task = self._calibration_task
        self._calibration_task = None
        if calibration_task and not calibration_task.done():
            await self._cancel_and_wait(calibration_task)

        # Cancel monitoring task
        task = self._task
        self._task = None
        if task:
            await self._cancel_and_wait(task)

        logger.info("LoopGuard sentinel stopped")

    @staticmethod
    async def _cancel_and_wait(task: asyncio.Task[None]) -> None:
        """Cancel a task and await it without eating our own cancellation.

        A plain suppress(CancelledError) around the await also swallows a
        cancellation aimed at the *calling* task — stop() runs inside request
        finally blocks, so that would turn a client disconnect or server
        shutdown into a request that ignores its own cancellation. Re-raise
        when the current task has a cancellation pending.
        """
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
