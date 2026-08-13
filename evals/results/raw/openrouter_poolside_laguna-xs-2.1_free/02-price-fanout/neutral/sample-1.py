import asyncio

from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str) -> dict:
    symbols_list = symbols.split(",")
    coroutines = [helpers.afetch_price(symbol) for symbol in symbols_list]
    prices = await asyncio.gather(*coroutines)
    return {"prices": dict(zip(symbols_list, prices))}
