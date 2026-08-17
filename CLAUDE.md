# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

fastapi-loopguard — a middleware library that detects event-loop blocking in FastAPI/Starlette apps with per-request attribution. When synchronous code (`time.sleep`, blocking I/O, CPU-bound work) freezes the async event loop, LoopGuard reports which requests were in flight and, depending on enforcement mode, warns, logs, or fails the response with an educational 503.

**Division of docs — do not duplicate them here.** `README.md` owns the pitch, install, and quick-start snippet. `docs/CONFIGURATION.md` is the authoritative reference for every `LoopGuardConfig` option and the recommended recipes; add new options there. This file owns architecture, invariants, and workflow.

There is no CONTRIBUTING.md. Release history lives in `CHANGELOG.md` (since 0.5.0) and in git tags (`v0.3.0` …).

## Quick Start

```bash
pip install -e ".[dev]"                  # dev deps: pytest, mypy, ruff, coverage, httpx, fastapi
pytest                                   # full suite (asyncio_mode=auto, testpaths=tests)
pytest tests/test_middleware.py::TestLoopGuardMiddleware::test_dev_mode_headers   # one test
mypy src/                                # strict mode, src/ only
ruff check src/ tests/                   # lint — CI runs this exact scope
ruff format --check src/ tests/          # CI verifies formatting; drop --check to rewrite
coverage run -m pytest tests/ && coverage report --fail-under=80   # the CI gate

pip install -e ".[stress]"               # everything under examples/ needs uvicorn + locust
python examples/demo_app.py              # demo on :8765 — /api/users returns 503 (strict mode)
python examples/stress_app.py            # stress target on :8000
python examples/run_stress_test.py --skip-locust   # validation suite against a running :8000
```

CI lints and type-checks `src/` and `tests/` only — `examples/` is unchecked and does not satisfy the `ANN` rules the rest of the tree does. `tests/test_metrics.py` skips entirely unless `.[prometheus]` is installed, which is why `metrics.py` reports 0% coverage on a plain `.[dev]` run; the 80% gate still passes at ~88% overall.

## Tech Stack (versions verified 2026-08-11)

- Python `>=3.12`; CI matrix is 3.12 and 3.13. mypy is pinned to `python_version = "3.12"` with `strict = true`.
- **One runtime dependency: `starlette>=0.37.0,<1.0`.** FastAPI is a *dev* dependency — the middleware is pure ASGI and must never import `fastapi` from `src/`. Adding any runtime dependency requires asking first.
- Extras: `prometheus` (prometheus-client), `structlog`, `all`, `dev`, `stress` (locust + uvicorn). The `structlog` extra is currently declared but unused — nothing imports structlog.
- ruff selects `["E","F","I","N","W","UP","B","C4","SIM","ANN"]`, ignoring only `ANN401`. **`ANN` means every function needs full annotations**, tests and fixtures included. Line length 88, double quotes.
- Build backend is hatchling; wheel packages `src/fastapi_loopguard`. Publishing triggers on a `v*` tag via PyPI trusted publishing (OIDC) — there is **no version-bump automation**, so `pyproject.toml` must be bumped by hand. `__init__.__version__` is derived from installed package metadata; after bumping, re-run `pip install -e .` or the version tests fail against stale metadata.
- `.claude/` is git-ignored and excluded from the sdist. Committing anything there needs an explicit `.gitignore` negation.

## Architecture

```
src/fastapi_loopguard/
  config.py         LoopGuardConfig — frozen slotted dataclass + __post_init__ validation
  context.py        RequestContext, RequestRegistry, module-global _registry, free functions
  monitor.py        SentinelMonitor sleep-measure loop, AdaptiveThreshold
  middleware.py     pure-ASGI LoopGuardMiddleware, enforcement modes, HTML/JSON error pages
  logging.py        StructuredFormatter (JSON), configure_logging, log_blocking_event
  metrics.py        optional Prometheus LoopGuardMetrics (see Known Gaps — not wired in)
  pytest_plugin.py  pytest11 entry point, @pytest.mark.no_blocking, BlockingDetector
```

**Layering (strict — a module imports only lower layers):** `config`, `context` → `monitor` → `middleware`. `logging`, `metrics`, and `pytest_plugin` are leaves; nothing on the detection path imports them, and they must not import `middleware`. `middleware.py` imports `LoopGuardConfig` inside `__init__` with an "avoid circular imports" comment — the cycle no longer exists, but the deferred import is harmless and not worth churning.

`pytest_plugin.py` is registered as a `pytest11` entry point, so it auto-loads for **every** project that installs this package. Treat its hooks as public API and keep them cheap and side-effect-free for unmarked tests.

**Detection flow:** ASGI `lifespan.startup` starts the monitor → `_handle_http` skips `exclude_paths`, then registers a `RequestContext` and writes the id to `scope["state"]["loopguard_request_id"]` → `_monitor_loop` sleeps `monitor_interval_ms` and computes `lag_ms = (elapsed - interval) * 1000` → lag over threshold calls `_handle_blocking`, which calls `record_blocking` on every active context → the send wrapper reads `ctx.blocking_count` / `ctx.total_blocking_ms` and emits headers or a 503 → `finally` unregisters (and stops a lazily started monitor once the registry empties) → any terminal lifespan message (`shutdown.complete`, `shutdown.failed`, `startup.failed`) stops the monitor.

## Detection Invariants (non-negotiable)

1. **Pure ASGI — never `BaseHTTPMiddleware`.** It is deprecated, breaks contextvars, and leaks memory. `__call__` dispatches on `scope["type"]`; WebSocket and every other type pass through untouched, with no context registered.
2. **Blocking attributes to ALL active requests.** The sentinel measures loop lag, not call stacks, so it cannot know which request blocked. `_handle_blocking` iterates every context from `get_active_requests()` and records the same lag on each. This over-reports under concurrency **by design** — narrowing it is a redesign, not a bug fix.
3. **The registry needs no locks.** asyncio is single-threaded, so `RequestRegistry` is a plain dict keyed by `request_id`. Never add a lock, a `threading` primitive, or thread-safety without first changing that premise and saying so.
4. **Calibration never blocks the first request, and can only tighten.** `start_with_background_calibration()` starts `_monitor_loop` immediately on `fallback_threshold_ms` and calibrates in a named background task. Baseline is the **minimum** of `calibration_iterations` samples (the idle floor — robust to contamination from live traffic), and the calibrated threshold is clamped to `[monitor_interval_ms, fallback_threshold_ms]`: it may lower the fallback, never raise it. The adaptive window is censored (only sub-threshold samples admitted), its floor follows the calibrated threshold, and its recalculated value is clamped to the `fallback_threshold_ms` ceiling — without the ceiling each raise widens the censor gate and the threshold ratchets upward unboundedly. So neither calibration nor adaptation can be poisoned upward by the app's own blocking or its noise. A failed or cancelled calibration keeps the fallback threshold and must never raise into startup. Config guarantees `fallback_threshold_ms >= monitor_interval_ms`, so the clamp can never invert.
5. **Unregister always runs.** `_handle_http` wraps dispatch in `try/finally: unregister_request(request_id)`. An exception from the wrapped app must never leak a context into the registry — a leak makes every later blocking event attribute to a dead request forever.
6. **`dev_mode` is headers-only; a 503 requires explicit strict mode.** `_get_effective_enforcement_mode()` always returns `enforcement_mode` — `dev_mode` never changes it. Because blocking is attributed to ALL in-flight requests (invariant 2), a status change punishes innocent bystanders, so it must stay opt-in via `enforcement_mode="strict"`. No text anywhere may claim the library identifies WHICH endpoint blocked — it narrows it to the requests in flight during the stall.
7. **One blocking event is reported exactly once.** A sample that fires the single-shot detection is never appended to `_lag_history`, within one `_monitor_loop` iteration a single-lag trigger suppresses the cumulative one, and `_lag_history` is cleared after a cumulative fire so a window reports at most once. The window stores **baseline-corrected excess lag** (`max(0, lag - baseline)`), never raw lag — raw per-tick timer jitter alone would sum past the default cumulative threshold on an idle loop. Cumulative window sums are recorded in `RequestContext.cumulative_events`, separate from the individual-lag `blocking_events` list; `blocking_count` / `total_blocking_ms` sum both. One event also emits exactly **one log line** (a summary across in-flight requests), never one line per context — no O(N) work on the loop thread right after a stall.
8. **Lifecycle calls are idempotent, race-free, and cancellation-safe; lazy monitors stop when idle.** `start()`, `start_with_background_calibration()`, and `stop()` all return early when already in the target state. `start()` marks `_running` **before** its blocking calibration so a concurrent `stop()` vetoes the loop start. `_stop_monitor` clears `_started`/`_lazy_started`/`_monitor` **before** awaiting the monitor's stop — that await yields, and a request arriving mid-stop must see `_started=False` and start a fresh monitor rather than run unmonitored. `stop()` awaits cancelled tasks via `_cancel_and_wait`, which re-raises when the *calling* task has a pending cancellation (it runs inside request `finally` blocks; a bare `suppress(CancelledError)` would make requests ignore their own cancellation). A lifespan app that raises gets the monitor stopped in the `except` path, not leaked. `_handle_http` lazily starts the monitor for apps that run without ASGI lifespan and stops it when the last in-flight request unregisters (so `httpx.ASGITransport` tests leak no tasks); lifespan-managed monitors persist between requests. Double-start must stay a no-op. Consequence: in lazy mode background calibration rarely completes and the fallback threshold governs.

## Conventions

- **`LoopGuardConfig` is frozen — never mutate it, construct a new one.** All validation lives in `__post_init__` and raises `ValueError` with a message naming the field.
- Every new config option needs three things: a validation rule in `__post_init__`, a case in `TestLoopGuardConfig`, and a row in `docs/CONFIGURATION.md`. Missing any one of them is an incomplete change.
- **Response headers are lowercase bytes.** Pass-through responses carry `x-request-id`, `x-blocking-count`, `x-blocking-total-ms`, and `x-blocking-detected`, plus `x-loopguard-warning: blocking-detected` in warn mode. The strict 503 built by `_send_strict_error` carries `x-loopguard-enforcement: strict` and **omits `x-blocking-detected`** — a separate header set, not an extension of the first.
- `request_id` is the first 8 characters of a `uuid4` — short enough to read in a terminal, not a security token.
- **All internal timing uses `loop.time()` or `time.monotonic()`** — never `datetime` or wall-clock, which jump under NTP.
- Hot-path classes use `__slots__`: `LoopGuardConfig`, `RequestContext`, `RequestRegistry`, `SentinelMonitor`, `AdaptiveThreshold`, `LoopGuardMiddleware`. Adding an attribute means adding it to `__slots__`, and `test_context.py` asserts the absence of `__dict__`.
- Logger name is `"fastapi_loopguard"`, shared by `monitor.py` and `logging.py`. `monitor.py` logs inline with `%`-style lazy formatting; `logging.log_blocking_event()` is a helper for library *users* and is intentionally not called internally.
- `exclude_paths` is checked before anything else in `_handle_http`, so health checks cost nothing.
- Backward-compat shims are public API and stay: `get_current_request`, `set_current_request`, `reset_current_request`, `init_metrics`. `get_current_request` returns an arbitrary active context and is only correct for single-request cases — new code uses `get_active_requests()`.
- `logging`, `metrics`, and `pytest_plugin` are **not** re-exported from `__init__.py`; import them by module path.

## Testing

- Definition of done: `pytest` green, `mypy src/` clean, `ruff check src/ tests/` and `ruff format --check src/ tests/` clean, and coverage at or above **80** (`--fail-under=80` is the CI gate).
- **There is no `conftest.py`.** The `clear_registry` fixture is duplicated per file, roughly 15 times. Match the local pattern in the file you are editing; introducing a shared conftest is its own change, not a side effect of an unrelated one.
- Blocking is simulated with `time.sleep(...)` followed by a short `await asyncio.sleep(...)` — the second call is what lets the sentinel observe the lag while the context is still registered. Omitting it makes the test pass for the wrong reason.
- HTTP tests use `httpx.AsyncClient(transport=ASGITransport(app=app))`. Plugin tests use the `pytester` fixture to run generated test files in-process.
- Each invariant has dedicated coverage: `test_enforcement_mode.py` for modes and dev-mode escalation, `test_monitor.py` for calibration, idempotency, and task cancellation, `test_cumulative_blocking.py` for the window, `test_context.py` for registry lifecycle and `__slots__`, `test_pytest_plugin.py` for the marker.
- Timing tests are inherently flaky under load. Prefer driving `SentinelMonitor` directly with an `on_blocking` callback (as `test_cumulative_blocking.py` does) over asserting on wall-clock durations.

## The evals harness (`evals/`)

Not shipped with the package, but it decides what this project publishes about
other people's models, so it carries its own invariants:

1. **A sample that never ran is never evidence.** `runner.score_task` returns
   three states, not two: measured-and-clean, measured-and-blocked, and
   `measured: false` with `non_blocking: None`. Unmeasured samples are dropped
   from blocked-rate denominators. Folding them into "did not block" is a
   one-directional bias on the exact number the benchmark advertises, and it
   is the bug that reached a published table once already.
2. **Measured means the trap actually executed.** The runner appends a counter
   to its *copy* of `helpers.py` and requires a non-zero count. The tally is a
   file, not a module global, because a `ProcessPoolExecutor` answer is correct
   and runs the helper in a child process.
3. **The prompt the model sees is the committed fixture, byte for byte.** All
   instrumentation goes into the temp-dir copy. `neutral/task.md` and
   `hinted/task.md` must differ by exactly one added line — the hint sentence.
   Anything else makes the measured gap unattributable. There is a one-line
   symmetry check in `evals/README.md`; run it after touching any task.
4. **Changing a prompt invalidates that cell's samples.** `helpers.py`,
   `app_skeleton.py` and either `task.md` are all part of the prompt. Archive
   and regenerate the affected cells; do not re-score across a prompt change.
5. **An empty completion is an API failure, not a model failure.** Adapters
   retry it and then raise. Never write it out as an empty `app.py`.
6. **Scoring is free; generation is not.** After any judge change run
   `python evals/matrix.py --rescore`, which re-judges every committed
   solution and re-derives `app.py` from the archived raw response. Only a
   prompt change needs the paid path.

## Known Gaps (accurate as of 2026-08-11)

Recorded so they are not rediscovered. None are fixed yet; fixing any of them is its own task. The fuller list, including design tensions deferred from the 0.5 correctness pass, is `FINDINGS.md`.

1. **`prometheus_enabled` is inert.** Neither `middleware.py` nor `monitor.py` imports `metrics.py`, so enabling the flag exposes nothing. Wiring it up means calling `record_blocking` / `record_request` / `set_threshold` from the monitor.
2. **`docs/CONFIGURATION.md` names metrics that do not exist.** It lists `loopguard_blocking_events_total` and `loopguard_blocking_duration_ms`; the real names are `loopguard_blocking_total`, `loopguard_lag_seconds`, `loopguard_requests_monitored_total`, and `loopguard_threshold_seconds`.
3. **`get_metrics()` can never find an instance.** It reads `_instances[prefix]` while `create_metrics` writes `f"{prefix}:{id(registry)}"`. `tests/test_metrics.py:188` documents the mismatch in a comment instead of failing on it.
4. **`_generate_warning_banner()` is dead code** — defined in `middleware.py`, never called.

## Fundamental Guidelines

*(Distilled from [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills))*

- **Think first.** Surface assumptions and tradeoffs; if a request is ambiguous or a simpler approach exists, say so before coding — don't pick silently.
- **Simplicity first.** Minimum code that solves the problem. No speculative features, abstractions, config, or error handling for impossible cases.
- **Surgical changes.** Touch only what the task requires. Match existing style, don't refactor working code, remove only orphans your own change created.
- **Goal-driven.** Turn tasks into verifiable goals (e.g. "fix bug" → "write a failing test, make it pass"); state a brief plan for multi-step work.
