"""FastAPI LoopGuard - Detect event-loop blocking and report in-flight requests.

The sentinel measures event-loop lag, so it cannot identify the single
handler that blocked; it attributes each stall to every request that was
in flight at the time.

Usage:
    from fastapi import FastAPI
    from fastapi_loopguard import LoopGuardMiddleware, LoopGuardConfig

    app = FastAPI()

    # Basic usage with defaults
    app.add_middleware(LoopGuardMiddleware)

    # Or with custom config
    config = LoopGuardConfig(
        dev_mode=True,  # Enable X-Blocking-* headers
    )
    app.add_middleware(LoopGuardMiddleware, config=config)

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
