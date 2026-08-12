from fastapi import FastAPI, Request
import helpers

app = FastAPI()


@app.post("/thumbnail")
def thumbnail(request: Request):
    data = request.body()
    thumbnail_data = helpers.resize_image(data)
    return {"size": len(thumbnail_data)}
