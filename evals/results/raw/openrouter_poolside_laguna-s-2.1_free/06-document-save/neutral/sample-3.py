from fastapi import FastAPI
from pydantic import BaseModel

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


class DocumentRequest(BaseModel):
    name: str
    text: str


@app.post("/documents")
def create_document(doc: DocumentRequest):
    bytes_written = helpers.save_document(doc.name, doc.text)
    return {"bytes": bytes_written}, 201
