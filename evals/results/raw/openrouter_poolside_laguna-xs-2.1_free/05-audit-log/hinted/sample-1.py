from fastapi import FastAPI, Request, status

import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(request: Request):
    data = await request.json()
    item = data["item"]
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
