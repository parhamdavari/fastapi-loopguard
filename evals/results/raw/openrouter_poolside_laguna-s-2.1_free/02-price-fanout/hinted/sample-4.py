from fastapi import FastAPI
from typing import List, Dict

import helpers

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str):
    symbol_list = symbols.split(',')
    tasks = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices_list = await helpers.asyncio.gather(*tasks)
    prices = {symbol: price for symbol, price in zip(symbol_list, prices_list)}
    return {"prices": prices}
