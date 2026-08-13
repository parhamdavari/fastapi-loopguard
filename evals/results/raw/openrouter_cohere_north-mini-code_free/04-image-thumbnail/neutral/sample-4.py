from fastapi import FastAPI, Request

import helpers  # noqa: F401

app = FastAPI()


@app.post("/thumbnail")
async def get_thumbnail(request: Request):
    data = await request.body()
    thumbnail_bytes = helpers.resize_image(data)
    return {"size": len(thumbnail_bytes)}
