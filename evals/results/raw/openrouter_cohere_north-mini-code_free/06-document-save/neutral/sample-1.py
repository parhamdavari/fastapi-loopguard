from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/documents", status_code=201)
def create_document(payload: dict):
    name = payload["name"]
    text = payload["text"]
    bytes_written = helpers.save_document(name, text)
    return {"bytes": bytes_written}
