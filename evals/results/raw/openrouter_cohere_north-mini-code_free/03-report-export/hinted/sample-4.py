from fastapi import FastAPI, HTTPException
import asyncio

import helpers

app = FastAPI()

@app.post("/reports")
async def reports_endpoint(payload: dict):
    """
    Accept a JSON payload with a key 'rows' (list) and return the length
    of the CPU-rendered report. The rendering is offloaded to a thread
    to avoid blocking the event loop.
    """
    rows = payload.get("rows")
    if rows is None:
        raise HTTPException(status_code=422, detail="Missing 'rows' field")
    # Run the CPU-bound render in a thread to keep the event loop free
    loop = asyncio.get_event_loop()
    rendered = await loop.run_in_executor(None, helpers.render_report, rows)
    return {"length": len(rendered)}
