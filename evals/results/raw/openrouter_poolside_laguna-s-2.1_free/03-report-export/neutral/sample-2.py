from fastapi import FastAPI, Request

import helpers  # noqa: F401

app = FastAPI()


@app.post("/reports")
async def create_report(request: Request):
    body = await request.json()
    rows = body.get("rows", [])
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
