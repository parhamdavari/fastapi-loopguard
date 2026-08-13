from fastapi import FastAPI
from pydantic import BaseModel
import helpers

app = FastAPI()


class OrderCreate(BaseModel):
    item: str


@app.post("/orders", status_code=201)
async def create_order(order: OrderCreate):
    await helpers.aappend_audit_line(f"order:{order.item}")
    return {"status": "created"}
