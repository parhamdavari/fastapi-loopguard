from fastapi import FastAPI

import helpers  # noqa: F401 (the provided API)

app = FastAPI()


@app.post("/orders", status_code=201)
def create_order(order: dict):
    """
    Process an order.

    Accepts a JSON object with an "item" field, passes it to `helpers.process_order`,
    and returns the enriched order.
    """
    return helpers.process_order(order)
