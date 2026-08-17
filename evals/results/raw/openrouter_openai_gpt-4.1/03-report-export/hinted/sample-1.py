from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import helpers
import asyncio
from typing import Any, Dict

app = FastAPI()


@app.post("/reports")
async def create_report(request: Request):
    data: Dict[str, Any] = await request.json()
    rows = data.get("rows", [])
    loop = asyncio.get_running_loop()
    rendered = await loop.run_in_executor(None, helpers.render_report, rows)
    return JSONResponse({"length": len(rendered)}, status_code=200)
