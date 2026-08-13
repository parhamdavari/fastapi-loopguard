from fastapi import FastAPI

import helpers  # noqa: F401

app = FastAPI()


@app.get("/users/{user_id}")
def get_user(user_id: int):
    user = helpers.load_user(user_id)
    return user
