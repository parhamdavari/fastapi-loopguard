from fastapi import FastAPI
import asyncio

import helpers

app = FastAPI()


@app.post("/reports")
async def generate_report(rows: list):
    """
    Endpoint to generate a report from rows.
    
    - Runs render_report in a background thread to avoid blocking the event loop
    - Returns the length of the rendered report
    """
    result = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(result)}
