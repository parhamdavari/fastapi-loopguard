from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str = ""):
    # Parse and clean the comma-separated symbols
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {"prices": {}}

    # Fetch prices concurrently using the async helper
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]
    prices = await asyncio.gather(*tasks)

    # Build the result mapping symbol -> price
    result = {sym: price for sym, price in zip(symbol_list, prices)}
    return {"prices": result}
