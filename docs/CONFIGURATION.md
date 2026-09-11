# Configuration Reference

All configuration options for `LoopGuardConfig`.

## Quick Reference

```python
from fastapi_loopguard import LoopGuardConfig

config = LoopGuardConfig(
    # Enforcement
    enforcement_mode="warn",      # "log" | "warn" | "strict"
    dev_mode=False,               # Adds x-blocking-* headers in "log" mode only;
                                  # "warn" and "strict" send them regardless

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
| `enforcement_mode` | `Literal["log", "warn", "strict"]` | `"warn"` | How to respond: `"log"`, `"warn"`, or `"strict"`. See [Enforcement modes](#enforcement-modes) — `"strict"` fails every request in flight, not just the one that blocked. |
| `dev_mode` | bool | `False` | Adds the `x-blocking-*` response headers **in `"log"` mode only**. `"warn"` and `"strict"` send them regardless, so the flag has no effect there, and it never changes the enforcement mode. See [A note on the diagnostic headers](#a-note-on-the-diagnostic-headers). |
| `log_blocking_events` | bool | `True` | Log blocking events to console |
| `exclude_paths` | frozenset | `{"/health", ...}` | Paths to skip monitoring |

---

## Enforcement modes

| Mode | Response | Log output | `x-blocking-*` headers |
|------|----------|-----------|------------------------|
| `"log"` | untouched | one `WARNING` line per event on the `fastapi_loopguard` logger | only when `dev_mode=True` |
| `"warn"` (default) | untouched | the same log line, plus a console banner on stderr | always |
| `"strict"` | `503` + educational HTML/JSON page | the same log line, plus the console banner | always (the 503 carries its own header set, with `x-loopguard-enforcement: strict` and no `x-blocking-detected`) |

The log line comes from the monitor and is gated on `log_blocking_events`
(default `True`); the console banner is not.

### Strict mode fails every request in flight

The sentinel measures event-loop lag, not call stacks, so it cannot name the
handler that blocked. Every stall is attributed to **all** requests that were in
flight while the loop was frozen — and in strict mode every one of them receives
the 503, with the same body and the same `x-blocking-total-ms`.

Concretely: 100 concurrent requests arrive and one of them calls
`time.sleep(0.5)`. All 100 return 503. The other 99 did nothing wrong; they were
awaiting correctly while the loop was frozen. A purely `await`-based endpoint left
in flight is 503'd by a blocking call made in a different request 200ms later.

That blast radius is why strict mode is opt-in and why `dev_mode` cannot turn it
on. Keep it to development and CI; in production use `"warn"` or `"log"`.

### Streaming responses are a blind spot

Headers and the strict-mode 503 are both decided at `http.response.start`, and
Starlette's `StreamingResponse` sends that message before the body generator runs.
So for `StreamingResponse`, SSE, and token-streaming endpoints:

- response headers cannot report blocking that happens after the first chunk is on
  the wire — headers cannot be revised once sent, so the response claims
  `x-blocking-detected: false`;
- strict mode cannot 503 a response whose `200` has already shipped.

The channel that still works for those routes is the log output: the monitor logs
each event as it is detected, independently of the response, so
`enforcement_mode="log"` (or `"warn"`) reports the stall even when no header can.
Do not rely on response headers or strict mode to guard a streaming endpoint.

---

## A note on the diagnostic headers

`x-request-id`, `x-blocking-count`, `x-blocking-total-ms` and
`x-blocking-detected` are sent by default in `"warn"` and `"strict"` — not only in
`dev_mode`. `dev_mode` exists to add them to `"log"` mode, which is otherwise
silent on the wire.

That means the defaults expose internal event-loop timing to every client. It is
what you want in development and CI. If you serve untrusted clients and would
rather not publish it, choose `enforcement_mode="log"` and leave `dev_mode` at
`False`, or strip the `x-blocking-*` headers at your reverse proxy.

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

When enabled, exposes:
- `loopguard_blocking_events_total` - Counter of blocking events
- `loopguard_blocking_duration_ms` - Histogram of blocking durations

---

## Common Configurations

### Development (diagnostic headers)
```python
config = LoopGuardConfig()  # "warn" default already sends the x-blocking-* headers
```

### Development / CI (strict enforcement, 503 on blocking)
```python
config = LoopGuardConfig(enforcement_mode="strict")
```
Remember that this 503s every request in flight during a stall, not just the one
that blocked — see [Strict mode fails every request in flight](#strict-mode-fails-every-request-in-flight).

### Production (silent monitoring)
```python
config = LoopGuardConfig(
    enforcement_mode="log",
    prometheus_enabled=True,
)
```

### Production with the diagnostic headers kept
```python
config = LoopGuardConfig(
    enforcement_mode="log",
    dev_mode=True,  # the only mode where dev_mode changes anything
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
