from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
import helpers

import asyncio
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()

_executor = ThreadPoolExecutor()

@app.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(request: Request):
    order = await request.json()
    loop = asyncio.get_event_loop()
    processed_order = await loop.run_in_executor(_executor, helpers.process_order, order)
    return JSONResponse(content=processed_order, status_code=201)
