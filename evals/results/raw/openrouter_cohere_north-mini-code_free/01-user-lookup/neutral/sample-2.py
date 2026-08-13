from fastapi import FastAPI

import helpers  # noqa: F401

app = FastAPI()

@app.get("/users/{user_id}")
def get_user(user_id: int) -> dict:
    """
    Retrieve a user by ID.

    Uses the synchronous `load_user` helper.
    """
    return helpers.load_user(user_id)
