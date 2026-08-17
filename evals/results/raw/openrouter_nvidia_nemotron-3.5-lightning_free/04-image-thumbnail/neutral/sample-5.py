from fastapi import FastAPI, Body
import helpers

app = FastAPI()


@app.post("/thumbnail")
def thumbnail(image_bytes: bytes = Body(...)):
    thumbnail_data = helpers.resize_image(image_bytes)
    return {"size": len(thumbnail_data)}
