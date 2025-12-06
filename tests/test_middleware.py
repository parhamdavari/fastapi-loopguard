"""Tests for LoopGuardMiddleware."""

import asyncio
import contextlib
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocket

from fastapi_loopguard import LoopGuardConfig, LoopGuardMiddleware
from fastapi_loopguard.context import get_registry


@pytest.fixture
def app() -> FastAPI:
    """Create a test FastAPI application."""
    app = FastAPI()

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/slow")
    async def slow() -> dict[str, str]:
        await asyncio.sleep(0.1)
        return {"status": "slow"}

    @app.get("/blocking")
    async def blocking() -> dict[str, str]:
        time.sleep(0.1)  # Intentional blocking!
        # Give monitor a chance to detect the blocking before context unregisters
        await asyncio.sleep(0.01)
        return {"status": "blocked"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    return app


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    """Clear the request registry before each test."""
    get_registry().clear()


class TestLoopGuardMiddleware:
    """Tests for the middleware."""

    async def test_middleware_passes_requests(self, app: FastAPI) -> None:
        """Test that requests pass through normally."""
        config = LoopGuardConfig(enabled=False)
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_dev_mode_headers(self, app: FastAPI) -> None:
        """Test that dev mode adds headers."""
        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/")

        assert response.status_code == 200
        # Note: headers are lowercase in pure ASGI
        assert "x-request-id" in response.headers
        assert "x-blocking-count" in response.headers
        assert "x-blocking-total-ms" in response.headers
        assert "x-blocking-detected" in response.headers

    async def test_excluded_paths_skip_monitoring(self, app: FastAPI) -> None:
        """Test that excluded paths don't get monitoring headers."""
        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/health")

        assert response.status_code == 200
        # Health endpoint should not have monitoring headers
        assert "x-request-id" not in response.headers

    async def test_detects_blocking_endpoint(self, app: FastAPI) -> None:
        """Test that blocking endpoints are detected."""
        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=2.0,  # Fast monitoring
            calibration_iterations=10,
            threshold_multiplier=2.0,
            fallback_threshold_ms=5.0,  # Low threshold
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # First request initializes and starts background calibration
            await client.get("/")
            # Give monitor time to calibrate and start monitoring loop
            # Calibration: 10 iterations * 2ms = ~20ms, plus buffer
            await asyncio.sleep(0.1)
            # Now test blocking endpoint
            response = await client.get("/blocking")

        assert response.status_code == 200
        assert response.json() == {"status": "blocked"}

        # Should have detected blocking
        blocking_count = int(response.headers.get("x-blocking-count", "0"))
        assert blocking_count >= 1
        assert response.headers.get("x-blocking-detected") == "true"

    async def test_non_blocking_endpoint(self, app: FastAPI) -> None:
        """Test that non-blocking endpoints report no blocking."""
        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            fallback_threshold_ms=50.0,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/slow")

        assert response.status_code == 200

        # Async sleep should not trigger blocking detection
        blocking_count = int(response.headers.get("x-blocking-count", "0"))
        assert blocking_count == 0
        assert response.headers.get("x-blocking-detected") == "false"

    async def test_registry_cleanup(self, app: FastAPI) -> None:
        """Test that requests are cleaned up from registry after completion."""
        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Make several requests
            for _ in range(5):
                await client.get("/")

        # All requests should be cleaned up
        assert get_registry().active_count() == 0

    async def test_concurrent_requests_unique_ids(self, app: FastAPI) -> None:
        """Test that concurrent requests get unique IDs."""
        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Make concurrent requests
            tasks = [client.get("/slow") for _ in range(10)]
            responses = await asyncio.gather(*tasks)

        # All should succeed
        assert all(r.status_code == 200 for r in responses)

        # All should have unique request IDs
        request_ids = [r.headers["x-request-id"] for r in responses]
        assert len(set(request_ids)) == 10

        # Registry should be empty after all complete
        assert get_registry().active_count() == 0


class TestLifespanEvents:
    """Tests for middleware lifespan handling."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_lifespan_startup_starts_monitor(self) -> None:
        """Test that monitor starts during lifespan startup."""
        startup_called = False

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            nonlocal startup_called
            startup_called = True
            yield

        app = FastAPI(lifespan=lifespan)

        @app.get("/")
        async def root() -> dict[str, str]:
            return {"status": "ok"}

        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        middleware = LoopGuardMiddleware(app, config=config)

        # Directly test lifespan handling by calling ASGI interface
        # Create a mock lifespan scope and message flow
        startup_complete = asyncio.Event()
        shutdown_complete = asyncio.Event()
        messages: list[dict] = []

        async def receive() -> dict[str, str]:
            if not startup_complete.is_set():
                startup_complete.set()
                return {"type": "lifespan.startup"}
            await shutdown_complete.wait()
            return {"type": "lifespan.shutdown"}

        async def send(message: dict[str, str]) -> None:
            messages.append(message)
            if message["type"] == "lifespan.startup.complete":
                # Monitor should now be started
                pass

        scope = {"type": "lifespan", "asgi": {"version": "3.0"}}

        # Run lifespan in background
        lifespan_task = asyncio.create_task(middleware(scope, receive, send))

        # Wait for startup to complete
        await asyncio.sleep(0.1)

        # Verify startup message was sent
        assert any(m["type"] == "lifespan.startup.complete" for m in messages)
        # Monitor should be started
        assert middleware._started

        # Signal shutdown
        shutdown_complete.set()
        await asyncio.sleep(0.1)

        # Clean up
        lifespan_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await lifespan_task

    async def test_lifespan_shutdown_stops_monitor(self) -> None:
        """Test that monitor stops during lifespan shutdown."""

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
            yield

        app = FastAPI(lifespan=lifespan)

        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        middleware = LoopGuardMiddleware(app, config=config)

        # Mock lifespan flow
        phase = {"current": "startup"}
        messages: list[dict] = []

        async def receive() -> dict[str, str]:
            if phase["current"] == "startup":
                phase["current"] = "running"
                return {"type": "lifespan.startup"}
            elif phase["current"] == "running":
                phase["current"] = "shutdown"
                return {"type": "lifespan.shutdown"}
            else:
                # Block forever
                await asyncio.Event().wait()
                return {}

        async def send(message: dict[str, str]) -> None:
            messages.append(message)

        scope = {"type": "lifespan", "asgi": {"version": "3.0"}}

        # Run full lifespan
        await middleware(scope, receive, send)

        # Verify shutdown complete message was sent
        assert any(m["type"] == "lifespan.shutdown.complete" for m in messages)
        # Monitor should be stopped
        assert not middleware._started
        assert middleware._monitor is None

    async def test_middleware_without_lifespan_lazy_start(self) -> None:
        """Test that middleware starts lazily without lifespan events."""
        # App without lifespan
        app = FastAPI()

        @app.get("/")
        async def root() -> dict[str, str]:
            return {"status": "ok"}

        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # First request should trigger lazy start
            response = await client.get("/")

        assert response.status_code == 200
        # Headers should be present even with lazy start
        assert "x-request-id" in response.headers


class TestDisabledMiddleware:
    """Tests for middleware when disabled."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_disabled_middleware_no_headers(self) -> None:
        """Test that disabled middleware doesn't add headers even with dev_mode."""
        app = FastAPI()

        @app.get("/")
        async def root() -> dict[str, str]:
            return {"status": "ok"}

        config = LoopGuardConfig(
            enabled=False,
            dev_mode=True,  # Even with dev_mode, should not add headers
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/")

        assert response.status_code == 200
        assert "x-request-id" not in response.headers
        assert "x-blocking-count" not in response.headers

    async def test_disabled_middleware_no_monitoring(self) -> None:
        """Test that disabled middleware doesn't detect blocking."""
        app = FastAPI()

        @app.get("/blocking")
        async def blocking() -> dict[str, str]:
            time.sleep(0.05)  # Intentional blocking
            return {"status": "blocked"}

        config = LoopGuardConfig(
            enabled=False,
            dev_mode=True,
            monitor_interval_ms=2.0,
            fallback_threshold_ms=5.0,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/blocking")

        assert response.status_code == 200
        # No monitoring should have occurred
        assert "x-blocking-detected" not in response.headers

    async def test_disabled_middleware_no_registry_impact(self) -> None:
        """Test that disabled middleware doesn't register contexts."""
        app = FastAPI()

        @app.get("/")
        async def root() -> dict[str, int]:
            # Check registry during request
            count = get_registry().active_count()
            return {"active_count": count}

        config = LoopGuardConfig(enabled=False)
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/")

        assert response.status_code == 200
        # With disabled middleware, no context should be registered
        assert response.json()["active_count"] == 0


class TestWebSocketPassthrough:
    """Tests for WebSocket connection handling."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    def test_websocket_passthrough(self) -> None:
        """Test that WebSocket connections pass through without monitoring."""
        from starlette.testclient import TestClient

        app = FastAPI()

        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket) -> None:
            await websocket.accept()
            data = await websocket.receive_text()
            await websocket.send_text(f"echo: {data}")
            await websocket.close()

        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        with (
            TestClient(app) as client,
            client.websocket_connect("/ws") as ws,
        ):
            ws.send_text("hello")
            message = ws.receive_text()
            assert message == "echo: hello"

        # Registry should be empty - WebSocket doesn't register
        assert get_registry().active_count() == 0


class TestMiddlewareErrorHandling:
    """Tests for error handling in middleware."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_app_exception_cleanup(self) -> None:
        """Test that context is unregistered even on exception."""
        app = FastAPI()

        @app.get("/error")
        async def error_endpoint() -> dict[str, str]:
            raise ValueError("Intentional error")

        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/error")

        # Error should result in 500
        assert response.status_code == 500

        # But registry should be cleaned up
        assert get_registry().active_count() == 0

    async def test_app_exception_propagates(self) -> None:
        """Test that exceptions propagate correctly."""
        app = FastAPI()

        @app.get("/error")
        async def error_endpoint() -> dict[str, str]:
            raise ValueError("Intentional error")

        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get("/error")

        # Error should propagate as 500 Internal Server Error
        assert response.status_code == 500


class TestScopeState:
    """Tests for scope state handling."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def test_request_id_stored_in_scope_state(self) -> None:
        """Test that request_id is accessible in scope state."""
        app = FastAPI()

        @app.get("/")
        async def root(request: Request) -> dict[str, str]:
            request_id = request.scope.get("state", {}).get("loopguard_request_id")
            return {"request_id": request_id}

        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/")

        assert response.status_code == 200
        data = response.json()
        # Request ID should be accessible in endpoint
        assert data["request_id"] is not None
        assert len(data["request_id"]) == 8  # UUID[:8]
        # Should match the header
        assert data["request_id"] == response.headers["x-request-id"]

    async def test_scope_without_state_creates_it(self) -> None:
        """Test that middleware creates state dict if missing."""
        app = FastAPI()

        @app.get("/")
        async def root(request: Request) -> dict[str, bool]:
            # State should exist and have request_id
            state = request.scope.get("state", {})
            has_request_id = "loopguard_request_id" in state
            return {"has_request_id": has_request_id}

        config = LoopGuardConfig(
            dev_mode=True,
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        app.add_middleware(LoopGuardMiddleware, config=config)

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.get("/")

        assert response.status_code == 200
        assert response.json()["has_request_id"] is True
