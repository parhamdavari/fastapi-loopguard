from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import helpers
import asyncio

app = FastAPI()

@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(...)):
    # split and sanitize symbols
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    # Launch all async fetches concurrently
    coros = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices = await asyncio.gather(*coros)
    result = {symbol: price for symbol, price in zip(symbol_list, prices)}
    return JSONResponse(status_code=200, content={"prices": result})
