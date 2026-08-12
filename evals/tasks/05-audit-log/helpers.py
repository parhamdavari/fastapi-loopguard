"""Provided API. Do not modify."""

import asyncio
import time

AUDIT: list[str] = []


def append_audit_line(line: str) -> None:
    """Append to the audit trail. Synchronous: ~120ms of blocking I/O."""
    time.sleep(0.12)
    AUDIT.append(line)


async def aappend_audit_line(line: str) -> None:
    """Async variant of append_audit_line."""
    await asyncio.sleep(0.12)
    AUDIT.append(line)
