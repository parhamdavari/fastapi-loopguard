from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/thumbnail")
async def create_thumbnail(image_bytes: bytes):
    thumbnail_bytes = helpers.resize_image(image_bytes)
    return {"size": len(thumbnail_bytes)}
