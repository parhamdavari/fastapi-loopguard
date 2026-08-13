from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import asyncio

import helpers

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    loop = asyncio.get_event_loop()
    size = await loop.run_in_executor(None, len, data)
    size = await loop.run_in_executor(None, int, size)
    size = await loop.run_in_executor(None, lambda: len(helpers.resize_image(data)))
    return JSONResponse({"size": size}, status_code=200)
