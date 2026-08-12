from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio

import helpers  # noqa: F401

app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await helpers.aload_user(user_id)
    return JSONResponse(user, status_code=200)
