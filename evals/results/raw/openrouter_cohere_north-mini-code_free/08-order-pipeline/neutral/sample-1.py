from fastapi import FastAPI, JSONResponse
import helpers

app = FastAPI()


@app.post("/orders")
async def create_order(order: dict):
    processed_order = helpers.process_order(order)
    return JSONResponse(content=processed_order, status_code=201)
