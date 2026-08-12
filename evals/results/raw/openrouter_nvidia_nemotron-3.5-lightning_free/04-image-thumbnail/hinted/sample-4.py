from fastapi import FastAPI, Request
import helpers
import asyncio

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    thumbnail_bytes = await asyncio.to_thread(helpers.resize_image, data)
    return {"size": len(thumbnail_bytes)}
