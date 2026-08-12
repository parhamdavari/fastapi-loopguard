from fastapi import FastAPI, Body
import helpers  # noqa: F401

app = FastAPI()


@app.post("/orders", status_code=201)
def create_order(item: str = Body(...)):
    helpers.append_audit_line(f"order:{item}")
    return {"status": "created"}
