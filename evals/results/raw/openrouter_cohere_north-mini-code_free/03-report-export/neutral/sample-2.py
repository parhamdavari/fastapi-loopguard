from fastapi import FastAPI, Request

import helpers  # noqa: F401  (the provided API)

app = FastAPI()

@app.post("/reports")
async def reports(request: Request):
    data = await request.json()
    rows = data["rows"]
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
