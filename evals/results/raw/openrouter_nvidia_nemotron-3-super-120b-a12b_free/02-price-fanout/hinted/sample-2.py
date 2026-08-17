from fastapi import FastAPI
import helpers
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str):
    """
    Return prices for the given comma‑separated symbols.
    Example: /portfolio?symbols=AAA,BBB,CCC
    """
    if not symbols:
        return {"prices": {}}

    # Split the query string into individual symbols, stripping whitespace.
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    # Create a list of coroutines to fetch each price concurrently.
    coroutines = [helpers.afetch_price(sym) for sym in symbol_list]

    # Run all coroutines concurrently and gather their results.
    prices = await asyncio.gather(*coroutines)

    # Build the response dictionary.
    result = {sym: price for sym, price in zip(symbol_list, prices)}
    return {"prices": result}
