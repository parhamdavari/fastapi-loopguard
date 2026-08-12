"""Tests for LoopGuardMiddleware."""

import asyncio
import contextlib
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Receive, Scope, Send
from starlette.websockets import WebSocket

from fastapi_loopguard import LoopGuardConfig, LoopGuardMiddleware, SentinelMonitor
from fastapi_loopguard.context import RequestContext, get_registry
from fastapi_loopguard.middleware import (
    _console_supports_color,
    _format_console_warning,
)


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


def _live_loopguard_tasks() -> list[str]:
    """Names of loopguard tasks still alive on the current loop."""
    return sorted(
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name().startswith("loopguard") and not task.done()
    )


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
            enforcement_mode="log",  # Use log mode to test header detection
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

    async def test_startup_failed_stops_monitor(self) -> None:
        """lifespan.startup.failed must not leak a running monitor."""

        async def failing_app(scope: Scope, receive: Receive, send: Send) -> None:
            message = await receive()
            assert message["type"] == "lifespan.startup"
            await send({"type": "lifespan.startup.failed", "message": "db down"})

        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        middleware = LoopGuardMiddleware(failing_app, config=config)

        async def receive() -> Message:
            return {"type": "lifespan.startup"}

        async def send(message: Message) -> None:
            pass

        await middleware({"type": "lifespan"}, receive, send)

        assert not middleware._started
        assert middleware._monitor is None
        assert _live_loopguard_tasks() == []

    async def test_shutdown_failed_stops_monitor(self) -> None:
        """lifespan.shutdown.failed must stop the monitor like shutdown.complete."""

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await receive()  # lifespan.startup
            await send({"type": "lifespan.startup.complete"})
            await receive()  # lifespan.shutdown
            await send({"type": "lifespan.shutdown.failed", "message": "cleanup"})

        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        middleware = LoopGuardMiddleware(app, config=config)

        messages = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

        async def receive() -> Message:
            return messages.pop(0)

        async def send(message: Message) -> None:
            pass

        await middleware({"type": "lifespan"}, receive, send)

        assert not middleware._started
        assert middleware._monitor is None
        assert _live_loopguard_tasks() == []

    async def test_lazy_monitor_stops_when_idle(self) -> None:
        """Without lifespan, the lazily started monitor must not leak tasks."""

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        middleware = LoopGuardMiddleware(app, config=config)

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            pass

        scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
        await middleware(scope, receive, send)

        # Request finished, no requests in flight: nothing may keep running
        assert not middleware._started
        assert _live_loopguard_tasks() == []

    async def test_lifespan_monitor_persists_across_requests(self) -> None:
        """A lifespan-managed monitor must NOT stop between requests."""

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "lifespan":
                await receive()  # lifespan.startup
                await send({"type": "lifespan.startup.complete"})
                await asyncio.Event().wait()  # stay in lifespan until cancelled
            else:
                await send(
                    {"type": "http.response.start", "status": 200, "headers": []}
                )
                await send({"type": "http.response.body", "body": b"ok"})

        config = LoopGuardConfig(
            monitor_interval_ms=5.0,
            calibration_iterations=10,
            log_blocking_events=False,
        )
        middleware = LoopGuardMiddleware(app, config=config)

        async def lifespan_receive() -> Message:
            return {"type": "lifespan.startup"}

        async def send(message: Message) -> None:
            pass

        lifespan_task = asyncio.create_task(
            middleware({"type": "lifespan"}, lifespan_receive, send)
        )
        await asyncio.sleep(0.05)
        assert middleware._started

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
        try:
            await middleware(scope, receive, send)

            # Lifespan-managed monitor survives the request completing
            assert middleware._started
            assert "loopguard-monitor" in _live_loopguard_tasks()
        finally:
            lifespan_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await lifespan_task
            if middleware._monitor:
                await middleware._monitor.stop()

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


class TestSendWrapperConformance:
    """Send wrappers must forward unknown ASGI message types and preserve keys."""

    @pytest.fixture(autouse=True)
    def clear_registry(self) -> None:
        """Clear the request registry before each test."""
        get_registry().clear()

    async def _drive(
        self,
        config: LoopGuardConfig,
        messages: list[Message],
    ) -> list[Message]:
        """Send one request through the middleware, return what the server got."""

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            for message in messages:
                await send(message)

        middleware = LoopGuardMiddleware(app, config=config)
        sent: list[Message] = []

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
        await middleware(scope, receive, send)
        return sent

    async def test_strict_mode_forwards_pathsend(self) -> None:
        """FileResponse on pathsend-capable servers must not hang in strict mode."""
        config = LoopGuardConfig(enforcement_mode="strict", log_blocking_events=False)
        sent = await self._drive(
            config,
            [
                {"type": "http.response.start", "status": 200, "headers": []},
                {"type": "http.response.pathsend", "path": "/tmp/file.bin"},
            ],
        )
        assert "http.response.pathsend" in [m["type"] for m in sent]

    async def test_strict_mode_forwards_trailers_messages(self) -> None:
        """http.response.trailers must pass through the strict-mode wrapper."""
        config = LoopGuardConfig(enforcement_mode="strict", log_blocking_events=False)
        sent = await self._drive(
            config,
            [
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                    "trailers": True,
                },
                {"type": "http.response.body", "body": b"data", "more_body": False},
                {
                    "type": "http.response.trailers",
                    "headers": [(b"x-checksum", b"abc")],
                },
            ],
        )
        assert "http.response.trailers" in [m["type"] for m in sent]

    _START_WITH_TRAILERS: list[Message] = [
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"trailer", b"x-checksum")],
            "trailers": True,
        },
        {"type": "http.response.body", "body": b"data", "more_body": False},
    ]

    def _start_message(self, sent: list[Message]) -> Message:
        return next(m for m in sent if m["type"] == "http.response.start")

    async def test_warn_mode_preserves_start_message_keys(self) -> None:
        """Rebuilding http.response.start must not drop keys like 'trailers'."""
        config = LoopGuardConfig(enforcement_mode="warn", log_blocking_events=False)
        sent = await self._drive(config, self._START_WITH_TRAILERS)
        assert self._start_message(sent).get("trailers") is True

    async def test_headers_mode_preserves_start_message_keys(self) -> None:
        """The dev-mode headers wrapper must not drop keys like 'trailers'."""
        config = LoopGuardConfig(
            enforcement_mode="log", dev_mode=True, log_blocking_events=False
        )
        sent = await self._drive(config, self._START_WITH_TRAILERS)
        assert self._start_message(sent).get("trailers") is True

    async def test_strict_mode_preserves_start_message_keys(self) -> None:
        """The strict wrapper (no blocking) must not drop keys like 'trailers'."""
        config = LoopGuardConfig(enforcement_mode="strict", log_blocking_events=False)
        sent = await self._drive(config, self._START_WITH_TRAILERS)
        assert self._start_message(sent).get("trailers") is True


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


class TestLazyStopRace:
    """A request arriving while a lazy stop is in flight must be monitored."""

    @pytest.fixture(autouse=True)
    def _clear_registry(self) -> None:
        get_registry().clear()

    async def test_request_arriving_mid_stop_gets_fresh_monitor(self) -> None:
        config = LoopGuardConfig(log_blocking_events=False)
        observed: dict[str, object] = {}

        async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
            observed["monitor"] = middleware._monitor
            monitor = middleware._monitor
            observed["running"] = monitor.is_running if monitor else False
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = LoopGuardMiddleware(inner_app, config=config)

        release = asyncio.Event()
        entered = asyncio.Event()

        class _SlowStopMonitor:
            is_running = False

            async def stop(self) -> None:
                entered.set()
                await release.wait()

        middleware._monitor = _SlowStopMonitor()  # type: ignore[assignment]
        middleware._started = True
        middleware._lazy_started = True

        stop_task = asyncio.create_task(middleware._stop_monitor())
        await entered.wait()

        # Flags must be cleared BEFORE the await inside _stop_monitor; the
        # old ordering left _started=True here and the request below would
        # have run unmonitored against a dying monitor
        assert middleware._started is False
        assert middleware._monitor is None
        assert middleware._lazy_started is False

        sent: list[Message] = []

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
        await middleware(scope, receive, send)

        release.set()
        await stop_task

        monitor = observed["monitor"]
        assert isinstance(monitor, SentinelMonitor)
        assert observed["running"] is True
        assert sent[0]["status"] == 200


class TestLifespanExceptionCleanup:
    """A lifespan app that raises must not leak the monitor tasks."""

    @pytest.fixture(autouse=True)
    def _clear_registry(self) -> None:
        get_registry().clear()

    async def test_lifespan_app_exception_stops_monitor(self) -> None:
        config = LoopGuardConfig(log_blocking_events=False)

        async def failing_app(scope: Scope, receive: Receive, send: Send) -> None:
            await receive()  # consumes lifespan.startup -> monitor starts
            raise RuntimeError("startup exploded")

        middleware = LoopGuardMiddleware(failing_app, config=config)

        async def receive() -> Message:
            return {"type": "lifespan.startup"}

        async def send(message: Message) -> None:
            pass

        scope: Scope = {"type": "lifespan"}
        with pytest.raises(RuntimeError, match="startup exploded"):
            await middleware(scope, receive, send)

        assert middleware._started is False
        assert middleware._monitor is None
        assert _live_loopguard_tasks() == []


class TestResponseShapeConformance:
    """Response shapes beyond one start + one terminal body."""

    @pytest.fixture(autouse=True)
    def _clear_registry(self) -> None:
        get_registry().clear()

    async def _drive_messages(
        self,
        config: LoopGuardConfig,
        messages: list[Message],
        path: str = "/x",
    ) -> list[Message]:
        """Send one request through the middleware, return what the server got."""

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            for message in messages:
                await send(message)

        middleware = LoopGuardMiddleware(app, config=config)
        sent: list[Message] = []

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {"type": "http", "method": "GET", "path": path, "headers": []}
        await middleware(scope, receive, send)
        return sent

    @pytest.mark.parametrize(
        "config",
        [
            LoopGuardConfig(log_blocking_events=False),  # warn (default)
            LoopGuardConfig(
                enforcement_mode="log", dev_mode=True, log_blocking_events=False
            ),  # dev headers
            LoopGuardConfig(
                enforcement_mode="strict", log_blocking_events=False
            ),  # strict clean path
        ],
        ids=["warn", "dev-headers", "strict"],
    )
    async def test_streaming_bodies_pass_through_every_wrapper(
        self, config: LoopGuardConfig
    ) -> None:
        """Multiple body chunks with more_body survive all three wrappers."""
        chunks = [
            {"type": "http.response.body", "body": b"a", "more_body": True},
            {"type": "http.response.body", "body": b"b", "more_body": True},
            {"type": "http.response.body", "body": b"c", "more_body": False},
        ]
        sent = await self._drive_messages(
            config,
            [{"type": "http.response.start", "status": 200, "headers": []}, *chunks],
        )

        starts = [m for m in sent if m["type"] == "http.response.start"]
        bodies = [m for m in sent if m["type"] == "http.response.body"]
        assert len(starts) == 1  # headers injected exactly once
        assert [m["body"] for m in bodies] == [b"a", b"b", b"c"]
        header_names = [name for name, _ in starts[0]["headers"]]
        assert b"x-request-id" in header_names

    async def test_no_body_204_response(self) -> None:
        """A 204 with an empty terminal body passes untouched."""
        config = LoopGuardConfig(dev_mode=True, log_blocking_events=False)
        sent = await self._drive_messages(
            config,
            [
                {"type": "http.response.start", "status": 204, "headers": []},
                {"type": "http.response.body", "body": b"", "more_body": False},
            ],
        )

        assert sent[0]["status"] == 204
        assert dict(sent[0]["headers"])[b"x-blocking-detected"] == b"false"

    @pytest.mark.parametrize(
        "config",
        [
            LoopGuardConfig(log_blocking_events=False),
            LoopGuardConfig(
                enforcement_mode="log", dev_mode=True, log_blocking_events=False
            ),
        ],
        ids=["warn", "dev-headers"],
    )
    async def test_pathsend_and_trailers_forwarded(
        self, config: LoopGuardConfig
    ) -> None:
        """Extension messages pass through the warn and dev-header wrappers."""
        sent = await self._drive_messages(
            config,
            [
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                    "trailers": True,
                },
                {"type": "http.response.pathsend", "path": "/tmp/file.bin"},
                {"type": "http.response.trailers", "headers": [(b"x-t", b"1")]},
            ],
        )

        types = [m["type"] for m in sent]
        assert "http.response.pathsend" in types
        assert "http.response.trailers" in types
        assert sent[0].get("trailers") is True  # start-message key preserved

    async def test_app_exception_propagates_before_response_start(self) -> None:
        """An exception before any send propagates; nothing reaches the client."""
        config = LoopGuardConfig(log_blocking_events=False)

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            raise RuntimeError("pre-start explosion")

        middleware = LoopGuardMiddleware(app, config=config)
        sent: list[Message] = []

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent.append(message)

        scope: Scope = {"type": "http", "method": "GET", "path": "/x", "headers": []}
        with pytest.raises(RuntimeError, match="pre-start explosion"):
            await middleware(scope, receive, send)

        assert sent == []
        assert get_registry().active_count() == 0  # context unregistered


class TestLifespanEdgeCases:
    """Repeated and out-of-order lifespan events."""

    @pytest.fixture(autouse=True)
    def _clear_registry(self) -> None:
        get_registry().clear()

    async def _run_lifespan(
        self,
        middleware: LoopGuardMiddleware,
        incoming: list[Message],
    ) -> list[Message]:
        """Drive one lifespan connection: app echoes a terminal per message."""

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            for _ in range(len(incoming)):
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})

        middleware.app = app
        queue = list(incoming)
        sent: list[Message] = []

        async def receive() -> Message:
            return queue.pop(0)

        async def send(message: Message) -> None:
            sent.append(message)

        await middleware({"type": "lifespan"}, receive, send)
        return sent

    async def test_double_startup_starts_one_monitor(self) -> None:
        config = LoopGuardConfig(log_blocking_events=False)
        middleware = LoopGuardMiddleware(lambda: None, config=config)  # replaced

        await self._run_lifespan(
            middleware,
            [{"type": "lifespan.startup"}, {"type": "lifespan.startup"}],
        )
        first_monitor = middleware._monitor

        assert middleware._started is True
        assert first_monitor is not None
        await middleware._stop_monitor()

    async def test_startup_after_shutdown_restarts_monitor(self) -> None:
        config = LoopGuardConfig(log_blocking_events=False)
        middleware = LoopGuardMiddleware(lambda: None, config=config)

        await self._run_lifespan(
            middleware,
            [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}],
        )
        assert middleware._started is False
        assert _live_loopguard_tasks() == []

        await self._run_lifespan(middleware, [{"type": "lifespan.startup"}])
        assert middleware._started is True
        assert middleware._monitor is not None

        await middleware._stop_monitor()

    async def test_disabled_middleware_lifespan_starts_nothing(self) -> None:
        config = LoopGuardConfig(enabled=False, log_blocking_events=False)
        middleware = LoopGuardMiddleware(lambda: None, config=config)

        await self._run_lifespan(
            middleware,
            [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}],
        )

        assert middleware._started is False
        assert middleware._monitor is None
        assert _live_loopguard_tasks() == []


class TestExcludePathSemantics:
    """exclude_paths is an exact match on the raw scope path."""

    @pytest.fixture(autouse=True)
    def _clear_registry(self) -> None:
        get_registry().clear()

    async def _request_monitored(self, config: LoopGuardConfig, path: str) -> bool:
        """True if the request registered a context (i.e. was monitored)."""
        registered: list[int] = []

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            registered.append(get_registry().active_count())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = LoopGuardMiddleware(app, config=config)

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            pass

        scope: Scope = {"type": "http", "method": "GET", "path": path, "headers": []}
        await middleware(scope, receive, send)
        return registered[0] > 0

    async def test_custom_exclude_paths(self) -> None:
        config = LoopGuardConfig(
            exclude_paths=frozenset({"/internal/ping"}), log_blocking_events=False
        )
        assert await self._request_monitored(config, "/internal/ping") is False
        assert await self._request_monitored(config, "/api/users") is True

    async def test_exclusion_is_exact_not_prefix(self) -> None:
        """Documents current semantics: /health/live is NOT excluded by /health."""
        config = LoopGuardConfig(log_blocking_events=False)
        assert await self._request_monitored(config, "/health") is False
        assert await self._request_monitored(config, "/health/live") is True


class TestScopeStatePreserved:
    """A pre-populated scope state dict must be extended, not replaced."""

    @pytest.fixture(autouse=True)
    def _clear_registry(self) -> None:
        get_registry().clear()

    async def test_existing_state_keys_survive(self) -> None:
        config = LoopGuardConfig(log_blocking_events=False)
        seen: dict[str, object] = {}

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            seen.update(scope["state"])
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = LoopGuardMiddleware(app, config=config)

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            pass

        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "headers": [],
            "state": {"outer_middleware": "present"},
        }
        await middleware(scope, receive, send)

        assert seen["outer_middleware"] == "present"
        assert "loopguard_request_id" in seen


class TestConsoleWarningFormat:
    """The blocking banner: content, color discipline, and parity."""

    def _ctx(self) -> "RequestContext":
        ctx = RequestContext(request_id="deadbeef", path="/api/users", method="GET")
        ctx.record_blocking(3000.1)
        return ctx

    def test_plain_rendering_has_all_content_and_no_escapes(self) -> None:
        text = _format_console_warning(self._ctx(), use_color=False)

        assert "LOOPGUARD: Event Loop Blocked!" in text
        assert "GET /api/users" in text
        assert "deadbeef" in text
        assert "1 time(s), 3000.1ms total" in text
        # Invariant 6 wording: never claims to know the culprit
        assert "may be this request or any other concurrent request" in text
        assert "ALL requests were frozen" in text
        for fix in (
            "time.sleep(n)       -> await asyncio.sleep(n)",
            "requests.get(url)   -> await httpx.AsyncClient().get(url)",
            "open(f).read()      -> await aiofiles.open(f)",
            "subprocess.run(...) -> await asyncio.create_subprocess_exec(...)",
        ):
            assert fix in text
        assert "https://fastapi.tiangolo.com/async/" in text
        assert "\x1b[" not in text

    def test_color_rendering_is_plain_plus_escapes(self) -> None:
        import re

        ctx = self._ctx()
        colored = _format_console_warning(ctx, use_color=True)
        plain = _format_console_warning(ctx, use_color=False)

        assert "\x1b[" in colored
        stripped = re.sub(r"\x1b\[[0-9;]*m", "", colored)
        assert stripped == plain

    def test_color_decision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Tty:
            def isatty(self) -> bool:
                return True

        class _Pipe:
            def isatty(self) -> bool:
                return False

        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setattr("sys.stderr", _Tty())
        assert _console_supports_color() is True

        monkeypatch.setenv("NO_COLOR", "1")
        assert _console_supports_color() is False

        monkeypatch.delenv("NO_COLOR")
        monkeypatch.setattr("sys.stderr", _Pipe())
        assert _console_supports_color() is False


class TestErrorPageCodeBlocks:
    """The 503 page's code examples must keep their newlines (issue #10)."""

    def test_examples_are_pre_blocks_with_real_newlines(self) -> None:
        config = LoopGuardConfig(log_blocking_events=False)
        middleware = LoopGuardMiddleware(lambda: None, config=config)
        ctx = RequestContext(request_id="deadbeef", path="/api/users", method="GET")
        ctx.record_blocking(150.0)

        html = middleware._generate_error_html(ctx)

        assert '<pre class="code-block bad">' in html
        assert '<pre class="code-block good">' in html
        # Each example sits on its own line inside the <pre>
        assert "\ntime.sleep(1)\n" in html
        assert '\nrequests.get("https://api.example.com")\n' in html
        assert "\nawait asyncio.sleep(1)\n" in html
        # No div-wrapped code blocks remain (divs collapse the newlines)
        assert '<div class="code-block' not in html
