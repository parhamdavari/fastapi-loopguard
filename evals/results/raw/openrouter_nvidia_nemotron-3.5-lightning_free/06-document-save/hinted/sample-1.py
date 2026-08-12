from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401

app = FastAPI()


@app.post("/documents", status_code=201)
async def create_document(payload: dict):
    name = payload["name"]
    text = payload["text"]
    bytes_count = await asyncio.to_thread(helpers.save_document, name, text)
    return {"bytes": bytes_count}
