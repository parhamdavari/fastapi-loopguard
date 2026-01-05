# Configuration Reference

All configuration options for `LoopGuardConfig`.

## Quick Reference

```python
from fastapi_loopguard import LoopGuardConfig

config = LoopGuardConfig(
    # Enforcement
    enforcement_mode="warn",      # "log" | "warn" | "strict"
    dev_mode=False,               # Auto-escalates to strict when True

    # Detection tuning
    monitor_interval_ms=10.0,     # How often to check (ms)
    threshold_multiplier=5.0,     # Blocking = lag > baseline × multiplier
    fallback_threshold_ms=50.0,   # Threshold if calibration fails

    # Cumulative detection (enabled by default)
    cumulative_blocking_enabled=True,
    cumulative_blocking_threshold_ms=200.0,
    cumulative_window_ms=1000.0,

    # Adaptive threshold (disabled by default)
    adaptive_threshold=False,

    # Integrations
    prometheus_enabled=False,
    log_blocking_events=True,
)
```

---

## Core Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `True` | Master switch. Set `False` to disable entirely. |
| `enforcement_mode` | str | `"warn"` | How to respond: `"log"`, `"warn"`, or `"strict"` |
| `dev_mode` | bool | `False` | Enables response headers. Auto-escalates to strict mode. |
| `log_blocking_events` | bool | `True` | Log blocking events to console |
| `exclude_paths` | frozenset | `{"/health", ...}` | Paths to skip monitoring |

---

## Detection Tuning

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `monitor_interval_ms` | float | `10.0` | Sentinel check frequency (ms) |
| `threshold_multiplier` | float | `5.0` | Blocking detected when lag > baseline × this |
| `calibration_iterations` | int | `100` | Samples during startup calibration |
| `fallback_threshold_ms` | float | `50.0` | Used if calibration is unreliable |

---

## Cumulative Blocking Detection

Catches "death by a thousand cuts" - many small blocks that add up.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `cumulative_blocking_enabled` | bool | `True` | Enable cumulative detection |
| `cumulative_blocking_threshold_ms` | float | `200.0` | Alert if total blocking exceeds this... |
| `cumulative_window_ms` | float | `1000.0` | ...within this time window (ms) |

**Example:** With defaults, alerts if blocking totals >200ms within any 1-second window.

---

## Adaptive Threshold

Dynamically adjusts threshold based on observed latency. Useful for high-concurrency environments.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `adaptive_threshold` | bool | `False` | Enable adaptive mode |
| `adaptive_window_size` | int | `1000` | Samples in sliding window |
| `adaptive_percentile` | float | `0.95` | Percentile for baseline (0.5-0.99) |
| `adaptive_min_samples` | int | `100` | Min samples before activation |
| `adaptive_update_interval_ms` | float | `1000.0` | Recalculation frequency (ms) |

---

## Integrations

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `prometheus_enabled` | bool | `False` | Expose Prometheus metrics |

When enabled, exposes:
- `loopguard_blocking_events_total` - Counter of blocking events
- `loopguard_blocking_duration_ms` - Histogram of blocking durations

---

## Common Configurations

### Development (strict enforcement)
```python
config = LoopGuardConfig(dev_mode=True)
```

### Production (silent monitoring)
```python
config = LoopGuardConfig(
    enforcement_mode="log",
    prometheus_enabled=True,
)
```

### High-concurrency (adaptive threshold)
```python
config = LoopGuardConfig(
    adaptive_threshold=True,
    adaptive_percentile=0.99,
)
```

### Sensitive detection (lower threshold)
```python
config = LoopGuardConfig(
    monitor_interval_ms=5.0,
    threshold_multiplier=3.0,
    fallback_threshold_ms=30.0,
)
```
