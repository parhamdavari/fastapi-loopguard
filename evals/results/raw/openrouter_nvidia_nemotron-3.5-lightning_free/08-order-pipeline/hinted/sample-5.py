from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(order: dict):
    return await asyncio.to_thread(helpers.process_order, order)
