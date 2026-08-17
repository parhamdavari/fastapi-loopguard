from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import helpers
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(...)):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    # Use helpers.afetch_price concurrently (non-blocking)
    coros = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices = await asyncio.gather(*coros)
    return JSONResponse(content={"prices": dict(zip(symbol_list, prices))}, status_code=200)
