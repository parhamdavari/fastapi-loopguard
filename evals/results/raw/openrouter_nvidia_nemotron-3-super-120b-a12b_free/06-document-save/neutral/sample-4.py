from fastapi import FastAPI
from pydantic import BaseModel
import helpers

app = FastAPI()


class Document(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=201)
def create_document(document: Document):
    bytes_written = helpers.save_document(document.name, document.text)
    return {"bytes": bytes_written}
