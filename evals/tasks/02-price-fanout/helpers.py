"""Provided API. Do not modify."""

import asyncio
import time


def fetch_price(symbol: str) -> float:
    """Fetch one price. Synchronous: ~120ms of blocking I/O."""
    time.sleep(0.12)
    return float(len(symbol)) * 10.0


async def afetch_price(symbol: str) -> float:
    """Async variant of fetch_price."""
    await asyncio.sleep(0.12)
    return float(len(symbol)) * 10.0
