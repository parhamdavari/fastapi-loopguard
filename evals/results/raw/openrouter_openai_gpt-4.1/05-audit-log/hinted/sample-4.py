from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

import helpers

app = FastAPI()


@app.post("/orders")
async def create_order(request: Request):
    body = await request.json()
    item = body.get("item")
    if not item or not isinstance(item, str):
        return JSONResponse({"error": "Missing or invalid 'item'"}, status_code=400)
    await helpers.aappend_audit_line(f"order:{item}")
    return JSONResponse({"status": "created"}, status_code=status.HTTP_201_CREATED)
