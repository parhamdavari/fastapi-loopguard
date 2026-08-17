from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(data: bytes) -> dict:
    thumbnail_data = await run_in_threadpool(helpers.resize_image, data)
    return {"size": len(thumbnail_data)}
