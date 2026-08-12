from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/documents", status_code=201)
async def save_document(payload: dict) -> dict:
    size = helpers.save_document(payload["name"], payload["text"])  # blocks ~120ms
    return {"bytes": size}
