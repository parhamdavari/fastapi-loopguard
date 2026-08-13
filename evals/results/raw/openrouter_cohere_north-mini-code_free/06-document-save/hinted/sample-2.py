from fastapi import FastAPI
import helpers
import asyncio

app = FastAPI()


@app.post("/documents")
async def create_document(payload: dict):
    """Accept a document name and text, persist it asynchronously, and return the saved byte count."""
    name = payload["name"]
    text = payload["text"]

    # Run the blocking I/O in a thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    bytes_saved = await loop.run_in_executor(
        None, helpers.save_document, name, text
    )

    return {"bytes": bytes_saved}, 201
