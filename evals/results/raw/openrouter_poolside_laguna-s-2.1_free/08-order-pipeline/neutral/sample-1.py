from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import JSONResponse

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/orders")
async def create_order(request: Request):
    body = await request.json()
    order = helpers.process_order(body)
    return JSONResponse(content=order, status_code=201)
