import asyncio
from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def create_thumbnail(data: bytes):
    thumbnail = await asyncio.to_thread(helpers.resize_image, data)
    return {"size": len(thumbnail)}
