"""FastAPI LoopGuard - Detect event-loop blocking with per-request attribution.

Usage:
    from fastapi import FastAPI
    from fastapi_loopguard import LoopGuardMiddleware, LoopGuardConfig

    app = FastAPI()

    # Basic usage with defaults
    app.add_middleware(LoopGuardMiddleware)

    # Or with custom config
    config = LoopGuardConfig(
        dev_mode=True,  # Enable X-Blocking-* headers
        prometheus_enabled=True,  # Enable Prometheus metrics
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

__version__ = "0.3.0"

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
