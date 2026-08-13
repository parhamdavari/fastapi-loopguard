from fastapi import FastAPI, Request

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/orders")
async def create_order(request: Request):
    body = await request.json()
    order = {"item": body["item"]}
    processed_order = helpers.process_order(order)
    return processed_order, 201
