from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(payload: dict) -> dict:
    helpers.append_audit_line(f"order:{payload['item']}")  # blocks ~120ms
    return {"status": "created"}
