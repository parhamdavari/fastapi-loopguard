from fastapi import FastAPI, Request

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/documents", status_code=201)
async def create_document(request: Request):
    data = await request.json()
    name = data["name"]
    text = data["text"]
    bytes_saved = helpers.save_document(name, text)
    return {"bytes": bytes_saved}
