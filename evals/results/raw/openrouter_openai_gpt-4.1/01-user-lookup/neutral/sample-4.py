from fastapi import FastAPI
from fastapi.responses import JSONResponse
import helpers
import asyncio

app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    loop = asyncio.get_running_loop()
    user = await loop.run_in_executor(None, helpers.load_user, user_id)
    return JSONResponse(status_code=200, content=user)
