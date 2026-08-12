import asyncio
from fastapi import FastAPI, Body

import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(order: dict = Body(...)):
    return await asyncio.to_thread(helpers.process_order, order)
