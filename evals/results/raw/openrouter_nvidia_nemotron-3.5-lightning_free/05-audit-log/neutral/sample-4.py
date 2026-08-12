from fastapi import FastAPI

import helpers

app = FastAPI()


@app.post("/orders")
async def create_item(item: str):
    helpers.append_audit_line(f"order:{item}")
    return {"status": "created"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
