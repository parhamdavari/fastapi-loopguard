import asyncio
from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/documents", status_code=201)
async def create_document(payload: dict):
    name = payload["name"]
    text = payload["text"]
    bytes_written = await asyncio.to_thread(helpers.save_document, name, text)
    return {"bytes": bytes_written}
