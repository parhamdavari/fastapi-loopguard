from fastapi import FastAPI
import helpers
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str):
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {"prices": {}}
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]
    prices = await asyncio.gather(*tasks)
    return {"prices": dict(zip(symbol_list, prices))}
