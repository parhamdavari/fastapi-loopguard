from fastapi import FastAPI
import helpers
import asyncio
from pydantic import BaseModel

app = FastAPI()

class DocumentInput(BaseModel):
    name: str
    text: str

@app.post("/documents")
async def create_document(document: DocumentInput):
    bytes_count = await asyncio.to_thread(helpers.save_document, document.name, document.text)
    return {"bytes": bytes_count}, 201
