import asyncio

from httpx import ASGITransport, AsyncClient

from app import app


async def test_renders_report():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post("/reports", json={"rows": ["a", "b", "c"]})
    await asyncio.sleep(0.02)  # let the sentinel record any pending lag

    assert response.status_code == 200
    assert response.json() == {"length": 5}  # "a\nb\nc"
