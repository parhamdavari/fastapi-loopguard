from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import asyncio
import helpers

app = FastAPI()

@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    loop = asyncio.get_event_loop()
    thumbnail_data = await loop.run_in_executor(None, helpers.resize_image, data)
    return JSONResponse({"size": len(thumbnail_data)})
