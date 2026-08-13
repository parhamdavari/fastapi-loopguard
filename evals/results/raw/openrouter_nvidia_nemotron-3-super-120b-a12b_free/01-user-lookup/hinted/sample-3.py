from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    return await helpers.aload_user(user_id)
