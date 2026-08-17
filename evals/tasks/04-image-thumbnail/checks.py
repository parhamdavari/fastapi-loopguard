import asyncio

from httpx import ASGITransport, AsyncClient

import helpers
from app import app


async def test_thumbnail_size():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post("/thumbnail", content=b"x" * 100)
    await asyncio.sleep(0.02)  # let the sentinel record any pending lag

    assert response.status_code == 200
    assert response.json() == {"size": 25}
    # The expected body is derivable without the helper; require the real call
    # so a hardcoded response cannot score as functional AND non-blocking.
    assert helpers.calls() >= 1, "the solution never called the provided helper"
