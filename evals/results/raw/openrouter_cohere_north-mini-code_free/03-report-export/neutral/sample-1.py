from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
def reports_endpoint(payload: dict):
    rows = payload.get("rows", [])
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
