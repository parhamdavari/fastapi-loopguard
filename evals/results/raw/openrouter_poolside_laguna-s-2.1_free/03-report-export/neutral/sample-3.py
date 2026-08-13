from fastapi import FastAPI, Request
import helpers

app = FastAPI()


@app.post("/reports")
async def reports(request: Request):
    body = await request.json()
    rows = body.get("rows", [])
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
