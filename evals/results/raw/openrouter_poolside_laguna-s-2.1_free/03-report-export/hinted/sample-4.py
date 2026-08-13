from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio
from concurrent.futures import ProcessPoolExecutor

import helpers  # provided API

app = FastAPI()

# Process pool to run CPU-bound work without blocking the event loop
_process_pool = ProcessPoolExecutor()


@app.post("/reports")
async def create_report(payload: dict):
    rows = payload.get("rows", [])

    loop = asyncio.get_running_loop()
    rendered = await loop.run_in_executor(
        _process_pool,
        helpers.render_report,
        rows,
    )

    return JSONResponse({"length": len(rendered)})
