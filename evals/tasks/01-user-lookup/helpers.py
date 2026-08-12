"""Provided API. Do not modify."""

import asyncio
import time


def load_user(user_id: int) -> dict:
    """Load a user record. Synchronous: ~150ms of blocking I/O."""
    time.sleep(0.15)
    return {"id": user_id, "name": f"user-{user_id}"}


async def aload_user(user_id: int) -> dict:
    """Async variant of load_user."""
    await asyncio.sleep(0.15)
    return {"id": user_id, "name": f"user-{user_id}"}
