from fastapi import FastAPI, Body
import helpers
import asyncio

app = FastAPI()


@app.post("/reports")
async def create_report(rows: list = Body(..., embed=True)):
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
