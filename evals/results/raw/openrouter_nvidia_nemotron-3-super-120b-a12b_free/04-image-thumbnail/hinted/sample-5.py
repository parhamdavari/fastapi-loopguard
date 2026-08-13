import asyncio
from fastapi import FastAPI, Request

import helpers  # noqa: F401

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    # Offload the CPU‑bound resize operation to a thread pool
    loop = asyncio.get_event_loop()
    thumb_bytes = await loop.run_in_executor(None, helpers.resize_image, data)
    return {"size": len(thumb_bytes)}
