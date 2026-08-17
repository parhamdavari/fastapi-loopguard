from fastapi import FastAPI, HTTPException
from typing import Dict

import helpers

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str):
    symbol_list = [s for s in symbols.split(',') if s]
    tasks = [helpers.afetch_price(symbol) for symbol in symbol_list]
    results = await asyncio.gather(*tasks)
    price_dict = {symbol: price for symbol, price in zip(symbol_list, results)}
    return {"prices": price_dict}
