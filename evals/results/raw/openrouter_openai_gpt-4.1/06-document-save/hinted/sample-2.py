from fastapi import FastAPI, status
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import helpers
import asyncio

app = FastAPI()


class DocumentIn(BaseModel):
    name: str
    text: str


@app.post("/documents", status_code=status.HTTP_201_CREATED)
async def create_document(doc: DocumentIn):
    loop = asyncio.get_running_loop()
    bytes_written = await loop.run_in_executor(
        None, helpers.save_document, doc.name, doc.text
    )
    return {"bytes": bytes_written}
