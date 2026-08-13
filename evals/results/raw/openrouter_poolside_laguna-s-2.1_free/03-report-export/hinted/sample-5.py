from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio

import helpers

app = FastAPI()


@app.post("/reports")
async def generate_report(request_body: dict):
    rows = request_body["rows"]
    rendered_report = await asyncio.to_thread(helpers.render_report, rows)
    return JSONResponse({"length": len(rendered_report)}, status_code=200)
