from fastapi import FastAPI, Body

import helpers  # noqa: F401 (the provided API)

app = FastAPI()


@app.post("/orders")
async def create_order(item: str = Body(...)):
    """Create an order and log it to the audit trail."""
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}, 201
