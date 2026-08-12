from fastapi import FastAPI

import helpers

app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int) -> dict:
    return helpers.load_user(user_id)  # blocks the loop for ~150ms
