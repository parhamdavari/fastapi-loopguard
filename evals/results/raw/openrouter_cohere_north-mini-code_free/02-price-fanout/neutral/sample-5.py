from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401 (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str):
    # Split the comma-separated symbols and strip whitespace
    symbol_list = [s.strip() for s in symbols.split(",")]

    # Concurrently fetch prices for all symbols
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]
    prices_list = await asyncio.gather(*tasks)

    # Map each symbol to its fetched price
    prices = {sym: price for sym, price in zip(symbol_list, prices_list)}

    return {"prices": prices}
