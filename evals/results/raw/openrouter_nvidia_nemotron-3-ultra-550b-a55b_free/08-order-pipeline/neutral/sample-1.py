from fastapi import FastAPI, Body

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/orders", status_code=201)
def create_order(order: dict = Body(...)):
    processed_order = helpers.process_order(order)
    return processed_order
