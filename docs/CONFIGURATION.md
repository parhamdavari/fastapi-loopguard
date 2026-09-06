# Configuration Reference

All configuration options for `LoopGuardConfig`.

## Quick Reference

```python
from fastapi_loopguard import LoopGuardConfig

config = LoopGuardConfig(
    # Enforcement
    enforcement_mode="warn",      # "log" | "warn" | "strict"
    dev_mode=False,               # Adds X-Blocking-* response headers when True

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
| `dev_mode` | bool | `False` | Enables response headers. Never changes the enforcement mode. |
| `log_blocking_events` | bool | `True` | Log blocking events to console |
| `exclude_paths` | frozenset | `{"/health", ...}` | Paths to skip monitoring |

---

## Detection Tuning

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `monitor_interval_ms` | float | `10.0` | Sentinel check frequency (ms) |
| `threshold_multiplier` | float | `5.0` | Blocking detected when lag > baseline × this |
| `calibration_iterations` | int | `100` | Samples during startup calibration |
| `fallback_threshold_ms` | float | `50.0` | Threshold before/without calibration, and the hard ceiling a calibrated or adaptive threshold can never exceed. Must be ≥ `monitor_interval_ms` (lag below the sampling interval cannot be resolved). |

**Validation:** `exclude_paths` must be a collection of paths — a bare string is rejected (it would silently become a substring match).

---

## Cumulative Blocking Detection

Catches "death by a thousand cuts" - many small blocks that add up.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `cumulative_blocking_enabled` | bool | `True` | Enable cumulative detection |
| `cumulative_blocking_threshold_ms` | float | `200.0` | Alert if total blocking exceeds this... |
| `cumulative_window_ms` | float | `1000.0` | ...within this time window (ms) |

**Example:** With defaults, alerts if blocking totals >200ms within any 1-second window.

Only lag **in excess of the calibrated baseline** counts toward the window sum, so platform timer jitter on an idle loop cannot accumulate into a false positive.

---

## Adaptive Threshold

Dynamically adjusts threshold based on observed latency. Useful for high-concurrency environments.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `adaptive_threshold` | bool | `False` | Enable adaptive mode |
| `adaptive_window_size` | int | `1000` | Samples in sliding window |
| `adaptive_percentile` | float | `0.95` | Percentile for baseline (0.5-0.99) |
| `adaptive_min_samples` | int | `100` | Min samples before activation |
| `adaptive_update_interval_ms` | float | `1000.0` | Recalculation frequency (ms). Must be ≥ `monitor_interval_ms`. |

The adaptive threshold is clamped to `[calibrated threshold, fallback_threshold_ms]`: adaptation may tighten detection but can never raise the threshold above the fallback, so a noisy loop cannot ratchet the detector blind.

---

## Integrations

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `prometheus_enabled` | bool | `False` | Expose Prometheus metrics |

Requires the extra: `pip install fastapi-loopguard[prometheus]`. Without it the
flag logs an error once and metrics stay off; the app still starts.

When enabled, registers on the default `prometheus_client` registry:

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `loopguard_blocking_total` | Counter | `event_type` | Blocking events, one increment per event |
| `loopguard_lag_seconds` | Histogram | `event_type` | Measured loop lag |
| `loopguard_requests_monitored_total` | Counter | `route`, `method` | Requests completed through the middleware |
| `loopguard_threshold_seconds` | Gauge | — | Current detection threshold |

`event_type` is `single` for one over-threshold sample and `cumulative` for a
saturated window. They are different quantities — a window sum is not a stall
duration — so keep them apart when you compute percentiles.

**Blocking carries no route label, by design.** The sentinel measures loop lag,
not call stacks, so it cannot say which endpoint blocked. A route label there
would read as an accusation the data does not support.

`route` is the matched route template (`/users/{user_id}`), never the raw
request path. The raw path is client-controlled and unbounded, so using it as
a label would let anyone grow your process's memory by requesting random URLs;
unmatched requests collapse to `unmatched`, non-standard HTTP verbs to `other`,
and the whole label set is capped at 200 distinct pairs as a backstop.

Serve the metrics yourself, for example with `prometheus_client.make_asgi_app()`
mounted on your app.

---

## Common Configurations

### Development (diagnostic headers)
```python
config = LoopGuardConfig(dev_mode=True)
```

### Development / CI (strict enforcement, 503 on blocking)
```python
config = LoopGuardConfig(enforcement_mode="strict")
```

**Do not run strict mode in production.** Blocking is attributed to every
request in flight during the stall, so one slow handler turns into 503s for
unrelated users. The 503 page is a debugging aid, not an error page for real
traffic.

### A note on the diagnostic headers

`x-blocking-count` and `x-blocking-total-ms` go to every client, including in
the default `warn` mode. They tell an unauthenticated caller exactly which of
your endpoints stall the loop and by how long, which is the reconnaissance
step for a cheap availability attack on an async app. If your service is
public and you only want the logs, use `enforcement_mode="log"` with
`dev_mode=False`, which sends no diagnostic headers at all.

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
