from fastapi import FastAPI

import helpers  # noqa: F401 (the provided API)

app = FastAPI()


@app.post("/reports")
async def reports(request: dict):
    rows = request["rows"]
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
