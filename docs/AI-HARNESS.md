# LoopGuard as a Test Harness for AI-Generated Code

AI coding agents write plausible async code that quietly blocks the event
loop — `requests` instead of `httpx`, `open().read()` in a handler, a sync
SDK call inside `async def`. The type checker passes, the tests pass, and
the app freezes under load.

LoopGuard's pytest plugin turns that failure mode into a red test with a
machine-readable explanation the agent can fix from — no per-test
annotations required.

Evidence status: the premise is measured — unprompted GPT-4.1 blocked the
loop in 21/37 measured benchmark samples, and all seven models tested blocked
at least once (see [Results](../evals/README.md#results)); whether an agent
can repair from this report alone is untested and tracked in
[#19](https://github.com/parhamdavari/fastapi-loopguard/issues/19).

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

## The `loopguard` command

Installing the package also installs a `loopguard` console script, for an
agent or a CI step that wants the verdict without parsing JSON itself.
This is the pair of commands to put in a CI config:

```bash
pytest --loopguard-all-async --loopguard-report=loopguard.json
loopguard report loopguard.json
```

A clean run prints one line:

```
loopguard: clean  tests=42  flagged=0  threshold=50.0ms
```

A blocked run adds one line per flagged test, with its node id and the
worst lag measured while it ran:

```
loopguard: blocked  tests=42  flagged=2  threshold=50.0ms
  blocked tests/test_api.py::test_upload  worst_lag=180.24ms
  blocked tests/test_api.py::test_render  worst_lag=95.0ms
```

Exit codes follow the ruff/pyright convention, and are also in
`loopguard report --help`:

| Code | Meaning |
|------|---------|
| `0` | clean — no blocking detected in the report |
| `1` | blocking detected |
| `2` | the report is missing, unreadable, or malformed |

Exit 2 is a tool failure, kept distinct from a verdict on purpose: a
typo'd path, a truncated file, or a report carrying neither `status` nor
`totals` must not read as "clean". It prints one line to stderr and
nothing to stdout. `--quiet` suppresses the summary and communicates
through the exit code alone; it still reports a malformed report on
stderr.

The verdict comes from the top-level `status` key. A report without one
is a `schema_version` 1 report, and falls back to `totals.flagged > 0`,
so a report written by an older version of the plugin still gates. The
command reads only those keys — it does not validate against the JSON
Schema below, which would need `jsonschema`, a dev-only dependency.

`loopguard` with no subcommand prints usage and exits 0; an unknown
subcommand exits 2.

## The report

```json
{
  "schema_version": 2,
  "status": "blocked",
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

### The top-level verdict

`status` is the whole run in one key: `"blocked"` when at least one
instrumented test was flagged, `"clean"` otherwise. Read it instead of
deriving `totals.flagged > 0`; `totals` is unchanged, so consumers written
against `schema_version` 1 keep working.

A run that instrumented **no** tests reports `"status": "clean"` with
`"totals": {"tests": 0, "flagged": 0}`. The report says what was observed,
and nothing blocked because nothing was watched — it is not evidence that
the suite is clean. A gate that must also insist the suite was actually
checked (a misconfigured `asyncio_mode`, a rename that dropped every async
test) reads `totals.tests > 0` alongside `status`.

### Schema

[`loopguard-report.schema.json`](loopguard-report.schema.json) is the
JSON Schema (draft 2020-12) for the payload above. Its `$id` carries the
`schema_version` it describes, so it changes on every bump; the file path
stays the same and always describes the current version. Every object in
it sets `additionalProperties: true` on purpose — the report grows by
adding keys, so a validator must tolerate keys it does not know rather
than reject a newer report. CI validates both this example and a freshly
generated report against it, so the doc and the plugin cannot drift.

## Interpreting the strict 503 (runtime harness)

For integration tests that drive a live app, run the middleware with
`LoopGuardConfig(enforcement_mode="strict")`: blocking requests fail with
a 503 whose JSON body carries the same shape of diagnosis
(`error: "event_loop_blocked"`, blocking count and total ms, and the same
fix suggestions under `help.common_causes`).

### Checking a running app directly

This path needs no pytest and no plugin — just a strict-mode app and an
HTTP client. `examples/demo_app.py` is already configured that way, so it
works as-is:

```bash
python examples/demo_app.py                # :8765, enforcement_mode="strict"
```

Ask for JSON explicitly. The middleware serves the educational HTML page to
any request whose `Accept` header contains `text/html` and the JSON body to
everything else, so an explicit `Accept: application/json` is what keeps the
output parseable regardless of client defaults.

```bash
curl -sS -m 30 -H 'Accept: application/json' \
  -w '\nHTTP %{http_code}\n' http://127.0.0.1:8765/api/users
```

Against the demo app's blocking endpoint that prints:

```json
{
  "error": "event_loop_blocked",
  "message": "Event loop blocking detected while this request was in flight",
  "request": {
    "id": "eb564065",
    "method": "GET",
    "path": "/api/users"
  },
  "blocking": {
    "count": 1,
    "total_ms": 3000.99
  },
  "help": {
    "problem": "Synchronous code blocked the async event loop",
    "common_causes": [
      "time.sleep() -> await asyncio.sleep()",
      "requests.get() -> await httpx.AsyncClient().get()",
      "open().read() -> await aiofiles.open()",
      "subprocess.run() -> asyncio.create_subprocess_exec()",
      "CPU-bound work -> asyncio.to_thread(func)"
    ],
    "docs": "https://fastapi.tiangolo.com/async/"
  }
}
```

`blocking.count` is how many events were attributed to this request and
`blocking.total_ms` their total. The same two numbers are on the response as
`x-blocking-count` and `x-blocking-total-ms`, next to
`x-loopguard-enforcement: strict`.

The same check in Python (`pip install httpx` — it is a dev dependency of
this package, not a runtime one), exiting non-zero when blocking was seen:

```python
import httpx

resp = httpx.get(
    "http://127.0.0.1:8765/api/users",
    headers={"Accept": "application/json"},
    timeout=30.0,
)
body = resp.json()
if resp.status_code == 503 and body.get("error") == "event_loop_blocked":
    blocking = body["blocking"]
    print(f"blocked count={blocking['count']} total_ms={blocking['total_ms']}")
    raise SystemExit(1)
print(f"no blocking observed status={resp.status_code}")
```

The verdict to derive: `503` **and** `error == "event_loop_blocked"` means
blocking was observed while that request was in flight — fail. `200` means
LoopGuard observed no blocking on that request, which is not the same as the
app being clean. Check both, not the status alone: a 503 from the app's own
handler is not a LoopGuard verdict. And under concurrent load the 503 goes to
every request in flight during the stall, not only the one that blocked, so
drive this one request at a time if you want to read it as a per-endpoint
result.

Do not use this path on a `StreamingResponse`, SSE, or token-streaming
route. The status and the headers are decided at `http.response.start`,
before the body generator runs, so neither can report blocking that happens
after the first chunk is on the wire — see [Streaming responses are a blind
spot](CONFIGURATION.md#streaming-responses-are-a-blind-spot). Those routes
need the log output instead.

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
and read `status` (or `totals.flagged`, for a per-test count) from the
report — checking `totals.tests > 0` first, so a solution whose tests
never ran is not scored as clean. A ready-made task set lives in
`evals/` at the repository root.
