from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import helpers  # noqa: F401

import asyncio

app = FastAPI()


@app.post("/thumbnail")
async def create_thumbnail(request: Request):
    data = await request.body()
    loop = asyncio.get_running_loop()
    thumb_bytes = await loop.run_in_executor(None, helpers.resize_image, data)
    return JSONResponse({"size": len(thumb_bytes)})
