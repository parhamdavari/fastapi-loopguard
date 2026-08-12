<p align="center">
  <img src="assets/loopguard-logo.webp" alt="LoopGuard" width="280" />
</p>

<p align="center">
  <strong>Catch event-loop blocking in FastAPI and see which requests were in flight.</strong>
</p>

<p align="center">
  <a href="https://badge.fury.io/py/fastapi-loopguard"><img src="https://badge.fury.io/py/fastapi-loopguard.svg" alt="PyPI version"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <img src="assets/demo.gif" alt="LoopGuard demo: a fast endpoint passes, a blocking endpoint fails with a 503, and the console banner explains why" width="800" />
</p>

---

When something blocks your event loop (via `time.sleep()`, blocking I/O, or CPU work), LoopGuard detects it **and narrows it down to the requests that were in flight when the loop stalled**. The sentinel measures loop lag, so it cannot name the single guilty handler — it reports every request that was active during the stall.

## Install

```bash
pip install fastapi-loopguard
```

## Quick Start

```python
from fastapi import FastAPI
from fastapi_loopguard import LoopGuardMiddleware

app = FastAPI()
app.add_middleware(LoopGuardMiddleware)
```

## Enforcement Modes

| Mode | Behavior | Use Case |
|------|----------|----------|
| `"warn"` | Console warnings + headers | **Default** |
| `"strict"` | HTTP 503 + error page | Development / CI |
| `"log"` | Silent logging | Production |

```python
from fastapi_loopguard import LoopGuardConfig

# Development: diagnostic headers on every response
config = LoopGuardConfig(dev_mode=True)

# Development / CI: fail loudly with an educational 503
config = LoopGuardConfig(enforcement_mode="strict")

# Production: silent logging
config = LoopGuardConfig(enforcement_mode="log")

app.add_middleware(LoopGuardMiddleware, config=config)
```

## What You Get

### Strict Mode
Returns an educational 503 page that explains what went wrong and how to fix it:

<p align="center">
  <img src="assets/error-page.gif" alt="Strict mode error page" width="600" />
</p>

---

### Warn Mode
Adds diagnostic headers to every response for debugging:

<p align="center">
  <img src="assets/error-page-screenshot-endpoint.png" alt="Warn mode headers" width="600" />
</p>

---

### Log Mode
Writes structured logs listing the requests that were in flight:

<p align="center">
  <img src="assets/error-page-screenshot-console.png" alt="Console output" width="600" />
</p>

---

## Testing AI-Generated Code

Measured, not assumed: asked for ordinary endpoints with no warning, GPT-4.1 blocked the event loop in 21 of 40 samples ([benchmark](evals/README.md#results), N=5 per task, 2026-08-12). One sentence of instruction removed the problem — the bundled pytest plugin is that sentence, enforced. It turns blocking into a red test and a machine-readable report the agent can fix from, with no per-test annotations:

```ini
# pytest.ini
[pytest]
loopguard_all_async = true          # every async test fails on blocking
loopguard_report = loopguard.json   # verdicts + fix hints for the agent
```

See [docs/AI-HARNESS.md](docs/AI-HARNESS.md) for the report schema, the `no_blocking` / `allow_blocking` markers, and a drop-in snippet for your project's agent instructions.

---

<p align="center">
  <a href="docs/CONFIGURATION.md"><strong>Full Configuration Reference</strong></a>
</p>
