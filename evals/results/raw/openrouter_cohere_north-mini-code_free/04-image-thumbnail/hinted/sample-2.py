from fastapi import FastAPI, Request
import asyncio

import helpers  # noqa: F401 (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    # Read the raw image bytes from the request body
    data = await request.body()
    # Run the CPU‑bound resize operation in a thread to avoid blocking the event loop
    thumbnail_bytes = await asyncio.to_thread(helpers.resize_image, data)
    return {"size": len(thumbnail_bytes)}
