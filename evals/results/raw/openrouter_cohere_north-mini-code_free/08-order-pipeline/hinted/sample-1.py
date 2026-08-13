from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401 (the provided API)

app = FastAPI()

@app.post("/orders")
async def create_order(order: dict):
    processed = await asyncio.to_thread(helpers.process_order, order)
    return processed, 201
