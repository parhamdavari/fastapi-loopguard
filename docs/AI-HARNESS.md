# LoopGuard as a Test Harness for AI-Generated Code

AI coding agents write plausible async code that quietly blocks the event
loop — `requests` instead of `httpx`, `open().read()` in a handler, a sync
SDK call inside `async def`. The type checker passes, the tests pass, and
the app freezes under load.

LoopGuard's pytest plugin turns that failure mode into a red test with a
machine-readable explanation the agent can fix from — no per-test
annotations required.

## Quick start

```ini
# pytest.ini (or [tool.pytest.ini_options] in pyproject.toml)
[pytest]
asyncio_mode = auto
loopguard_all_async = true          # every async test is a blocking gate
loopguard_report = loopguard.json   # verdicts for the agent to read
loopguard_threshold_ms = 50
```

Run the suite as usual:

```bash
pytest
```

Any async test whose execution blocks the event loop past the threshold
fails, and `loopguard.json` records what happened. Both settings also
exist as CLI flags: `--loopguard-all-async`, `--loopguard-report=PATH`.

## Options

| Option | Where | Default | Meaning |
|--------|-------|---------|---------|
| `loopguard_threshold_ms` | ini | `50` | Lag beyond this fails the test |
| `loopguard_all_async` | ini / `--loopguard-all-async` | off | Treat every async test as `@pytest.mark.no_blocking` |
| `loopguard_report` | ini / `--loopguard-report=PATH` | off | Write the JSON verdict file |
| `@pytest.mark.no_blocking` | marker | — | Gate one test explicitly (works without all-async mode) |
| `@pytest.mark.allow_blocking` | marker | — | Exempt one test from all-async mode |

Exit semantics are plain pytest: flagged tests fail, so any CI that runs
pytest is already enforcing the gate.

## The report

```json
{
  "schema_version": 1,
  "threshold_ms": 50.0,
  "totals": {"tests": 42, "flagged": 1},
  "tests": [
    {
      "nodeid": "tests/test_api.py::test_upload",
      "verdict": "blocked",
      "events": [{"lag_ms": 180.24, "threshold_ms": 50.0}],
      "hints": [
        "time.sleep(n) -> await asyncio.sleep(n)",
        "requests.get(url) -> await httpx.AsyncClient().get(url)",
        "open(f).read() -> await aiofiles.open(f)",
        "subprocess.run(...) -> await asyncio.create_subprocess_exec(...)",
        "CPU-bound work -> await asyncio.to_thread(func)"
      ]
    },
    {
      "nodeid": "tests/test_api.py::test_list",
      "verdict": "clean",
      "events": [],
      "hints": []
    }
  ]
}
```

Only instrumented tests appear (`totals.tests` counts them). A `blocked`
verdict means the loop lagged past the threshold while that test ran; the
sentinel measures lag, not call stacks, so the culprit is in the code that
test executed — usually the endpoint it called.

## Interpreting the strict 503 (runtime harness)

For integration tests that drive a live app, run the middleware with
`LoopGuardConfig(enforcement_mode="strict")`: blocking requests fail with
a 503 whose JSON body carries the same shape of diagnosis
(`error: "event_loop_blocked"`, blocking count and total ms, and the same
fix suggestions under `help.common_causes`).

## Drop-in snippet for a consumer project's CLAUDE.md / agents.md

```markdown
## Async discipline (enforced)

This project gates async code with fastapi-loopguard. `pytest` fails any
async test that blocks the event loop for >50ms and writes verdicts to
`loopguard.json`.

When a test fails with "Event loop blocking detected":
1. Read `loopguard.json`; find the `blocked` entry for that test.
2. The blocking call is in the code path that test exercises. Replace
   sync calls with the async equivalents listed under `hints`.
3. Never widen `loopguard_threshold_ms` or add `allow_blocking` to make
   a test pass — fix the blocking call instead.
```

## Scoring models instead of guarding CI

The same gate scores whether a model writes non-blocking async code: run
each generated solution against a functional test file plus the plugin,
and read `totals.flagged` from the report. A ready-made task set lives in
`evals/` at the repository root.
