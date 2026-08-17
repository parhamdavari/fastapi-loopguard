from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/thumbnail")
def thumbnail(image_data: bytes):
    thumbnail_data = helpers.resize_image(image_data)
    return {"size": len(thumbnail_data)}
