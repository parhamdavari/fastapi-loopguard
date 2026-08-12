from fastapi import FastAPI
from pydantic import BaseModel
import helpers

app = FastAPI()


class DocumentCreate(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=201)
def create_document(doc: DocumentCreate):
    bytes_count = helpers.save_document(doc.name, doc.text)
    return {"bytes": bytes_count}
