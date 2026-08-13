from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(body: dict):
    item = body["item"]
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
