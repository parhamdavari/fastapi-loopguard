from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(payload: dict) -> dict:
    return helpers.process_order(payload)  # blocks ~150ms two frames deep
