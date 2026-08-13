from fastapi import FastAPI
import asyncio
import helpers

app = FastAPI()

@app.get("/portfolio")
async def get_portfolio(symbols: str):
    symbols_list = symbols.split(',')
    prices = await asyncio.gather(*[helpers.afetch_price(s) for s in symbols_list])
    return {"prices": dict(zip(symbols_list, prices))}
