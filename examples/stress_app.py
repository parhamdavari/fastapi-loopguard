"""Stress test application for LoopGuard validation.

This FastAPI application provides various endpoint types to thoroughly test
the LoopGuard middleware under pressure:

- Fast endpoints (baseline)
- Async non-blocking endpoints
- Blocking CPU-bound endpoints
- Blocking I/O-bound endpoints
- Mixed workload endpoints
- Diagnostic endpoints

Usage:
    python examples/stress_app.py

    # Or with uvicorn directly:
    uvicorn examples.stress_app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from fastapi_loopguard import LoopGuardConfig, LoopGuardMiddleware, get_registry

app = FastAPI(
    title="LoopGuard Stress Test",
    description="Test application for validating LoopGuard under pressure",
    version="0.2.0",
)

# Aggressive config for stress testing
config = LoopGuardConfig(
    enabled=True,
    dev_mode=True,
    monitor_interval_ms=5.0,  # Fast detection
    threshold_multiplier=2.0,  # Sensitive
    calibration_iterations=20,  # Quick startup
    fallback_threshold_ms=10.0,  # Low threshold
    log_blocking_events=True,
)
app.add_middleware(LoopGuardMiddleware, config=config)


# ============== FAST ENDPOINTS ==============


@app.get("/")
async def root() -> dict[str, str]:
    """Instant response - baseline."""
    return {"status": "ok", "type": "fast"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check - excluded from monitoring."""
    return {"status": "healthy"}


# ============== ASYNC (NON-BLOCKING) ENDPOINTS ==============


@app.get("/async/short")
async def async_short() -> dict[str, Any]:
    """Short async sleep - should NOT trigger blocking."""
    await asyncio.sleep(0.01)  # 10ms
    return {"status": "ok", "type": "async", "delay_ms": 10}


@app.get("/async/medium")
async def async_medium() -> dict[str, Any]:
    """Medium async sleep - should NOT trigger blocking."""
    await asyncio.sleep(0.05)  # 50ms
    return {"status": "ok", "type": "async", "delay_ms": 50}


@app.get("/async/long")
async def async_long() -> dict[str, Any]:
    """Long async sleep - should NOT trigger blocking."""
    await asyncio.sleep(0.1)  # 100ms
    return {"status": "ok", "type": "async", "delay_ms": 100}


# ============== BLOCKING ENDPOINTS (CPU-BOUND) ==============


@app.get("/blocking/short")
async def blocking_short() -> dict[str, Any]:
    """Short blocking - SHOULD trigger detection."""
    time.sleep(0.02)  # 20ms blocking
    await asyncio.sleep(0.01)  # Give monitor time
    return {"status": "blocked", "type": "cpu", "delay_ms": 20}


@app.get("/blocking/medium")
async def blocking_medium() -> dict[str, Any]:
    """Medium blocking - SHOULD trigger detection."""
    time.sleep(0.05)  # 50ms blocking
    await asyncio.sleep(0.01)
    return {"status": "blocked", "type": "cpu", "delay_ms": 50}


@app.get("/blocking/long")
async def blocking_long() -> dict[str, Any]:
    """Long blocking - SHOULD trigger detection (multiple events)."""
    time.sleep(0.1)  # 100ms blocking
    await asyncio.sleep(0.01)
    return {"status": "blocked", "type": "cpu", "delay_ms": 100}


@app.get("/blocking/cpu-intensive")
async def blocking_cpu() -> dict[str, Any]:
    """CPU-intensive work - SHOULD trigger detection."""
    # Simulate CPU-bound work
    data = b"x" * 1000000
    for _ in range(50):
        hashlib.sha256(data).hexdigest()
    await asyncio.sleep(0.01)
    return {"status": "blocked", "type": "cpu-intensive"}


# ============== BLOCKING ENDPOINTS (I/O-BOUND) ==============


@app.get("/blocking/file-read")
async def blocking_file() -> dict[str, Any]:
    """Synchronous file I/O - SHOULD trigger detection."""
    # Read a file synchronously (blocking)
    with contextlib.suppress(Exception):
        Path("/etc/passwd").read_text()
    time.sleep(0.03)  # Simulate slow disk
    await asyncio.sleep(0.01)
    return {"status": "blocked", "type": "file-io"}


# ============== MIXED WORKLOAD ENDPOINTS ==============


@app.get("/mixed/mostly-async")
async def mixed_mostly_async() -> dict[str, Any]:
    """Mostly async with small blocking section."""
    await asyncio.sleep(0.05)
    time.sleep(0.015)  # Small blocking
    await asyncio.sleep(0.02)
    return {"status": "mixed", "blocking_ms": 15}


@app.get("/mixed/mostly-blocking")
async def mixed_mostly_blocking() -> dict[str, Any]:
    """Mostly blocking with async sections."""
    await asyncio.sleep(0.01)
    time.sleep(0.04)
    await asyncio.sleep(0.01)
    time.sleep(0.03)
    await asyncio.sleep(0.01)
    return {"status": "mixed", "blocking_ms": 70}


# ============== DIAGNOSTIC ENDPOINTS ==============


@app.get("/debug/registry")
async def debug_registry() -> dict[str, Any]:
    """Return current registry state."""
    registry = get_registry()
    return {
        "active_count": registry.active_count(),
        "active_ids": [ctx.request_id for ctx in registry.get_all_active()],
    }


@app.get("/debug/config")
async def debug_config() -> dict[str, Any]:
    """Return current LoopGuard configuration."""
    return {
        "enabled": config.enabled,
        "dev_mode": config.dev_mode,
        "monitor_interval_ms": config.monitor_interval_ms,
        "threshold_multiplier": config.threshold_multiplier,
        "calibration_iterations": config.calibration_iterations,
        "fallback_threshold_ms": config.fallback_threshold_ms,
        "exclude_paths": list(config.exclude_paths),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
