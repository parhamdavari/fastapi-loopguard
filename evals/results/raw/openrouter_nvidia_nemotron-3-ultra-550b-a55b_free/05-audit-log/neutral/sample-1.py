from fastapi import FastAPI, status
from pydantic import BaseModel

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


class OrderCreate(BaseModel):
    item: str


@app.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(order: OrderCreate):
    line = f"order:{order.item}"
    await helpers.aappend_audit_line(line)
    return {"status": "created"}
