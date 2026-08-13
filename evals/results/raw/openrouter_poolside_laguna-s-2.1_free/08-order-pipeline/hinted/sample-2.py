from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import asyncio
import helpers

app = FastAPI()


@app.post("/orders")
async def create_order(request: Request):
    body = await request.json()
    order = body if isinstance(body, dict) else dict(body)
    processed = await asyncio.to_thread(helpers.process_order, order)
    return JSONResponse(content=processed, status_code=201)
