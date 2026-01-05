"""LoopGuard middleware for FastAPI/Starlette.

This is a pure ASGI middleware implementation that avoids the issues
with BaseHTTPMiddleware (deprecated, breaks contextvars, memory leaks).
"""

from __future__ import annotations

import json
import sys
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
            # Determine effective enforcement mode
            effective_mode = self._get_effective_enforcement_mode()

            if effective_mode == "strict":
                await self._handle_strict_mode(scope, receive, send, ctx)
            elif effective_mode == "warn":
                await self._handle_warn_mode(scope, receive, send, ctx)
            elif self._config.dev_mode:
                # "log" mode with dev headers
                await self._handle_with_headers(scope, receive, send, ctx)
            else:
                # "log" mode without headers
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

    def _get_effective_enforcement_mode(self) -> str:
        """Get the effective enforcement mode, considering dev_mode escalation.

        When dev_mode=True and enforcement_mode is not explicitly "log",
        auto-escalate to "strict" for maximum learning impact.
        """
        if self._config.dev_mode and self._config.enforcement_mode != "log":
            return "strict"
        return self._config.enforcement_mode

    def _get_client_accepts_html(self, scope: Scope) -> bool:
        """Check if client prefers HTML based on Accept header."""
        headers = dict(scope.get("headers", []))
        accept = headers.get(b"accept", b"").decode("utf-8", errors="ignore")
        return "text/html" in accept

    def _log_console_warning(self, ctx: RequestContext) -> None:
        """Print attention-grabbing console warning to stderr."""
        warning = f"""
{"=" * 72}
{"!" * 72}
  LOOPGUARD: Event Loop Blocked!
{"!" * 72}

  Request: {ctx.method} {ctx.path}
  Request ID: {ctx.request_id}
  Blocked: {ctx.blocking_count} time(s), {ctx.total_blocking_ms:.1f}ms total

  Your async code ran BLOCKING operations.
  ALL other requests were frozen while waiting.

  Common fixes:
    time.sleep(n)       -> await asyncio.sleep(n)
    requests.get(url)   -> await httpx.AsyncClient().get(url)
    open(f).read()      -> await aiofiles.open(f)
    subprocess.run(...) -> await asyncio.create_subprocess_exec(...)

  Docs: https://fastapi.tiangolo.com/async/
{"=" * 72}
"""
        print(warning, file=sys.stderr)

    def _generate_error_html(self, ctx: RequestContext) -> str:
        """Generate educational HTML error page for strict mode."""
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Event Loop Blocked - LoopGuard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            background: #0f0f23;
            color: #cccccc;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .error-box {{
            background: linear-gradient(135deg, #dc2626, #b91c1c);
            padding: 24px;
            border-radius: 12px;
            margin-bottom: 32px;
            box-shadow: 0 4px 24px rgba(220, 38, 38, 0.3);
        }}
        .error-box h1 {{
            color: white;
            font-size: 1.75rem;
            margin-bottom: 16px;
        }}
        .error-box p {{
            color: rgba(255,255,255,0.9);
            font-size: 1rem;
            line-height: 1.6;
        }}
        .error-box code {{
            background: rgba(0,0,0,0.2);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'SF Mono', Monaco, monospace;
        }}
        h2 {{
            color: #fbbf24;
            font-size: 1.25rem;
            margin: 24px 0 12px;
        }}
        .code-block {{
            background: #1e1e3f;
            border-radius: 8px;
            padding: 16px;
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 0.9rem;
            overflow-x: auto;
            margin: 12px 0;
        }}
        .bad {{ border-left: 4px solid #dc2626; }}
        .good {{ border-left: 4px solid #22c55e; }}
        .bad-label {{ color: #f87171; font-weight: bold; margin-bottom: 8px; }}
        .good-label {{ color: #4ade80; font-weight: bold; margin-bottom: 8px; }}
        .comment {{ color: #6b7280; }}
        ul {{ margin-left: 24px; line-height: 2; }}
        a {{ color: #60a5fa; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #333;
            color: #666;
            font-size: 0.875rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="error-box">
            <h1>Event Loop Blocked!</h1>
            <p>
                <strong>Request:</strong> <code>{ctx.method} {ctx.path}</code><br>
                <strong>Blocked:</strong> {ctx.blocking_count} time(s),
                totaling <code>{ctx.total_blocking_ms:.1f}ms</code>
            </p>
        </div>

        <h2>What Happened?</h2>
        <p>
            Your async endpoint executed <strong>synchronous (blocking) code</strong>
            that froze the event loop. During this time, ALL other requests were
            waiting and couldn't be processed.
        </p>

        <h2>Common Causes & Fixes</h2>

        <div class="bad-label">BAD - These block the event loop:</div>
        <div class="code-block bad">
<span class="comment"># Sleeping</span>
time.sleep(1)

<span class="comment"># HTTP requests</span>
requests.get("https://api.example.com")

<span class="comment"># File I/O</span>
open("data.json").read()

<span class="comment"># Subprocess</span>
subprocess.run(["ls", "-la"])
        </div>

        <div class="good-label">GOOD - Use async alternatives:</div>
        <div class="code-block good">
<span class="comment"># Sleeping</span>
await asyncio.sleep(1)

<span class="comment"># HTTP requests</span>
async with httpx.AsyncClient() as client:
    await client.get("https://api.example.com")

<span class="comment"># File I/O</span>
async with aiofiles.open("data.json") as f:
    await f.read()

<span class="comment"># Subprocess</span>
proc = await asyncio.create_subprocess_exec("ls", "-la")
await proc.wait()
        </div>

        <h2>Quick Fixes</h2>
        <ul>
            <li>Use <code>asyncio.to_thread(func)</code> for CPU-bound work</li>
            <li>Replace <code>requests</code> with <code>httpx</code></li>
            <li>Replace <code>open()</code> with <code>aiofiles</code></li>
            <li>Use async database drivers (asyncpg, aiomysql, motor)</li>
        </ul>

        <h2>Learn More</h2>
        <p>
            <a href="https://fastapi.tiangolo.com/async/">FastAPI Async</a> &bull;
            <a href="https://docs.python.org/3/library/asyncio.html">asyncio Docs</a>
        </p>

        <div class="footer">
            Request ID: {ctx.request_id} &bull;
            Detected by <a href="https://github.com/pyhub-kr/fastapi-loopguard">LoopGuard</a>
        </div>
    </div>
</body>
</html>"""

    def _generate_error_json(self, ctx: RequestContext) -> str:
        """Generate educational JSON error response for API clients."""
        return json.dumps(
            {
                "error": "event_loop_blocked",
                "message": "Blocking operation detected in async endpoint",
                "request": {
                    "id": ctx.request_id,
                    "method": ctx.method,
                    "path": ctx.path,
                },
                "blocking": {
                    "count": ctx.blocking_count,
                    "total_ms": round(ctx.total_blocking_ms, 2),
                },
                "help": {
                    "problem": "Synchronous code blocked the async event loop",
                    "common_causes": [
                        "time.sleep() -> await asyncio.sleep()",
                        "requests.get() -> await httpx.AsyncClient().get()",
                        "open().read() -> await aiofiles.open()",
                        "subprocess.run() -> asyncio.create_subprocess_exec()",
                        "CPU-bound work -> asyncio.to_thread(func)",
                    ],
                    "docs": "https://fastapi.tiangolo.com/async/",
                },
            },
            indent=2,
        )

    def _generate_warning_banner(self, ctx: RequestContext) -> str:
        """Generate HTML warning banner for injection into responses."""
        return f"""
<div id="loopguard-warning" style="
    position: fixed; top: 0; left: 0; right: 0; z-index: 99999;
    background: linear-gradient(90deg, #dc2626, #f87171);
    color: white; padding: 12px 20px; font-family: system-ui, sans-serif;
    font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    display: flex; align-items: center; justify-content: space-between;
">
    <span>
        <strong>LoopGuard:</strong> Event loop blocked {ctx.blocking_count}x
        ({ctx.total_blocking_ms:.1f}ms) during {ctx.method} {ctx.path}
        <a href="https://fastapi.tiangolo.com/async/"
           style="color: white; margin-left: 8px;">Learn about async</a>
    </span>
    <button onclick="this.parentElement.remove()" style="
        background: none; border: none; color: white;
        cursor: pointer; font-size: 20px; padding: 0 8px;
    ">&times;</button>
</div>
"""

    async def _send_strict_error(
        self,
        send: Send,
        ctx: RequestContext,
        accepts_html: bool,
    ) -> None:
        """Send 503 error response with educational content."""
        if accepts_html:
            body = self._generate_error_html(ctx)
            content_type = b"text/html; charset=utf-8"
        else:
            body = self._generate_error_json(ctx)
            content_type = b"application/json"

        body_bytes = body.encode("utf-8")

        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"content-type", content_type),
                    (b"content-length", str(len(body_bytes)).encode()),
                    (b"x-request-id", ctx.request_id.encode()),
                    (b"x-blocking-count", str(ctx.blocking_count).encode()),
                    (
                        b"x-blocking-total-ms",
                        f"{ctx.total_blocking_ms:.2f}".encode(),
                    ),
                    (b"x-loopguard-enforcement", b"strict"),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body_bytes,
            }
        )

    async def _handle_warn_mode(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        ctx: RequestContext,
    ) -> None:
        """Handle request in warn mode - loud warnings but response passes through."""
        response_started = False
        warning_logged = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started, warning_logged

            if message["type"] == "http.response.start" and not response_started:
                response_started = True

                # Add warning headers
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

                if ctx.blocking_count > 0:
                    headers.append((b"x-loopguard-warning", b"blocking-detected"))
                    # Log console warning once
                    if not warning_logged:
                        self._log_console_warning(ctx)
                        warning_logged = True

                message = {
                    "type": message["type"],
                    "status": message.get("status", 200),
                    "headers": headers,
                }

            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _handle_strict_mode(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        ctx: RequestContext,
    ) -> None:
        """Handle request in strict mode - return 503 if blocking detected."""
        response_started = False
        blocking_detected = False
        accepts_html = self._get_client_accepts_html(scope)

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started, blocking_detected

            if message["type"] == "http.response.start" and not response_started:
                response_started = True

                # Check if blocking was detected
                if ctx.blocking_count > 0:
                    blocking_detected = True
                    # Don't send original response headers
                    return

                # No blocking - add headers and pass through
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", ctx.request_id.encode()),
                        (b"x-blocking-count", b"0"),
                        (b"x-blocking-total-ms", b"0.00"),
                        (b"x-blocking-detected", b"false"),
                    ]
                )

                message = {
                    "type": message["type"],
                    "status": message.get("status", 200),
                    "headers": headers,
                }
                await send(message)

            elif message["type"] == "http.response.body":
                if blocking_detected:
                    # Skip original body - we'll send error response after
                    return
                await send(message)

        await self.app(scope, receive, send_wrapper)

        # If blocking was detected, send error response
        if blocking_detected:
            self._log_console_warning(ctx)
            await self._send_strict_error(send, ctx, accepts_html)
