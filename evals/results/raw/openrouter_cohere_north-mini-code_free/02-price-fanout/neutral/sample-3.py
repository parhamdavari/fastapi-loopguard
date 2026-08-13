from fastapi import FastAPI, Query
import asyncio

import helpers  # noqa: F401 (provided API)

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str = Query(...)):
    """
    Fetch the price of every requested symbol asynchronously and return them.
    """
    # Split comma-separated symbols, strip whitespace, and ignore empty entries
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    # Create a task for each symbol using the async helper
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]

    # Run all fetches concurrently
    prices = await asyncio.gather(*tasks)

    # Pair symbols with their fetched prices
    result = {sym: price for sym, price in zip(symbol_list, prices)}

    return {"prices": result}
