from fastapi import FastAPI, Body

import helpers

app = FastAPI()


@app.post("/orders", status_code=201)
async def create_order(payload: dict = Body(...)):
    item = payload.get("item")
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
