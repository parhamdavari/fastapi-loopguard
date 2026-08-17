from fastapi import FastAPI
from pydantic import BaseModel
import helpers

app = FastAPI()


class ReportRequest(BaseModel):
    rows: list


@app.post("/reports")
def post_reports(request: ReportRequest):
    rendered = helpers.render_report(request.rows)
    return {"length": len(rendered)}
