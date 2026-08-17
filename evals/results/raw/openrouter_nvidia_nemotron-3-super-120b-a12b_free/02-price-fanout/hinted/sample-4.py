from fastapi import FastAPI, Query
import helpers
import asyncio
from typing import Dict, List

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str = Query("")):
    """Return current prices for the given comma‑separated symbols."""
    if not symbols:
        return {"prices": {}}

    # Split and clean the symbol list
    symbol_list: List[str] = [s.strip() for s in symbols.split(",") if s.strip()]

    # Launch all async fetches concurrently
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]
    prices: List[float] = await asyncio.gather(*tasks)

    # Build the response mapping
    price_map: Dict[str, float] = {sym: price for sym, price in zip(symbol_list, prices)}
    return {"prices": price_map}
