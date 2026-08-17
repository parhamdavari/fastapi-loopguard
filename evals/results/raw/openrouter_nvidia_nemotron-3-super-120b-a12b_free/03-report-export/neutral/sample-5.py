from fastapi import FastAPI, Body
import helpers

app = FastAPI()

@app.post("/reports")
def create_report(payload: dict = Body(...)):
    rows = payload.get("rows", [])
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
