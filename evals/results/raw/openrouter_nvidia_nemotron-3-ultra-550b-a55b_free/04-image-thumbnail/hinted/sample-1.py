from fastapi import FastAPI, Request
import asyncio
from concurrent.futures import ThreadPoolExecutor

import helpers

app = FastAPI()

# Thread pool for CPU-bound image processing
_executor = ThreadPoolExecutor(max_workers=4)


@app.post("/thumbnail")
async def create_thumbnail(request: Request):
    data = await request.body()
    loop = asyncio.get_running_loop()
    thumbnail = await loop.run_in_executor(_executor, helpers.resize_image, data)
    return {"size": len(thumbnail)}
