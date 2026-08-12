import asyncio

from httpx import ASGITransport, AsyncClient

from app import app


async def test_processes_order():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post("/orders", json={"item": "widget"})
    await asyncio.sleep(0.02)  # let the sentinel record any pending lag

    assert response.status_code == 201
    assert response.json() == {"item": "widget", "reserved": True}
