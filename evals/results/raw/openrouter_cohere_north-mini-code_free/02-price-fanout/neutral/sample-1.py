from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str):
    # Parse comma-separated symbols, stripping whitespace
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    # Create async tasks for concurrent price fetching
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]
    # Run all tasks concurrently
    results = await asyncio.gather(*tasks)
    # Build the required response dictionary
    price_dict = {sym: price for sym, price in zip(symbol_list, results)}
    return {"prices": price_dict}
