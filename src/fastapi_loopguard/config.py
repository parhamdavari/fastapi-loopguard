"""Configuration for LoopGuard middleware."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LoopGuardConfig:
    """Configuration for the LoopGuard middleware.

    Attributes:
        enabled: Whether monitoring is active. Set False to disable entirely.
        monitor_interval_ms: How often the sentinel checks for blocking (milliseconds).
            Default 10ms detects blocking >50ms with ~0.002% CPU overhead.
            The sleep is non-blocking (cooperative), so it doesn't affect throughput.
        threshold_multiplier: Blocking detected when lag > baseline × multiplier.
        calibration_iterations: Number of samples during startup calibration.
        fallback_threshold_ms: Used if calibration produces unreliable results.
        dev_mode: Enable response headers with lag information.
        log_blocking_events: Log when blocking is detected.
        prometheus_enabled: Expose Prometheus metrics.
        adaptive_threshold: Enable adaptive threshold based on sliding window.
        adaptive_window_size: Number of samples in the sliding window.
        adaptive_percentile: Percentile (0.0-1.0) for baseline calculation.
        adaptive_min_samples: Minimum samples before adaptive mode activates.
        adaptive_update_interval_ms: How often to recalculate threshold.
    """

    enabled: bool = True
    monitor_interval_ms: float = 10.0
    threshold_multiplier: float = 5.0
    calibration_iterations: int = 100
    fallback_threshold_ms: float = 50.0
    dev_mode: bool = False
    log_blocking_events: bool = True
    prometheus_enabled: bool = False

    # Adaptive threshold settings
    adaptive_threshold: bool = False
    adaptive_window_size: int = 1000
    adaptive_percentile: float = 0.95
    adaptive_min_samples: int = 100
    adaptive_update_interval_ms: float = 1000.0

    # Cumulative blocking detection
    cumulative_blocking_enabled: bool = False
    cumulative_blocking_threshold_ms: float = 200.0
    cumulative_window_ms: float = 1000.0

    # Internal: paths to exclude from monitoring (e.g., health checks)
    exclude_paths: frozenset[str] = field(
        default_factory=lambda: frozenset({"/health", "/healthz", "/ready", "/metrics"})
    )

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.monitor_interval_ms <= 0:
            raise ValueError("monitor_interval_ms must be positive")
        if self.threshold_multiplier <= 1:
            raise ValueError("threshold_multiplier must be greater than 1")
        if self.calibration_iterations < 10:
            raise ValueError("calibration_iterations must be at least 10")
        if self.fallback_threshold_ms <= 0:
            raise ValueError("fallback_threshold_ms must be positive")
        # Adaptive threshold validation
        if self.adaptive_window_size < 100:
            raise ValueError("adaptive_window_size must be at least 100")
        if not 0.5 <= self.adaptive_percentile <= 0.99:
            raise ValueError("adaptive_percentile must be between 0.5 and 0.99")
        if self.adaptive_min_samples < 10:
            raise ValueError("adaptive_min_samples must be at least 10")
        if self.adaptive_min_samples > self.adaptive_window_size:
            raise ValueError(
                "adaptive_min_samples cannot be greater than adaptive_window_size"
            )
        if self.adaptive_update_interval_ms <= 0:
            raise ValueError("adaptive_update_interval_ms must be positive")
        # Cumulative blocking validation
        if self.cumulative_blocking_threshold_ms <= 0:
            raise ValueError("cumulative_blocking_threshold_ms must be positive")
        if self.cumulative_window_ms <= 0:
            raise ValueError("cumulative_window_ms must be positive")
        if (
            self.cumulative_blocking_enabled
            and self.cumulative_window_ms < self.monitor_interval_ms
        ):
            raise ValueError(
                "cumulative_window_ms cannot be less than monitor_interval_ms"
            )
