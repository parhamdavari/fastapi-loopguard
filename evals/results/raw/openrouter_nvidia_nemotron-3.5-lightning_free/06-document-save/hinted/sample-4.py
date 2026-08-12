from fastapi import FastAPI, Body
import asyncio
import helpers  # noqa: F401

app = FastAPI()


@app.post("/documents", status_code=201)
async def create_document(data: dict = Body(...)):
    name = data["name"]
    text = data["text"]
    bytes_written = await asyncio.to_thread(helpers.save_document, name, text)
    return {"bytes": bytes_written}
