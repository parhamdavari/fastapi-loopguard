from fastapi import FastAPI
import asyncio
import helpers  # noqa: F401 (provides afetch_price)

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str):
    """
    Fetch the current price for each given symbol concurrently.

    Query parameters:
        symbols (str): Comma-separated list of stock symbols (e.g., "AAA,BBB,CCC").

    Returns:
        {"prices": {symbol: price, ...}} with HTTP status 200.
    """
    # Split and clean the symbols list
    symbol_list = [sym.strip() for sym in symbols.split(",") if sym.strip()]

    # Create a task for each symbol's price fetch
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]

    # Run all fetches concurrently and collect results
    prices_list = await asyncio.gather(*tasks)

    # Pair symbols with their fetched prices
    prices = {sym: price for sym, price in zip(symbol_list, prices_list)}

    return {"prices": prices}
