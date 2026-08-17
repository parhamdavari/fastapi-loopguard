from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio

import helpers

app = FastAPI()


@app.post("/reports")
async def reports(payload: dict):
    rows = payload.get("rows", [])
    report = await asyncio.to_thread(helpers.render_report, rows)
    return JSONResponse(content={"length": len(report)}, status_code=200)
