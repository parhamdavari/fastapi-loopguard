from fastapi import FastAPI, status
from pydantic import BaseModel
import asyncio
import helpers  # noqa: F401

app = FastAPI()


class DocumentRequest(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=status.HTTP_201_CREATED)
async def create_document(doc: DocumentRequest):
    bytes_written = await asyncio.to_thread(helpers.save_document, doc.name, doc.text)
    return {"bytes": bytes_written}
