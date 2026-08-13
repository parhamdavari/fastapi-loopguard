from fastapi import FastAPI, Body, status
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(order: dict = Body(...)):
    processed = await asyncio.to_thread(helpers.process_order, order)
    return processed
