from fastapi import FastAPI, Body
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(order: dict = Body(...)):
    processed = await asyncio.to_thread(helpers.process_order, order)
    return processed
