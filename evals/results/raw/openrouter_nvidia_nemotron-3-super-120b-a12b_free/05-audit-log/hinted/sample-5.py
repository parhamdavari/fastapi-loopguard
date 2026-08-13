from fastapi import FastAPI, status
from pydantic import BaseModel
import helpers

app = FastAPI()

class Order(BaseModel):
    item: str

@app.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(order: Order):
    await helpers.aappend_audit_line(f"order:{order.item}")
    return {"status": "created"}
