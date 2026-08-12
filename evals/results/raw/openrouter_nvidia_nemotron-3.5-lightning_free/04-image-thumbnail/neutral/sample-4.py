from fastapi import FastAPI, Request

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request):
    data = await request.body()
    thumbnail_data = helpers.resize_image(data)
    return {"size": len(thumbnail_data)}
