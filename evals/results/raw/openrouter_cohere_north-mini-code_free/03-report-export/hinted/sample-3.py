import asyncio

from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
async def generate_report(payload: dict):
    """Receive rows and return rendered report length."""
    rows = payload["rows"]
    # Run CPU-bound rendering in a separate thread
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
