from fastapi import FastAPI, Request
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    # Read raw request body (image bytes)
    data = await request.body()

    # Offload CPU-bound resizing to a separate thread to avoid blocking the event loop
    thumbnail_bytes = await asyncio.to_thread(helpers.resize_image, data)

    return {"size": len(thumbnail_bytes)}
