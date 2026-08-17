from fastapi import FastAPI
import helpers
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str = ""):
    """
    Return current prices for the given comma‑separated symbols.
    Example: GET /portfolio?symbols=AAA,BBB,CCC
    """
    if not symbols:
        return {"prices": {}}

    # Split, strip whitespace, and normalise to upper case
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not sym_list:
        return {"prices": {}}

    # Fetch all prices concurrently using the async helper
    coros = [helpers.afetch_price(sym) for sym in sym_list]
    prices = await asyncio.gather(*coros)

    return {"prices": dict(zip(sym_list, prices))}
