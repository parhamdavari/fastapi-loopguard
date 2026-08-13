from fastapi import FastAPI, Request
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    """Accepts raw image bytes and returns the size of the generated thumbnail."""
    # Get the raw request body
    data = await request.body()
    
    # Run the CPU-bound resize_image in a thread pool executor to avoid blocking
    loop = asyncio.get_event_loop()
    thumbnail_bytes = await loop.run_in_executor(
        None,  # Use default thread pool
        helpers.resize_image,
        data
    )
    
    # Return the size of the generated thumbnail
    return {"size": len(thumbnail_bytes)}
