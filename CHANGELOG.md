# Changelog

## 0.6.0 (unreleased)

Detection-core hardening. Fixes found by a line-by-line audit of the
detection path; every item below changes observable behavior.

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
