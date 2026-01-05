<p align="center">
  <img src="assets/loopguard-logo.webp" alt="LoopGuard" width="280" />
</p>

<p align="center">
  <strong>Catch event-loop blocking in FastAPI with per-request attribution.</strong>
</p>

<p align="center">
  <a href="https://badge.fury.io/py/fastapi-loopguard"><img src="https://badge.fury.io/py/fastapi-loopguard.svg" alt="PyPI version"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

---

When a request blocks your event loop (via `time.sleep()`, blocking I/O, or CPU work), LoopGuard detects it **and tells you which endpoint caused it**.

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

# Development: strict enforcement (503 on blocking)
config = LoopGuardConfig(dev_mode=True)

# Production: silent logging
config = LoopGuardConfig(enforcement_mode="log")

app.add_middleware(LoopGuardMiddleware, config=config)
```

## What You Get

### Strict Mode
Returns an educational 503 page that explains what went wrong and how to fix it:

<p align="center">
  <img src="assets/error-page-screenshot.png" alt="Strict mode error page" width="600" />
</p>

---

### Warn Mode
Adds diagnostic headers to every response for debugging:

<p align="center">
  <img src="assets/error-page-screenshot-endpoint.png" alt="Warn mode headers" width="600" />
</p>

---

### Log Mode
Writes structured logs with full request attribution:

<p align="center">
  <img src="assets/error-page-screenshot-console.png" alt="Console output" width="600" />
</p>

---

<p align="center">
  <a href="docs/CONFIGURATION.md"><strong>Full Configuration Reference</strong></a>
</p>
