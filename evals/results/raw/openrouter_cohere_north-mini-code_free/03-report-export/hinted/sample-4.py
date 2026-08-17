from fastapi import FastAPI
import helpers
import asyncio

app = FastAPI()

@app.post("/reports")
async def post_reports(rows: list):
    """Render a report from rows and return the length of the rendered string."""
    # Offload the blocking render to a thread to avoid blocking the event loop.
    rendered = await asyncio.get_event_loop().run_in_executor(
        None, helpers.render_report, rows
    )
    return {"length": len(rendered)}
