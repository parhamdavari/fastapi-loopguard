from fastapi import FastAPI
from pydantic import BaseModel
import helpers
import asyncio

app = FastAPI()

class ReportRequest(BaseModel):
    rows: list

@app.post("/reports")
async def create_report(request: ReportRequest):
    rendered = await asyncio.to_thread(helpers.render_report, request.rows)
    return {"length": len(rendered)}
