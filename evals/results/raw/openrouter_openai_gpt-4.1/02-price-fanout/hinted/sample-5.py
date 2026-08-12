from fastapi import FastAPI, Query
from typing import Dict
import helpers
import asyncio

app = FastAPI()

@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(...)):
    symbol_list = [s for s in symbols.split(",") if s]
    # fan out async price fetches
    prices_list = await asyncio.gather(*(helpers.afetch_price(symbol) for symbol in symbol_list))
    prices = dict(zip(symbol_list, prices_list))
    return {"prices": prices}
