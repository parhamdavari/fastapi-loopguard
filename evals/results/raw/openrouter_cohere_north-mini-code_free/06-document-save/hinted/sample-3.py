from fastapi import FastAPI
from pydantic import BaseModel
import asyncio
import helpers

app = FastAPI()


class DocumentCreate(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=201)
async def create_document(doc: DocumentCreate):
    bytes_written = await asyncio.to_thread(helpers.save_document, doc.name, doc.text)
    return {"bytes": bytes_written}
