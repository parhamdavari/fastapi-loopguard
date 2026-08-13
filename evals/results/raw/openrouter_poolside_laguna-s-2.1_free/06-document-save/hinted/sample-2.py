from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio
import helpers

app = FastAPI()


@app.post("/documents")
async def save_document_endpoint(payload: dict):
    name = payload.get("name")
    text = payload.get("text")
    loop = asyncio.get_event_loop()
    bytes_saved = await loop.run_in_executor(None, helpers.save_document, name, text)
    return JSONResponse(content={"bytes": bytes_saved}, status_code=201)
