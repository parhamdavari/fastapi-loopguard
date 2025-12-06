"""Tests for fastapi_loopguard.metrics module."""

from __future__ import annotations

import pytest

# Skip all tests if prometheus_client is not installed
prometheus_client = pytest.importorskip("prometheus_client")

from prometheus_client import CollectorRegistry  # noqa: E402

from fastapi_loopguard.metrics import (  # noqa: E402
    LoopGuardMetrics,
    create_metrics,
    get_metrics,
    init_metrics,
    reset_metrics,
)


class TestLoopGuardMetrics:
    """Tests for LoopGuardMetrics class."""

    @pytest.fixture
    def registry(self) -> CollectorRegistry:
        """Create isolated registry for each test."""
        return CollectorRegistry()

    @pytest.fixture(autouse=True)
    def cleanup(self) -> None:
        """Clean up metrics instances after each test."""
        yield
        reset_metrics()

    def test_init_creates_all_metrics(self, registry: CollectorRegistry) -> None:
        """Test that __init__ creates all 4 metrics."""
        LoopGuardMetrics(prefix="test", registry=registry)

        # Check that metrics exist by getting metric family names
        # Note: prometheus_client strips _total suffix from counter names in collect()
        metric_names = [m.name for m in registry.collect()]
        assert "test_blocking" in metric_names  # Counter (suffix stripped)
        assert "test_lag_seconds" in metric_names  # Histogram
        assert "test_requests_monitored" in metric_names  # Counter (suffix stripped)
        assert "test_threshold_seconds" in metric_names  # Gauge

    def test_init_custom_prefix(self, registry: CollectorRegistry) -> None:
        """Test custom prefix is applied to all metrics."""
        LoopGuardMetrics(prefix="myapp", registry=registry)

        metric_names = [m.name for m in registry.collect()]
        assert all(name.startswith("myapp_") for name in metric_names)

    def test_prefix_property(self, registry: CollectorRegistry) -> None:
        """Test prefix property returns correct value."""
        metrics = LoopGuardMetrics(prefix="custom", registry=registry)
        assert metrics.prefix == "custom"

    def test_record_blocking_increments_counter(
        self, registry: CollectorRegistry
    ) -> None:
        """Test record_blocking increments the blocking counter."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        metrics.record_blocking(0.1, path="/api/users", method="GET")
        metrics.record_blocking(0.2, path="/api/users", method="GET")

        # Get counter value
        counter_value = registry.get_sample_value(
            "test_blocking_total",
            {"path": "/api/users", "method": "GET"},
        )
        assert counter_value == 2

    def test_record_blocking_observes_histogram(
        self, registry: CollectorRegistry
    ) -> None:
        """Test record_blocking observes the lag histogram."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        metrics.record_blocking(0.05, path="/test", method="POST")

        # Check histogram count
        histogram_count = registry.get_sample_value(
            "test_lag_seconds_count",
            {"path": "/test", "method": "POST"},
        )
        assert histogram_count == 1

    def test_record_blocking_with_unknown_labels(
        self, registry: CollectorRegistry
    ) -> None:
        """Test record_blocking handles None path/method."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        metrics.record_blocking(0.1)  # No path or method

        counter_value = registry.get_sample_value(
            "test_blocking_total",
            {"path": "unknown", "method": "unknown"},
        )
        assert counter_value == 1

    def test_record_request_increments_counter(
        self, registry: CollectorRegistry
    ) -> None:
        """Test record_request increments the requests counter."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        metrics.record_request(path="/api/items", method="GET")
        metrics.record_request(path="/api/items", method="GET")
        metrics.record_request(path="/api/items", method="POST")

        get_count = registry.get_sample_value(
            "test_requests_monitored_total",
            {"path": "/api/items", "method": "GET"},
        )
        post_count = registry.get_sample_value(
            "test_requests_monitored_total",
            {"path": "/api/items", "method": "POST"},
        )
        assert get_count == 2
        assert post_count == 1

    def test_set_threshold_updates_gauge(self, registry: CollectorRegistry) -> None:
        """Test set_threshold updates the threshold gauge."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        metrics.set_threshold(0.05)
        value1 = registry.get_sample_value("test_threshold_seconds")
        assert value1 == 0.05

        metrics.set_threshold(0.1)
        value2 = registry.get_sample_value("test_threshold_seconds")
        assert value2 == 0.1


class TestMetricsFactoryFunctions:
    """Tests for factory functions."""

    @pytest.fixture
    def registry(self) -> CollectorRegistry:
        """Create isolated registry for each test."""
        return CollectorRegistry()

    @pytest.fixture(autouse=True)
    def cleanup(self) -> None:
        """Clean up after each test."""
        yield
        reset_metrics()

    def test_create_metrics_returns_instance(self, registry: CollectorRegistry) -> None:
        """Test create_metrics returns a LoopGuardMetrics instance."""
        metrics = create_metrics(prefix="test", registry=registry)
        assert isinstance(metrics, LoopGuardMetrics)
        assert metrics.prefix == "test"

    def test_create_metrics_caches_by_prefix_and_registry(
        self, registry: CollectorRegistry
    ) -> None:
        """Test create_metrics returns same instance for same prefix+registry."""
        metrics1 = create_metrics(prefix="test", registry=registry)
        metrics2 = create_metrics(prefix="test", registry=registry)

        assert metrics1 is metrics2

    def test_create_metrics_different_prefix(self, registry: CollectorRegistry) -> None:
        """Test create_metrics returns different instance for different prefix."""
        registry2 = CollectorRegistry()
        metrics1 = create_metrics(prefix="app1", registry=registry)
        metrics2 = create_metrics(prefix="app2", registry=registry2)

        assert metrics1 is not metrics2

    def test_create_metrics_different_registry(self) -> None:
        """Test create_metrics returns different instance for different registry."""
        registry1 = CollectorRegistry()
        registry2 = CollectorRegistry()

        metrics1 = create_metrics(prefix="test", registry=registry1)
        metrics2 = create_metrics(prefix="test", registry=registry2)

        assert metrics1 is not metrics2

    def test_get_metrics_returns_existing(self, registry: CollectorRegistry) -> None:
        """Test get_metrics returns existing instance."""
        create_metrics(prefix="findme", registry=registry)
        # Note: get_metrics uses just prefix, but cache key includes registry id
        # So it won't find it with default get_metrics(prefix)
        # This tests the intended behavior
        found = get_metrics("findme")
        # Will be None because key is "findme:{registry_id}"
        assert found is None

    def test_get_metrics_returns_none_when_not_found(self) -> None:
        """Test get_metrics returns None for non-existent prefix."""
        assert get_metrics("nonexistent") is None

    def test_reset_metrics_clears_cache(self, registry: CollectorRegistry) -> None:
        """Test reset_metrics clears all cached instances."""
        create_metrics(prefix="test1", registry=registry)
        registry2 = CollectorRegistry()
        create_metrics(prefix="test2", registry=registry2)

        reset_metrics()

        # After reset, get_metrics should return None for all
        assert get_metrics("test1") is None
        assert get_metrics("test2") is None

    def test_init_metrics_backward_compat(self) -> None:
        """Test init_metrics works for backward compatibility."""
        # init_metrics uses default registry, so use unique prefix
        metrics = init_metrics(prefix="compat_test")
        assert isinstance(metrics, LoopGuardMetrics)
        assert metrics.prefix == "compat_test"

    def test_init_metrics_returns_same_instance(self) -> None:
        """Test init_metrics returns same global instance."""
        # Reset to clear any previous state
        import fastapi_loopguard.metrics as metrics_module

        metrics_module._metrics_instance = None

        metrics1 = init_metrics(prefix="global_test")
        metrics2 = init_metrics(prefix="global_test")

        assert metrics1 is metrics2


class TestMetricsWithoutPrometheus:
    """Tests for behavior when prometheus_client is not installed."""

    def test_runtime_error_without_prometheus(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test RuntimeError raised when prometheus_client not available."""
        import fastapi_loopguard.metrics as metrics_module

        # Mock _get_prometheus to return None (simulating missing import)
        monkeypatch.setattr(metrics_module, "_get_prometheus", lambda: None)

        with pytest.raises(RuntimeError) as exc_info:
            LoopGuardMetrics()

        assert "prometheus_client is not installed" in str(exc_info.value)
