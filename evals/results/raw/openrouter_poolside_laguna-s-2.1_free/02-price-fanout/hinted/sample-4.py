from fastapi import FastAPI

import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str):
    symbols_list = symbols.split(',')
    prices = await asyncio.gather(*(helpers.afetch_price(symbol) for symbol in symbols_list))
    return {"prices": {symbol: price for symbol, price in zip(symbols_list, prices)}}
