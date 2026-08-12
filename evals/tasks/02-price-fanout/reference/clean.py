import asyncio

from fastapi import FastAPI

import helpers

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str) -> dict:
    names = symbols.split(",")
    prices = await asyncio.gather(*(helpers.afetch_price(s) for s in names))
    return {"prices": dict(zip(names, prices, strict=True))}
