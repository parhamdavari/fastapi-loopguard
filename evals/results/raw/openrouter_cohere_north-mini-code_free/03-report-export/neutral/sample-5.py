from fastapi import FastAPI

import helpers

app = FastAPI()

@app.post("/reports")
def reports(payload: dict):
    rows = payload["rows"]
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
