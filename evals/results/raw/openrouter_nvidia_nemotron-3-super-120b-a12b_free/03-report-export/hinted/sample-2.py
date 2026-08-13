from fastapi import FastAPI, Body
import helpers
import asyncio

app = FastAPI()


@app.post("/reports")
async def create_report(rows: list = Body(..., embed=True)):
    # Offload the CPU‑bound rendering to a thread pool to keep the event loop free
    loop = asyncio.get_event_loop()
    rendered = await loop.run_in_executor(None, helpers.render_report, rows)
    return {"length": len(rendered)}
