from fastapi import FastAPI, Query
import asyncio
import helpers  # noqa: F401  (the provided API)

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(...)):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    tasks = [helpers.afetch_price(sym) for sym in symbol_list]
    prices = await asyncio.gather(*tasks)
    price_dict = {sym: price for sym, price in zip(symbol_list, prices)}
    return {"prices": price_dict}
