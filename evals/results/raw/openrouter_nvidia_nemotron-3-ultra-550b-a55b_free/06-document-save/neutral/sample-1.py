from fastapi import FastAPI, status
from pydantic import BaseModel
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


class Document(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=status.HTTP_201_CREATED)
async def create_document(doc: Document):
    # Offload the blocking I/O to a thread pool
    byte_count = await asyncio.to_thread(helpers.save_document, doc.name, doc.text)
    return {"bytes": byte_count}
