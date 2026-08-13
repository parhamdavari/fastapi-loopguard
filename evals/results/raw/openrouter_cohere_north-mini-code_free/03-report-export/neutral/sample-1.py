from fastapi import FastAPI, Request
import helpers
import asyncio

app = FastAPI()


@app.post("/reports")
async def post_reports(request: Request):
    # Parse the JSON body manually to avoid relying on Pydantic models,
    # adhering to the constraint of using only standard library for parsing logic.
    data = await request.json()
    rows = data.get("rows", [])

    # Execute the CPU-bound rendering function in a separate thread
    # to avoid blocking the FastAPI event loop.
    rendered_report = await asyncio.to_thread(helpers.render_report, rows)

    return {"length": len(rendered_report)}
