from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/documents")
async def create_document(name: str, text: str):
    loop = asyncio.get_running_loop()
    byte_count = await loop.run_in_executor(None, helpers.save_document, name, text)
    return {"bytes": byte_count}, 201
