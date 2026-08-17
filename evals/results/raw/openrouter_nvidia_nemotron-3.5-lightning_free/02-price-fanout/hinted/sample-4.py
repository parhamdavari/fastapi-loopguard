from fastapi import FastAPI, Query
import helpers
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str = Query(...)):
    symbol_list = [s.strip() for s in symbols.split(",")]
    prices = await asyncio.gather(*(helpers.afetch_price(s) for s in symbol_list))
    price_dict = {symbol: price for symbol, price in zip(symbol_list, prices)}
    return {"prices": price_dict}
