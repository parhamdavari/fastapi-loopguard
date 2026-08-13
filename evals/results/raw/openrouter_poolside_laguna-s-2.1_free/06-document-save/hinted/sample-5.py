from fastapi import FastAPI, Body
from fastapi.responses import JSONResponse
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/documents")
async def save_document(
    name: str = Body(..., embed=True),
    text: str = Body(..., embed=True),
):
    bytes_written = await asyncio.to_thread(helpers.save_document, name, text)
    return JSONResponse(
        {"bytes": bytes_written},
        status_code=201,
    )
