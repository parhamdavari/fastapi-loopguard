from fastapi import FastAPI
import asyncio

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str):
    symbols_list = symbols.split(',')
    tasks = [helpers.afetch_price(sym) for sym in symbols_list]
    prices = await asyncio.gather(*tasks)
    return {"prices": dict(zip(symbols_list, prices))}
