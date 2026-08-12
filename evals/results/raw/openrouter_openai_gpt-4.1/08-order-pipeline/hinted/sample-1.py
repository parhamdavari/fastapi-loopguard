from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
import asyncio
import helpers

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(request: Request):
    order = await request.json()
    loop = asyncio.get_running_loop()
    processed_order = await loop.run_in_executor(None, helpers.process_order, order)
    return JSONResponse(content=processed_order, status_code=status.HTTP_201_CREATED)
