from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio

import helpers

app = FastAPI()


@app.post("/reports")
async def create_report(payload: dict):
    rows = payload.get("rows", [])
    loop = asyncio.get_event_loop()
    rendered = await loop.run_in_executor(None, helpers.render_report, rows)
    return JSONResponse(content={"length": len(rendered)}, status_code=200)
