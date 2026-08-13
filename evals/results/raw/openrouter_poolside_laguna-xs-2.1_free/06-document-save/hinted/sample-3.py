import asyncio
from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/documents", status_code=201)
async def create_document(name: str, text: str):
    loop = asyncio.get_running_loop()
    bytes_written = await loop.run_in_executor(None, helpers.save_document, name, text)
    return {"bytes": bytes_written}
