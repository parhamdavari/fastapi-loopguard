from fastapi import FastAPI
import helpers

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(payload: dict):
    item = payload["item"]
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
