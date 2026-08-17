from fastapi import FastAPI, Body
from typing import List, Any

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.post("/reports")
def create_report(rows: List[Any] = Body(..., embed=True)):
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
