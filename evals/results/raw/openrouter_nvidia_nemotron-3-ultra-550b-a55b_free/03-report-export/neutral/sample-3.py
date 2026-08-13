from fastapi import FastAPI, Body
from pydantic import BaseModel

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


class ReportRequest(BaseModel):
    rows: list


@app.post("/reports")
def create_report(request: ReportRequest):
    rendered = helpers.render_report(request.rows)
    return {"length": len(rendered)}
