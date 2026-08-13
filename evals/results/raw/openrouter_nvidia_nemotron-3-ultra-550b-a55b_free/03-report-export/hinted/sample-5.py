from fastapi import FastAPI, Request
import asyncio
import helpers

app = FastAPI()


@app.post("/reports")
async def create_report(request: Request):
    data = await request.json()
    rows = data.get("rows", [])
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
