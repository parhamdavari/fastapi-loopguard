from fastapi import FastAPI, Body

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
def create_report(rows: list = Body(...)):
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
