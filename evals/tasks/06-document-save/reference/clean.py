import asyncio

from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/documents", status_code=201)
async def save_document(payload: dict) -> dict:
    size = await asyncio.to_thread(
        helpers.save_document, payload["name"], payload["text"]
    )
    return {"bytes": size}
