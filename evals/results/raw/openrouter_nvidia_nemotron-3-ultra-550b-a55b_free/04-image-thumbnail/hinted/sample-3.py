from fastapi import FastAPI, Request
import asyncio
import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/thumbnail")
async def thumbnail(request: Request) -> dict:
    data = await request.body()
    thumbnail_bytes = await asyncio.to_thread(helpers.resize_image, data)
    return {"size": len(thumbnail_bytes)}
