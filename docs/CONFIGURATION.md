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

Two channels still work for those routes. The monitor logs each event as it is
detected, independently of the response. And `"warn"` and `"strict"` check again
after the handler returns, which is late enough to see a stall that began
mid-stream, so the console banner still reaches stderr — at most one banner per
request. Do not rely on response headers or strict mode to guard a streaming
endpoint.

---

## A note on the diagnostic headers

`x-request-id`, `x-blocking-count`, `x-blocking-total-ms` and
`x-blocking-detected` are sent by default in `"warn"` and `"strict"` — not only in
`dev_mode`. `dev_mode` exists to add them to `"log"` mode, which is otherwise
silent on the wire.

That means the defaults expose internal event-loop timing to every client. It is
what you want in development and CI. On a public service it is also the
reconnaissance step for a cheap availability attack: the headers tell an
unauthenticated caller exactly which of your endpoints stall the loop and by how
long. If you serve untrusted clients and would rather not publish it, choose
`enforcement_mode="log"` and leave `dev_mode` at `False` — that combination sends
no diagnostic headers at all — or strip the `x-blocking-*` headers at your
reverse proxy.

---

## Log output and JSON formatting

Every detected event produces one `WARNING` line on the `fastapi_loopguard`
logger, gated on `log_blocking_events`. By default it is plain text and goes
wherever your app's logging configuration sends it.

`fastapi_loopguard.logging` (imported by module path — it is deliberately not
re-exported from the package root) installs a handler on that logger, with an
optional JSON formatter:

```python
from fastapi_loopguard.logging import configure_logging

configure_logging(structured=True)  # JSON on stderr
```

That emits one JSON object per event:

```json
{"timestamp": "2026-09-11T14:12:14.591664+00:00", "level": "WARNING", "logger": "fastapi_loopguard", "message": "Event loop blocked for 494.06ms across 2 in-flight request(s): 59cb0aa5,7b1e2f04"}
```

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `level` | int | `logging.INFO` | Level set on the `fastapi_loopguard` logger |
| `structured` | bool | `False` | `True` uses `StructuredFormatter` (JSON); `False` a plain text formatter |
| `stream` | stream | `sys.stderr` | Where the handler writes |

`configure_logging` is idempotent — calling it again replaces the handler it
installed rather than stacking a duplicate — and it sets `propagate = False`, so
an app with its own root handler does not log every event twice. If you already
configure logging centrally, skip it and attach
`fastapi_loopguard.logging.StructuredFormatter()` to your own handler instead.

`StructuredFormatter` copies `path`, `method`, `lag_ms`, `request_id` and
`blocking_count` into the JSON object when a record carries them as `extra`
fields. The monitor's own line sets none of them — it summarises across all
in-flight requests in the message instead — and `log_blocking_event()` in the
same module, a helper for callers who want to emit their own per-request record,
sets the first four. Nothing in the library sets `blocking_count`: the formatter
will emit it from a record you build yourself, but never fills it in for you.

---

## Detection Tuning

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `monitor_interval_ms` | float | `10.0` | Sentinel check frequency (ms) |
| `threshold_multiplier` | float | `5.0` | Blocking detected when lag > baseline × this |
| `calibration_iterations` | int | `100` | Samples during startup calibration |
| `fallback_threshold_ms` | float | `50.0` | Threshold before/without calibration, and the hard ceiling a calibrated or adaptive threshold can never exceed. Must be ≥ `monitor_interval_ms` (lag below the sampling interval cannot be resolved). |

### The effective threshold is calibrated, and usually lower than the fallback

`fallback_threshold_ms` is a ceiling, not the value in force. At startup the
monitor measures the loop's idle baseline (the **minimum** of
`calibration_iterations` samples) and sets

```
threshold = clamp(baseline × threshold_multiplier,
                  monitor_interval_ms,          # floor: lag below the sampling
                                                # interval cannot be resolved
                  fallback_threshold_ms)        # ceiling: calibration may only
                                                # ever tighten detection
```

An idle loop has a very small baseline, so the product usually falls under the
floor and the threshold lands on `monitor_interval_ms` — 10 ms at the defaults,
not 50 ms. (Calibrating with the defaults on a quiet laptop while writing this
measured a 0.12 ms baseline and a 10 ms threshold.) That is why an app with no
traffic can log a line like `Event loop blocked for 19.01ms (no active
request)`: 19 ms is over the threshold actually in force. Those events are real
stalls with no request in flight to attribute them to — a background task, an
import, a GC pause — and the log line (plus the Prometheus counter, if enabled)
is the only channel that reports them, since there is no response to carry a
header.

Calibration runs in a background task started from the ASGI `lifespan.startup`
event. An app served without lifespan (an `httpx.ASGITransport` test, for
instance) starts the monitor lazily on the first request and stops it when the
last one finishes, so calibration rarely gets to complete there and
`fallback_threshold_ms` governs.

There is no switch that disables calibration. To keep the threshold at
`fallback_threshold_ms`, raise `threshold_multiplier` until
`baseline × multiplier` clears it (with a 0.12 ms baseline, `500.0` pins it at
50 ms); to loosen detection generally, raise `monitor_interval_ms`, which raises
the floor with it. `log_blocking_events=False` silences the line without
changing detection.

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
config = LoopGuardConfig()  # "warn" default already sends the x-blocking-* headers
```

### Development / CI (strict enforcement, 503 on blocking)
```python
config = LoopGuardConfig(enforcement_mode="strict")
```
Remember that this 503s every request in flight during a stall, not just the one
that blocked — see [Strict mode fails every request in flight](#strict-mode-fails-every-request-in-flight).
For a runnable `curl`/`httpx` check against an app running in this mode, see
[Checking a running app directly](AI-HARNESS.md#checking-a-running-app-directly).

**Do not run strict mode in production.** Blocking is attributed to every
request in flight during the stall, so one slow handler turns into 503s for
unrelated users. The 503 page is a debugging aid, not an error page for real
traffic.

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
