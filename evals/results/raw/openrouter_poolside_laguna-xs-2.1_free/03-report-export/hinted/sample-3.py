from fastapi import FastAPI, Body
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
async def post_report(rows: list = Body(...)):
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
