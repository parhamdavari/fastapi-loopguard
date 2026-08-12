import asyncio

from fastapi import FastAPI, Request

import helpers

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request) -> dict:
    data = await request.body()
    thumb = await asyncio.to_thread(helpers.resize_image, data)
    return {"size": len(thumb)}
