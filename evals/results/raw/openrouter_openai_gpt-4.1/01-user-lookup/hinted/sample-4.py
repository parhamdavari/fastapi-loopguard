from fastapi import FastAPI
from fastapi.responses import JSONResponse
import helpers
import asyncio

app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    # Use the async version directly (no event loop blocking)
    user = await helpers.aload_user(user_id)
    return JSONResponse(content=user, status_code=200)
