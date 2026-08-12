from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import helpers  # noqa: F401
from concurrent.futures import ThreadPoolExecutor
import asyncio

app = FastAPI()

executor = ThreadPoolExecutor()

@app.post("/reports")
async def create_report(request: Request):
    data = await request.json()
    rows = data.get("rows", [])
    loop = asyncio.get_running_loop()
    # Run helpers.render_report in a threadpool to avoid blocking event loop
    rendered = await loop.run_in_executor(executor, helpers.render_report, rows)
    return JSONResponse({"length": len(rendered)})
