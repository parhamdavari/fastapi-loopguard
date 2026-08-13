from fastapi import FastAPI, Request

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/documents")
async def create_document(request: Request):
    data = await request.json()
    name = data.get("name")
    text = data.get("text")
    bytes_written = helpers.save_document(name, text)
    return {"bytes": bytes_written}
