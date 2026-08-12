from fastapi import FastAPI, Query
from typing import Dict, List
import helpers
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(..., description="Comma-separated list of symbols")):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {"prices": {}}

    coros = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices = await asyncio.gather(*coros)
    result: Dict[str, float] = dict(zip(symbol_list, prices))
    return {"prices": result}
