from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401

app = FastAPI()


@app.post("/reports")
async def create_report(rows: list):
    """
    Render a CPU‑bound report in a separate thread to avoid blocking the event loop.

    Parameters
    ----------
    rows : list
        JSON payload with an array of rows to be rendered.

    Returns
    -------
    dict
        `{"length": <len of rendered string>}`
    """
    # Offload the CPU‑bound work to a thread pool
    rendered = await asyncio.to_thread(helpers.render_report, rows)
    return {"length": len(rendered)}
