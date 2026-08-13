from fastapi import FastAPI, Request

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/orders")
async def create_order(request: Request):
    order = await request.json()
    processed = helpers.process_order(order)
    return processed, 201
