from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()

@app.post("/thumbnail")
async def thumbnail_endpoint(image_bytes: bytes):
    thumbnail = helpers.resize_image(image_bytes)
    return {"size": len(thumbnail)}
