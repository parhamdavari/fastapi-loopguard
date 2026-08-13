from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
def create_report(data: dict):
    rows = data["rows"]
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
