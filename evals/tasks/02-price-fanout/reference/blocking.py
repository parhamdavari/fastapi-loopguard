from fastapi import FastAPI

import helpers

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str) -> dict:
    names = symbols.split(",")
    prices = {s: helpers.fetch_price(s) for s in names}  # blocks 3x
    return {"prices": prices}
