from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/orders", status_code=201)
def create_order(order: dict) -> dict:
    processed = helpers.process_order(order)
    return processed
