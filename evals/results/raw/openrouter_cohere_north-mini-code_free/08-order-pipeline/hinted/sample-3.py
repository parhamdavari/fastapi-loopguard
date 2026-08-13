from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio
import helpers

app = FastAPI()

@app.post("/orders")
async def create_order(order: dict):
    """
    Process an order asynchronously and return it with HTTP 201.
    """
    processed_order = await asyncio.to_thread(helpers.process_order, order)
    return JSONResponse(content=processed_order, status_code=201)
