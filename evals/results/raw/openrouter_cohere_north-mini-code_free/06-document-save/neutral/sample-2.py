from fastapi import FastAPI
import helpers

app = FastAPI()

@app.post("/documents")
async def create_document(doc: dict):
    name = doc["name"]
    text = doc["text"]
    bytes_written = helpers.save_document(name, text)
    return {"bytes": bytes_written}
