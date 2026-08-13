from fastapi import FastAPI
import helpers
import asyncio

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(order: dict):
    processed = await asyncio.to_thread(helpers.process_order, order)
    return processed
