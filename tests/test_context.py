"""Tests for context module - RequestContext and RequestRegistry."""

import time

import pytest

from fastapi_loopguard.context import (
    RequestContext,
    RequestRegistry,
    get_active_requests,
    get_current_request,
    get_registry,
    register_request,
    reset_current_request,
    set_current_request,
    unregister_request,
)


class TestRequestContext:
    """Tests for RequestContext dataclass."""

    def test_request_context_creation_defaults(self) -> None:
        """Test that default values are auto-populated."""
        before = time.monotonic()
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        after = time.monotonic()

        assert ctx.request_id == "test-123"
        assert ctx.path == "/api/users"
        assert ctx.method == "GET"
        # start_time should be auto-populated between before and after
        assert before <= ctx.start_time <= after
        # blocking_events should be empty list
        assert ctx.blocking_events == []
        assert isinstance(ctx.blocking_events, list)

    def test_request_context_custom_start_time(self) -> None:
        """Test that explicit start_time is preserved."""
        custom_time = 12345.6789
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
            start_time=custom_time,
        )

        assert ctx.start_time == custom_time

    def test_record_blocking_single_event(self) -> None:
        """Test recording a single blocking event."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        before = time.monotonic()
        ctx.record_blocking(100.0)
        after = time.monotonic()

        assert len(ctx.blocking_events) == 1
        lag_ms, timestamp = ctx.blocking_events[0]
        assert lag_ms == 100.0
        assert before <= timestamp <= after

    def test_record_blocking_multiple_events(self) -> None:
        """Test recording multiple blocking events preserves order."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        lags = [50.0, 100.0, 75.5, 25.0, 150.0]
        for lag in lags:
            ctx.record_blocking(lag)

        assert len(ctx.blocking_events) == 5
        recorded_lags = [event[0] for event in ctx.blocking_events]
        assert recorded_lags == lags

    def test_total_blocking_ms_empty(self) -> None:
        """Test total_blocking_ms returns 0.0 for new context."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        assert ctx.total_blocking_ms == 0.0

    def test_total_blocking_ms_single_event(self) -> None:
        """Test total_blocking_ms for single event."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        ctx.record_blocking(50.0)

        assert ctx.total_blocking_ms == 50.0

    def test_total_blocking_ms_multiple_events(self) -> None:
        """Test total_blocking_ms sums all events correctly."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        ctx.record_blocking(100.0)
        ctx.record_blocking(50.0)
        ctx.record_blocking(25.5)

        assert ctx.total_blocking_ms == 175.5

    def test_blocking_count_empty(self) -> None:
        """Test blocking_count is 0 for new context."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        assert ctx.blocking_count == 0

    def test_blocking_count_after_records(self) -> None:
        """Test blocking_count after recording events."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        for _ in range(5):
            ctx.record_blocking(10.0)

        assert ctx.blocking_count == 5

    def test_request_context_uses_slots(self) -> None:
        """Test that RequestContext uses __slots__ for memory efficiency."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        # With __slots__, instances should not have __dict__
        assert not hasattr(ctx, "__dict__")

        # Attempting to add arbitrary attribute should fail
        with pytest.raises(AttributeError):
            ctx.arbitrary_attr = "value"  # type: ignore[attr-defined]


class TestRequestRegistry:
    """Tests for RequestRegistry class."""

    def test_registry_initialization(self) -> None:
        """Test that new registry is empty."""
        registry = RequestRegistry()

        assert registry.active_count() == 0
        assert list(registry.get_all_active()) == []

    def test_register_single_context(self) -> None:
        """Test registering a single context."""
        registry = RequestRegistry()
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        registry.register(ctx)

        assert registry.active_count() == 1
        assert registry.get("test-123") is ctx

    def test_register_multiple_contexts(self) -> None:
        """Test registering multiple contexts."""
        registry = RequestRegistry()
        contexts = [
            RequestContext(request_id=f"req-{i}", path=f"/path/{i}", method="GET")
            for i in range(3)
        ]

        for ctx in contexts:
            registry.register(ctx)

        assert registry.active_count() == 3
        for ctx in contexts:
            assert registry.get(ctx.request_id) is ctx

    def test_register_overwrites_duplicate_id(self) -> None:
        """Test that registering with same ID overwrites."""
        registry = RequestRegistry()
        ctx1 = RequestContext(
            request_id="test-1",
            path="/first",
            method="GET",
        )
        ctx2 = RequestContext(
            request_id="test-1",
            path="/second",
            method="POST",
        )

        registry.register(ctx1)
        registry.register(ctx2)

        assert registry.active_count() == 1
        result = registry.get("test-1")
        assert result is ctx2
        assert result.path == "/second"

    def test_unregister_existing_context(self) -> None:
        """Test unregistering an existing context."""
        registry = RequestRegistry()
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        registry.register(ctx)

        result = registry.unregister("test-123")

        assert result is ctx
        assert registry.active_count() == 0
        assert registry.get("test-123") is None

    def test_unregister_nonexistent_context(self) -> None:
        """Test unregistering non-existent context returns None."""
        registry = RequestRegistry()

        result = registry.unregister("nonexistent")

        assert result is None

    def test_get_nonexistent_context(self) -> None:
        """Test getting non-existent context returns None."""
        registry = RequestRegistry()

        result = registry.get("nonexistent")

        assert result is None

    def test_get_all_active_iteration(self) -> None:
        """Test iterating all active contexts."""
        registry = RequestRegistry()
        contexts = [
            RequestContext(request_id=f"req-{i}", path=f"/path/{i}", method="GET")
            for i in range(5)
        ]
        for ctx in contexts:
            registry.register(ctx)

        active = list(registry.get_all_active())

        assert len(active) == 5
        for ctx in contexts:
            assert ctx in active

    def test_get_all_active_empty_registry(self) -> None:
        """Test get_all_active on empty registry."""
        registry = RequestRegistry()

        active = list(registry.get_all_active())

        assert active == []

    def test_active_count_accuracy(self) -> None:
        """Test active_count tracks register/unregister correctly."""
        registry = RequestRegistry()

        # Register 3
        for i in range(3):
            ctx = RequestContext(request_id=f"req-{i}", path=f"/path/{i}", method="GET")
            registry.register(ctx)
        assert registry.active_count() == 3

        # Unregister 1
        registry.unregister("req-1")
        assert registry.active_count() == 2

        # Register 2 more
        for i in range(3, 5):
            ctx = RequestContext(request_id=f"req-{i}", path=f"/path/{i}", method="GET")
            registry.register(ctx)
        assert registry.active_count() == 4

    def test_clear_removes_all_contexts(self) -> None:
        """Test clear removes all contexts."""
        registry = RequestRegistry()
        for i in range(5):
            ctx = RequestContext(request_id=f"req-{i}", path=f"/path/{i}", method="GET")
            registry.register(ctx)

        registry.clear()

        assert registry.active_count() == 0
        for i in range(5):
            assert registry.get(f"req-{i}") is None

    def test_clear_on_empty_registry(self) -> None:
        """Test clear on empty registry is a no-op."""
        registry = RequestRegistry()

        # Should not raise
        registry.clear()

        assert registry.active_count() == 0

    def test_registry_uses_slots(self) -> None:
        """Test that RequestRegistry uses __slots__."""
        registry = RequestRegistry()

        # With __slots__, instances should not have __dict__
        assert not hasattr(registry, "__dict__")


class TestGlobalFunctions:
    """Tests for module-level global functions."""

    @pytest.fixture(autouse=True)
    def clear_global_registry(self) -> None:
        """Clear global registry before and after each test."""
        get_registry().clear()
        yield
        get_registry().clear()

    def test_get_registry_returns_singleton(self) -> None:
        """Test that get_registry returns the same instance."""
        registry1 = get_registry()
        registry2 = get_registry()

        assert registry1 is registry2

    def test_register_request_adds_to_global(self) -> None:
        """Test register_request adds to global registry."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        register_request(ctx)

        assert get_registry().get("test-123") is ctx

    def test_unregister_request_removes_from_global(self) -> None:
        """Test unregister_request removes from global registry."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        register_request(ctx)

        unregister_request("test-123")

        assert get_registry().get("test-123") is None

    def test_unregister_request_returns_context(self) -> None:
        """Test unregister_request returns the removed context."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        register_request(ctx)

        result = unregister_request("test-123")

        assert result is ctx

    def test_unregister_request_nonexistent_returns_none(self) -> None:
        """Test unregister_request returns None for non-existent."""
        result = unregister_request("nonexistent")

        assert result is None

    def test_get_active_requests_returns_iterator(self) -> None:
        """Test get_active_requests returns iterator over all contexts."""
        contexts = [
            RequestContext(request_id=f"req-{i}", path=f"/path/{i}", method="GET")
            for i in range(3)
        ]
        for ctx in contexts:
            register_request(ctx)

        active = list(get_active_requests())

        assert len(active) == 3
        for ctx in contexts:
            assert ctx in active

    def test_get_active_requests_empty(self) -> None:
        """Test get_active_requests on empty registry."""
        active = list(get_active_requests())

        assert active == []


class TestBackwardCompatibility:
    """Tests for backward compatibility aliases."""

    @pytest.fixture(autouse=True)
    def clear_global_registry(self) -> None:
        """Clear global registry before and after each test."""
        get_registry().clear()
        yield
        get_registry().clear()

    def test_get_current_request_returns_active(self) -> None:
        """Test get_current_request returns an active context."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        register_request(ctx)

        result = get_current_request()

        assert result is ctx

    def test_get_current_request_returns_any_of_multiple(self) -> None:
        """Test get_current_request returns one of multiple active contexts."""
        contexts = [
            RequestContext(request_id=f"req-{i}", path=f"/path/{i}", method="GET")
            for i in range(3)
        ]
        for ctx in contexts:
            register_request(ctx)

        result = get_current_request()

        # Should return one of the registered contexts
        assert result is not None
        assert result in contexts

    def test_get_current_request_empty_returns_none(self) -> None:
        """Test get_current_request returns None when empty."""
        result = get_current_request()

        assert result is None

    def test_set_current_request_returns_request_id(self) -> None:
        """Test set_current_request returns the request_id."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        token = set_current_request(ctx)

        assert token == "test-123"

    def test_set_current_request_registers_context(self) -> None:
        """Test set_current_request registers in global registry."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        set_current_request(ctx)

        assert get_registry().get("test-123") is ctx

    def test_reset_current_request_unregisters(self) -> None:
        """Test reset_current_request removes from global registry."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )
        set_current_request(ctx)

        reset_current_request("test-123")

        assert get_registry().active_count() == 0

    def test_set_reset_round_trip(self) -> None:
        """Test full set/reset cycle."""
        ctx = RequestContext(
            request_id="test-123",
            path="/api/users",
            method="GET",
        )

        # Set
        token = set_current_request(ctx)
        assert get_registry().active_count() == 1
        assert get_current_request() is ctx

        # Reset
        reset_current_request(token)
        assert get_registry().active_count() == 0
        assert get_current_request() is None
