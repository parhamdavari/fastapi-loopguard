from fastapi import FastAPI
import helpers  # noqa: F401
import asyncio

app = FastAPI()

@app.post("/orders", status_code=201)
async def create_order(order: dict):
    """Process an order asynchronously without blocking the event loop."""
    # Run the blocking helper in a separate thread.
    processed_order = await asyncio.to_thread(helpers.process_order, order)
    return processed_order
