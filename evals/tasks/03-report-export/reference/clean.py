import asyncio

from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/reports")
async def create_report(payload: dict) -> dict:
    rendered = await asyncio.to_thread(helpers.render_report, payload["rows"])
    return {"length": len(rendered)}
