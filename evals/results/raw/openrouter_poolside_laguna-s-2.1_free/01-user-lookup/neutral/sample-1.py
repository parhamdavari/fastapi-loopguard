from fastapi import FastAPI

import helpers

app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await helpers.aload_user(user_id)
    return user
