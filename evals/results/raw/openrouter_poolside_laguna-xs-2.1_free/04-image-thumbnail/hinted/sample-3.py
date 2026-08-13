from fastapi import FastAPI, Request
import helpers
import asyncio

app = FastAPI()

@app.post("/thumbnail")
async def create_thumbnail(request: Request):
    data = await request.body()
    loop = asyncio.get_event_loop()
    thumbnail = await loop.run_in_executor(None, helpers.resize_image, data)
    return {"size": len(thumbnail)}
