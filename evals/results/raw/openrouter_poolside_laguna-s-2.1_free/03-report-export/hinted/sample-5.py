from fastapi import FastAPI
import asyncio
from concurrent.futures import ThreadPoolExecutor

import helpers

app = FastAPI()

# Create a shared thread pool executor
executor = ThreadPoolExecutor(max_workers=4)


@app.post("/reports")
async def create_report(rows: list):
    loop = asyncio.get_event_loop()
    report = await loop.run_in_executor(executor, helpers.render_report, rows)
    return {"length": len(report)}
