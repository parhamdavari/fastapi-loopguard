"""Demo app showing fastapi-loopguard blocking detection."""

import asyncio
import time

from fastapi import FastAPI

from fastapi_loopguard import LoopGuardConfig, LoopGuardMiddleware

app = FastAPI(title="LoopGuard Demo")

# dev_mode adds diagnostic headers; strict mode fails blocking requests with 503
config = LoopGuardConfig(
    dev_mode=True,
    enforcement_mode="strict",
    log_blocking_events=True,
    fallback_threshold_ms=30.0,  # Low threshold for demo
)
app.add_middleware(LoopGuardMiddleware, config=config)


@app.get("/")
async def root():
    """Non-blocking endpoint."""
    return {"message": "Hello, this is non-blocking!"}


@app.get("/api/users")
async def get_users():
    """Endpoint that blocks the event loop - will trigger warning."""
    # This blocks the event loop! BAD!
    time.sleep(3)  # 3s blocking - long enough to feel every request freeze
    # Small yield to let monitor detect the blocking while context is still active
    await asyncio.sleep(0.02)
    return {"users": ["alice", "bob", "charlie"]}


@app.get("/api/items")
async def get_items():
    """Non-blocking endpoint using async sleep."""
    # This is correct - doesn't block
    await asyncio.sleep(0.1)
    return {"items": ["item1", "item2", "item3"]}


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 60)
    print("LoopGuard Demo App")
    print("=" * 60)
    print("\nEndpoints:")
    print("  GET /           - Non-blocking (no warning)")
    print("  GET /api/users  - BLOCKING (fails with educational 503)")
    print("  GET /api/items  - Non-blocking async sleep (no warning)")
    print("\nTry: curl http://localhost:8765/api/users")
    print("=" * 60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
