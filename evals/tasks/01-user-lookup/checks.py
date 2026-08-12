import asyncio

from httpx import ASGITransport, AsyncClient

from app import app


async def test_returns_user():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/users/42")
    await asyncio.sleep(0.02)  # let the sentinel record any pending lag

    assert response.status_code == 200
    assert response.json() == {"id": 42, "name": "user-42"}
