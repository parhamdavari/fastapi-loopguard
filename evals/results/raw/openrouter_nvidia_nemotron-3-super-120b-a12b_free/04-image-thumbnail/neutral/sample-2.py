from fastapi import FastAPI, Body

import helpers

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(data: bytes = Body(...)):
    thumb = helpers.resize_image(data)
    return {"size": len(thumb)}
