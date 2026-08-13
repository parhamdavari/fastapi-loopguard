import asyncio
from fastapi import FastAPI, Request

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def create_thumbnail(request: Request):
    data = await request.body()
    loop = asyncio.get_running_loop()
    resized_data = await loop.run_in_executor(None, helpers.resize_image, data)
    return {"size": len(resized_data)}
