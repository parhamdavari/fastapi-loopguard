from fastapi import FastAPI
import helpers  # noqa: F401
import asyncio

app = FastAPI()


@app.get("/portfolio")
async def portfolio(symbols: str = ""):
    symbol_list = [s for s in symbols.split(",") if s]
    if not symbol_list:
        return {"prices": {}}
    prices = await asyncio.gather(*(helpers.afetch_price(s) for s in symbol_list))
    return {"prices": dict(zip(symbol_list, prices))}
