import asyncio

from fastapi import FastAPI, Body
from fastapi.responses import JSONResponse

import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders")
async def create_order(order: dict = Body(...)):
    processed_order = await asyncio.to_thread(helpers.process_order, order)
    return JSONResponse(content=processed_order, status_code=201)
