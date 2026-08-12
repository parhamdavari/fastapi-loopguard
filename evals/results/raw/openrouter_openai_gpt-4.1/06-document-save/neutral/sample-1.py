from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/documents", status_code=201)
async def save_document_endpoint(request: Request):
    data = await request.json()
    name = data.get("name")
    text = data.get("text")
    if name is None or text is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Missing 'name' or 'text'"},
        )
    saved_bytes = helpers.save_document(name, text)
    return {"bytes": saved_bytes}
