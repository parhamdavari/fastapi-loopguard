from fastapi import FastAPI, Body
import helpers

app = FastAPI()


@app.post("/orders")
async def create_order(item: str = Body(..., embed=True)):
    await helpers.aappend_audit_line(f"order:{item}")
    return {"status": "created"}
