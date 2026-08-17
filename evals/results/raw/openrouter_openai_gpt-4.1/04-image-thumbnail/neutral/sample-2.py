from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import helpers  # noqa: F401

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    thumb = helpers.resize_image(data)
    return JSONResponse(content={"size": len(thumb)})
