import asyncio

from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
async def render_report_endpoint(data: dict):
    rows = data["rows"]
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
