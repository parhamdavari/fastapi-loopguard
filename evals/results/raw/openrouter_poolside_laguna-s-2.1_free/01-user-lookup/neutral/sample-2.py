from fastapi import FastAPI
from fastapi.responses import JSONResponse

import helpers

app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await helpers.aload_user(user_id)
    return JSONResponse(content=user, status_code=status.HTTP_200_OK)
import helpers
import asyncio
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    try:
        user = await helpers.aload_user(user_id)
        return JSONResponse(content=user, status_code=status.HTTP_200_OK)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
