from fastapi import FastAPI
from pydantic import BaseModel

import helpers  # noqa: F401

app = FastAPI()


class DocumentIn(BaseModel):
    name: str
    text: str


@app.post("/documents")
async def create_document(doc: DocumentIn):
    result = helpers.save_document(doc.name, doc.text)
    return {"bytes": result}
