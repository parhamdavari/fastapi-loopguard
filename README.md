<p align="center">
  <img src="assets/loopguard-logo.webp" alt="LoopGuard logo" width="320" />
</p>

<h1 align="center">fastapi-loopguard</h1>

<p align="center">
  Detect event-loop blocking in FastAPI/Starlette with <strong>per-request attribution</strong>.
</p>

---

[![PyPI version](https://badge.fury.io/py/fastapi-loopguard.svg)](https://badge.fury.io/py/fastapi-loopguard)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## The Problem

Your async FastAPI app might be secretly synchronous. Common culprits:

```python
# These block the event loop!
time.sleep(1)           # Use: await asyncio.sleep(1)
requests.get(url)       # Use: httpx.AsyncClient
open(file).read()       # Use: aiofiles
```

When code blocks the event loop, **all concurrent requests wait**. But existing tools only show global metrics — you can't tell *which endpoint* is blocking.

## The Solution

`fastapi-loopguard` monitors your event loop and tells you exactly which request caused the blocking:

```
WARNING: Event loop blocked for 150.23ms during GET /api/users
```

## Installation

```bash
pip install fastapi-loopguard
```

## Quick Start

```python
from fastapi import FastAPI
from fastapi_loopguard import LoopGuardMiddleware, LoopGuardConfig

app = FastAPI()

# Basic usage
app.add_middleware(LoopGuardMiddleware)

# Or with configuration
config = LoopGuardConfig(
    dev_mode=True,           # Add X-Blocking-* headers to responses
    prometheus_enabled=True,  # Expose Prometheus metrics
)
app.add_middleware(LoopGuardMiddleware, config=config)
```

## Dev Mode Headers

When `dev_mode=True`, every response includes:

```
X-Request-Id: abc123
X-Blocking-Count: 2
X-Blocking-Total-Ms: 156.34
X-Blocking-Detected: true
```

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `True` | Enable/disable monitoring |
| `monitor_interval_ms` | `10` | How often to check for blocking (ms) |
| `threshold_multiplier` | `5` | Blocking = lag > baseline × multiplier |
| `dev_mode` | `False` | Add debug headers to responses |
| `log_blocking_events` | `True` | Log when blocking detected |
| `prometheus_enabled` | `False` | Expose Prometheus metrics |
| `exclude_paths` | `{"/health", ...}` | Paths to skip monitoring |

### Adaptive Threshold (v0.3.0+)

| Option | Default | Description |
|--------|---------|-------------|
| `adaptive_threshold` | `False` | Enable adaptive threshold based on sliding window |
| `adaptive_window_size` | `1000` | Number of samples in sliding window |
| `adaptive_percentile` | `0.95` | Percentile (0.5-0.99) for baseline calculation |
| `adaptive_min_samples` | `100` | Minimum samples before adapting |
| `adaptive_update_interval_ms` | `1000` | How often to recalculate threshold |

## High-Concurrency Configuration

Different environments need different settings to balance detection sensitivity with false positive rates:

| Environment | Users | Recommended Settings |
|------------|-------|---------------------|
| Development | 1-10 | Default settings |
| Staging | 10-100 | `threshold_multiplier=8` |
| Production | 100-500 | `adaptive_threshold=True` |
| High-traffic | 500+ | `adaptive_threshold=True`, `adaptive_percentile=0.99` |

### Example: High-Concurrency Production

```python
config = LoopGuardConfig(
    adaptive_threshold=True,
    adaptive_window_size=2000,
    adaptive_percentile=0.99,
    fallback_threshold_ms=100.0,  # Higher minimum
)
app.add_middleware(LoopGuardMiddleware, config=config)
```

Adaptive mode automatically adjusts the threshold based on observed latency patterns, reducing false positives in high-concurrency environments where event loop scheduling jitter increases naturally.

## How It Works

1. **Calibration**: On startup, measures baseline event loop latency
2. **Sentinel Task**: Continuously sleeps for small intervals, measuring actual delay
3. **Detection**: If actual delay >> expected delay, the loop was blocked
4. **Attribution**: Uses `contextvars` to know which request was active during blocking

## Performance

The sentinel uses cooperative `asyncio.sleep()` — it doesn't consume CPU while waiting. Overhead is approximately **0.002% CPU** (20 microseconds per second).

## License

MIT
