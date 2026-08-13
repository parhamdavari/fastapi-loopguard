from fastapi import FastAPI, Body, status

import helpers

app = FastAPI()


@app.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(item: str = Body(...)):
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
