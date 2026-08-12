from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/reports")
async def create_report(payload: dict) -> dict:
    rendered = helpers.render_report(payload["rows"])  # blocks ~150ms
    return {"length": len(rendered)}
