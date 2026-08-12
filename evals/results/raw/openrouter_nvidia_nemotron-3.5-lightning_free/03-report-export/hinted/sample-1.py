from fastapi import FastAPI, Body
import asyncio
import helpers

app = FastAPI()


@app.post("/reports")
async def post_reports(rows: list = Body(...)):
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
