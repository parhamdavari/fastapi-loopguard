from fastapi import FastAPI, Body, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


class DocumentCreate(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=status.HTTP_201_CREATED)
async def create_document(doc: DocumentCreate = Body(...)):
    bytes_written = await run_in_threadpool(helpers.save_document, doc.name, doc.text)
    return {"bytes": bytes_written}
