from fastapi import FastAPI
import helpers
import asyncio


app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(data: bytes):
    """Endpoint to generate a thumbnail from raw image bytes."""
    # Run the CPU-bound resize_image function in a thread pool to avoid blocking the event loop
    thumbnail_data = await asyncio.to_thread(helpers.resize_image, data)
    return {"size": len(thumbnail_data)}
