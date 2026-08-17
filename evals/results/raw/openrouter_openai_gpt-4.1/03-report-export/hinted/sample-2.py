from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import helpers
import asyncio
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()

executor = ThreadPoolExecutor()

@app.post("/reports")
async def create_report(request: Request):
    body = await request.json()
    rows = body.get("rows", [])

    loop = asyncio.get_running_loop()
    rendered = await loop.run_in_executor(executor, helpers.render_report, rows)
    return JSONResponse({"length": len(rendered)}, status_code=200)
