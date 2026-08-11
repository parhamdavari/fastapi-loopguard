# Changelog

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
