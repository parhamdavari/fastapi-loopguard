from fastapi import FastAPI
import asyncio
import helpers

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(order: dict):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, helpers.process_order, order
    )
