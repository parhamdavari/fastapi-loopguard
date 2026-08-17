from fastapi import FastAPI, Request
import asyncio

import helpers  # noqa: F401 (provided API)

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    # Read the raw request body (image bytes)
    data = await request.body()
    # Run CPU‑bound resizing in a separate thread to avoid blocking the event loop
    thumbnail_bytes = await asyncio.to_thread(helpers.resize_image, data)
    # Return the size of the generated thumbnail
    return {"size": len(thumbnail_bytes)}
