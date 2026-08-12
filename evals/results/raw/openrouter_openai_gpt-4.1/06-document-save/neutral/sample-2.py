from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

import helpers  # noqa: F401  (the provided API)

app = FastAPI()

@app.post("/documents")
async def save_document_endpoint(request: Request):
    body = await request.json()
    name = body.get("name")
    text = body.get("text")

    # No validation required by prompt; fastapi will error on bad request
    bytes_written = helpers.save_document(name, text)
    return JSONResponse(content={"bytes": bytes_written}, status_code=status.HTTP_201_CREATED)
