from fastapi import FastAPI, status
from fastapi import Request
from fastapi.responses import JSONResponse

import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(req: Request):
    data = await req.json()
    item = data["item"]
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
