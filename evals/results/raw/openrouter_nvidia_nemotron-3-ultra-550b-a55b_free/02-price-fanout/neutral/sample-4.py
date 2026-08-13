from fastapi import FastAPI, Query
import asyncio
import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(..., description="Comma-separated list of symbols")):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    # Fetch prices concurrently using the async helper
    prices = await asyncio.gather(*(helpers.afetch_price(sym) for sym in symbol_list))
    price_dict = {sym: price for sym, price in zip(symbol_list, prices)}
    return {"prices": price_dict}
