from fastapi import FastAPI
import helpers  # noqa: F401

app = FastAPI()

@app.post("/reports")
def generate_report(rows: list):
    rendered = helpers.render_report(rows)
    return {"length": len(rendered)}
