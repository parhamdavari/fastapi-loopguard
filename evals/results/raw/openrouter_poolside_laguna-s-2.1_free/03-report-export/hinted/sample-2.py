from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse
import asyncio
import helpers

app = FastAPI()


async def render_report_async(rows):
    """Run CPU-bound render_report in a way that doesn't block the event loop."""
    loop = asyncio.get_event_loop()
    # Run the blocking, CPU-bound function in a separate thread so the
    # asyncio event loop remains free to handle other requests.
    return await loop.run_in_executor(None, helpers.render_report, rows)


@app.post("/reports")
async def reports(request: dict):
    """
    Accept {"rows": [...]} and return {"length": <length of rendered report>}.
    Rendering is delegated to a worker thread to avoid blocking the event loop.
    """
    rows = request.get("rows", [])

    # Perform CPU-bound rendering off the event loop.
    rendered = await render_report_async(rows)

    # Return the length of the rendered report.
    return JSONResponse(content={"length": len(rendered)})
