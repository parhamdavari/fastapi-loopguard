from fastapi import FastAPI, Body

import helpers

app = FastAPI()


@app.post("/orders")
async def create_order(order: dict = Body(...)):
    processed_order = helpers.process_order(order)
    return processed_order, 201
