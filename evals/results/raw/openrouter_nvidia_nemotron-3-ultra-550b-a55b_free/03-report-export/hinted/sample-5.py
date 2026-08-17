from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


class ReportRequest(BaseModel):
    rows: list


@app.post("/reports")
async def create_report(request: ReportRequest):
    # Run the synchronous render_report in a thread pool to avoid blocking the event loop
    rendered = await asyncio.to_thread(helpers.render_report, request.rows)
    return {"length": len(rendered)}
