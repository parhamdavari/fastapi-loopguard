import asyncio

from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/documents")
async def save_document(body: dict):
    name = body["name"]
    text = body["text"]
    bytes_written = await asyncio.to_thread(helpers.save_document, name, text)
    return {"bytes": bytes_written}, 201
