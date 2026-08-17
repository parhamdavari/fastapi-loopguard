import asyncio
from fastapi import FastAPI

import helpers  # provided API

app = FastAPI()

@app.get("/portfolio")
async def get_portfolio(symbols: str):
    """
    Fetch prices for given comma-separated symbols asynchronously.

    Args:
        symbols: Comma-separated list of symbol strings (e.g., "AAA,BBB,CCC").

    Returns:
        {"prices": {"AAA": 30.0, "BBB": 30.0, "CCC": 30.0}}
    """
    # Parse the comma-separated string into a list of trimmed symbols
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    # Create a list of async tasks to fetch each price
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]

    # Run all tasks concurrently (non-blocking)
    results = await asyncio.gather(*tasks)

    # Build the price dictionary mapping symbol -> price
    price_dict = {sym: price for sym, price in zip(symbol_list, results)}

    # Return the required JSON structure
    return {"prices": price_dict}
