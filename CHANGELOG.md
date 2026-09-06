# Changelog

## Unreleased

### Security

- **Reflected XSS in the strict-mode 503 page.** `_generate_error_html`
  interpolated the request method and path into HTML with no escaping, and
  ASGI servers percent-decode the path — so a request for
  `/%3Cscript%3E...%3C/script%3E` with `Accept: text/html` executed attacker
  JavaScript on the application's own origin. Because blocking attributes to
  every request in flight, the attacker only had to have a request in flight
  while any other request stalled the loop. Both values are now escaped, and
  the never-called `_generate_warning_banner()` — which had the same hole —
  is deleted. Present since strict mode shipped; the JSON error body was
  never affected.
- **Unbounded Prometheus label cardinality.** With `prometheus_enabled=True`,
  metrics were labelled by the raw request path. Every distinct URL minted a
  child metric that is never evicted, so unauthenticated traffic to random
  paths grew process memory without bound — and ordinary traffic to a route
  with a path parameter did the same on its own. Requests are now labelled by
  the matched route template, unmatched requests collapse to `unmatched`,
  non-standard HTTP verbs to `other`, and the label set is capped at 200
  pairs. This shipped inert (nothing imported `metrics.py`), so no released
  version was exploitable.
- **Log injection through the console banner.** The blocking banner printed
  the decoded request path to stderr raw, so `%0A` forged lines in any log
  aggregator reading it. Control characters are now escaped.
- `docs/CONFIGURATION.md` now says plainly that strict mode must not run in
  production, and that the diagnostic headers tell any unauthenticated client
  which endpoints stall the loop.

### Fixed

- **Blocking that ended without an `await` went unreported.** The sentinel
  measures a tick by resuming from its own sleep, so a handler — or a test —
  that blocked and then returned without awaiting left that sleep expired and
  never measured: strict mode returned 200, warn mode reported
  `x-blocking-detected: false`, and the pytest harness scored the test clean.
  This is the ordinary shape of blocking code, so the miss was the common
  case, not an edge case. `SentinelMonitor.poll()` now takes a synchronous
  measurement on the response path, and `BlockingDetector.stop()` drains its
  monitor instead of cancelling it. The monitor loop then reports only the
  residual of a polled tick, so a stall spanning a response is reported in
  full and no millisecond is counted twice.
- **A cancelled or recovering monitor invented blocking.** `poll()` measured
  against the tick marker even when the monitor task had been cancelled or
  was inside its error-recovery sleep, reporting a stall that grew with
  wall-clock time — a 503, in strict mode, for a request that did nothing
  wrong. Those paths now clear the marker, and `poll()` refuses to measure a
  tick no live task owns.
- **The middleware could fail a request it was only observing.** The response
  path measurement and the request counter both ran unguarded, and the
  measurement runs before `unregister_request` — so an exception leaked the
  request context permanently, after which every later blocking event
  attributed to a request that had long finished. Both now swallow and log.
- **A Prometheus registration failure took the app down.** Only the
  missing-package case was caught, so a duplicate registration on the
  process-wide registry failed startup, or the first request on apps without
  lifespan. Any setup failure now disables metrics and logs.
- `BlockingDetector.stop()` bounds its drain and no longer lets a monitor
  exception replace a test's own failure.
- **`prometheus_enabled` now exposes metrics.** Nothing on the detection path
  imported `metrics.py`, so the flag did nothing at all. The monitor records
  `loopguard_blocking_total`, `loopguard_lag_seconds`,
  `loopguard_requests_monitored_total` and `loopguard_threshold_seconds`.
  Blocking metrics carry an `event_type` label (`single` / `cumulative`) and
  no route label: the sentinel measures loop lag, not call stacks, so it
  cannot say which endpoint blocked, and one event is one increment rather
  than one per in-flight request.
  Without the `prometheus` extra installed the flag logs an error once and
  stays off rather than failing the app.
- **`get_metrics()` could never find an instance.** It looked up the bare
  prefix while `create_metrics()` stored `prefix` plus registry identity. It
  now takes the registry and derives the same key.
- `docs/CONFIGURATION.md` listed two metric names that do not exist. It now
  documents the four real ones, their labels, and how to serve them.

### Changed

- **The minimum Python is now 3.11**, down from 3.12. Nothing in the library
  needed 3.12; the real floor is `asyncio.Task.cancelling()`, which landed in
  3.11. CI runs 3.11, 3.12 and 3.13.

---

The `evals/` benchmark and the claims it backs were
corrected; `README.md` and `docs/AI-HARNESS.md` now quote the new figures.

- The scorer no longer reports an unmeasured sample as non-blocking. A
  solution that failed to import, returned empty, or was rejected before the
  endpoint body was recorded as `non_blocking: true` and kept in the
  blocked-rate denominator — a bias with only one direction, pointing at the
  headline number. Verdicts now carry `measured`, and unmeasured samples are
  excluded from those denominators. 105 of 560 samples were affected.
- An empty completion from a provider is retried and then raised, instead of
  being written out as an empty `app.py` and scored as a model failure.
- Code extraction prefers the last fenced block that parses and defines `app`,
  and tolerates a language tag glued to the first statement. Previously a
  response that re-listed `helpers.py` could have that listing saved as the
  solution.
- Task prompts are condition-symmetric: `neutral/task.md` and `hinted/task.md`
  now differ by exactly one added sentence on all eight tasks. Three pairs
  previously differed by more, including one with different functional specs.
  Tasks 02, 03 and 04 were regenerated against the corrected prompts.
- Each task's checks assert the provided helper actually ran, so a hardcoded
  response cannot score as functional and non-blocking.
- Request pacing and retry with backoff are in the harness rather than
  described in prose, so the published run is reproducible from the repository.
- `python-multipart` and `aiofiles` are declared in `evals/requirements.txt`;
  without them the judge failed valid solutions at import.
- New: `python evals/matrix.py --rescore` re-judges every committed solution
  with no API calls.

## 0.6.1 (2026-08-12)

- The console blocking banner is restyled: a slim rule frame instead of
  the `=`/`!` walls, with ANSI color hierarchy (headline red, explanation
  dim, fixes cyan) on real terminals. Redirected streams and `NO_COLOR`
  environments get identical plain text, so log grep patterns keep
  working. (#9)
- The 503 page's BAD/GOOD code examples render each snippet on its own
  line again: the blocks are now `<pre>` elements; the previous `<div>`s
  collapsed the newlines. (#10)

## 0.6.0 (2026-08-12)

Detection-core hardening plus the AI test harness. Fixes found by a
line-by-line audit of the detection path; every item below changes
observable behavior.

- The adaptive threshold can no longer ratchet itself blind. Recalculation
  is clamped to the `fallback_threshold_ms` ceiling; previously each raise
  widened the censor gate that admits the next round of samples, compounding
  50 -> 241 -> 573ms within seconds on merely-noisy traffic.
- Cumulative detection no longer counts timer jitter. The window now sums
  baseline-corrected excess lag (`max(0, lag - baseline)`); raw per-tick
  platform jitter (~2ms idle on macOS) alone could previously cross the
  200ms default within one 1000ms window on a completely idle loop.
- Lazy stop/start race fixed: a request arriving while the monitor was
  stopping (last request just finished) used to observe stale lifecycle
  flags and run unmonitored. Flags are now cleared before the stop awaits,
  so a mid-stop request starts a fresh monitor.
- `stop()` no longer swallows a cancellation aimed at the calling task.
  It runs inside request `finally` blocks; the old
  `suppress(CancelledError)` turned client disconnects and server shutdown
  into requests that ignored their own cancellation.
- `stop()` issued during a blocking `start()` calibration now vetoes the
  loop start instead of being a silent no-op.
- A lifespan app that raises no longer leaks the monitor tasks.
- One blocking event now logs exactly one summary line instead of one line
  per in-flight request (O(N) log formatting on the loop thread right after
  a stall). The per-context `on_blocking` callback contract is unchanged.
- New config validation: `fallback_threshold_ms >= monitor_interval_ms`,
  `adaptive_update_interval_ms >= monitor_interval_ms`, and `exclude_paths`
  may not be a bare string (it would silently become a substring match).
- Strict mode's clean-path headers are now computed from the request
  context instead of hardcoded zero literals.
- Calibration clamps a negative raw baseline (timers may fire up to
  clock_resolution early) to 0.

AI test harness (pytest plugin):

- New `loopguard_all_async` mode (ini or `--loopguard-all-async`): every
  async test is treated as `@pytest.mark.no_blocking`, with a new
  `@pytest.mark.allow_blocking` opt-out marker. Built for gating
  AI-generated code without per-test annotations.
- New `loopguard_report` option (ini or `--loopguard-report=PATH`): writes
  a JSON verdict file at session end with per-test blocking events and
  concrete sync->async fix hints. See `docs/AI-HARNESS.md`.
- The detector is now armed before the test body runs. A test that blocked
  before its first real await (an ASGI request dispatch does exactly that)
  was previously invisible to the gate.
- BREAKING: the `loopguard_detector` fixture was removed. It yielded a
  detector that was never started, so assertions on its (always empty)
  `blocking_events` passed unconditionally.
- `@pytest.mark.no_blocking` on a synchronous test now emits a warning
  instead of silently doing nothing.
- The plugin no longer calls `asyncio.iscoroutinefunction` (deprecated on
  Python 3.14), so downstream suites running `-W error` stay green.
- `BlockingDetector.stop()` no longer swallows the test's own cancellation.

Also:

- New `evals/` directory: a starter benchmark (5 FastAPI tasks + runner)
  scoring whether an AI model writes non-blocking async code.
- `configure_logging()` is idempotent and disables propagation;
  `StructuredFormatter` preserves `exc_info` tracebacks.
- `prometheus-client` joined the `dev` extra so the metrics tests run in CI.

## 0.5.0 (2026-08-11)

Correctness release. Every fix below changes externally observable behavior.

- `dev_mode` no longer turns blocking into 503s. Previously, one endpoint's
  sync block made every concurrent innocent request fail with 503 while the
  actual culprit returned 200. `dev_mode` now only adds diagnostic headers;
  a 503 requires explicitly setting `enforcement_mode="strict"`. Docs no
  longer claim the library identifies which endpoint caused blocking — it
  reports the requests that were in flight during the stall.
- A single blocking event is reported once, not twice. A 300ms block used to
  produce two events summing to ~600ms in headers and logs (single-shot plus
  a cumulative re-count of the same sample). Cumulative window sums are now
  recorded separately from individual lag samples.
- Calibration can no longer be poisoned by the app's own blocking. Background
  calibration during a busy blocking startup used to raise the detection
  threshold to ~8x the fallback, after which real blocking went undetected.
  A calibrated threshold now only ever tightens the fallback.
- The adaptive threshold no longer chases sustained blocking. ~120 blocks of
  ~70ms used to yield ~9 detections and a final threshold near 380ms;
  detection now keeps firing for the whole run.
- Adaptive mode no longer discards a calibration-tightened threshold. Its
  floor used to be pinned at the fallback and its first update fired
  immediately, snapping a calibrated 10ms threshold back to 50ms on the
  first tick. The floor now follows the calibrated threshold.
- Responses using ASGI extension messages no longer hang in strict mode:
  `http.response.pathsend` (Starlette `FileResponse` on Hypercorn/Granian),
  `http.response.trailers`, and unknown message types now pass through.
- `"trailers": True` and any other key on `http.response.start` survive
  header injection instead of being silently dropped.
- The monitor no longer leaks background tasks when startup fails
  (`lifespan.startup.failed` / `lifespan.shutdown.failed` now stop it), and a
  lazily started monitor (apps without lifespan, e.g. tests using
  `httpx.ASGITransport`) stops when the last in-flight request finishes.
- `__version__` now matches the installed package metadata (it was hard-coded
  to 0.3.0 while the package shipped as 0.4.1), and the 503 error page links
  to the real repository.
