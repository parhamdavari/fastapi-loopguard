"""Prometheus metrics for LoopGuard.

Supports custom registries for test isolation via the registry parameter.
"""

from __future__ import annotations

from typing import Any


def _get_prometheus() -> tuple[type, type, type, Any] | None:
    """Try to import prometheus_client with registry support."""
    try:
        from prometheus_client import REGISTRY, Counter, Gauge, Histogram

        return Counter, Histogram, Gauge, REGISTRY
    except ImportError:
        return None


class LoopGuardMetrics:
    """Prometheus metrics for loop-lag monitoring.

    Metrics exposed:
        - loopguard_blocking_total: Counter of blocking events
        - loopguard_lag_seconds: Histogram of lag durations
        - loopguard_requests_monitored_total: Counter of monitored requests
        - loopguard_threshold_seconds: Gauge of current threshold

    Supports custom registries for test isolation.
    """

    __slots__ = (
        "_prefix",
        "_registry",
        "_blocking_total",
        "_lag_histogram",
        "_requests_total",
        "_threshold_gauge",
    )

    def __init__(
        self,
        prefix: str = "loopguard",
        registry: Any = None,
    ) -> None:
        """Initialize metrics.

        Args:
            prefix: Prefix for all metric names.
            registry: Prometheus registry to use. If None, uses default REGISTRY.

        Raises:
            RuntimeError: If prometheus_client is not installed.
        """
        prometheus = _get_prometheus()
        if prometheus is None:
            raise RuntimeError(
                "prometheus_client is not installed. "
                "Install with: pip install fastapi-loopguard[prometheus]"
            )

        counter_cls, histogram_cls, gauge_cls, default_registry = prometheus
        self._prefix = prefix
        self._registry = registry if registry is not None else default_registry

        # Create metrics with explicit registry
        self._blocking_total: Any = counter_cls(
            f"{prefix}_blocking_total",
            "Total number of blocking events detected",
            ["path", "method"],
            registry=self._registry,
        )

        self._lag_histogram: Any = histogram_cls(
            f"{prefix}_lag_seconds",
            "Histogram of event loop lag durations",
            ["path", "method"],
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=self._registry,
        )

        self._requests_total: Any = counter_cls(
            f"{prefix}_requests_monitored_total",
            "Total number of requests monitored",
            ["path", "method"],
            registry=self._registry,
        )

        self._threshold_gauge: Any = gauge_cls(
            f"{prefix}_threshold_seconds",
            "Current blocking detection threshold",
            registry=self._registry,
        )

    @property
    def prefix(self) -> str:
        """The metric name prefix."""
        return self._prefix

    def record_blocking(
        self,
        lag_seconds: float,
        path: str | None = None,
        method: str | None = None,
    ) -> None:
        """Record a blocking event.

        Args:
            lag_seconds: The blocking duration in seconds.
            path: The request path.
            method: The HTTP method.
        """
        labels = {
            "path": path or "unknown",
            "method": method or "unknown",
        }
        self._blocking_total.labels(**labels).inc()
        self._lag_histogram.labels(**labels).observe(lag_seconds)

    def record_request(self, path: str, method: str) -> None:
        """Record a monitored request.

        Args:
            path: The request path.
            method: The HTTP method.
        """
        self._requests_total.labels(path=path, method=method).inc()

    def set_threshold(self, threshold_seconds: float) -> None:
        """Set the current threshold gauge.

        Args:
            threshold_seconds: The current threshold in seconds.
        """
        self._threshold_gauge.set(threshold_seconds)


# Instance management - use regular dict since __slots__ prevents weak refs
_instances: dict[str, LoopGuardMetrics] = {}


def get_metrics(prefix: str = "loopguard") -> LoopGuardMetrics | None:
    """Get existing metrics instance by prefix.

    Args:
        prefix: The prefix used when creating the metrics.

    Returns:
        The metrics instance, or None if not found.
    """
    return _instances.get(prefix)


def create_metrics(
    prefix: str = "loopguard",
    registry: Any = None,
) -> LoopGuardMetrics:
    """Create or get a metrics instance.

    For testing, pass a custom registry to avoid pollution.

    Args:
        prefix: Prefix for all metric names.
        registry: Optional Prometheus registry for test isolation.

    Returns:
        The metrics instance.
    """
    # Use registry id to allow different registries with same prefix
    key = f"{prefix}:{id(registry)}"
    if key not in _instances:
        metrics = LoopGuardMetrics(prefix, registry)
        _instances[key] = metrics
    return _instances[key]


def reset_metrics() -> None:
    """Reset all metrics instances.

    For testing only - clears the instance cache.
    """
    _instances.clear()


# Backward compatibility aliases
_metrics_instance: LoopGuardMetrics | None = None


def init_metrics(prefix: str = "loopguard") -> LoopGuardMetrics:
    """Initialize the global metrics instance.

    Deprecated: Use create_metrics() for new code.

    Args:
        prefix: Prefix for all metric names.

    Returns:
        The initialized metrics instance.
    """
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = create_metrics(prefix)
    return _metrics_instance
