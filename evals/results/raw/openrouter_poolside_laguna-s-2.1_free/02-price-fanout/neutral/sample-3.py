from fastapi import FastAPI
from typing import List, Dict

import helpers  # noqa: F401

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str) -> Dict[str, Dict[str, float]]:
    symbol_list: List[str] = symbols.split(",")
    tasks = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices_list = await asyncio.gather(*tasks)
    prices = {symbol: price for symbol, price in zip(symbol_list, prices_list)}
    return {"prices": prices}
