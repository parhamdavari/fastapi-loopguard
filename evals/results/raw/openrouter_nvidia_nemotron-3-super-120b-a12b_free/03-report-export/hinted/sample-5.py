from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
import helpers

app = FastAPI()


@app.post("/reports")
async def create_report(payload: dict):
    rows = payload.get("rows", [])
    rendered = await run_in_threadpool(helpers.render_report, rows)
    return {"length": len(rendered)}
