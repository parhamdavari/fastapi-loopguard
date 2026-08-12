from fastapi import FastAPI
import helpers  # noqa: F401  (the provided API)
import asyncio

app = FastAPI()


@app.post("/reports")
async def render_reports(rows: list):
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
