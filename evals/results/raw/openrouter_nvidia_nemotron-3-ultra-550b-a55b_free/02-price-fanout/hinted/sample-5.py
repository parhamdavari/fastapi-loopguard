from fastapi import FastAPI, Query
import asyncio
import helpers

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(...)):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    prices = await asyncio.gather(*(helpers.afetch_price(sym) for sym in symbol_list))
    return {"prices": dict(zip(symbol_list, prices))}
