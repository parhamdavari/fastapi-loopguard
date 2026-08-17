from fastapi import FastAPI, Request
import asyncio
import helpers  # noqa: F401

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    # Read raw image bytes from the request body
    data = await request.body()
    # Offload the CPU‑bound resize operation to a thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    thumbnail_bytes = await loop.run_in_executor(None, helpers.resize_image, data)
    # Return the size of the thumbnail
    return {"size": len(thumbnail_bytes)}
