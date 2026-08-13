from fastapi import FastAPI, Body

import helpers

app = FastAPI()


@app.post("/orders", status_code=201)
def create_order(order: dict = Body(...)):
    return helpers.process_order(order)
