from fastapi import FastAPI, Query
import helpers

app = FastAPI()


@app.get("/portfolio")
async def get_portfolio(symbols: str = Query(...)):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    # Fetch all prices concurrently using the async helper
    prices = await asyncio.gather(*[helpers.afetch_price(sym) for sym in symbol_list])
    result = {sym: price for sym, price in zip(symbol_list, prices)}
    return {"prices": result}
