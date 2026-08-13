from fastapi import FastAPI
from pydantic import BaseModel
import helpers

app = FastAPI()

class OrderItem(BaseModel):
    item: str

@app.post("/orders", status_code=201)
async def create_order(order: OrderItem):
    await helpers.aappend_audit_line(f"order:{order.item}")
    return {"status": "created"}
