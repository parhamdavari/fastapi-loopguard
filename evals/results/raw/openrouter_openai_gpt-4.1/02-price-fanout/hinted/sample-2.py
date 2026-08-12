from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import helpers  # The provided API
import asyncio

app = FastAPI()

@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(...)):
    # Split and clean symbol list
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    # Create a coroutine for each symbol to fetch its price concurrently
    coros = [helpers.afetch_price(symbol) for symbol in symbol_list]

    # Gather all prices concurrently
    prices_list = await asyncio.gather(*coros)

    # Map prices to corresponding symbols
    prices = dict(zip(symbol_list, prices_list))

    return JSONResponse(content={"prices": prices}, status_code=200)
