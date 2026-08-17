from fastapi import FastAPI
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = ''):
    symbols_list = [s for s in symbols.split(",")] if symbols else []

    async def fetch_all(symbols):
        tasks = [helpers.afetch_price(symbol) for symbol in symbols]
        return await asyncio.gather(*tasks)

    prices_list = await fetch_all(symbols_list)

    return {"prices": {symbol: price for symbol, price in zip(symbols_list, prices_list)}}
