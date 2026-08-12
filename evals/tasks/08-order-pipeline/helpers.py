"""Provided API. Do not modify."""

import time


def _reserve_inventory(item: str) -> None:
    # Talks to the warehouse service over its synchronous protocol: ~150ms.
    time.sleep(0.15)


def _enrich(order: dict) -> dict:
    _reserve_inventory(order["item"])
    return {**order, "reserved": True}


def process_order(order: dict) -> dict:
    """Validate and enrich an order, reserving its inventory."""
    return _enrich(order)
