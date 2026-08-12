from fastapi import FastAPI
import helpers
import asyncio
from pydantic import BaseModel

app = FastAPI()


class ReportRequest(BaseModel):
    rows: list


@app.post("/reports")
async def post_reports(req: ReportRequest):
    rendered = await asyncio.to_thread(helpers.render_report, req.rows)
    return {"length": len(rendered)}
