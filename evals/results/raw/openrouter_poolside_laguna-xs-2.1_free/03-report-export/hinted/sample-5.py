from fastapi import FastAPI
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
async def reports_endpoint(body: dict):
    rows = body["rows"]
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
