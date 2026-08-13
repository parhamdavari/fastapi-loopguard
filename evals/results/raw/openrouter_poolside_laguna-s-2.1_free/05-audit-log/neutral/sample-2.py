from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/orders")
async def create_order(payload: dict):
    item = payload.get("item")
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
