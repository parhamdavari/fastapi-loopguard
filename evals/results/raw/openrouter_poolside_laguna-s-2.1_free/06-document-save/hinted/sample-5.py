from fastapi import FastAPI, Body
from fastapi.responses import JSONResponse
import asyncio

import helpers

app = FastAPI()

@app.post("/documents")
async def save_document(
    name: str = Body(...),
    text: str = Body(...),
):
    bytes_written = await asyncio.to_thread(helpers.save_document, name, text)
    return JSONResponse(
        {"bytes": bytes_written},
        status_code=201,
    )
