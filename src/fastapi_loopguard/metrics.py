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


# Every label value that reaches a Prometheus client mints a child metric that
# is never evicted, so an unbounded label is remote memory exhaustion. Requests
# are labelled by route template, which the app's route table bounds, and this
# cap is the backstop for anything that slips past that.
MAX_LABEL_PAIRS = 200
OVERFLOW_LABEL = "other"

_STANDARD_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"}
)


class LoopGuardMetrics:
    """Prometheus metrics for loop-lag monitoring.

    Metrics exposed:
        - loopguard_blocking_total: Counter of blocking events, by event_type
        - loopguard_lag_seconds: Histogram of lag durations, by event_type
        - loopguard_requests_monitored_total: Counter of monitored requests,
          by route template and method
        - loopguard_threshold_seconds: Gauge of current threshold

    Blocking carries no route label on purpose. The sentinel measures loop
    lag, not call stacks, so it cannot say which endpoint blocked — a route
    label there would read as an accusation the data does not support.

    Supports custom registries for test isolation.
    """

    __slots__ = (
        "_prefix",
        "_registry",
        "_blocking_total",
        "_lag_histogram",
        "_requests_total",
        "_threshold_gauge",
        "_seen_labels",
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
        self._seen_labels: set[tuple[str, str]] = set()

        self._blocking_total: Any = counter_cls(
            f"{prefix}_blocking_total",
            "Total number of blocking events detected",
            ["event_type"],
            registry=self._registry,
        )

        self._lag_histogram: Any = histogram_cls(
            f"{prefix}_lag_seconds",
            "Histogram of event loop lag durations",
            ["event_type"],
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            registry=self._registry,
        )

        self._requests_total: Any = counter_cls(
            f"{prefix}_requests_monitored_total",
            "Total number of requests monitored",
            ["route", "method"],
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

    def _bounded(self, route: str, method: str) -> tuple[str, str]:
        """Clamp a label pair to a fixed budget of distinct values."""
        upper = method.upper()
        safe_method = upper if upper in _STANDARD_METHODS else OVERFLOW_LABEL
        pair = (route, safe_method)
        if pair in self._seen_labels:
            return pair
        if len(self._seen_labels) >= MAX_LABEL_PAIRS:
            return (OVERFLOW_LABEL, OVERFLOW_LABEL)
        self._seen_labels.add(pair)
        return pair

    def record_blocking(self, lag_seconds: float, event_type: str = "single") -> None:
        """Record one blocking event.

        Called once per event, not once per in-flight request: this runs on
        the loop thread immediately after a stall, where per-request work
        would pile more delay onto an already-late loop.

        Args:
            lag_seconds: The measured lag in seconds.
            event_type: "single" for one over-threshold sample, "cumulative"
                for a saturated window. They are different quantities, so a
                percentile over the mix would be meaningless without this.
        """
        self._blocking_total.labels(event_type=event_type).inc()
        self._lag_histogram.labels(event_type=event_type).observe(lag_seconds)

    def record_request(self, route: str, method: str) -> None:
        """Record a monitored request.

        Args:
            route: The matched route template (never the raw request path —
                that is client-controlled and unbounded).
            method: The HTTP method. Non-standard verbs collapse to "other".
        """
        safe_route, safe_method = self._bounded(route, method)
        self._requests_total.labels(route=safe_route, method=safe_method).inc()

    def set_threshold(self, threshold_seconds: float) -> None:
        """Set the current threshold gauge.

        Args:
            threshold_seconds: The current threshold in seconds.
        """
        self._threshold_gauge.set(threshold_seconds)


# Instance management - use regular dict since __slots__ prevents weak refs
_instances: dict[str, LoopGuardMetrics] = {}


def _instance_key(prefix: str, registry: Any) -> str:
    """Cache key for an instance. Registry identity is part of it so two
    registries can share a prefix without colliding.

    id() is only safe because _instances pins every registry alive. After
    reset_metrics() a registry can be collected and a new one can land on the
    same address, so a lookup then could return a stale instance.
    """
    return f"{prefix}:{id(registry)}"


def get_metrics(
    prefix: str = "loopguard",
    registry: Any = None,
) -> LoopGuardMetrics | None:
    """Get an existing metrics instance.

    Args:
        prefix: The prefix used when creating the metrics.
        registry: The registry it was created with. Must match the
            create_metrics() call, or the lookup misses.

    Returns:
        The metrics instance, or None if not found.
    """
    return _instances.get(_instance_key(prefix, registry))


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
    key = _instance_key(prefix, registry)
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
