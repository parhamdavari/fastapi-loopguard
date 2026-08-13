from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/documents")
def save_doc(doc: dict):
    name = doc["name"]
    text = doc["text"]
    bytes_saved = helpers.save_document(name, text)
    return {"bytes": bytes_saved}, 201
