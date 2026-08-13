from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
async def create_report(request: Request):
    body = await request.json()
    rows = body.get("rows", [])
    rendered = helpers.render_report(rows)
    return JSONResponse(content={"length": len(rendered)}, status_code=200)
