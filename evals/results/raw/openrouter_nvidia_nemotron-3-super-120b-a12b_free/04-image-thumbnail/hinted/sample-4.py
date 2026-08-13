import asyncio
from fastapi import FastAPI, Request
import helpers

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    # Offload the CPU‑bound resize operation to a thread pool
    thumbnail_bytes = await asyncio.get_event_loop().run_in_executor(
        None, helpers.resize_image, data
    )
    return {"size": len(thumbnail_bytes)}
