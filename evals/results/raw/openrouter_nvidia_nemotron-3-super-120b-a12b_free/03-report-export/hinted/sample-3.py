from fastapi import FastAPI, Body
import helpers
import asyncio

app = FastAPI()


@app.post("/reports")
async def post_reports(data: dict = Body(...)):
    rows = data.get("rows", [])
    # Offload the synchronous, blocking render_report to a thread pool
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
