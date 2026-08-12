from fastapi import FastAPI
from fastapi.responses import JSONResponse
from concurrent.futures import ThreadPoolExecutor
import asyncio

import helpers  # noqa: F401

app = FastAPI()

_executor = ThreadPoolExecutor()

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    loop = asyncio.get_running_loop()
    user = await loop.run_in_executor(_executor, helpers.load_user, user_id)
    return JSONResponse(content=user, status_code=200)
