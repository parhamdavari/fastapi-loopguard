from fastapi import FastAPI, Body

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/documents")
def save_document(name: str = Body(...), text: str = Body(...)):
    bytes_saved = helpers.save_document(name, text)
    return {"bytes": bytes_saved}, 201
