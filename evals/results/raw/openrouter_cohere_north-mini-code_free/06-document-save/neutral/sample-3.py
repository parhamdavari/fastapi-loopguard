from fastapi import FastAPI, status
from pydantic import BaseModel

import helpers  # noqa: F401

app = FastAPI()


class DocumentRequest(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=status.HTTP_201_CREATED)
def create_document(request: DocumentRequest):
    """Persist the document and return the number of bytes written."""
    bytes_written = helpers.save_document(request.name, request.text)
    return {"bytes": bytes_written}
