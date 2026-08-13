from fastapi import FastAPI, Depends
import asyncio
from concurrent.futures import ThreadPoolExecutor

import helpers

app = FastAPI()

billing = helpers.BillingClient()  # the shared client instance

# Shared executor for running blocking calls off the event loop
_executor = ThreadPoolExecutor(max_workers=4)


def get_billing() -> helpers.BillingClient:
    """FastAPI dependency providing the billing client."""
    return billing


@app.post("/charges")
async def create_charge(
    amount: float,
    billing_client: helpers.BillingClient = Depends(get_billing),
):
    """Charge `amount` via the legacy (blocking) billing client without
    blocking the event loop, then return the receipt id."""
    loop = asyncio.get_running_loop()
    receipt = await loop.run_in_executor(
        _executor, billing_client.charge, amount
    )
    return {"receipt": receipt}, 201
