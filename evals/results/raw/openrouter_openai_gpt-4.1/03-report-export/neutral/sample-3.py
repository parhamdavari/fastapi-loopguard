from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import helpers

app = FastAPI()


@app.post("/reports")
async def create_report(request: Request):
    data = await request.json()
    rows = data.get("rows", [])
    rendered = helpers.render_report(rows)
    return JSONResponse({"length": len(rendered)})
