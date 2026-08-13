from fastapi import FastAPI
import asyncio
import helpers

app = FastAPI()

@app.post("/reports")
async def reports_endpoint(payload: dict):
    rows = payload["rows"]
    loop = asyncio.get_running_loop()
    rendered = await loop.run_in_executor(None, helpers.render_report, rows)
    return {"length": len(rendered)}
