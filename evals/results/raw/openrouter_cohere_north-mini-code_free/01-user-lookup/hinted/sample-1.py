from fastapi import FastAPI

import helpers  # noqa: F401

app = FastAPI()


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    """Return the user record for the given user_id."""
    user = await helpers.aload_user(user_id)
    return user
