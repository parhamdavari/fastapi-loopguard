from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def create_thumbnail(request: Request):
    data = await request.body()
    thumbnail = await run_in_threadpool(helpers.resize_image, data)
    return {"size": len(thumbnail)}
