from fastapi import FastAPI, Request
import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def create_thumbnail(request: Request):
    data = await request.body()
    thumbnail = helpers.resize_image(data)
    return {"size": len(thumbnail)}
