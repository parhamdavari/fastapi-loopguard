from fastapi import FastAPI

import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders", status_code=201)
def process_order_endpoint(order: dict):
    return helpers.process_order(order)
