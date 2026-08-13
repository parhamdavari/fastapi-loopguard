from fastapi import FastAPI
from pydantic import BaseModel

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


class DocumentCreate(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=201)
def create_document(doc: DocumentCreate):
    bytes_saved = helpers.save_document(doc.name, doc.text)
    return {"bytes": bytes_saved}
