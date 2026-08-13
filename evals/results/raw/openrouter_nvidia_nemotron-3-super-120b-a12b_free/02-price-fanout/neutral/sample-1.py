from fastapi import FastAPI
import helpers
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str = ""):
    # Split the comma‑separated list, stripping whitespace and ignoring empties
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    # If no symbols were provided, return an empty prices dict
    if not symbol_list:
        return {"prices": {}}

    # Fetch all prices concurrently using the async helper
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]
    prices = await asyncio.gather(*tasks)

    # Build the result mapping symbol → price
    result = {sym: price for sym, price in zip(symbol_list, prices)}
    return {"prices": result}
