# app.py
from fastapi import FastAPI
from typing import List
from urllib.parse import parse_qs

import asyncio
import helpers

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = ""):
    symbol_list: List[str] = [s.strip() for s in symbols.split(",") if s.strip()]
    
    async def fetch(symbol: str):
        # Use async fetch to avoid blocking
        return {symbol: await helpers.afetch_price(symbol)}
    
    tasks = [fetch(symbol) for symbol in symbol_list]
    
    # Gather results concurrently
    results = await asyncio.gather(*tasks)
    
    # Merge individual results into a single dict
    prices = {}
    for result in results:
        prices.update(result)
    
    return {"prices": prices}
