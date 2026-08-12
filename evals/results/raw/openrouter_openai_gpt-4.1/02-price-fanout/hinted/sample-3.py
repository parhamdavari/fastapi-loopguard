from fastapi import FastAPI, Query
from typing import Dict

import helpers  # noqa: F401

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(..., description="Comma-separated list of symbols")) -> Dict[str, Dict[str, float]]:
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    prices = await _get_prices(symbol_list)
    return {"prices": prices}


async def _get_prices(symbol_list):
    coros = [helpers.afetch_price(symbol) for symbol in symbol_list]
    results = await asyncio.gather(*coros)
    return dict(zip(symbol_list, results))
