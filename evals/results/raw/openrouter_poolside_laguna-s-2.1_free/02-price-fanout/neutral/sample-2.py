from fastapi import FastAPI
from fastapi.responses import JSONResponse

import helpers  # noqa: F401 (the provided API)
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str):
    symbol_list = symbols.split(",")
    prices = await asyncio.gather(*[helpers.afetch_price(s) for s in symbol_list])
    result = {"prices": {s: p for s, p in zip(symbol_list, prices)}}
    return JSONResponse(content=result, status_code=200)
