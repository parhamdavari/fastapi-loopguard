# Findings not fixed in the 0.5 pass

Everything noticed while fixing the 0.5 correctness defects but deliberately
left alone. Each item is its own future task.

## Detection design

1. **Adaptive threshold discards the calibrated threshold.**
   `AdaptiveThreshold` is constructed with `min_threshold_ms = fallback_threshold_ms`
   and `recalculate()` returns `_current_threshold_ms` even below `min_samples`.
   Because `_last_adapt_time` starts at `0.0`, the first monitor iteration
   immediately overwrites a calibration-tightened threshold (e.g. 10ms) back to
   the 50ms fallback. Calibration and adaptive mode fight each other; adaptive
   effectively wins on the first tick.

2. **Sub-threshold noise can still inflate the adaptive threshold.**
   The 0.5 fix censors detected-blocking samples out of the window, but samples
   just below the threshold are admitted by design, and
   `P95 x threshold_multiplier` of ~40ms noise still produces a ~230ms
   threshold that would mask a later 100ms block. Per the forensics guidance,
   median+MAD over the censored window would be more robust than a percentile.

3. **Strict mode cannot fail a response after `http.response.start` has passed.**
   If blocking is first detected mid-stream, the 200 and its headers are
   already on the wire and the body keeps streaming; the response then claims
   no blocking. Inherent to header-based reporting; worth documenting.

4. **Explicit strict mode still 503s all in-flight requests.**
   The sentinel cannot name the culprit, so strict mode punishes bystanders
   under concurrency. Now opt-in and documented, but the real per-callback
   attribution rewrite (the 0.5+ plan) is what removes this.

5. **Lazy mode (no ASGI lifespan) rarely completes calibration.**
   The stop-when-idle lifecycle cancels background calibration when the last
   request finishes, so lifespan-less deployments run on the fallback
   threshold and have no between-request monitoring. Accepted tradeoff for
   not leaking tasks; worth a README note if such deployments matter.

## ASGI / architecture

6. **`exclude_paths` matches the raw `scope["path"]`.**
   Breaks under `root_path` and `Mount`, and `/health/live` is not excluded by
   `/health`. Prefix or route-template matching would fix it.

7. **Module-global `RequestRegistry` breaks with two apps in one process.**
   A mounted sub-app or a second middleware-wrapped app cross-attributes
   blocking between apps. Keying state per middleware instance (or per loop)
   would fix it.

8. **The package could be zero-dependency.**
   `middleware.py` imports only type aliases from `starlette.types`; moving
   that import under `TYPE_CHECKING` removes the runtime dependency entirely
   (works on Litestar, Quart, Django ASGI, ...). Also, the `<1.0` upper bound
   on starlette will block installs the day Starlette 1.0 ships.

9. **`get_current_request()` returns an arbitrary active context.**
   A backward-compat shim that silently gives wrong answers under concurrency.
   Pre-1.0 with few users, removal is cheaper than the confusion.

## Dead / inert code and docs drift

10. **`prometheus_enabled` is inert** (known gap #3): nothing on the detection
    path imports `metrics.py`. Out of scope here (`metrics.py` untouchable).

11. **`_generate_warning_banner()` is dead code** (known gap #6).

12. **`docs/CONFIGURATION.md` names metrics that do not exist** (known gap #4)
    and `get_metrics()` can never find an instance (known gap #5).

13. **Docs drift created by the 0.5 fixes themselves:**
    - `CLAUDE.md` invariant 4 (P75 baseline), invariant 6 (dev_mode
      escalation), and known gaps 1-2 describe pre-0.5 behavior. CLAUDE.md has
      uncommitted local edits, so it was left untouched.
    - `docs/CONFIGURATION.md` describes `fallback_threshold_ms` as "Used if
      calibration is unreliable"; since 0.5 it is the hard ceiling for the
      calibrated threshold.

14. **`_handle_lifespan` locals `started` / `shutdown_complete` are write-only.**

15. **The `structlog` extra is declared but nothing imports structlog**
    (already noted in CLAUDE.md).

## Repro caveat worth keeping

16. **Calibration poisoning (defect 2) required blocking to span the whole
    calibration window.** With idle gaps, clean tail samples dominated and the
    old `max(..., fallback)` floor masked the bug. The fix removes the
    mechanism either way, but tests that "prove" poisoning need dense blocking.
