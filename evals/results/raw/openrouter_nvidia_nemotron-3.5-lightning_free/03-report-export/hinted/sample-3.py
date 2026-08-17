from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401

app = FastAPI()


@app.post("/reports")
async def render_report(rows: list):
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
