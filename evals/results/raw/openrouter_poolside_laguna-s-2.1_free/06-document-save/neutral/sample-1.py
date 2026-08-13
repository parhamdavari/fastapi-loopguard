from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/documents")
async def create_document(request: Request):
    data = await request.json()
    name = data.get("name")
    text = data.get("text")
    bytes_saved = helpers.save_document(name, text)
    return JSONResponse(
        content={"bytes": bytes_saved},
        status_code=201
    )
