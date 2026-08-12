from fastapi import FastAPI, Path
import helpers  # noqa: F401 (the provided API)

app = FastAPI()


@app.get("/users/{user_id}")
def get_user(user_id: int = Path(...)):
    user = helpers.load_user(user_id)
    return user
