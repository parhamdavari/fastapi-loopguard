from fastapi import FastAPI, Body
import asyncio
import helpers  # noqa: F401

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(data: bytes = Body(...)):
    thumbnail_data = await asyncio.to_thread(helpers.resize_image, data)
    return {"size": len(thumbnail_data)}
