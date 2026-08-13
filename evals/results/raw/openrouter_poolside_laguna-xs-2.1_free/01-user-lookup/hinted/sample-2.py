from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/users/{user_id}")
async def read_user(user_id: int):
    user = await helpers.aload_user(user_id)
    return user
