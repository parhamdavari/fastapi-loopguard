from fastapi import FastAPI, Body
import helpers

app = FastAPI()


@app.post("/documents", status_code=201)
def create_document(name: str = Body(...), text: str = Body(...)):
    bytes_written = helpers.save_document(name, text)
    return {"bytes": bytes_written}
