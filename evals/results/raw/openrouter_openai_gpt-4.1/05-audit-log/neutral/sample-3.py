from fastapi import FastAPI, status
from fastapi import Request
from fastapi.responses import JSONResponse

import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(payload: dict):
    item = payload.get("item")
    if not isinstance(item, str):
        return JSONResponse({"detail": "Missing or invalid 'item' field"}, status_code=400)
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
