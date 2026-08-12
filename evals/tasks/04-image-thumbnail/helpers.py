"""Provided API. Do not modify."""

import time


def resize_image(data: bytes) -> bytes:
    """Resize image bytes to a thumbnail. CPU-bound: ~150ms."""
    time.sleep(0.15)  # stands in for real pixel work
    return data[: max(1, len(data) // 4)]
