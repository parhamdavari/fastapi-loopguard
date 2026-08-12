import asyncio

from httpx import ASGITransport, AsyncClient

import helpers
from app import app


async def test_saves_document():
    helpers.SAVED.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post(
            "/documents", json={"name": "a.txt", "text": "hello"}
        )
    await asyncio.sleep(0.02)  # let the sentinel record any pending lag

    assert response.status_code == 201
    assert response.json() == {"bytes": 5}
    assert helpers.SAVED == {"a.txt": "hello"}
