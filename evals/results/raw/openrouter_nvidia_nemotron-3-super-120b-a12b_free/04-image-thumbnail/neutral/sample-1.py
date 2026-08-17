from fastapi import FastAPI, Request

import helpers

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    thumb = helpers.resize_image(data)
    return {"size": len(thumb)}
