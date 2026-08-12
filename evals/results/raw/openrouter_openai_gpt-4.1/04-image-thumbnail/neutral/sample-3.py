from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import helpers  # noqa: F401

app = FastAPI()


@app.post("/thumbnail")
async def create_thumbnail(request: Request):
    data = await request.body()
    thumbnail_bytes = helpers.resize_image(data)
    return JSONResponse({"size": len(thumbnail_bytes)}, status_code=200)
