from fastapi import FastAPI, Request

import helpers

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request) -> dict:
    data = await request.body()
    thumb = helpers.resize_image(data)  # blocks ~150ms
    return {"size": len(thumb)}
