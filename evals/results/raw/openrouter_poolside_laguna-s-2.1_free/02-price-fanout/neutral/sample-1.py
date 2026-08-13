from fastapi import FastAPI

import helpers  # noqa: F401
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str):
    symbol_list = symbols.split(",")
    tasks = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices = await asyncio.gather(*tasks)
    return {"prices": {symbol: price for symbol, price in zip(symbol_list, prices)}}
