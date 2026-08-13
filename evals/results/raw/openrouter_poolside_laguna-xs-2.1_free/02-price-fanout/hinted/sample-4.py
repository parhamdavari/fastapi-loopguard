from fastapi import FastAPI

import helpers
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str):
    symbol_list = symbols.split(',')
    tasks = [helpers.afetch_price(symbol) for symbol in symbol_list]
    prices = await asyncio.gather(*tasks)
    return {"prices": dict(zip(symbol_list, prices))}
