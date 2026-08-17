from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
async def create_report(request: Request):
    data = await request.json()
    rows = data.get("rows", [])
    rendered = await run_in_threadpool(helpers.render_report, rows)
    return {"length": len(rendered)}
