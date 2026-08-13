from fastapi import FastAPI, Body
import helpers
import asyncio

app = FastAPI()


@app.post("/documents", status_code=201)
async def create_document(payload: dict = Body(...)):
    name = payload.get("name")
    text = payload.get("text")
    # Offload the blocking I/O to a thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    bytes_written = await loop.run_in_executor(None, helpers.save_document, name, text)
    return {"bytes": bytes_written}
