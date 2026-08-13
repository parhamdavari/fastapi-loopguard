from fastapi import FastAPI
from typing import Dict

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str):
    symbol_list = symbols.split(",")
    tasks = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices_list = await helpers.asyncio.gather(*tasks)
    prices = dict(zip(symbol_list, prices_list))
    return {"prices": prices}
