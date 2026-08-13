from fastapi import FastAPI
import helpers
import asyncio
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()

# Create a thread pool executor for off‑loading CPU‑bound work
_executor = ThreadPoolExecutor()


@app.post("/reports")
async def create_report(payload: dict):
    """
    Expects JSON: {"rows": [...]}
    Returns: {"length": <length of rendered report>}
    """
    rows = payload.get("rows", [])
    loop = asyncio.get_event_loop()
    # Run the CPU‑bound render_report in a thread to keep the event loop free
    rendered = await loop.run_in_executor(_executor, helpers.render_report, rows)
    return {"length": len(rendered)}
