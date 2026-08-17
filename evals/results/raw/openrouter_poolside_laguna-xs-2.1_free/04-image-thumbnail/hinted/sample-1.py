from fastapi import FastAPI
import helpers
import asyncio

app = FastAPI()


@app.post("/thumbnail")
async def create_thumbnail(data: bytes):
    resized = await asyncio.to_thread(helpers.resize_image, data)
    return {"size": len(resized)}
