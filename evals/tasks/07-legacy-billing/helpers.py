"""Provided API. Do not modify."""

import time


class BillingClient:
    """Client for the legacy billing service.

    The vendor SDK is synchronous only; each call performs ~120ms of
    network I/O."""

    def __init__(self) -> None:
        self.receipts: list[str] = []

    def charge(self, amount: float) -> str:
        """Charge the amount and return a receipt id."""
        time.sleep(0.12)
        receipt = f"rcpt-{len(self.receipts) + 1}"
        self.receipts.append(receipt)
        return receipt
