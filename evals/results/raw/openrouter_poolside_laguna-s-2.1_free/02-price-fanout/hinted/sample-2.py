from fastapi import FastAPI
from typing import List, Dict

import helpers

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str):
    symbol_list = symbols.split(",")
    tasks = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices = await asyncio.gather(*tasks)
    return {"prices": dict(zip(symbol_list, prices))}
