from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import asyncio

import helpers  # noqa: F401

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(...)):
    symbol_list = [sym.strip() for sym in symbols.split(",") if sym.strip()]
    # Use asyncio.gather on helpers.afetch_price (async, non-blocking)
    coros = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices_list = await asyncio.gather(*coros)
    prices = dict(zip(symbol_list, prices_list))
    return JSONResponse(content={"prices": prices}, status_code=200)
