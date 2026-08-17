from fastapi import FastAPI, Body

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
def create_thumbnail(image_data: bytes = Body(...)) -> dict:
    thumbnail_bytes = helpers.resize_image(image_data)
    return {"size": len(thumbnail_bytes)}
