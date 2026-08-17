from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
def create_thumbnail(data: bytes):
    thumbnail = helpers.resize_image(data)
    return {"size": len(thumbnail)}
