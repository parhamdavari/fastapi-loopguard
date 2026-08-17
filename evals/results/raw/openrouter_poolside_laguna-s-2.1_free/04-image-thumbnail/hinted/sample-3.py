from fastapi import FastAPI
from fastapi import Request
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    thumbnail_data = await asyncio.to_thread(helpers.resize_image, data)
    return {"size": len(thumbnail_data)}
