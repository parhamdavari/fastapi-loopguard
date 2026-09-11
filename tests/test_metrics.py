"""Tests for fastapi_loopguard.metrics module."""

from __future__ import annotations

import pytest

# Skip all tests if prometheus_client is not installed
prometheus_client = pytest.importorskip("prometheus_client")

import asyncio  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from prometheus_client import CollectorRegistry  # noqa: E402

from fastapi_loopguard import (  # noqa: E402
    LoopGuardConfig,
    LoopGuardMiddleware,
    SentinelMonitor,
)
from fastapi_loopguard.context import get_registry  # noqa: E402
from fastapi_loopguard.metrics import (  # noqa: E402
    MAX_LABEL_PAIRS,
    OVERFLOW_LABEL,
    LoopGuardMetrics,
    create_metrics,
    get_metrics,
    init_metrics,
    reset_metrics,
)

if TYPE_CHECKING:
    from collections.abc import Generator


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

        metrics.record_blocking(0.1)
        metrics.record_blocking(0.2)

        counter_value = registry.get_sample_value(
            "test_blocking_total",
            {"event_type": "single"},
        )
        assert counter_value == 2

    def test_record_blocking_observes_histogram(
        self, registry: CollectorRegistry
    ) -> None:
        """Test record_blocking observes the lag histogram."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        metrics.record_blocking(0.05)

        histogram_count = registry.get_sample_value(
            "test_lag_seconds_count",
            {"event_type": "single"},
        )
        assert histogram_count == 1

    def test_cumulative_events_are_a_separate_series(
        self, registry: CollectorRegistry
    ) -> None:
        """A window sum is a different quantity from one stall's duration."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        metrics.record_blocking(0.05)
        metrics.record_blocking(0.4, "cumulative")

        assert (
            registry.get_sample_value("test_blocking_total", {"event_type": "single"})
            == 1
        )
        assert (
            registry.get_sample_value(
                "test_blocking_total", {"event_type": "cumulative"}
            )
            == 1
        )

    def test_record_request_increments_counter(
        self, registry: CollectorRegistry
    ) -> None:
        """Test record_request increments the requests counter."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        metrics.record_request("/api/items", "GET")
        metrics.record_request("/api/items", "GET")
        metrics.record_request("/api/items", "POST")

        get_count = registry.get_sample_value(
            "test_requests_monitored_total",
            {"route": "/api/items", "method": "GET"},
        )
        post_count = registry.get_sample_value(
            "test_requests_monitored_total",
            {"route": "/api/items", "method": "POST"},
        )
        assert get_count == 2
        assert post_count == 1

    def test_label_pairs_are_capped(self, registry: CollectorRegistry) -> None:
        """Distinct label values cannot grow without bound."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        for i in range(MAX_LABEL_PAIRS + 500):
            metrics.record_request(f"/route/{i}", "GET")

        series = {
            sample.labels["route"]
            for metric in registry.collect()
            for sample in metric.samples
            if sample.name == "test_requests_monitored_total"
        }
        assert len(series) == MAX_LABEL_PAIRS + 1  # the cap plus the overflow bucket
        assert OVERFLOW_LABEL in series
        assert (
            registry.get_sample_value(
                "test_requests_monitored_total",
                {"route": OVERFLOW_LABEL, "method": OVERFLOW_LABEL},
            )
            == 500
        )

    def test_nonstandard_method_collapses(self, registry: CollectorRegistry) -> None:
        """An arbitrary HTTP verb cannot mint its own series."""
        metrics = LoopGuardMetrics(prefix="test", registry=registry)

        metrics.record_request("/x", "AAAAAAAA")

        assert (
            registry.get_sample_value(
                "test_requests_monitored_total",
                {"route": "/x", "method": OVERFLOW_LABEL},
            )
            == 1
        )

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
        """get_metrics finds an instance when given the same registry."""
        created = create_metrics(prefix="findme", registry=registry)

        assert get_metrics("findme", registry) is created

    def test_get_metrics_misses_on_a_different_registry(
        self, registry: CollectorRegistry
    ) -> None:
        """The registry is part of the identity, so the default misses."""
        create_metrics(prefix="findme", registry=registry)

        assert get_metrics("findme") is None

    def test_get_metrics_finds_the_default_registry_instance(self) -> None:
        """The common case: created and looked up with no registry."""
        created = create_metrics(prefix="defaultreg")

        assert get_metrics("defaultreg") is created

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


class TestPrometheusEnabledIsWired:
    """`prometheus_enabled=True` must actually export samples.

    The flag existed for several releases while nothing on the detection path
    imported this module, so enabling it exposed nothing at all.
    """

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> Generator[None, None, None]:
        """Clear the request registry before and after each test."""
        get_registry().clear()
        yield
        get_registry().clear()

    @pytest.fixture
    def isolated_metrics(self, monkeypatch: pytest.MonkeyPatch) -> LoopGuardMetrics:
        """Bind the monitor's metrics to a private registry.

        The monitor calls create_metrics() with no arguments, which would land
        on the process-wide default registry and collide across tests.
        """
        registry = CollectorRegistry()
        metrics = LoopGuardMetrics(prefix="wiretest", registry=registry)
        monkeypatch.setattr(
            "fastapi_loopguard.metrics.create_metrics",
            lambda *args, **kwargs: metrics,
        )
        return metrics

    def _sample(self, metrics: LoopGuardMetrics, name: str) -> float:
        total = 0.0
        for metric in metrics._registry.collect():
            for sample in metric.samples:
                if sample.name == name:
                    total += sample.value
        return total

    async def test_blocking_is_exported(
        self, isolated_metrics: LoopGuardMetrics
    ) -> None:
        """A detected stall increments the blocking counter."""
        monitor = SentinelMonitor(
            LoopGuardConfig(
                prometheus_enabled=True,
                monitor_interval_ms=5.0,
                fallback_threshold_ms=20.0,
                cumulative_blocking_enabled=False,
            )
        )
        await monitor.start_with_background_calibration()
        try:
            await asyncio.sleep(0.02)
            time.sleep(0.15)
            monitor.poll()
        finally:
            await monitor.stop()

        assert self._sample(isolated_metrics, "wiretest_blocking_total") == 1.0

    async def test_requests_are_exported(
        self, isolated_metrics: LoopGuardMetrics
    ) -> None:
        """Every monitored request increments the request counter."""
        app = FastAPI()
        app.add_middleware(
            LoopGuardMiddleware,
            config=LoopGuardConfig(prometheus_enabled=True),
        )

        @app.get("/ping")
        async def ping() -> dict[str, bool]:
            return {"ok": True}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get("/ping")
            await client.get("/ping")

        assert (
            self._sample(isolated_metrics, "wiretest_requests_monitored_total") == 2.0
        )

    async def test_unmatched_paths_do_not_mint_series(
        self, isolated_metrics: LoopGuardMetrics
    ) -> None:
        """A 404 flood must not grow the metric store.

        The raw request path is client-controlled and unbounded, so using it
        as a label is remote memory exhaustion: every distinct URL mints a
        child metric that is never evicted.
        """
        app = FastAPI()
        app.add_middleware(
            LoopGuardMiddleware,
            config=LoopGuardConfig(prometheus_enabled=True),
        )

        @app.get("/ping")
        async def ping() -> dict[str, bool]:
            return {"ok": True}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for i in range(300):
                await client.get(f"/nope/{i}")

        routes = {
            sample.labels["route"]
            for metric in isolated_metrics._registry.collect()
            for sample in metric.samples
            if sample.name == "wiretest_requests_monitored_total"
        }
        assert routes == {"unmatched"}

    async def test_path_parameters_collapse_to_the_route_template(
        self, isolated_metrics: LoopGuardMetrics
    ) -> None:
        """Ordinary traffic to /users/{id} is one series, not one per id."""
        app = FastAPI()
        app.add_middleware(
            LoopGuardMiddleware,
            config=LoopGuardConfig(prometheus_enabled=True),
        )

        @app.get("/users/{user_id}")
        async def user(user_id: str) -> dict[str, bool]:
            return {"ok": True}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for i in range(50):
                await client.get(f"/users/{i}")

        assert (
            self._sample(isolated_metrics, "wiretest_requests_monitored_total") == 50.0
        )
        routes = {
            sample.labels["route"]
            for metric in isolated_metrics._registry.collect()
            for sample in metric.samples
            if sample.name == "wiretest_requests_monitored_total"
        }
        assert routes == {"/users/{user_id}"}

    def test_threshold_gauge_is_set_at_startup(
        self, isolated_metrics: LoopGuardMetrics
    ) -> None:
        """The gauge reflects the threshold the monitor starts on."""
        SentinelMonitor(
            LoopGuardConfig(prometheus_enabled=True, fallback_threshold_ms=42.0)
        )

        assert self._sample(isolated_metrics, "wiretest_threshold_seconds") == 0.042

    def test_missing_extra_logs_instead_of_raising(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Without prometheus_client the flag is loud, not fatal."""

        def _raise(*args: object, **kwargs: object) -> LoopGuardMetrics:
            raise RuntimeError("prometheus_client is not installed.")

        monkeypatch.setattr("fastapi_loopguard.metrics.create_metrics", _raise)

        with caplog.at_level(logging.ERROR, logger="fastapi_loopguard"):
            monitor = SentinelMonitor(LoopGuardConfig(prometheus_enabled=True))

        assert monitor._metrics is None
        assert "prometheus_client is not installed" in caplog.text
