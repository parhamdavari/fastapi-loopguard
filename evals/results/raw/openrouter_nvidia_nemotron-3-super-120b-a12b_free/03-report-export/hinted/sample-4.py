from fastapi import FastAPI
import helpers
import asyncio

app = FastAPI()


@app.post("/reports")
async def create_report(payload: dict):
    rows = payload.get("rows", [])
    # Run the synchronous, blocking render_report in a thread to avoid blocking the event loop
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
