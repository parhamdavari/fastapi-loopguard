from fastapi import FastAPI

import asyncio

import helpers

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str):
    symbol_list = symbols.split(',')
    coroutines = [helpers.afetch_price(s) for s in symbol_list]
    prices = await asyncio.gather(*coroutines)
    return {"prices": dict(zip(symbol_list, prices))}
