from fastapi import FastAPI, Request
import asyncio

import helpers  # noqa: F401

app = FastAPI()

@app.post("/thumbnail")
async def thumbnail(request: Request):
    # Read raw image bytes from request body
    data = await request.body()
    # Offload CPU‑bound resize_image to a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    thumbnail_bytes = await loop.run_in_executor(
        None, helpers.resize_image, data
    )
    return {"size": len(thumbnail_bytes)}
