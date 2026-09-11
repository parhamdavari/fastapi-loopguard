"""FastAPI LoopGuard - Detect event-loop blocking and report in-flight requests.

The sentinel measures event-loop lag, so it cannot identify the single
handler that blocked; it attributes each stall to every request that was
in flight at the time.

Usage:
    from fastapi import FastAPI
    from fastapi_loopguard import LoopGuardMiddleware, LoopGuardConfig

    app = FastAPI()

    # Basic usage with defaults ("warn": console warnings + x-blocking-* headers)
    app.add_middleware(LoopGuardMiddleware)

    # Or with custom config
    config = LoopGuardConfig(
        enforcement_mode="log",  # silent; no headers by default
        dev_mode=True,           # ...unless dev_mode adds them back
    )
    app.add_middleware(LoopGuardMiddleware, config=config)

The x-blocking-* response headers are sent by default in the "warn" and
"strict" enforcement modes; `dev_mode` only adds them in "log" mode, and
never changes the enforcement mode.

Headers and the strict-mode 503 are both decided at http.response.start, so
neither can report blocking that happens after the first chunk of a
StreamingResponse is on the wire. For streaming routes, the log output is
the channel that still reports.

v0.2.0 Changes:
    - Pure ASGI middleware (no BaseHTTPMiddleware)
    - Concurrent request tracking with RequestRegistry
    - Background calibration (first request not blocked)
    - Proper lifecycle management via ASGI lifespan

v0.3.0 Changes:
    - PEP 561 py.typed marker for type stub discovery
    - Adaptive thresholds for high-concurrency environments
    - Improved test coverage (logging, metrics, pytest plugin)
    - High-concurrency configuration documentation
"""

from importlib.metadata import version as _package_version

from .config import LoopGuardConfig
from .context import (
    RequestContext,
    RequestRegistry,
    get_active_requests,
    get_current_request,
    get_registry,
    register_request,
    unregister_request,
)
from .middleware import LoopGuardMiddleware
from .monitor import SentinelMonitor

__version__ = _package_version("fastapi-loopguard")

__all__ = [
    # Core classes
    "LoopGuardConfig",
    "LoopGuardMiddleware",
    "SentinelMonitor",
    # Context tracking
    "RequestContext",
    "RequestRegistry",
    "get_registry",
    "register_request",
    "unregister_request",
    "get_active_requests",
    "get_current_request",  # Backward compat
    # Version
    "__version__",
]
