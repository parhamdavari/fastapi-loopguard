from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import helpers
import asyncio

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    loop = asyncio.get_running_loop()
    thumbnail_bytes = await loop.run_in_executor(None, helpers.resize_image, data)
    return JSONResponse({"size": len(thumbnail_bytes)})
