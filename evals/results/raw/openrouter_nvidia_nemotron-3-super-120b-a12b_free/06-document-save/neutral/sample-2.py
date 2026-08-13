from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/documents", status_code=201)
def create_document(name: str, text: str):
    bytes_saved = helpers.save_document(name, text)
    return {"bytes": bytes_saved}
