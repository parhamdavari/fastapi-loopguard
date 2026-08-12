"""Provided API. Do not modify."""

import time

SAVED: dict[str, str] = {}


def save_document(name: str, text: str) -> int:
    """Write a document to archive storage. Synchronous file I/O:
    ~120ms per write on the networked filesystem."""
    time.sleep(0.12)
    SAVED[name] = text
    return len(text.encode())
