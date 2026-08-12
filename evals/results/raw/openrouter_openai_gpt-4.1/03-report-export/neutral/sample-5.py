from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import helpers  # noqa: F401

app = FastAPI()


@app.post("/reports")
async def reports(request: Request):
    data = await request.json()
    rows = data.get("rows", [])
    report_str = helpers.render_report(rows)
    return JSONResponse(content={"length": len(report_str)}, status_code=200)
