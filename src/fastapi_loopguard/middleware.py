"""LoopGuard middleware for FastAPI/Starlette.

This is a pure ASGI middleware implementation that avoids the issues
with BaseHTTPMiddleware (deprecated, breaks contextvars, memory leaks).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .context import RequestContext, register_request, unregister_request
from .monitor import SentinelMonitor

if TYPE_CHECKING:
    from .config import LoopGuardConfig


class LoopGuardMiddleware:
    """Pure ASGI middleware that detects event loop blocking per-request.

    This middleware:
    1. Handles ASGI lifespan for proper startup/shutdown
    2. Registers request contexts for attribution
    3. Manages the sentinel monitor lifecycle
    4. Adds debug headers in dev mode via send wrapper

    Usage:
        from fastapi import FastAPI
        from fastapi_loopguard import LoopGuardMiddleware, LoopGuardConfig

        app = FastAPI()
        config = LoopGuardConfig(dev_mode=True)
        app.add_middleware(LoopGuardMiddleware, config=config)

    Improvements in v0.2.0:
    - Pure ASGI implementation (no BaseHTTPMiddleware)
    - Proper lifespan handling for monitor lifecycle
    - Background calibration (first request not blocked)
    - Send wrapper for header injection
    """

    __slots__ = ("app", "_config", "_monitor", "_started")

    def __init__(
        self,
        app: ASGIApp,
        config: LoopGuardConfig | None = None,
    ) -> None:
        """Initialize the middleware.

        Args:
            app: The ASGI application to wrap.
            config: Optional configuration. Uses defaults if not provided.
        """
        self.app = app

        # Import here to avoid circular imports
        from .config import LoopGuardConfig as ConfigClass

        self._config = config or ConfigClass()
        self._monitor: SentinelMonitor | None = None
        self._started = False

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """ASGI interface implementation.

        Args:
            scope: The connection scope.
            receive: Async callable to receive messages.
            send: Async callable to send messages.
        """
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
        elif scope["type"] == "http":
            await self._handle_http(scope, receive, send)
        else:
            # WebSocket or other types - pass through
            await self.app(scope, receive, send)

    async def _handle_lifespan(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Handle lifespan events for proper startup/shutdown.

        Intercepts lifespan messages to start/stop the monitor.
        """
        started = False
        shutdown_complete = False

        async def receive_wrapper() -> Message:
            nonlocal started
            message = await receive()

            if message["type"] == "lifespan.startup":
                # Start monitor before signaling startup complete
                if self._config.enabled and not self._started:
                    await self._start_monitor()
                started = True

            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal shutdown_complete

            if message["type"] == "lifespan.shutdown.complete":
                # Stop monitor after app signals shutdown complete
                if self._monitor:
                    await self._monitor.stop()
                    self._monitor = None
                    self._started = False
                shutdown_complete = True

            await send(message)

        await self.app(scope, receive_wrapper, send_wrapper)

    async def _start_monitor(self) -> None:
        """Start the sentinel monitor with background calibration."""
        if self._started:
            return

        self._monitor = SentinelMonitor(self._config)
        # Use background calibration so first request isn't blocked
        await self._monitor.start_with_background_calibration()
        self._started = True

    async def _handle_http(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Handle HTTP requests with context tracking.

        Registers request context, calls app, adds debug headers.
        """
        path = scope.get("path", "")

        # Skip monitoring for excluded paths
        if path in self._config.exclude_paths:
            await self.app(scope, receive, send)
            return

        # Skip if disabled
        if not self._config.enabled:
            await self.app(scope, receive, send)
            return

        # Lazy start for apps without lifespan events
        if not self._started:
            await self._start_monitor()

        # Create and register request context
        request_id = str(uuid.uuid4())[:8]
        method = scope.get("method", "UNKNOWN")

        ctx = RequestContext(
            request_id=request_id,
            path=path,
            method=method,
        )

        # Store request_id in scope state for handlers to access
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["loopguard_request_id"] = request_id

        register_request(ctx)

        try:
            if self._config.dev_mode:
                # Use send wrapper to inject headers
                await self._handle_with_headers(scope, receive, send, ctx)
            else:
                await self.app(scope, receive, send)
        finally:
            unregister_request(request_id)

    async def _handle_with_headers(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        ctx: RequestContext,
    ) -> None:
        """Handle request with debug header injection.

        Uses a send wrapper to add X-Request-Id, X-Blocking-Count, etc.
        headers to the response.
        """
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started

            if message["type"] == "http.response.start" and not response_started:
                response_started = True

                # Get existing headers and add our debug headers
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", ctx.request_id.encode()),
                        (b"x-blocking-count", str(ctx.blocking_count).encode()),
                        (
                            b"x-blocking-total-ms",
                            f"{ctx.total_blocking_ms:.2f}".encode(),
                        ),
                        (
                            b"x-blocking-detected",
                            b"true" if ctx.blocking_count > 0 else b"false",
                        ),
                    ]
                )

                # Create new message with updated headers
                message = {
                    "type": message["type"],
                    "status": message.get("status", 200),
                    "headers": headers,
                }

            await send(message)

        await self.app(scope, receive, send_wrapper)
