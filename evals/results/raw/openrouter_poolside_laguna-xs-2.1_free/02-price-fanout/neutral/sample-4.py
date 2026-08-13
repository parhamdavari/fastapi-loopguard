from fastapi import FastAPI

import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str):
    symbol_list = symbols.split(",")
    prices = await asyncio.gather(*[helpers.afetch_price(s) for s in symbol_list])
    return {"prices": {symbol: price for symbol, price in zip(symbol_list, prices)}}
