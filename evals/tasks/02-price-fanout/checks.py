import asyncio
import time

from httpx import ASGITransport, AsyncClient

import helpers
from app import app


async def test_prices_fetched_concurrently():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        start = time.monotonic()
        response = await client.get("/portfolio", params={"symbols": "AAA,BBB,CCC"})
        elapsed = time.monotonic() - start
    await asyncio.sleep(0.02)  # let the sentinel record any pending lag

    assert response.status_code == 200
    assert response.json() == {"prices": {"AAA": 30.0, "BBB": 30.0, "CCC": 30.0}}
    # Concurrent: ~1 fetch (~0.12s). Sequential would be >= 0.36s.
    assert elapsed < 0.30
    # Prices are len(symbol)*10, so the body is derivable without the helper;
    # require the real calls so a hardcoded response cannot score as
    # functional AND non-blocking.
    assert helpers.calls() >= 3, "the solution never called the provided helper"
