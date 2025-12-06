# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

fastapi-loopguard is a middleware library that detects event-loop blocking in FastAPI/Starlette applications with per-request attribution. It identifies when synchronous operations (like `time.sleep()`, blocking I/O, or CPU-bound code) block the async event loop and reports which request was responsible.

## Development Commands

```bash
# Install dependencies (including dev tools)
pip install -e ".[dev]"

# Run tests
pytest

# Run single test
pytest tests/test_middleware.py::TestLoopGuardMiddleware::test_dev_mode_headers

# Type checking (strict mode)
mypy src/

# Linting and formatting
ruff check src/ tests/
ruff format src/ tests/

# Coverage
coverage run -m pytest && coverage report
```

## Architecture

### Core Components

**LoopGuardMiddleware** (`middleware.py`): Pure ASGI middleware (no BaseHTTPMiddleware) that:
- Handles ASGI lifespan events for proper startup/shutdown of the monitor
- Registers request contexts for attribution via `RequestRegistry`
- Injects debug headers (X-Request-Id, X-Blocking-Count, etc.) in dev mode via send wrapper

**SentinelMonitor** (`monitor.py`): Background async task that detects blocking by:
1. Sleeping for short intervals (default 10ms)
2. Measuring actual elapsed time vs expected time
3. If lag exceeds threshold (baseline × multiplier), blocking occurred
4. Attributes blocking to ALL active requests since we can't determine the specific cause

**RequestRegistry** (`context.py`): Thread-safe (via single-threaded asyncio) registry tracking concurrent requests. Uses dict keyed by request_id. When blocking is detected, the monitor iterates all active contexts.

**LoopGuardConfig** (`config.py`): Frozen dataclass with validation. Key settings:
- `monitor_interval_ms`: Check frequency (default 10ms)
- `threshold_multiplier`: Blocking = lag > baseline × multiplier (default 5.0)
- `dev_mode`: Enables X-Blocking-* response headers
- `adaptive_threshold`: Enable sliding-window based automatic threshold adjustment (v0.3.0+)

**AdaptiveThreshold** (`monitor.py`): Sliding window percentile-based threshold calculator:
- Maintains a bounded deque of recent lag samples (`adaptive_window_size`)
- Recalculates threshold as `P{adaptive_percentile} × multiplier`
- Only activates after `adaptive_min_samples` collected
- Reduces false positives in high-concurrency environments

### Blocking Detection Flow

1. Middleware registers `RequestContext` in global `RequestRegistry`
2. `SentinelMonitor` runs continuous sleep-measure loop
3. On startup: background calibration measures baseline latency (P75 of samples)
4. When lag > threshold: `_handle_blocking()` iterates all active contexts via `get_active_requests()`
5. Each context's `record_blocking()` appends event to `blocking_events` list
6. On response: middleware reads context stats and adds headers

### Optional Components

- **Prometheus metrics** (`metrics.py`): Optional `prometheus_client` integration
- **pytest plugin** (`pytest_plugin.py`): `@pytest.mark.no_blocking` marker fails tests that block

## Test Configuration

- Uses `pytest-asyncio` with `asyncio_mode = "auto"` and `asyncio_default_fixture_loop_scope = "function"`
- Tests use `httpx.AsyncClient` with `ASGITransport` for testing ASGI apps
- Each test clears the global `RequestRegistry` via `clear_registry` fixture
