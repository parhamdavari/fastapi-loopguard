from fastapi import FastAPI, status
from pydantic import BaseModel
import helpers

app = FastAPI()


class DocumentCreate(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=status.HTTP_201_CREATED)
def create_document(document: DocumentCreate):
    bytes_count = helpers.save_document(document.name, document.text)
    return {"bytes": bytes_count}
