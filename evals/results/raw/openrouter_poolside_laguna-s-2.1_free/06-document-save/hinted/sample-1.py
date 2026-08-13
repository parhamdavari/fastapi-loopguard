from fastapi import FastAPI
from pydantic import BaseModel
import asyncio

import helpers  # noqa: F401


app = FastAPI()


class DocumentRequest(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=201)
async def create_document(document: DocumentRequest):
    bytes_saved = await asyncio.to_thread(
        helpers.save_document, document.name, document.text
    )
    return {"bytes": bytes_saved}
