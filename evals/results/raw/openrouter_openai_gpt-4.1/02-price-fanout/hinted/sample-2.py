from fastapi import FastAPI, Query
from typing import Dict
import asyncio

import helpers  # noqa: F401

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(..., description="Comma-separated list of symbols")) -> Dict[str, Dict[str, float]]:
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    coros = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices_list = await asyncio.gather(*coros)
    return {"prices": dict(zip(symbol_list, prices_list))}
