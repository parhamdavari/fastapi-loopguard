from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401

app = FastAPI()

@app.post("/reports")
async def process_report(request: dict):
    rows = request.get("rows")
    # Run the CPU-bound rendering in a separate thread to avoid blocking the event loop
    rendered_report = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered_report)}
