from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401 (provided API)

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str):
    """Fetch prices for a comma-separated list of symbols concurrently."""
    symbol_list = [s.strip() for s in symbols.split(",")]
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]
    prices = await asyncio.gather(*tasks)
    return {"prices": dict(zip(symbol_list, prices))}
