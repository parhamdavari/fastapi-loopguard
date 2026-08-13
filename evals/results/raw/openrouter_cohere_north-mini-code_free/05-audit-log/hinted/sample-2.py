from fastapi import FastAPI
from fastapi.responses import JSONResponse
import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders")
async def create_order(payload: dict):
    """Create an order and log it to the audit trail."""
    item_name = payload["item"]
    await helpers.aappend_audit_line(f"order:{item_name}")
    return JSONResponse(content={"status": "created"}, status_code=201)
