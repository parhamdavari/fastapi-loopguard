from fastapi import FastAPI, status
import asyncio
import helpers

app = FastAPI()


@app.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(order: dict):
    processed = await asyncio.to_thread(helpers.process_order, order)
    return processed
