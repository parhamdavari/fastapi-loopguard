from fastapi import FastAPI, Request
from concurrent.futures import ThreadPoolExecutor
import asyncio

import helpers  # noqa: F401

app = FastAPI()
executor = ThreadPoolExecutor()  # Can tune max_workers if needed


@app.post("/thumbnail")
async def create_thumbnail(request: Request):
    data = await request.body()
    loop = asyncio.get_running_loop()
    # Run the CPU-bound helpers.resize_image in a thread pool (do not block event loop)
    thumbnail = await loop.run_in_executor(executor, helpers.resize_image, data)
    return {"size": len(thumbnail)}
