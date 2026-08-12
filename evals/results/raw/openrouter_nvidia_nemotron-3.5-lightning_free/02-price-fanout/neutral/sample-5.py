from fastapi import FastAPI, Query
import helpers
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str = Query(...)):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    prices = await asyncio.gather(*(helpers.afetch_price(s) for s in symbol_list))
    return {"prices": {s: p for s, p in zip(symbol_list, prices)}}
