from fastapi import FastAPI, Query
import asyncio
import helpers

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str = Query(...)):
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    prices = await asyncio.gather(*(helpers.afetch_price(s) for s in sym_list))
    price_dict = {symbol: price for symbol, price in zip(sym_list, prices)}
    return {"prices": price_dict}
