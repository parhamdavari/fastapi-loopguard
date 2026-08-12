from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(payload: dict) -> dict:
    await helpers.aappend_audit_line(f"order:{payload['item']}")
    return {"status": "created"}
