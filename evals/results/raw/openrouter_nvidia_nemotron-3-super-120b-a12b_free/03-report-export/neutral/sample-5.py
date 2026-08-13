from fastapi import FastAPI
from pydantic import BaseModel
import helpers

app = FastAPI()


class ReportRequest(BaseModel):
    rows: list


@app.post("/reports")
def create_report(request: ReportRequest):
    rendered_report = helpers.render_report(request.rows)
    return {"length": len(rendered_report)}
