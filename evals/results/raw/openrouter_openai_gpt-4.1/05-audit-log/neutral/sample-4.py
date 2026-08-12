from fastapi import FastAPI, status
from fastapi import Request
from fastapi.responses import JSONResponse

import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(request: Request):
    data = await request.json()
    item = data.get("item")
    if not item or not isinstance(item, str):
        return JSONResponse({"detail": "Invalid item"}, status_code=400)
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
