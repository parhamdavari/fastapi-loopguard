# Findings not fixed in the 0.5/0.6 passes

Everything noticed while fixing the 0.5 correctness defects (and the 0.6
hardening pass) but deliberately left alone. Each item is its own future task.

Linked from the README, so it is checked against the code rather than left to
rot: every item below was re-verified on 2026-09-11. Items that have since been
fixed are struck through with a note, not deleted.

## Detection design

1. ~~**Sub-threshold noise can still inflate the adaptive threshold.**~~
   **Fixed in the 0.6 pass:** the adaptive threshold is now clamped to the
   `fallback_threshold_ms` ceiling, closing both the one-step inflation and
   the compounding ratchet (each raise widened the censor gate). Median+MAD
   over the censored window remains a possible refinement below the ceiling.

2. **Strict mode cannot fail a response after `http.response.start` has passed.**
   If blocking is first detected mid-stream, the 200 and its headers are
   already on the wire and the body keeps streaming; the response then claims
   no blocking. Inherent to header-based reporting. Documented by test
   (`test_enforcement_mode.py::TestStrictModeStreaming`). Related accepted
   behavior, also documented by test: if the app raises after strict mode
   swallowed its `http.response.start`, the exception wins — the client gets
   the server's 500, not LoopGuard's 503.

3. **Explicit strict mode still 503s all in-flight requests.**
   The sentinel cannot name the culprit, so strict mode punishes bystanders
   under concurrency. Now opt-in and documented, but the real per-callback
   attribution rewrite (the 0.5+ plan) is what removes this.

4. **Lazy mode (no ASGI lifespan) rarely completes calibration.**
   The stop-when-idle lifecycle cancels background calibration when the last
   request finishes, so lifespan-less deployments run on the fallback
   threshold and have no between-request monitoring. Accepted tradeoff for
   not leaking tasks; worth a README note if such deployments matter.

## ASGI / architecture

5. **`exclude_paths` matches the raw `scope["path"]`.**
   Breaks under `root_path` and `Mount`, and `/health/live` is not excluded by
   `/health`. Prefix or route-template matching would fix it.

6. **Module-global `RequestRegistry` breaks with two apps in one process.**
   A mounted sub-app or a second middleware-wrapped app cross-attributes
   blocking between apps. Keying state per middleware instance (or per loop)
   would fix it.

7. **The package could be zero-dependency.**
   `middleware.py` imports only type aliases from `starlette.types`; moving
   that import under `TYPE_CHECKING` removes the runtime dependency entirely
   (works on Litestar, Quart, Django ASGI, ...). ~~Also, the `<1.0` upper bound
   on starlette will block installs the day Starlette 1.0 ships.~~ — the bound
   was widened to `<2.0` in #4; the `TYPE_CHECKING` move is still open.

8. **`get_current_request()` returns an arbitrary active context.**
   A backward-compat shim that silently gives wrong answers under concurrency.
   Pre-1.0 with few users, removal is cheaper than the confusion.

## Dead / inert code and docs drift

9. ~~**`prometheus_enabled` is inert**~~ — fixed. `monitor.__init__` imports
   `metrics.py` lazily when the flag is set, and records blocking events,
   monitored requests and the current threshold.

10. ~~**`_generate_warning_banner()` is dead code**~~ — removed. It was also
    an unescaped-HTML template, so leaving it in the file was an invitation to
    wire up an XSS hole later.

11. ~~**`docs/CONFIGURATION.md` names metrics that do not exist** and
    `get_metrics()` can never find an instance~~ — both fixed. The docs list
    the four real metrics with their labels, and `get_metrics()` takes the
    registry so it derives the same key `create_metrics()` wrote.

12. ~~**`docs/CONFIGURATION.md` describes `fallback_threshold_ms` as "Used if
    calibration is unreliable"**~~ — fixed in the 0.6 pass; the docs now
    describe it as the hard ceiling.

13. ~~**`_handle_lifespan` locals `started` / `shutdown_complete` are
    write-only.**~~ — removed in the 0.6 pass.

14. ~~**The `structlog` extra is declared but nothing imports structlog**~~ —
    the extra was removed rather than wired in (#51).

## Repro caveat worth keeping

15. **Calibration poisoning (defect 2) required blocking to span the whole
    calibration window.** With idle gaps, clean tail samples dominated and the
    old `max(..., fallback)` floor masked the bug. The fix removes the
    mechanism either way, but tests that "prove" poisoning need dense blocking.

## Accepted in the 0.6 hardening pass (documented, not fixed)

16. **Installing the middleware twice injects duplicate `x-*` headers.**
    Nothing marks a scope as already instrumented; two instances register two
    contexts per request and both send wrappers extend the headers. Low
    priority — a doubled middleware is a user configuration error.

17. **`Accept` negotiation is a bare substring test with last-header-wins.**
    Duplicate `Accept` headers collapse via `dict()`, and q-values are
    ignored, so `text/html;q=0.1, application/json;q=0.9` still gets the HTML
    page. Cosmetic: only chooses the error-page format.

18. **8-hex-char request ids (32 bits) can collide silently.** A collision
    overwrites the registry entry and the first unregister removes the second
    request's context. Birthday bound is ~77k concurrent in-flight requests;
    accepted as unrealistic, noted here so it is a known trade.

19. **The pytest plugin's clock-drift check (#83) needs a tolerance, not an
    exact match, because uvloop's `loop.time()` is not read fresh on every
    call.** libuv (and therefore uvloop) caches the loop's notion of "now"
    once per iteration rather than calling the OS clock on every `time()`
    access, so two `loop.time()` reads a few microseconds apart on a busy
    uvloop can legitimately return the same (or a slightly stale) value even
    with no tampering at all. `BlockingDetector` compares a tick's `loop.time()`
    -measured elapsed against the same tick measured on the pinned real
    clock (`_REAL_MONOTONIC`) and only distrusts the clock past one monitor
    interval (5ms) of disagreement — comparing for exact equality would
    false-positive on every uvloop suite on this basis alone. No test in
    this repo runs under uvloop, so this is a reasoned default, not a
    measurement.

20. **A `time.monotonic` tamper fully undone before `BlockingDetector` next
    runs is undetectable, and this is not closable by a cleverer check.**
    While the clock is frozen, the event loop cannot run at all — a
    synchronous block prevents that regardless of tampering — so nothing in
    `pytest_plugin.py` executes during the freeze to record anything about
    it. By the time anything of the detector's runs again, `time.monotonic`
    may already be the real function once more, and every measurement taken
    from that point (identity, or elapsed-since-any-earlier-checkpoint on
    either clock) reads exactly as it would for a slow but healthy tick,
    because both clocks are now reading the same underlying source again.
    "Tampered, then fully restored" and "slow but healthy" are the same
    measurement, not merely a close one — no tolerance value, drift
    formula, or additional clock source changes that, because the
    information needed to tell them apart was never observable in the
    first place. A fallback that flagged any tick whose own real-clock lag
    exceeded one monitor interval (with no drift or identity evidence at
    all) was tried and reverted: it "closed" this gap only by also flagging
    every sufficiently long *legitimate* block, and reproducibly
    false-positived (~200ms) on this project's own bounded-worst-case test
    pattern — a real, deliberate, generously-thresholded block via
    `@pytest.mark.no_blocking(threshold_ms=...)`, exactly the case
    documented as legitimate elsewhere in this file and in CLAUDE.md. What
    the design keeps instead: `poll()` measures every tick against
    `_REAL_MONOTONIC`, never `time.monotonic`, so a block that happens
    *behind* a freeze is still caught as lag once the tick is measured —
    the freeze itself stays invisible, but a genuine block inside it never
    does.

## Fixed since the first draft

- Adaptive mode discarding the calibrated threshold (floor pinned at the
  fallback, first update firing immediately) — fixed on this branch; the
  adaptive floor now follows the calibrated threshold.
- CLAUDE.md invariants 4 and 6 and known gaps 1-2 describing pre-0.5
  behavior — CLAUDE.md updated on this branch.
